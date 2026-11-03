"""Web UI views. Kept thin: check permissions, render, enqueue background jobs.

Sections:

* Collection   - the collection page (run form + recent runs), run detail, results
* Device tabs  - "Configuration" and "Compliance" tabs plus the "Collect" button on devices
* Schedules    - recurring collections
* Compliance   - templates, services, service rules and the per-device status list
* Legacy URLs  - 0.1.x addresses redirected to their new home

Permissions are NetBox's own (see permissions.py). Generic NetBox views check the
model permission of their queryset; custom views list theirs in ``permission_required``.
"""

from core.choices import JobStatusChoices
from core.models import Job
from dcim.models import Device
from django.contrib import messages
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.views.generic import View
from django_rq import get_queue
from netbox.object_actions import AddObject, BulkDelete, BulkExport, DeleteObject, EditObject
from netbox.views import generic
from rq.exceptions import NoSuchJobError
from rq.job import Job as RQJob
from utilities.views import (
    ConditionalLoginRequiredMixin,
    ContentTypePermissionRequiredMixin,
    ViewTab,
    register_model_view,
)

from . import filtersets, forms, jobs, tables
from .choices import CollectStatusChoices
from .collection.targets import DeviceSelection
from .compliance.engine import templates_for_device
from .models import (
    Collection,
    CollectSchedule,
    Compliance,
    Service,
    ServiceMapping,
    ServiceRule,
    Template,
)
from .permissions import COLLECT_CONFIG, COLLECT_CONFIG_ACTION, VIEW_CONFIG, VIEW_CONFIG_ACTION
from .storage import ConfigRepository, device_config_snapshot


class PermissionRequiredView(ContentTypePermissionRequiredMixin, View):
    """Plain view guarded by a fixed list of NetBox permissions (all of them are required)."""

    permission_required: tuple[str, ...] = ()

    def get_required_permission(self):
        return self.permission_required[0]

    @property
    def additional_permissions(self):
        return self.permission_required[1:]


def _run_link(job) -> str:
    url = reverse("plugins:config_officer:run", kwargs={"pk": job.pk})
    return format_html('<a href="{}">run #{}</a>', url, job.pk)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


class CollectionDashboardView(PermissionRequiredView):
    """Start a collection (all devices / by tag / selected devices) and watch recent runs."""

    permission_required = ("config_officer.view_collection",)
    template_name = "config_officer/collection_dashboard.html"

    def _render(self, request, form):
        runs = (
            Job.objects.filter(name__in=jobs.COLLECTION_JOB_NAMES)
            .select_related("user")
            .order_by("-created")[:15]
        )
        latest = (
            Collection.objects.restrict(request.user, "view")
            .filter(device__isnull=False)
            .order_by("device_id", "-timestamp")
            .distinct("device_id")
        )
        status_counts = {}
        for status in latest.values_list("status", flat=True):
            status_counts[status] = status_counts.get(status, 0) + 1
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "can_collect": request.user.has_perm(COLLECT_CONFIG),
                "runs_table": tables.RunTable(runs, orderable=False),
                "status_counts": [
                    (value, label, color, status_counts.get(value, 0))
                    for value, label, color in CollectStatusChoices.CHOICES
                    if value
                    in (
                        CollectStatusChoices.STATUS_SUCCEEDED,
                        CollectStatusChoices.STATUS_FAILED,
                        CollectStatusChoices.STATUS_SKIPPED,
                    )
                ],
                "schedules": CollectSchedule.objects.restrict(request.user, "view").filter(
                    enabled=True
                ),
            },
        )

    def get(self, request):
        return self._render(request, forms.RunCollectionForm(initial=request.GET or None))

    def post(self, request):
        if not request.user.has_perm(COLLECT_CONFIG):
            return self.handle_no_permission()
        form = forms.RunCollectionForm(request.POST)
        if not form.is_valid():
            return self._render(request, form)
        selection = form.get_selection()
        job = jobs.enqueue_collection(selection, request.user)
        messages.success(
            request,
            format_html(_("Collection of {} queued as {}."), selection.describe(), _run_link(job)),
        )
        return redirect("plugins:config_officer:run", pk=job.pk)


