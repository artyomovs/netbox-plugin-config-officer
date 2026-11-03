"""FilterSets: query-string filters shared by the UI list views and the REST API."""

import django_filters
from core.models import Job
from dcim.filtersets import DeviceFilterSet
from dcim.models import Device, DeviceRole, DeviceType
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from netbox.filtersets import BaseFilterSet, NetBoxModelFilterSet

from .choices import (
    CollectFailChoices,
    CollectStatusChoices,
    ServiceComplianceChoices,
    TransportChoices,
)
from .models import Collection, CollectSchedule, Service, ServiceRule, Template


class TemplateFilterSet(NetBoxModelFilterSet):
    service_id = django_filters.ModelMultipleChoiceFilter(
        field_name="servicerule__service",
        queryset=Service.objects.all(),
        distinct=True,
        label=_("Used by service (ID)"),
    )

    class Meta:
        model = Template
        fields = ("id", "name", "description")

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value)
            | Q(description__icontains=value)
            | Q(configuration__icontains=value)
        )


class ServiceFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = Service
        fields = ("id", "name", "description")

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))


class ServiceRuleFilterSet(NetBoxModelFilterSet):
    service_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Service.objects.all(), label=_("Service (ID)")
    )
    template_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Template.objects.all(), label=_("Template (ID)")
    )
    device_role_id = django_filters.ModelMultipleChoiceFilter(
        field_name="device_roles", queryset=DeviceRole.objects.all(), label=_("Device role (ID)")
    )
    device_type_id = django_filters.ModelMultipleChoiceFilter(
        field_name="device_types", queryset=DeviceType.objects.all(), label=_("Device type (ID)")
    )

    class Meta:
        model = ServiceRule
        fields = ("id", "description")

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(description__icontains=value)
            | Q(service__name__icontains=value)
            | Q(template__name__icontains=value)
        )


class CollectScheduleFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = CollectSchedule
        fields = ("id", "name", "enabled", "all_devices", "interval_hours")

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(name__icontains=value)


class CollectionFilterSet(BaseFilterSet):
    q = django_filters.CharFilter(method="search", label=_("Search"))
    device_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Device.objects.all(), label=_("Device (ID)")
    )
    device = django_filters.ModelMultipleChoiceFilter(
        field_name="device__name",
        to_field_name="name",
        queryset=Device.objects.all(),
        label=_("Device (name)"),
    )
    job_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Job.objects.all(), label=_("Run (job ID)")
    )
    status = django_filters.MultipleChoiceFilter(choices=CollectStatusChoices)
    failed_reason = django_filters.MultipleChoiceFilter(choices=CollectFailChoices)
    transport = django_filters.MultipleChoiceFilter(choices=TransportChoices)

    class Meta:
        model = Collection
        fields = ("id", "config_changed")

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(Q(device__name__icontains=value) | Q(message__icontains=value))


class DeviceComplianceFilterSet(DeviceFilterSet):
    """All standard device filters plus compliance-specific ones (compliance list view)."""

    compliance_service_id = django_filters.ModelMultipleChoiceFilter(
        field_name="servicemapping__service",
        queryset=Service.objects.all(),
        distinct=True,
        label=_("Compliance service (ID)"),
    )
    compliance_status = django_filters.MultipleChoiceFilter(
        field_name="compliance__status",
        choices=ServiceComplianceChoices,
        label=_("Compliance status"),
    )
    has_compliance_service = django_filters.BooleanFilter(
        method="filter_has_compliance_service",
        label=_("Has a compliance service"),
    )

    class Meta(DeviceFilterSet.Meta):
        pass

    def filter_has_compliance_service(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(servicemapping__isnull=not value).distinct()
