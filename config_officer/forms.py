from django import forms
from netbox.forms import NetBoxModelForm
from utilities.forms.widgets import APISelectMultiple, DateTimePicker
from utilities.forms import BootstrapMixin
from utilities.forms.fields import DynamicModelMultipleChoiceField, TagFilterField
from .choices import CollectStatusChoices
from .models import (
    Collection,
    Template,
    ProvidedService,
    ServiceMapping
)
from dcim.models import DeviceRole, DeviceType, Device
from tenancy.models import Tenant
from .choices import ServiceComplianceChoices




BLANK_CHOICE = (('', '---------'),)


class CollectionFilterForm (BootstrapMixin, NetBoxModelForm):
    """Form fo filtering information about collection run-config tasks."""

    status = forms.ChoiceField(
        choices=BLANK_CHOICE + CollectStatusChoices.CHOICES,
        required=False,
        label = 'Status'
    )

    failed_reason = forms.ChoiceField(
        choices=BLANK_CHOICE + CollectStatusChoices.CHOICES,
        required=False,
        label='Failed Reason',
    )

    class Meta:
        model = Collection
        fields = ('status', 'failed_reason')


class TemplateForm(BootstrapMixin, NetBoxModelForm):
    name = forms.CharField(
        required=True,
        label = "Name",
    )

    description = forms.CharField(
        required=False,
        label = "Description",
    )

    class Meta:
        model = Template
        fields = ('name', 'description', 'configuration')


class ServiceForm(BootstrapMixin, NetBoxModelForm):
    name = forms.CharField(
        required=True,
        label = "Name",
    )

    description = forms.CharField(
        required=False,
        label = "Description",
    )

    class Meta:
        model = Template
        fields = ('name', 'description')


class ServiceRuleForm(BootstrapMixin, NetBoxModelForm):
    service = forms.ModelChoiceField(
        queryset=ProvidedService.objects.all(),
        widget=BootstrapMixin()
    )

    description = forms.CharField(
        required=False,
        label = "Description",
    )

    device_role = DynamicModelMultipleChoiceField(
        queryset=DeviceRole.objects.all(),
        required=True,
    )

    device_type = DynamicModelMultipleChoiceField(
        queryset=DeviceType.objects.all(),
        required=False,
        label='Model',
        display_field="model",
        widget=APISelectMultiple(
        )
    )

    template = forms.ModelChoiceField(
        queryset=Template.objects.order_by('name'),
        widget=BootstrapMixin()
    )

    class Meta:
        model = Template
        fields = ('service', 'device_role', 'device_type', 'template', 'description',)


class ServiceMappingForm(BootstrapMixin, NetBoxModelForm):
    service = forms.ModelChoiceField(
        queryset=ProvidedService.objects.all(),
        widget=BootstrapMixin()
    )

    device = forms.ModelChoiceField(
        queryset=Device.objects.all(),
        widget=BootstrapMixin()
    )

    class Meta:
        model = ServiceMapping
        fields = ('service', 'device')


class ServiceMappingCreateForm(BootstrapMixin, forms.Form):
    model = ServiceMapping
    pk = forms.ModelMultipleChoiceField(
        queryset=Device.objects.all(),
        widget=forms.MultipleHiddenInput()
    )
    service = forms.ModelMultipleChoiceField(
        queryset=ProvidedService.objects.all(),
        label='Service'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ServiceMappingFilterForm(BootstrapMixin, NetBoxModelForm):
    model = Device
    field_order = ('q', 'status', 'role', 'tenant', 'device_type_id', 'tag')
    q = forms.CharField(
        required=False,
        label='Search device or service'
    )
    tenant = DynamicModelMultipleChoiceField(
        queryset=Tenant.objects.all(),
        to_field_name='slug',
        required=False,
        widget=APISelectMultiple(
            # value_field="slug",
            # null_option=True,
        )
    )
    role = DynamicModelMultipleChoiceField(
        queryset=DeviceRole.objects.all(),
        to_field_name='slug',
        required=False,
        widget=APISelectMultiple(
            # value_field="slug",
        )
    )
    device_type_id = DynamicModelMultipleChoiceField(
        queryset=DeviceType.objects.all(),
        required=False,
        label='Model',
        display_field="model",
        widget=APISelectMultiple(
        )
    )
    status = forms.MultipleChoiceField(
        label='Status',
        choices=ServiceComplianceChoices,
        required=False,
        widget=BootstrapMixin()
    )

    tag = TagFilterField(model)

    class Meta:
        model = Device
        fields = ('q', 'status', 'role', 'tenant', 'device_type_id', 'tag')
