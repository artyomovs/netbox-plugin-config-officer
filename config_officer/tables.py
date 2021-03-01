"""Tables for config_officer plugin."""

import django_tables2 as tables
from utilities.tables import BaseTable, ToggleColumn, ColoredLabelColumn, TagColumn
from .models import (
    Collection, 
    Template,
    Service
)
from tenancy.tables import COL_TENANT
from django_tables2.utils import Accessor
from dcim.models import Device

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

TEMPLATE_LINK = """
<a href="{% url 'plugins:config_officer:template' pk=record.pk %}">
    {{ record.name|default:"&mdash;" }}
</a>
"""

DESCRIPTION = """{{ record.description|default:"&mdash;" }}"""

TEMPLATE_TEXT = """
<button type="button" id='button_collapse' class="btn btn-link collapsed text-muted" data-toggle="collapse" data-target=#input_area_{{ record.pk }}>Collapse/Expand</button>
<div class="w-100">
    <div id=input_area_{{ record.pk }} class="width:20px collapse multi-collapse">        
        <pre>{{ record.configuration }}</pre>
    </div>
</div>
"""

SERVICE_TEMPLATES = """
{% for service in record.get_services_list %}
    <a href="{% url 'plugins:config_officer:service' pk=service.pk %}">
        {{ service.name|default:"&mdash;" }}
    </a><br>
{% endfor %}
"""

SERVICE_LINK = """
<a href="{% url 'plugins:config_officer:service' pk=record.pk %}">
    {{ record.name|default:"&mdash;" }}
</a>
"""

DEVICE_COUNT = """{{ record.get_devices_count }}"""

RULES_COUNT = """{{ record.get_service_rules_count }}"""


RULE_SERVICE_LINK = """
<a href="{% url 'plugins:config_officer:service' pk=record.service.pk %}">
    {{ record.service|default:"&mdash;" }}
</a>
"""

DEVICE_ROLE = """{{ record.device_role|default:"all" }}"""

DEVICE_TYPE = """{{ record.device_type|default:"all" }}"""

RULE_TEMPLATE_LINK = """
<a href="{% url 'plugins:config_officer:template' pk=record.template.pk %}">
    {{ record.template|default:"&mdash;" }}
</a>
"""

SERVICE_MAPPING_DEVICE_LINK = """
<a href="{% url 'dcim:device' pk=record.pk %}">
    {{ record|default:'<span class="label label-info">UNKNOWN DEVICE</span>' }}
</a>
"""


ATTACHED_SERVICES_LIST = """
{% if record.compliance %}
    {% for service in record.compliance.get_services_list_for_device %}
        <a href="{% url 'plugins:config_officer:service' pk=service.pk %}">
            {{ service.name|default:"&mdash;" }}
        </a><br>
    {% endfor %}
{% else %}
    &mdash;
{% endif %}
"""


COMPLIANCE_STATUS = """
{% if record.compliance %}
    <a href="{% url 'plugins:config_officer:compliance' device=record.pk %}">
        {% if record.compliance.status == 'compliance' %}
            <label class="label" style="background-color: green">{{ record.compliance.status }}</label>
        {% else %}
            <label class="label" style="background-color: red">{{ record.compliance.status }}</label>
        {% endif %}
    </a>
{% endif %}
"""


COMPLIANCE_NOTES = """
{% if record.compliance %}
    <span class="text-nowrap">    
        {% if record.compliance.notes %}        
            <p class="text-warning">{{ record.compliance.notes|default:"&mdash;" }}</p>
        {% else %}
            <a href="{% url 'plugins:config_officer:compliance' device=record.pk %}">
                details
            </a>
        {% endif %}                     
    </span>
{% else %}
    &mdash;
{% endif %}
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


class TemplateListTable(BaseTable):
    """Template list table."""

    pk = ToggleColumn()

    name = tables.TemplateColumn(
        order_by=("name",), template_code=TEMPLATE_LINK, verbose_name="Template"
    )

    description = tables.TemplateColumn(
        template_code=DESCRIPTION,
        verbose_name="Description",
    )

    configuration = tables.TemplateColumn(
        template_code=TEMPLATE_TEXT,
        verbose_name="Text",
    )

    services = tables.TemplateColumn(
        template_code=SERVICE_TEMPLATES,
        verbose_name="Services",
        orderable=False,
    )    

    class Meta(BaseTable.Meta):
        model = Template
        fields = ("pk", "name", "description", "configuration", "services")


class ServiceListTable(BaseTable):
    pk = ToggleColumn()

    name = tables.TemplateColumn(
        order_by=("name",), template_code=SERVICE_LINK, verbose_name="Service"
    )

    description = tables.TemplateColumn(
        template_code=DESCRIPTION,
        verbose_name="Description",
    )

    devices_count = tables.TemplateColumn(
        template_code=DEVICE_COUNT,
        verbose_name="Devices",
        orderable=False,
    )

    rules_count = tables.TemplateColumn(
        template_code=RULES_COUNT,
        verbose_name="Rules",
        orderable=False,
    )    


    class Meta(BaseTable.Meta):
        model = Service
        fields = ("name", "description", "devices_count", "rules_count")        
        

class ServiceRuleListTable(BaseTable):
    pk = ToggleColumn()

    service = tables.TemplateColumn(
        template_code=RULE_SERVICE_LINK,
        verbose_name="Service",
    )

    device_role = tables.TemplateColumn(
        template_code=DEVICE_ROLE, verbose_name="Device role"
    )

    device_type = tables.TemplateColumn(
        template_code=DEVICE_TYPE, verbose_name="Device type"
    )

    template = tables.TemplateColumn(
        template_code=RULE_TEMPLATE_LINK, verbose_name="Device role"
    )

    description = tables.TemplateColumn(
        template_code=DESCRIPTION,
        verbose_name="Description",
    )


    class Meta(BaseTable.Meta):
        model = Service
        fields = ("service", "device_role", "device_type", "template", "description")


class ServiceMappingListTable(BaseTable):
    pk = ToggleColumn()
    name = tables.TemplateColumn(
        order_by=("name",), template_code=SERVICE_MAPPING_DEVICE_LINK,
        verbose_name='Device'
    )
    service = tables.TemplateColumn(
        template_code=ATTACHED_SERVICES_LIST,
        verbose_name="Service",
        orderable=False,
    )
    tenant = tables.TemplateColumn(template_code=COL_TENANT)
    device_role = ColoredLabelColumn(verbose_name="Role")
    device_type = tables.LinkColumn(
        viewname="dcim:devicetype",
        args=[Accessor("device_type.pk")],
        verbose_name="Type",
    )
    tags = TagColumn(url_name="dcim:device_list")

    status = tables.TemplateColumn(
        template_code=COMPLIANCE_STATUS,
        verbose_name="Status",
    )

    notes = tables.TemplateColumn(
        template_code=COMPLIANCE_NOTES,
        verbose_name="Notes",
        orderable=False,
    )

    class Meta(BaseTable.Meta):
        model = Device
        fields = (
            "pk",
            "name",
            "service",
            "tenant",
            "device_role",
            "device_type",
            "tags",
            "status",
            "notes"
        )
