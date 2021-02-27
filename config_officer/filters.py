from utilities.filters import NameSlugSearchFilterSet
import django_filters
from .models import Collection
from django.db.models import Q


class CollectionFilter(NameSlugSearchFilterSet):
    q = django_filters.CharFilter(
        method = 'search'
    )

    class Meta:
        model = Collection
        fields = ['status', 'failed_reason']

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        qs_filter = (
            Q(status__icontains=value)
            | Q(failed_reason__icontains=value)
        )
        return queryset.filter(qs_filter)        
