"""Views for config_officer plugin."""

from django.http import HttpResponse
from django.views.generic import View
from .models import Collection
from .filters import CollectionFilter
from .forms import CollectionFilterForm
from .tables import CollectionTable
# from utilities.views import ObjectListView
from netbox.views.generic import ObjectListView
from django.contrib.auth.mixins import PermissionRequiredMixin
from dcim.models import Device
from django_rq import get_queue
from django.shortcuts import render
from django_rq import get_queue


class GetConfigFromAllCiscoDevices(View):
    """Get show-running configuration from all devices with manufacture cisco."""

    def get(self, request):
        return HttpResponse("hello")


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


def collect_device_config(request, slug):
    if len(Device.objects.filter(name__iexact=slug)) == 0:
        message = f"Device {slug} not found"
    else:
        message = "Ok"
        try:
            get_queue("default").enqueue("config_officer.worker.collect_device_config_hostname", hostname=slug)
            message = f"Collection show-running config for {slug} has been started"
        except Exception as e:
            message = e
    return render(request, "config_officer/message.html", {"message": message})

