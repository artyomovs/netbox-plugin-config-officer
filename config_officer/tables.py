"""Tables for config_officer plugin."""

import django_tables2 as tables
from utilities.tables import BaseTable, ToggleColumn
from .models import Collection

# Templates
TASK_STATUS = """
{{ record.status|default:"&mdash;" }}
"""

TASK_FAILED_REASON = """
{{ record.failed_reason|default:"&mdash;" }}
"""

MESSAGE = """
{{ record.message|default:"&mdash;" }}
"""

# Classes
class CollectionTable(BaseTable):
    pk = ToggleColumn()
    device = tables.LinkColumn(
        verbose_name='Hostname',
    )

    status = tables.TemplateColumn(
        template_code=TASK_STATUS,
        verbose_name='Status',
    )  

    failed_reason = tables.TemplateColumn(
        template_code=TASK_FAILED_REASON,
        verbose_name='Failed Reason',
    )

    message = tables.TemplateColumn(
        template_code=MESSAGE,
        verbose_name='Message',
    )      

    class Meta(BaseTable.Meta):
        model = Collection
        fields = (
            'pk',
            'timestamp',
            'device',
            'status',
            'failed_reason',
            'message',            
        )