class CollectionRunView(PermissionRequiredView):
    """One collection run: progress, log and per-device results (no core.view_job needed)."""

    permission_required = ("config_officer.view_collection",)

    def get(self, request, pk):
        job = get_object_or_404(Job, pk=pk, name__in=jobs.COLLECTION_JOB_NAMES)
        results = (
            Collection.objects.restrict(request.user, "view")
            .filter(job=job)
            .select_related("device")
        )
        table = tables.CollectionTable(results, exclude=("pk", "run"))
        table.configure(request)
        running = job.status in (JobStatusChoices.STATUS_PENDING, JobStatusChoices.STATUS_RUNNING)
        return render(
            request,
            "config_officer/collection_run.html",
            {
                "job": job,
                "data": job.data or {},
                "log_entries": job.log_entries or [],
                "results_table": table,
                "running": running,
                "changelog_url": reverse("core:objectchange_list") + f"?request_id={job.job_id}",
            },
        )


@register_model_view(Collection, "list", path="", detail=False)
class CollectionListView(generic.ObjectListView):
    queryset = Collection.objects.select_related("device", "job")
    table = tables.CollectionTable
    filterset = filtersets.CollectionFilterSet
    filterset_form = forms.CollectionFilterForm
    actions = (BulkExport, BulkDelete)


@register_model_view(Collection)
class CollectionView(generic.ObjectView):
    queryset = Collection.objects.select_related("device", "job")
    actions = (DeleteObject,)


@register_model_view(Collection, "delete")
class CollectionDeleteView(generic.ObjectDeleteView):
    queryset = Collection.objects.all()
    default_return_url = "plugins:config_officer:collection_list"


@register_model_view(Collection, "bulk_delete", path="delete", detail=False)
class CollectionBulkDeleteView(generic.BulkDeleteView):
    queryset = Collection.objects.all()
    filterset = filtersets.CollectionFilterSet
    table = tables.CollectionTable
    default_return_url = "plugins:config_officer:collection_list"


# ---------------------------------------------------------------------------
# Device tabs and actions
# ---------------------------------------------------------------------------


@register_model_view(Device, name="config_officer_config", path="config-officer/configuration")
class DeviceConfigView(generic.ObjectView):
    """Device tab: last collected running config, collection status and git history."""

    queryset = Device.objects.all()
    template_name = "config_officer/device_config.html"
    tab = ViewTab(label=_("Configuration"), permission=VIEW_CONFIG, weight=2100)

    def get_queryset(self, request):
        return super().get_queryset(request).restrict(request.user, VIEW_CONFIG_ACTION)

    def get_extra_context(self, request, instance):
        repo = ConfigRepository.from_settings()
        context = {
            "latest_result": Collection.objects.filter(device=instance)
            .select_related("job")
            .first(),
            "can_collect": request.user.has_perm(COLLECT_CONFIG, instance),
            "snapshot": None,
            "worker_job_id": None,
        }
        if repo.is_available():
            # The web process sees the repository: read it directly.
            context["snapshot"] = device_config_snapshot(repo, instance.name)
        else:
            # Typical when only the worker mounts the repository: ask the worker.
            rq_job = get_queue("high").enqueue(jobs.load_device_config_view, instance.pk)
            context["worker_job_id"] = rq_job.id if rq_job is not None else None
        return context


class DeviceConfigStatusView(PermissionRequiredView):
    """Polled by the Configuration tab while the worker reads the repository."""

    permission_required = (VIEW_CONFIG,)

    def get(self, request, pk):
        device = get_object_or_404(Device.objects.restrict(request.user, VIEW_CONFIG_ACTION), pk=pk)
        try:
            rq_job = RQJob.fetch(
                request.GET.get("job", ""), connection=get_queue("high").connection
            )
        except NoSuchJobError:
            return JsonResponse({"error": "job not found or expired"}, status=404)
        # Only hand out results of our own job for this very device.
        if rq_job.func_name != "config_officer.jobs.load_device_config_view" or tuple(
            rq_job.args
        ) != (device.pk,):
            return JsonResponse({"error": "job not found or expired"}, status=404)
        if rq_job.is_failed:
            return JsonResponse({"ready": False, "failed": True})
        if not rq_job.is_finished:
            return JsonResponse({"ready": False, "failed": False})
        return JsonResponse({"ready": True, **rq_job.return_value()})


