"""Views for config_officer plugin."""

from django.http import HttpResponse
from django.views.generic import View
from django.contrib.auth.mixins import PermissionRequiredMixin
from dcim.models import Device
from django_rq import get_queue
from django.shortcuts import render, get_object_or_404, redirect
from django_rq import get_queue
from django.contrib import messages
from django.urls import reverse
from netbox.views.generic import (
    ObjectListView, 
    ObjectEditView, 
    BulkDeleteView,
    ObjectDeleteView
)
from .models import (
    Collection, 
    Template, 
    Service,
    ServiceRule,
    ServiceMapping,
    Compliance   
)
from .filters import CollectionFilter, ServiceMappingFilter
from .forms import (
    CollectionFilterForm, 
    TemplateForm,
    ServiceForm,
    ServiceRuleForm,  
    ServiceMappingForm,
    ServiceMappingCreateForm,
    ServiceMappingFilterForm
)
from .tables import (
    CollectionTable, 
    TemplateListTable,
    ServiceListTable,
    ServiceRuleListTable,
    ServiceMappingListTable
)
from .choices import CollectStatusChoices
from .git_manager import get_device_config, get_config_update_date, get_file_repo_state
from copy import deepcopy
from datetime import datetime
import pytz
import os 
import io 
import xlsxwriter
from django.db.models import Q
from django.conf import settings

PLUGIN_SETTINGS = settings.PLUGINS_CONFIG.get("config_officer", dict())
NETBOX_DEVICES_CONFIGS_DIR = PLUGIN_SETTINGS.get("NETBOX_DEVICES_CONFIGS_DIR", "/device_configs")
TIME_ZONE = os.environ.get("TIME_ZONE", "Europe/Moscow")


def global_collection():
    """Function for collect all devices running-configs."""

    devices_collecting = Collection.objects.filter(
        Q(status__iexact=CollectStatusChoices.STATUS_PENDING)
        | Q(status__iexact=CollectStatusChoices.STATUS_RUNNING)
    )
    count = len(devices_collecting)
    if count > 0:
        return f"Global collection not possible now. There are {count} devices are in {CollectStatusChoices.STATUS_PENDING} or {CollectStatusChoices.STATUS_RUNNING} state"
    else:
        get_queue("default").enqueue("config_officer.worker.collect_all_devices_configs")
        return "Global sync was started"


class GlobalCollectionDeviceConfigs(View):
    def get(self, request):
        message = global_collection()
        return render(request, "config_officer/collection_message.html", {"message": message})


class CollectStatusListView(PermissionRequiredMixin, ObjectListView):


    """Get status of collection show_running config from devices."""

    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Collection.objects.all().order_by("-id")
    filterset = CollectionFilter
    filterset_form = CollectionFilterForm
    table = CollectionTable
    template_name = "config_officer/collect_configs_list.html"
    
    # def post(self, request, *args, **kwargs):
    #     if "reCollect" in request.POST:
    #         pk_list = [int(pk) for pk in request.POST.getlist("pk")]
    #         devices_list = list()

    #         if len(pk_list) == 0:  # if nothing selected
    #             Collect_failed_list = Collection.objects.filter(
    #                 status__iexact=OnboardingStatusChoices.STATUS_FAILED
    #             )
    #             if len(Collect_failed_list) > 0:
    #                 for task in Collect_failed_list:
    #                     devices_list.append(task.device)
    #         else:
    #             for task_id in pk_list:
    #                 devices_list.append(Collection.objects.get(id=task_id).device)

    #         # -remove dublicates
    #         devices_list = list(dict.fromkeys(devices_list))

    #         if len(devices_list) == 0:
    #             msg = "Nothing to Collecthronize"
    #             messages.info(request, msg)
    #         else:
    #             count = len(devices_list)
    #             msg = f"Collecthronizaton with {count} devices was started"
    #             messages.success(request, msg)

    #         # --start Collect
    #         get_queue("default").enqueue(
    #             "Collect_devices.worker.Collect_devices_list", devices_list=devices_list
    #         )

    #         time.sleep(2)
    #         return redirect(request.get_full_path())


