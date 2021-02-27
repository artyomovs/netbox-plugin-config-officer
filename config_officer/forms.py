from django import forms
from utilities.forms import BootstrapMixin
from .choices import CollectStatusChoices
from .models import Collection

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