@register_model_view(Device, name="config_officer_compliance", path="config-officer/compliance")
class DeviceComplianceView(generic.ObjectView):
    """Device tab: compliance verdict, matching templates and missing lines."""

    queryset = Device.objects.all()
    template_name = "config_officer/device_compliance.html"
    tab = ViewTab(
        label=_("Compliance"),
        permission="config_officer.view_compliance",
        weight=2110,
        badge=lambda device: ServiceMapping.objects.filter(device=device).count(),
        hide_if_empty=True,
    )

    def get_extra_context(self, request, instance):
        return {
            "compliance": Compliance.objects.filter(device=instance).first(),
            "services": Service.objects.filter(servicemapping__device=instance).order_by("name"),
            "templates": templates_for_device(instance),
            "can_recheck": request.user.has_perm("config_officer.change_compliance"),
        }


class DeviceCollectView(PermissionRequiredView):
    """POST: collect one device now (the "Collect config" button on the device page)."""

    permission_required = (COLLECT_CONFIG,)

    def post(self, request, pk):
        device = get_object_or_404(
            Device.objects.restrict(request.user, COLLECT_CONFIG_ACTION), pk=pk
        )
        job = jobs.enqueue_collection(
            DeviceSelection(device_ids=(device.pk,)), request.user, trigger="device"
        )
        messages.success(
            request, format_html(_("Collection of {} queued as {}."), device, _run_link(job))
        )
        return redirect("plugins:config_officer:run", pk=job.pk)


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


@register_model_view(CollectSchedule, "list", path="", detail=False)
class CollectScheduleListView(generic.ObjectListView):
    queryset = CollectSchedule.objects.prefetch_related("device_tags", "tags")
    table = tables.CollectScheduleTable
    filterset = filtersets.CollectScheduleFilterSet
    filterset_form = forms.CollectScheduleFilterForm
    actions = (AddObject, BulkExport, BulkDelete)


@register_model_view(CollectSchedule)
class CollectScheduleView(generic.ObjectView):
    queryset = CollectSchedule.objects.prefetch_related("device_tags", "devices")
    actions = (EditObject, DeleteObject)

    def get_extra_context(self, request, instance):
        return {
            "next_job": jobs.next_scheduled_job(instance),
            "device_count": instance.get_selection().queryset().count(),
            "last_runs": Job.objects.filter(
                name__in=jobs.COLLECTION_JOB_NAMES,
                object_id=instance.pk,
                object_type__app_label="config_officer",
                object_type__model="collectschedule",
            ).order_by("-created")[:5],
            "can_collect": request.user.has_perm(COLLECT_CONFIG),
        }


@register_model_view(CollectSchedule, "add", detail=False)
@register_model_view(CollectSchedule, "edit")
class CollectScheduleEditView(generic.ObjectEditView):
    queryset = CollectSchedule.objects.all()
    form = forms.CollectScheduleForm
    # Creating a schedule means collecting devices, so the collect permission is required too.
    additional_permissions = [COLLECT_CONFIG]


@register_model_view(CollectSchedule, "delete")
class CollectScheduleDeleteView(generic.ObjectDeleteView):
    queryset = CollectSchedule.objects.all()


@register_model_view(CollectSchedule, "bulk_delete", path="delete", detail=False)
class CollectScheduleBulkDeleteView(generic.BulkDeleteView):
    queryset = CollectSchedule.objects.all()
    filterset = filtersets.CollectScheduleFilterSet
    table = tables.CollectScheduleTable


class CollectScheduleRunView(PermissionRequiredView):
    """POST: run a schedule now, once (its webhook is sent as well)."""

    permission_required = ("config_officer.view_collectschedule", COLLECT_CONFIG)

    def post(self, request, pk):
        schedule = get_object_or_404(CollectSchedule.objects.restrict(request.user, "view"), pk=pk)
        # Linked to the schedule (instance=...), so it shows up in the schedule's Jobs tab
        # and the run sends the schedule's webhook.
        job = jobs.CollectDevicesJob.enqueue(
            instance=schedule,
            user=request.user,
            selection=schedule.get_selection().as_dict(),
            trigger="schedule (run now)",
        )
        messages.success(
            request, format_html(_("Schedule {} queued as {}."), schedule, _run_link(job))
        )
        return redirect("plugins:config_officer:run", pk=job.pk)


