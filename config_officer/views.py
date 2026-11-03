import csv
import io
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import django_tables2 as tables_lib
from dcim.models import Device
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django_rq import get_connection, get_queue
from netbox.object_actions import AddObject
from netbox.views.generic import (
    ObjectDeleteView,
    ObjectEditView,
    ObjectJobsView,
    ObjectListView,
)
from rq.exceptions import NoSuchJobError
from rq.job import Job

from config_officer.jobs import CollectScheduleJob

from .choices import CollectStatusChoices
from .configuration import CONFIGS_PATH, TIME_ZONE
from .filters import CollectionFilter, ServiceMappingFilter
from .forms import (
    CollectionFilterForm,
    CollectScheduleForm,
    ServiceForm,
    ServiceMappingCreateForm,
    ServiceMappingFilterForm,
    ServiceMappingForm,
    ServiceRuleForm,
    TemplateForm,
)
from .git_manager import (
    get_config_update_date,
    get_device_config,
)
from .models import (
    Collection,
    CollectSchedule,
    Compliance,
    Service,
    ServiceMapping,
    ServiceRule,
    Template,
)
from .tables import (
    CollectionTable,
    CollectScheduleTable,
    ServiceListTable,
    ServiceMappingListTable,
    ServiceRuleListTable,
    TemplateListTable,
)

# ---------------------------------------------------------------------------
# Base helpers
# ---------------------------------------------------------------------------


class PluginTableView(PermissionRequiredMixin, View):
    """Base view: renders a django-tables2 table with an optional filter form."""

    permission_required = ("dcim.view_device",)
    queryset = None
    table_class = None
    filterset_class = None
    filterset_form_class = None
    template_name = "config_officer/generic_list.html"
    page_title = ""
    add_url = None

    def get_queryset(self, request):
        return self.queryset

    def get(self, request):
        qs = self.get_queryset(request)

        filterset = None
        filter_form = None
        if self.filterset_class:
            filterset = self.filterset_class(request.GET, queryset=qs)
            qs = filterset.qs
        if self.filterset_form_class:
            filter_form = self.filterset_form_class(request.GET)

        table = self.table_class(qs)
        tables_lib.RequestConfig(request, paginate={"per_page": 50}).configure(table)

        return render(
            request,
            self.template_name,
            {
                "table": table,
                "filter_form": filter_form,
                "page_title": self.page_title,
                "add_url": self.add_url,
            },
        )


# ---------------------------------------------------------------------------
# Global collection
# ---------------------------------------------------------------------------


def global_collection():
    in_progress = Collection.objects.filter(
        Q(status__iexact=CollectStatusChoices.STATUS_PENDING)
        | Q(status__iexact=CollectStatusChoices.STATUS_RUNNING)
    ).count()
    if in_progress:
        return (
            f"Global collection not possible now. There are {in_progress} devices in "
            f"{CollectStatusChoices.STATUS_PENDING} or {CollectStatusChoices.STATUS_RUNNING} state."
        )
    get_queue("default").enqueue("config_officer.worker.collect_all_devices_configs")
    return "Global sync was started."


class GlobalCollectionDeviceConfigs(View):
    def get(self, request):
        return render(
            request,
            "config_officer/collection_message.html",
            {"message": global_collection()},
        )


# ---------------------------------------------------------------------------
# Collection status
# ---------------------------------------------------------------------------


class CollectStatusListView(PluginTableView):
    queryset = Collection.objects.all().order_by("-id")
    table_class = CollectionTable
    filterset_class = CollectionFilter
    filterset_form_class = CollectionFilterForm
    template_name = "config_officer/collect_configs_list.html"
    page_title = "Collect running-config tasks"


class CollectTaskDelete(PermissionRequiredMixin, View):
    permission_required = ("dcim.view_device",)

    def get(self, request):
        pk = request.GET.get("pk")
        if pk:
            Collection.objects.filter(pk=pk).delete()
            messages.success(request, "Collection task deleted.")
        return redirect(reverse("plugins:config_officer:collection_status"))

    def post(self, request):
        pk_list = request.POST.getlist("pk")
        Collection.objects.filter(pk__in=pk_list).delete()
        messages.success(request, f"{len(pk_list)} task(s) deleted.")
        return redirect(reverse("plugins:config_officer:collection_status"))


