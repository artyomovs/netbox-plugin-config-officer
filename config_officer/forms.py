from django import forms
from utilities.forms import (
    BootstrapMixin, 
    DynamicModelMultipleChoiceField,
    StaticSelect2,
    APISelectMultiple
)
from .choices import CollectStatusChoices
from .models import (
    Collection, 
    Template,
    Service,
    ServiceMapping
)
from dcim.models import DeviceRole, DeviceType, Device

BLANK_CHOICE = (('', '---------'),)


class CollectionFilterForm (BootstrapMixin, forms.ModelForm):
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
        fields = ['status', 'failed_reason']


class TemplateForm(BootstrapMixin, forms.ModelForm):
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
        fields = [
            'name', 'description', 'configuration'
        ]  



class ServiceForm(BootstrapMixin, forms.ModelForm):
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
        fields = [
            'name', 'description'
        ]  



class ServiceRuleForm(BootstrapMixin, forms.ModelForm):
    service = forms.ModelChoiceField(
        queryset=Service.objects.all(),
        widget=StaticSelect2()
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
        widget=StaticSelect2()
    )    

    class Meta:
        model = Template
        fields = [
            'service', 'device_role', 'device_type', 'template', 'description'
        ]  


class ServiceMappingForm(BootstrapMixin, forms.ModelForm):
    service = forms.ModelChoiceField(
        queryset=Service.objects.all(),
        widget=StaticSelect2()
    )

    device = forms.ModelChoiceField(
        queryset=Device.objects.all(),
        widget=StaticSelect2()
    )

    class Meta:
        model = ServiceMapping
        fields = [
            'service', 'device'
        ]  


class ServiceMappingCreateForm(BootstrapMixin, forms.Form):
    model = ServiceMapping
    pk = forms.ModelMultipleChoiceField(
        queryset=Device.objects.all(),
        widget=forms.MultipleHiddenInput()
    )
    service = forms.ModelMultipleChoiceField(
        queryset=Service.objects.all(),
        label='Service'
    )    

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