# ---------------------------------------------------------------------------
# Compliance configuration: templates, services, rules
# ---------------------------------------------------------------------------


@register_model_view(Template, "list", path="", detail=False)
class TemplateListView(generic.ObjectListView):
    queryset = Template.objects.prefetch_related("tags")
    table = tables.TemplateTable
    filterset = filtersets.TemplateFilterSet
    filterset_form = forms.TemplateFilterForm
    actions = (AddObject, BulkExport, BulkDelete)


@register_model_view(Template)
class TemplateView(generic.ObjectView):
    queryset = Template.objects.all()

    def get_extra_context(self, request, instance):
        return {
            "rules": ServiceRule.objects.restrict(request.user, "view")
            .filter(template=instance)
            .select_related("service")
        }


@register_model_view(Template, "add", detail=False)
@register_model_view(Template, "edit")
class TemplateEditView(generic.ObjectEditView):
    queryset = Template.objects.all()
    form = forms.TemplateForm


@register_model_view(Template, "delete")
class TemplateDeleteView(generic.ObjectDeleteView):
    queryset = Template.objects.all()


@register_model_view(Template, "bulk_delete", path="delete", detail=False)
class TemplateBulkDeleteView(generic.BulkDeleteView):
    queryset = Template.objects.all()
    filterset = filtersets.TemplateFilterSet
    table = tables.TemplateTable


@register_model_view(Service, "list", path="", detail=False)
class ServiceListView(generic.ObjectListView):
    queryset = Service.objects.annotate(
        rule_count=Count("service_rules", distinct=True),
        device_count=Count("servicemapping", distinct=True),
    )
    table = tables.ServiceTable
    filterset = filtersets.ServiceFilterSet
    filterset_form = forms.ServiceFilterForm
    actions = (AddObject, BulkExport, BulkDelete)


@register_model_view(Service)
class ServiceView(generic.ObjectView):
    queryset = Service.objects.all()

    def get_extra_context(self, request, instance):
        rules = (
            ServiceRule.objects.restrict(request.user, "view")
            .filter(service=instance)
            .select_related("template")
            .prefetch_related("device_roles", "device_types")
        )
        rules_table = tables.ServiceRuleTable(rules, exclude=("pk", "service"))
        rules_table.configure(request)
        return {
            "rules_table": rules_table,
            "device_count": ServiceMapping.objects.filter(service=instance).count(),
        }


@register_model_view(Service, "add", detail=False)
@register_model_view(Service, "edit")
class ServiceEditView(generic.ObjectEditView):
    queryset = Service.objects.all()
    form = forms.ServiceForm


@register_model_view(Service, "delete")
class ServiceDeleteView(generic.ObjectDeleteView):
    queryset = Service.objects.all()


@register_model_view(Service, "bulk_delete", path="delete", detail=False)
class ServiceBulkDeleteView(generic.BulkDeleteView):
    queryset = Service.objects.all()
    filterset = filtersets.ServiceFilterSet
    table = tables.ServiceTable


@register_model_view(ServiceRule, "list", path="", detail=False)
class ServiceRuleListView(generic.ObjectListView):
    queryset = ServiceRule.objects.select_related("service", "template").prefetch_related(
        "device_roles", "device_types"
    )
    table = tables.ServiceRuleTable
    filterset = filtersets.ServiceRuleFilterSet
    filterset_form = forms.ServiceRuleFilterForm
    actions = (AddObject, BulkExport, BulkDelete)


@register_model_view(ServiceRule)
class ServiceRuleView(generic.ObjectView):
    queryset = ServiceRule.objects.select_related("service", "template").prefetch_related(
        "device_roles", "device_types"
    )


@register_model_view(ServiceRule, "add", detail=False)
@register_model_view(ServiceRule, "edit")
class ServiceRuleEditView(generic.ObjectEditView):
    queryset = ServiceRule.objects.all()
    form = forms.ServiceRuleForm


@register_model_view(ServiceRule, "delete")
class ServiceRuleDeleteView(generic.ObjectDeleteView):
    queryset = ServiceRule.objects.all()


@register_model_view(ServiceRule, "bulk_delete", path="delete", detail=False)
class ServiceRuleBulkDeleteView(generic.BulkDeleteView):
    queryset = ServiceRule.objects.all()
    filterset = filtersets.ServiceRuleFilterSet
    table = tables.ServiceRuleTable


