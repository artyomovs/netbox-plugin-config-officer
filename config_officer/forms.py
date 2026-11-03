"""Forms used by the UI views (model forms, list filter forms and action forms)."""

from dcim.choices import DeviceStatusChoices
from dcim.forms import DeviceFilterForm
from dcim.models import Device, DeviceRole, DeviceType
from django import forms
from django.utils.translation import gettext_lazy as _
from extras.models import Tag
from netbox.forms import NetBoxModelFilterSetForm, NetBoxModelForm
from utilities.forms import BOOLEAN_WITH_BLANK_CHOICES
from utilities.forms.fields import (
    DynamicModelChoiceField,
    DynamicModelMultipleChoiceField,
    TagFilterField,
)
from utilities.forms.rendering import FieldSet
from utilities.forms.widgets import DateTimePicker

from .choices import CollectFailChoices, CollectStatusChoices, ServiceComplianceChoices
from .collection.targets import DeviceSelection
from .models import Collection, CollectSchedule, Service, ServiceRule, Template

# ---------------------------------------------------------------------------
# Compliance configuration
# ---------------------------------------------------------------------------


class TemplateForm(NetBoxModelForm):
    configuration = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 16, "class": "font-monospace"}),
        help_text=_(
            "Configuration lines the device must contain. Indented lines belong to the section above "
            "them. <code>{{ anything }}</code> matches any value, e.g. <code>ntp server {{ ip }}</code>."
        ),
    )
    fieldsets = (
        FieldSet("name", "description", "configuration", name=_("Template")),
        FieldSet("tags", name=_("Tags")),
    )

    class Meta:
        model = Template
        fields = ("name", "description", "configuration", "tags")


class TemplateFilterForm(NetBoxModelFilterSetForm):
    model = Template
    service_id = DynamicModelMultipleChoiceField(
        queryset=Service.objects.all(), required=False, label=_("Service")
    )
    tag = TagFilterField(model)
    fieldsets = (FieldSet("q", "filter_id", "tag"), FieldSet("service_id", name=_("Usage")))


class ServiceForm(NetBoxModelForm):
    fieldsets = (
        FieldSet("name", "description", name=_("Service")),
        FieldSet("tags", name=_("Tags")),
    )

    class Meta:
        model = Service
        fields = ("name", "description", "tags")


class ServiceFilterForm(NetBoxModelFilterSetForm):
    model = Service
    tag = TagFilterField(model)
    fieldsets = (FieldSet("q", "filter_id", "tag"),)


class ServiceRuleForm(NetBoxModelForm):
    service = DynamicModelChoiceField(queryset=Service.objects.all())
    template = DynamicModelChoiceField(queryset=Template.objects.all())
    device_roles = DynamicModelMultipleChoiceField(
        queryset=DeviceRole.objects.all(),
        required=False,
        help_text=_("Leave empty to match any role."),
    )
    device_types = DynamicModelMultipleChoiceField(
        queryset=DeviceType.objects.all(),
        required=False,
        help_text=_("Leave empty to match any device type."),
    )
    fieldsets = (
        FieldSet("service", "template", "description", name=_("Rule")),
        FieldSet("device_roles", "device_types", name=_("Applies to")),
        FieldSet("tags", name=_("Tags")),
    )

    class Meta:
        model = ServiceRule
        fields = ("service", "template", "description", "device_roles", "device_types", "tags")


class ServiceRuleFilterForm(NetBoxModelFilterSetForm):
    model = ServiceRule
    service_id = DynamicModelMultipleChoiceField(
        queryset=Service.objects.all(), required=False, label=_("Service")
    )
    template_id = DynamicModelMultipleChoiceField(
        queryset=Template.objects.all(), required=False, label=_("Template")
    )
    device_role_id = DynamicModelMultipleChoiceField(
        queryset=DeviceRole.objects.all(), required=False, label=_("Role")
    )
    device_type_id = DynamicModelMultipleChoiceField(
        queryset=DeviceType.objects.all(), required=False, label=_("Device type")
    )
    tag = TagFilterField(model)
    fieldsets = (
        FieldSet("q", "filter_id", "tag"),
        FieldSet(
            "service_id", "template_id", "device_role_id", "device_type_id", name=_("Attributes")
        ),
    )


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

INTERVAL_PRESETS = [
    (1, _("Every hour")),
    (4, _("Every 4 hours")),
    (6, _("Every 6 hours")),
    (12, _("Every 12 hours")),
    (24, _("Once a day")),
    (48, _("Every 2 days")),
    (168, _("Once a week")),
]