def collect_device_config(request, slug):
    """Trigger single-device collection via RQ."""
    if not Device.objects.filter(name__iexact=slug).exists():
        return render(
            request,
            "config_officer/collection_message.html",
            {"message": f"Device '{slug}' not found."},
        )
    try:
        get_queue("default").enqueue(
            "config_officer.worker.collect_device_config_hostname", hostname=slug
        )
        return redirect(reverse("plugins:config_officer:collection_status"))
    except Exception as exc:
        return render(request, "config_officer/collection_message.html", {"message": str(exc)})


# ---------------------------------------------------------------------------
# Template views
# ---------------------------------------------------------------------------


class TemplateListView(PluginTableView):
    queryset = Template.objects.all()
    table_class = TemplateListTable
    template_name = "config_officer/template_list.html"
    page_title = "Device configuration templates"
    add_url = "plugins:config_officer:template_add"


class TemplateCreateView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ("dcim.view_device",)
    queryset = Template.objects.all()
    form = TemplateForm
    default_return_url = "plugins:config_officer:template_list"


class TemplateEditView(TemplateCreateView):
    pass


class TemplateView(PermissionRequiredMixin, View):
    permission_required = ("dcim.view_device",)

    def get(self, request, pk):
        template = get_object_or_404(Template, pk=pk)
        return render(request, "config_officer/template_view.html", {"template": template})


class TemplateDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ("dcim.view_device",)
    queryset = Template.objects.all()
    default_return_url = "plugins:config_officer:template_list"


# ---------------------------------------------------------------------------
# Service views
# ---------------------------------------------------------------------------


class ServiceListView(PluginTableView):
    queryset = Service.objects.all()
    table_class = ServiceListTable
    template_name = "config_officer/service_list.html"
    page_title = "Device services"
    add_url = "plugins:config_officer:service_add"


class ServiceCreateView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ("dcim.view_device",)
    queryset = Service.objects.all()
    form = ServiceForm
    default_return_url = "plugins:config_officer:service_list"


class ServiceEditView(ServiceCreateView):
    pass


class ServiceView(PermissionRequiredMixin, View):
    permission_required = ("dcim.view_device",)

    def get(self, request, pk):
        service = get_object_or_404(Service, pk=pk)
        service_rules = ServiceRule.objects.filter(service=service)
        return render(
            request,
            "config_officer/service_view.html",
            {"service": service, "service_rules": service_rules},
        )


class ServiceDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ("dcim.view_device",)
    queryset = Service.objects.all()
    default_return_url = "plugins:config_officer:service_list"


# ---------------------------------------------------------------------------
# ServiceRule views
# ---------------------------------------------------------------------------


class ServiceRuleListView(PluginTableView):
    queryset = ServiceRule.objects.all().order_by("service")
    table_class = ServiceRuleListTable
    template_name = "config_officer/service_rule_list.html"
    page_title = "Service rules"
    add_url = "plugins:config_officer:service_rule_add"


class ServiceRuleCreateView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ("dcim.view_device",)
    queryset = ServiceRule.objects.all()
    form = ServiceRuleForm
    default_return_url = "plugins:config_officer:service_rules_list"


class ServiceRuleEditView(ServiceRuleCreateView):
    pass


class ServiceRuleDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ("dcim.view_device",)
    queryset = ServiceRule.objects.all()
    default_return_url = "plugins:config_officer:service_rules_list"


# ---------------------------------------------------------------------------
# Compliance view
# ---------------------------------------------------------------------------


class ComplianceView(PermissionRequiredMixin, View):
    permission_required = ("dcim.view_device",)

    def get(self, request, device):
        record = get_object_or_404(Compliance, device=device)
        return render(
            request,
            "config_officer/compliance_view.html",
            {
                "record": record,
                "device_config": get_device_config(CONFIGS_PATH, record.device.name, "running"),
                "config_update_date": get_config_update_date(
                    CONFIGS_PATH, record.device.name, "running"
                ),
            },
        )