# ---------------------------------------------------------------------------
# Compliance status of devices
# ---------------------------------------------------------------------------


class ComplianceListView(generic.ObjectListView):
    """All devices with their services and compliance verdict; bulk assign / detach / re-check."""

    queryset = Device.objects.select_related(
        "compliance", "site", "role", "device_type", "tenant", "primary_ip4"
    ).prefetch_related("servicemapping_set__service", "tags")
    table = tables.DeviceComplianceTable
    filterset = filtersets.DeviceComplianceFilterSet
    filterset_form = forms.DeviceComplianceFilterForm
    template_name = "config_officer/compliance_list.html"
    actions = (BulkExport,)
    additional_permissions = ["config_officer.view_compliance"]


def _selected_devices(request):
    pks = [pk for pk in request.POST.getlist("pk") if pk.isdigit()]
    return Device.objects.restrict(request.user, "view").filter(pk__in=pks)


class AssignServicesView(PermissionRequiredView):
    permission_required = ("config_officer.add_servicemapping",)

    def post(self, request):
        return_url = reverse("plugins:config_officer:compliance_list")
        if "_confirm" not in request.POST:  # coming from the device list: show the form
            devices = _selected_devices(request)
            if not devices.exists():
                messages.warning(request, _("No devices were selected."))
                return redirect(return_url)
            form = forms.AssignServicesForm(initial={"pk": [d.pk for d in devices]})
        else:
            form = forms.AssignServicesForm(request.POST)
            if form.is_valid():
                devices = form.cleaned_data["pk"].restrict(request.user, "view")
                services = form.cleaned_data["services"]
                replace = form.cleaned_data["replace"]
                if replace and not request.user.has_perm("config_officer.delete_servicemapping"):
                    return self.handle_no_permission()
                for device in devices:
                    if replace:
                        ServiceMapping.objects.filter(device=device).exclude(
                            service__in=services
                        ).delete()
                    for service in services:
                        ServiceMapping.objects.get_or_create(device=device, service=service)
                job = jobs.enqueue_compliance_check([d.pk for d in devices], request.user)
                messages.success(
                    request,
                    _(
                        "Assigned {services} to {count} device(s); compliance check queued (job #{job})."
                    ).format(
                        services=", ".join(s.name for s in services), count=len(devices), job=job.pk
                    ),
                )
                return redirect(return_url)
            devices = Device.objects.filter(pk__in=request.POST.getlist("pk"))
        return render(
            request,
            "config_officer/assign_services.html",
            {"form": form, "devices": devices, "return_url": return_url},
        )


class DetachServicesView(PermissionRequiredView):
    permission_required = ("config_officer.delete_servicemapping",)

    def post(self, request):
        devices = _selected_devices(request)
        removed, _details = ServiceMapping.objects.filter(device__in=devices).delete()
        Compliance.objects.filter(device__in=devices).delete()
        messages.success(request, _("Removed {count} service assignment(s).").format(count=removed))
        return redirect("plugins:config_officer:compliance_list")


class RecheckComplianceView(PermissionRequiredView):
    permission_required = ("config_officer.change_compliance",)

    def post(self, request):
        device_ids = list(_selected_devices(request).values_list("pk", flat=True))
        if not device_ids:
            messages.warning(request, _("No devices were selected."))
        else:
            job = jobs.enqueue_compliance_check(device_ids, request.user)
            messages.success(
                request,
                _("Compliance check of {count} device(s) queued (job #{job}).").format(
                    count=len(device_ids), job=job.pk
                ),
            )
        return redirect(
            request.POST.get("return_url") or reverse("plugins:config_officer:compliance_list")
        )


# ---------------------------------------------------------------------------
# Legacy URLs (0.1.x), e.g. custom links pointing at /running_config/<hostname>/
# ---------------------------------------------------------------------------


class LegacyRunningConfigRedirect(ConditionalLoginRequiredMixin, View):
    def get(self, request, hostname):
        device = get_object_or_404(Device.objects.restrict(request.user, "view"), name=hostname)
        return redirect("dcim:device_config_officer_config", pk=device.pk)


class LegacyComplianceRedirect(ConditionalLoginRequiredMixin, View):
    def get(self, request, device):
        return redirect("dcim:device_config_officer_compliance", pk=device)
