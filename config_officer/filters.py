from utilities.filters import TreeNodeMultipleChoiceFilter
import django_filters
from .models import Collection
from django.db.models import Q
from dcim.models import DeviceRole, DeviceType
from .choices import ServiceComplianceChoices
from netbox.filtersets import NetBoxModelFilterSet
from extras.filters import TagFilter
from dcim.models import Device
from tenancy.filtersets import TenancyFilterSet


class CollectionFilter(NetBoxModelFilterSet):
    q = django_filters.CharFilter(method="search")

    class Meta:
        model = Collection
        fields = ["status", "failed_reason"]

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        qs_filter = Q(status__icontains=value) | Q(failed_reason__icontains=value)
        return queryset.filter(qs_filter)


class ServiceMappingFilter(NetBoxModelFilterSet, TenancyFilterSet):
    """Filter for template-compliance records."""

    q = django_filters.CharFilter(
        method="search",
        label="Search device or service",
    )
    device_type_id = django_filters.ModelMultipleChoiceFilter(
        queryset=DeviceType.objects.all(),
        label="Device type (ID)",
    )
    role_id = django_filters.ModelMultipleChoiceFilter(
        field_name="device_role_id",
        queryset=DeviceRole.objects.all(),
        label="Role (ID)",
    )
    role = django_filters.ModelMultipleChoiceFilter(
        field_name="device_role__slug",
        queryset=DeviceRole.objects.all(),
        to_field_name="slug",
        label="Role (slug)",
    )

    device_model = django_filters.ModelMultipleChoiceFilter(
        field_name="device_type__slug",
        queryset=DeviceType.objects.all(),
        to_field_name="slug",
        label="Device model (slug)",
    )

    status = django_filters.MultipleChoiceFilter(
        field_name="compliance__status",
        choices=ServiceComplianceChoices,
        null_value=None,
    )

    tag = TagFilter()

    class Meta:
        model = Device
        fields = ["id", "status", "name", "asset_tag", "device_model"]

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value)
            | Q(asset_tag__icontains=value.strip())
            | Q(compliance__services__contains=value.strip().splitlines())
        ).distinct()