# ---------------------------------------------------------------------------
# ServiceMapping views
# ---------------------------------------------------------------------------


class ServiceMappingListView(PermissionRequiredMixin, ObjectListView):
    permission_required = ("dcim.view_device",)
    queryset = Device.objects.all()
    filterset = ServiceMappingFilter
    filterset_form = ServiceMappingFilterForm
    table = ServiceMappingListTable
    template_name = "config_officer/service_mapping_list.html"

    def _export_to_csv(self):
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(
            [
                "Hostname",
                "PID",
                "Role",
                "IP",
                "Tenant",
                "Compliance",
                "Diff",
                "Notes",
            ]
        )

        for d in Device.objects.all().order_by("tenant"):
            if hasattr(d, "compliance"):
                writer.writerow(
                    [
                        d.name,
                        d.device_type.model,
                        d.role.name,
                        str(d.primary_ip4).split("/")[0] if d.primary_ip4 else "",
                        str(d.tenant),
                        d.compliance.status,
                        d.compliance.diff or "",
                        d.compliance.notes or "",
                    ]
                )
            else:
                writer.writerow(
                    [
                        d.name,
                        d.device_type.model,
                        d.role.name,
                        str(d.primary_ip4).split("/")[0] if d.primary_ip4 else "",
                        str(d.tenant),
                        "service not assigned",
                        "",
                        "",
                    ]
                )

        output.seek(0)
        return output

    def post(self, request, *args, **kwargs):
        if "_create" not in request.POST:
            return redirect(request.get_full_path())

        form = ServiceMappingCreateForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Form is not valid.")
            return redirect(request.get_full_path())

        data = deepcopy(form.cleaned_data)
        services = data["service"]
        if not services:
            messages.error(request, "No services selected.")
            return redirect(request.get_full_path())

        Compliance.objects.filter(device__in=data["pk"]).delete()
        for device in data["pk"]:
            ServiceMapping.objects.filter(device=device).delete()
            for service in services:
                ServiceMapping.objects.update_or_create(device=device, service=service)
            get_queue("default").enqueue(
                "config_officer.worker.check_device_config_compliance", device=device
            )
        messages.success(request, f"{list(services)} attached to {len(data['pk'])} device(s).")
        return redirect(request.get_full_path())

    def get(self, request, *args, **kwargs):
        if "to_excel" in request.GET:
            output = self._export_to_csv()
            tz = ZoneInfo(TIME_ZONE)
            filename = f"compliance_{datetime.now().astimezone(tz).strftime('%Y%m%d_%H%M%S')}.csv"
            response = HttpResponse(output, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        return super().get(request, *args, **kwargs)


class ServiceMappingCreateView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ("dcim.view_device",)
    queryset = ServiceMapping.objects.all()
    form = ServiceMappingForm
    default_return_url = "plugins:config_officer:service_mapping_list"


class ServiceMappingDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ("dcim.view_device",)
    queryset = ServiceMapping.objects.all()
    default_return_url = "plugins:config_officer:service_mapping_list"


class ServiceAssign(PermissionRequiredMixin, View):
    permission_required = ("dcim.view_device",)

    def post(self, request):
        pk_list = [int(pk) for pk in request.POST.getlist("pk")]
        selected_devices = Device.objects.filter(pk__in=pk_list)

        if not selected_devices.exists():
            messages.warning(request, "No devices were selected.")
            return redirect(reverse("plugins:config_officer:service_mapping_list"))

        return render(
            request,
            "generic/object_bulk_add_component.html",
            {
                "form": ServiceMappingCreateForm(initial={"pk": pk_list}),
                "parent_model_name": "Devices",
                "model_name": "Service",
                "table": ServiceMappingListTable(selected_devices),
                "return_url": reverse("plugins:config_officer:service_mapping_list"),
            },
        )


class ServiceDetach(PermissionRequiredMixin, View):
    permission_required = ("dcim.view_device",)

    def post(self, request):
        pk_list = [int(pk) for pk in request.POST.getlist("pk")]
        selected_devices = Device.objects.filter(pk__in=pk_list)

        if not selected_devices.exists():
            messages.warning(request, "No devices were selected.")
            return redirect(reverse("plugins:config_officer:service_mapping_list"))

        ServiceMapping.objects.filter(device__in=selected_devices).delete()
        Compliance.objects.filter(device__in=selected_devices).delete()
        messages.success(request, f"{selected_devices.count()} device(s) de-attached from service.")
        return redirect(reverse("plugins:config_officer:service_mapping_list"))


# ---------------------------------------------------------------------------
# Running config page (Custom Link target)
# ---------------------------------------------------------------------------


def running_config(request, hostname):
    """Enqueue jobs and return page immediately with loading state."""
    queue = get_queue("default")

    config_job = queue.enqueue(
        "config_officer.worker.get_device_running_config",
        hostname,
    )
    repo_job = queue.enqueue(
        "config_officer.worker.get_device_repo_state",
        hostname,
    )

    return render(
        request,
        "config_officer/device_running_config.html",
        {
            "hostname": hostname,
            "config_job_id": config_job.id,
            "repo_job_id": repo_job.id,
        },
    )


def running_config_status(request, hostname, config_job_id, repo_job_id):
    """Poll endpoint - returns JSON with job results when ready."""
    connection = get_connection("default")

    try:
        config_job = Job.fetch(config_job_id, connection=connection)
        repo_job = Job.fetch(repo_job_id, connection=connection)
    except NoSuchJobError as e:
        return JsonResponse({"error": str(e)}, status=404)

    if not config_job.is_finished or not repo_job.is_finished:
        failed = config_job.is_failed or repo_job.is_failed
        return JsonResponse(
            {
                "ready": False,
                "failed": failed,
            }
        )

    running = config_job.result
    repo_state = repo_job.result or {}

    # Serialize commits — datetime not JSON serializable
    commits = []
    for c in repo_state.get("commits", []):
        commits.append(
            {
                "hash": c["hash"],
                "msg": c["msg"],
                "diff": c["diff"],
                "date": c["date"].strftime("%Y-%m-%d %H:%M") if c.get("date") else "",
            }
        )

    return JsonResponse(
        {
            "ready": True,
            "running_config": running,
            "repo_state": {
                "commits_count": repo_state.get("commits_count", 0),
                "commits": commits,
                "first_commit_date": repo_state.get("first_commit_date", ""),
                "last_commit_date": repo_state.get("last_commit_date", ""),
                "error": repo_state.get("error", ""),
                "comment": repo_state.get("comment", ""),
            },
        }
    )


# ---------------------------------------------------------------------------
# Collect Schedule Views
# ---------------------------------------------------------------------------


class CollectScheduleListView(PermissionRequiredMixin, ObjectListView):
    permission_required = ("dcim.view_device",)
    queryset = CollectSchedule.objects.prefetch_related("devices")
    table = CollectScheduleTable
    actions = (AddObject,)
    default_return_url = "plugins:config_officer:schedule_list"


class CollectScheduleEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = ("dcim.view_device",)
    queryset = CollectSchedule.objects.all()
    form = CollectScheduleForm
    default_return_url = "plugins:config_officer:schedule_list"


class CollectScheduleDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = ("dcim.view_device",)
    queryset = CollectSchedule.objects.all()
    default_return_url = "plugins:config_officer:schedule_list"


class CollectScheduleRunNowView(PermissionRequiredMixin, View):
    permission_required = ("dcim.view_device",)

    def get(self, request, pk):
        schedule = get_object_or_404(CollectSchedule, pk=pk)

        CollectScheduleJob.enqueue(instance=schedule, user=request.user)

        messages.success(
            request,
            f"Collection has been queued for {schedule.devices.count()} devices.",
        )
        return redirect("plugins:config_officer:schedule_list")

    default_return_url = "plugins:config_officer:schedule_list"


class CollectScheduleJobsView(PermissionRequiredMixin, ObjectJobsView):
    permission_required = ("dcim.view_device",)
    queryset = CollectSchedule.objects.all()
    template_name = "generic/object_jobs.html"