class CollectScheduleForm(NetBoxModelForm):
    interval_hours = forms.TypedChoiceField(
        coerce=int, choices=INTERVAL_PRESETS, initial=24, label=_("Interval")
    )
    next_run = forms.DateTimeField(
        widget=DateTimePicker(),
        label=_("Start at"),
        help_text=_("First run; the following runs keep this time of day / cadence."),
    )
    devices = DynamicModelMultipleChoiceField(
        queryset=Device.objects.all(), required=False, selector=True
    )
    device_tags = DynamicModelMultipleChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        label=_("Device tags"),
        help_text=_("Devices with at least one of these tags (resolved at each run)."),
    )
    webhook_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text=_("Leave empty to keep the current secret."),
    )
    clear_webhook_secret = forms.BooleanField(required=False, label=_("Remove the webhook secret"))
    fieldsets = (
        FieldSet("name", "enabled", "interval_hours", "next_run", name=_("Schedule")),
        FieldSet("all_devices", "device_tags", "devices", name=_("Devices")),
        FieldSet("webhook_url", "webhook_secret", "clear_webhook_secret", name=_("Webhook")),
        FieldSet("tags", name=_("Tags")),
    )

    class Meta:
        model = CollectSchedule
        fields = (
            "name",
            "enabled",
            "interval_hours",
            "next_run",
            "all_devices",
            "device_tags",
            "devices",
            "webhook_url",
            "webhook_secret",
            "tags",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep intervals that are not in the presets (e.g. set through the API) selectable.
        current = self.instance.interval_hours if self.instance.pk else None
        if current and current not in dict(INTERVAL_PRESETS):
            self.fields["interval_hours"].choices = [
                *INTERVAL_PRESETS,
                (current, _("Every {n} hours").format(n=current)),
            ]

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if not (data.get("all_devices") or data.get("devices") or data.get("device_tags")):
            raise forms.ValidationError(
                _("Choose all devices, at least one tag or at least one device.")
            )
        if data.get("clear_webhook_secret"):
            data["webhook_secret"] = ""
        elif not data.get("webhook_secret") and self.instance.pk:
            data["webhook_secret"] = self.instance.webhook_secret  # unchanged
        return data


class CollectScheduleFilterForm(NetBoxModelFilterSetForm):
    model = CollectSchedule
    enabled = forms.NullBooleanField(
        required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES)
    )
    all_devices = forms.NullBooleanField(
        required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES)
    )
    tag = TagFilterField(model)
    fieldsets = (
        FieldSet("q", "filter_id", "tag"),
        FieldSet("enabled", "all_devices", name=_("Schedule")),
    )


class CollectionFilterForm(NetBoxModelFilterSetForm):
    model = Collection
    status = forms.MultipleChoiceField(choices=CollectStatusChoices, required=False)
    failed_reason = forms.MultipleChoiceField(choices=CollectFailChoices, required=False)
    config_changed = forms.NullBooleanField(
        required=False,
        label=_("Config changed"),
        widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    device_id = DynamicModelMultipleChoiceField(
        queryset=Device.objects.all(), required=False, label=_("Device")
    )
    fieldsets = (
        FieldSet("q", "filter_id"),
        FieldSet("status", "failed_reason", "config_changed", "device_id", name=_("Result")),
    )


class RunCollectionForm(forms.Form):
    """'Run collection' card on the collection page."""

    TARGET_ALL, TARGET_TAGS, TARGET_DEVICES = "all", "tags", "devices"

    target = forms.ChoiceField(
        choices=(
            (TARGET_TAGS, _("Devices with tags")),
            (TARGET_DEVICES, _("Selected devices")),
            (TARGET_ALL, _("All devices")),
        ),
        initial=TARGET_TAGS,
        widget=forms.RadioSelect,
    )
    tags = DynamicModelMultipleChoiceField(
        queryset=Tag.objects.all(), required=False, label=_("Tags")
    )
    devices = DynamicModelMultipleChoiceField(
        queryset=Device.objects.all(), required=False, selector=True
    )
    statuses = forms.MultipleChoiceField(
        choices=DeviceStatusChoices,
        required=False,
        label=_("Only status"),
        help_text=_("Optional: only devices with these statuses."),
    )

    def clean(self):
        data = super().clean()
        target = data.get("target")
        if target == self.TARGET_TAGS and not data.get("tags"):
            self.add_error("tags", _("Select at least one tag."))
        if target == self.TARGET_DEVICES and not data.get("devices"):
            self.add_error("devices", _("Select at least one device."))
        return data

    def get_selection(self) -> DeviceSelection:
        data = self.cleaned_data
        target = data["target"]
        return DeviceSelection(
            all_devices=target == self.TARGET_ALL,
            tag_slugs=tuple(tag.slug for tag in data["tags"]) if target == self.TARGET_TAGS else (),
            device_ids=tuple(device.pk for device in data["devices"])
            if target == self.TARGET_DEVICES
            else (),
            statuses=tuple(data.get("statuses") or ()),
        )


# ---------------------------------------------------------------------------
# Compliance status (device list)
# ---------------------------------------------------------------------------


class DeviceComplianceFilterForm(DeviceFilterForm):
    compliance_status = forms.MultipleChoiceField(
        choices=ServiceComplianceChoices, required=False, label=_("Compliance status")
    )
    compliance_service_id = DynamicModelMultipleChoiceField(
        queryset=Service.objects.all(), required=False, label=_("Compliance service")
    )
    has_compliance_service = forms.NullBooleanField(
        required=False,
        label=_("Has a compliance service"),
        widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    fieldsets = (
        FieldSet(
            "compliance_status",
            "compliance_service_id",
            "has_compliance_service",
            name=_("Compliance"),
        ),
        *DeviceFilterForm.fieldsets,
    )


class AssignServicesForm(forms.Form):
    pk = forms.ModelMultipleChoiceField(
        queryset=Device.objects.all(), widget=forms.MultipleHiddenInput()
    )
    services = forms.ModelMultipleChoiceField(queryset=Service.objects.all(), label=_("Services"))
    replace = forms.BooleanField(
        required=False,
        initial=True,
        label=_("Replace existing assignments"),
        help_text=_("Unchecked: the services are added to the ones already assigned."),
    )