class CollectTaskDelete(PermissionRequiredMixin, BulkDeleteView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Collection.objects.filter()
    table = CollectionTable
    default_return_url = "plugin:config_officer:collection_status"


def collect_device_config(request, slug):
    if len(Device.objects.filter(name__iexact=slug)) == 0:
        message = f"Device {slug} not found"
        return render(request, "config_officer/collection_message.html", {"message": message})
    else:
        message = "Ok"
        try:
            get_queue("default").enqueue("config_officer.worker.collect_device_config_hostname", hostname=slug)
            return redirect(reverse('plugins:config_officer:collection_status'))
        except Exception as e:
            message = e
            return render(request, "config_officer/collection_message.html", {"message": message})
    

class TemplateListView(PermissionRequiredMixin, ObjectListView):
    """All added templates."""

    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Template.objects.all().order_by("-id")
    table = TemplateListTable
    template_name = "config_officer/template_list.html"


class TemplateCreateView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    model = Template
    model_form = TemplateForm
    queryset = Template.objects.all()
    default_return_url = 'plugins:config_officer:template_list'


class TemplateBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Template.objects.filter()
    table = TemplateListTable
    default_return_url = "plugin:config_officer:template_list"


class TemplateView(PermissionRequiredMixin, View):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Template.objects.all()

    def get(self, request, pk):
        template = get_object_or_404(self.queryset, pk=pk)

        return render(
            request,
            "config_officer/template_view.html",
            {
                "template": template,
            },
        )


class TemplateEditView(TemplateCreateView):
    permission_required = ('dcim.view_site', 'dcim.view_device')


class TemplateDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Template.objects.all()
    default_return_url = 'plugins:config_officer:template_list'        


class ServiceListView(PermissionRequiredMixin, ObjectListView):
    """Device services list."""

    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Service.objects.all().order_by("-id")
    table = ServiceListTable
    template_name = "config_officer/service_list.html"


class ServiceCreateView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    model = Service
    queryset = Service.objects.all()
    model_form = ServiceForm
    default_return_url = 'plugins:config_officer:service_list'          


class ServiceBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    """Delete selected service."""
    
    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Service.objects.filter()
    table = ServiceListTable
    default_return_url = "plugin:config_officer:service_list"


class ServiceEditView(ServiceCreateView):
    permission_required = ('dcim.view_site', 'dcim.view_device')


class ServiceDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    model = Service
    default_return_url = 'plugins:config_officer:service_list'        


class ServiceView(PermissionRequiredMixin, View):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Service.objects.all()

    def get(self, request, pk):
        service = get_object_or_404(self.queryset, pk=pk)

        service_rules = ServiceRule.objects.filter(service=service)
        return render(
            request,
            "config_officer/service_view.html",
            {
                "service": service,
                "service_rules": service_rules
            },
        )


class ServiceRuleListView(PermissionRequiredMixin, ObjectListView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = ServiceRule.objects.all().order_by("service")
    table = ServiceRuleListTable
    template_name = "config_officer/service_rule_list.html"


class ServiceRuleCreateView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    model = ServiceRule
    queryset = ServiceRule.objects.all()
    model_form = ServiceRuleForm
    default_return_url = 'plugins:config_officer:service_rules_list'


class ServiceRuleEditView(ServiceRuleCreateView):
    permission_required = ('dcim.view_site', 'dcim.view_device')


class ServiceRuleDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    model = ServiceRule
    default_return_url = 'plugins:config_officer:service_rules_list'        


class ComplianceView(PermissionRequiredMixin, View):
    """Compliance details view for device."""

    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Compliance.objects.all()

    def get(self, request, device):
        record = get_object_or_404(self.queryset, device=device)
        device_config = get_device_config(NETBOX_DEVICES_CONFIGS_DIR, record.device.name, "running")
        config_update_date = get_config_update_date(NETBOX_DEVICES_CONFIGS_DIR, record.device.name, "running")
        return render(
            request,
            "config_officer/compliance_view.html",
            {
                "record": record,
                "device_config": device_config,
                "config_update_date": config_update_date
            },
        )


class ServiceMappingListView(PermissionRequiredMixin, ObjectListView):
    """Assign service to device and check compliance status table view.""" 

    permission_required = ('dcim.view_site', 'dcim.view_device')
    queryset = Device.objects.all()
    filterset = ServiceMappingFilter
    filterset_form = ServiceMappingFilterForm
    table = ServiceMappingListTable
    template_name = "config_officer/service_mapping_list.html"    

    def export_to_excel(self):
        output = io.BytesIO()
        header = [
            {'header': 'Hostname'},
            {'header': 'PID'},
            {'header': 'Role'},
            {'header': 'IP'},
            {'header': 'Tenant'},
            {'header': 'Compliance'},
            {'header': 'Diff'},
            {'header': 'Notes'}
        ]
        width = [len(i['header']) + 2 for i in header]

        data = []

        devices = Device.objects.all().order_by('tenant')
        for d in devices:
            if hasattr(d, 'compliance'):
                k = [
                    d.name,
                    d.device_type.model,
                    d.device_role.name,
                    str(d.primary_ip4).split('/')[0],
                    str(d.tenant),
                    d.compliance.status,
                    d.compliance.diff,
                    d.compliance.notes,
                ]
            else:
                k = [
                    d.name,
                    d.device_type.model,
                    d.device_role.name,
                    str(d.primary_ip4).split('/')[0],
                    str(d.tenant),
                    'service not assigned',
                    '',
                    '',
                ]
                    
            data.append(k)
            w = list()
            for i in k:
                if i:
                    w.append(len(i))
                else:
                    w.append(40)
            # w = [ for i in k]
            width = [max(width[i], w[i]) for i in range(0, len(width))]

        workbook = xlsxwriter.Workbook(
            output,
            {
                'remove_timezone': True,
                'default_date_format': 'yyyy-mm-dd',
            },
        )
        worksheet = workbook.add_worksheet(f'compliance')
        worksheet.add_table(
            0, 0, Device.objects.all().count(), len(header) - 1,
            {'columns': header, 'data': data}
        )
        for i in range(0, len(width)):
            worksheet.set_column(i, i , width[i])
        workbook.close()
        output.seek(0)
        return output

    def post(self, request, *args, **kwargs):        
        """POST from services-devices mappings view."""

        # Assign service to devices from table.
        if '_create' in request.POST:
            s = ServiceMappingCreateForm(request.POST)
            if s.is_valid():
                data = deepcopy(s.cleaned_data)
                    
                pk_list = [int(pk) for pk in request.POST.getlist('pk')]
                selected_devices = Device.objects.filter(pk__in=pk_list)       
                
                services = data['service']
                if len(services) == 0:
                    messages.error(request, 'No services selected')
                else:
                    # Delete all records about selected device from services and compliance tables                
                    # ServiceMapping.objects.filter(device__in=selected_devices).delete()                
                    Compliance.objects.filter(device__in=selected_devices).delete()                   
                    for device in data['pk']:  
                        ServiceMapping.objects.filter(device=device).delete()     
                        for service in services:
                            ServiceMapping.objects.update_or_create(device=device, service=service)                                          
                        # Check compliance right after services are assigned:
                        get_queue("default").enqueue("config_officer.worker.check_device_config_compliance", device=device)

                    messages.success(request, f'{services} were attached to {len(data["pk"])} devices')
            else:
                messages.error(request, 'Error form is not valid')
        return redirect(request.get_full_path())    

    def get(self, request, *args, **kwargs):
        if 'to_excel' in request.GET.keys():
            filename = f'compliance_{datetime.now().astimezone(pytz.timezone(TIME_ZONE)).strftime("%Y%m%d_%H%M%S")}.xlsx'
            response = HttpResponse(
                self.export_to_excel(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        return super().get(request, *args, **kwargs)                


class ServiceMappingCreateView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    model = ServiceMapping
    queryset = ServiceMapping.objects.all()
    model_form = ServiceMappingForm
    default_return_url = 'plugins:config_officer:service_mapping_list'      


class ServiceMappingDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ('dcim.view_site', 'dcim.view_device')
    model = ServiceMapping
    default_return_url = 'plugins:config_officer:service_mapping_list'     


class ServiceAssign(PermissionRequiredMixin, View):
    permission_required = ('dcim.view_site', 'dcim.view_device')

    def post(self, request):
        if '_device' in request.POST:
            pk_list = [int(pk) for pk in request.POST.getlist('pk')]

        selected_devices = Device.objects.filter(pk__in=pk_list)
        
        if not selected_devices:
            messages.warning(request, 'No devices were selected.')
            return redirect(reverse('plugins:config_officer:service_mapping_list'))
        
        return render(request, 'generic/object_bulk_add_component.html', {
            'form': ServiceMappingCreateForm(initial={'pk': pk_list}),
            'parent_model_name': 'Devices',
            'model_name': 'Service',
            'table': ServiceMappingListTable(selected_devices),
            'return_url': reverse('plugins:config_officer:service_mapping_list'),
        })


class ServiceDetach(PermissionRequiredMixin, View):
    permission_required = 'config_officer.delete'

    def post(self, request):
        if '_device' in request.POST:
            pk_list = [int(pk) for pk in request.POST.getlist('pk')]

        selected_devices = Device.objects.filter(pk__in=pk_list)
        if not selected_devices:
            messages.warning(request, 'No devices were selected.')
            return redirect(reverse('plugins:config_officer:service_mapping_list'))
                
        ServiceMapping.objects.filter(device__in=selected_devices).delete()
        Compliance.objects.filter(device__in=selected_devices).delete()
        get_queue("default").enqueue("config_officer.worker.upload_compliance_status_into_influxdb")
        messages.success(request, f'{len(selected_devices)} devices were de-attached from service.')
        return redirect(reverse('plugins:config_officer:service_mapping_list'))        


def running_config(request, hostname):
    """Show device config html page when custom link is clicked."""

    running_config = get_device_config(NETBOX_DEVICES_CONFIGS_DIR, hostname, "running")
    message = {}
    if not running_config:
        message["status"] = False
        message["comment"] = "Error reading runnig config file from directory"
    else:
        message["status"] = True
        message["running_config"] = running_config
    message["repo_state"] = get_file_repo_state(NETBOX_DEVICES_CONFIGS_DIR, f"{hostname}_running.txt")
    return render(request, "config_officer/device_runnig_config.html", {"message": message})