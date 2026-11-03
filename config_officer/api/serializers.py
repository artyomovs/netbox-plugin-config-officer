"""REST API serializers."""

from core.api.serializers import JobSerializer
from dcim.api.serializers import DeviceRoleSerializer, DeviceSerializer, DeviceTypeSerializer
from extras.api.serializers import TagSerializer
from netbox.api.serializers import BaseModelSerializer, NetBoxModelSerializer
from rest_framework import serializers

from config_officer.models import (
    Collection,
    CollectSchedule,
    Compliance,
    Service,
    ServiceRule,
    Template,
)


class TemplateSerializer(NetBoxModelSerializer):
    class Meta:
        model = Template
        fields = (
            "id",
            "url",
            "display",
            "name",
            "description",
            "configuration",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "description")


class ServiceSerializer(NetBoxModelSerializer):
    class Meta:
        model = Service
        fields = (
            "id",
            "url",
            "display",
            "name",
            "description",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "description")


class ServiceRuleSerializer(NetBoxModelSerializer):
    service = ServiceSerializer(nested=True)
    template = TemplateSerializer(nested=True, required=False, allow_null=True)
    device_roles = DeviceRoleSerializer(nested=True, many=True, required=False)
    device_types = DeviceTypeSerializer(nested=True, many=True, required=False)

    class Meta:
        model = ServiceRule
        fields = (
            "id",
            "url",
            "display",
            "service",
            "template",
            "description",
            "device_roles",
            "device_types",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "service", "template")


class CollectScheduleSerializer(NetBoxModelSerializer):
    devices = DeviceSerializer(nested=True, many=True, required=False)
    device_tags = TagSerializer(nested=True, many=True, required=False)
    webhook_secret = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = CollectSchedule
        fields = (
            "id",
            "url",
            "display",
            "name",
            "enabled",
            "all_devices",
            "devices",
            "device_tags",
            "interval_hours",
            "next_run",
            "webhook_url",
            "webhook_secret",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "enabled")

    def validate(self, data):
        data = super().validate(data)
        instance = self.instance
        all_devices = data.get("all_devices", instance.all_devices if instance else False)
        devices = data.get("devices", instance.devices.all() if instance else [])
        tags = data.get("device_tags", instance.device_tags.all() if instance else [])
        if not (all_devices or devices or tags):
            raise serializers.ValidationError("Set all_devices, devices or device_tags.")
        return data


class CollectionSerializer(BaseModelSerializer):
    device = DeviceSerializer(nested=True, read_only=True)
    job = JobSerializer(nested=True, read_only=True)

    class Meta:
        model = Collection
        fields = (
            "id",
            "url",
            "display",
            "device",
            "job",
            "status",
            "failed_reason",
            "message",
            "transport",
            "config_changed",
            "duration",
            "details",
            "timestamp",
        )
        brief_fields = ("id", "url", "display", "status")


class ComplianceSerializer(BaseModelSerializer):
    device = DeviceSerializer(nested=True, read_only=True)

    class Meta:
        model = Compliance
        fields = (
            "id",
            "url",
            "display",
            "device",
            "status",
            "notes",
            "diff",
            "generated_config",
            "services",
            "last_checked",
        )
        brief_fields = ("id", "url", "display", "status")


class RunCollectionSerializer(serializers.Serializer):
    """Body of POST /runs/: which devices to collect."""

    all_devices = serializers.BooleanField(default=False)
    tags = serializers.ListField(child=serializers.SlugField(), default=list, help_text="Tag slugs")
    devices = serializers.ListField(
        child=serializers.IntegerField(), default=list, help_text="Device IDs"
    )
    statuses = serializers.ListField(
        child=serializers.CharField(), default=list, help_text="Device statuses"
    )

    def validate(self, data):
        if not (data["all_devices"] or data["tags"] or data["devices"]):
            raise serializers.ValidationError("Set all_devices, tags or devices.")
        return data
