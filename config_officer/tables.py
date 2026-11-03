"""Tables for config_officer plugin - NetBox 4.x compatible."""

import django_tables2 as tables
from dcim.models import Device
from django_tables2.utils import Accessor
from netbox.tables import NetBoxTable, TagColumn, ToggleColumn

from .models import Collection, CollectSchedule, Service, ServiceRule, Template

# ---------------------------------------------------------------------------
# Template columns (raw HTML rendered inside TemplateColumn)
# ---------------------------------------------------------------------------

TEMPLATE_LINK = """
<a href="{% url 'plugins:config_officer:template' pk=record.pk %}">
    {{ record.name|default:"&mdash;" }}
</a>
"""

TEMPLATE_TEXT = """
<button type="button" class="btn btn-link btn-sm collapsed text-muted p-0"
        data-bs-toggle="collapse" data-bs-target="#cfg_{{ record.pk }}">
    Expand
</button>
<div id="cfg_{{ record.pk }}" class="collapse">
    <pre class="m-0 mt-1 small"><code>{{ record.configuration }}</code></pre>
</div>
"""

SERVICE_TEMPLATES = """
{% for service in record.get_services_list %}
    <a href="{% url 'plugins:config_officer:service' pk=service.pk %}">{{ service.name }}</a><br>
{% empty %}
    &mdash;
{% endfor %}
"""

TEMPLATE_ACTIONS = """
<a href="{% url 'plugins:config_officer:template_edit' pk=record.pk %}"
   class="btn btn-warning btn-sm" title="Edit"><i class="mdi mdi-pencil"></i></a>
<a href="{% url 'plugins:config_officer:template_delete' pk=record.pk %}"
   class="btn btn-danger btn-sm" title="Delete"><i class="mdi mdi-trash-can"></i></a>
"""

SERVICE_LINK = """
<a href="{% url 'plugins:config_officer:service' pk=record.pk %}">
    {{ record.name|default:"&mdash;" }}
</a>
"""

SERVICE_ACTIONS = """
<a href="{% url 'plugins:config_officer:service_edit' pk=record.pk %}"
   class="btn btn-warning btn-sm" title="Edit"><i class="mdi mdi-pencil"></i></a>
<a href="{% url 'plugins:config_officer:service_delete' pk=record.pk %}"
   class="btn btn-danger btn-sm" title="Delete"><i class="mdi mdi-trash-can"></i></a>
"""

RULE_SERVICE_LINK = """
<a href="{% url 'plugins:config_officer:service' pk=record.service.pk %}">
    {{ record.service|default:"&mdash;" }}
</a>
"""

RULE_TEMPLATE_LINK = """
{% if record.template %}
<a href="{% url 'plugins:config_officer:template' pk=record.template.pk %}">
    {{ record.template }}
</a>
{% else %}
&mdash;
{% endif %}
"""

DEVICE_ROLE = """{{ record.device_role.all|join:", "|default:"any" }}"""
DEVICE_TYPE = """{{ record.device_type.all|join:", "|default:"any" }}"""

RULE_ACTIONS = """
<a href="{% url 'plugins:config_officer:service_rule_edit' pk=record.pk %}"
   class="btn btn-warning btn-sm" title="Edit"><i class="mdi mdi-pencil"></i></a>
<a href="{% url 'plugins:config_officer:service_rule_delete' pk=record.pk %}"
   class="btn btn-danger btn-sm" title="Delete"><i class="mdi mdi-trash-can"></i></a>
"""

SERVICE_MAPPING_DEVICE_LINK = """
<a href="{% url 'dcim:device' pk=record.pk %}">
    {{ record.name|default:"UNKNOWN" }}
</a>
"""

ATTACHED_SERVICES_LIST = """
{% if record.compliance %}
    {% for service in record.compliance.get_services %}
        <a href="{% url 'plugins:config_officer:service' pk=service.pk %}">{{ service.name }}</a><br>
    {% empty %}
        &mdash;
    {% endfor %}
{% else %}
    &mdash;
{% endif %}
"""

COMPLIANCE_STATUS = """
{% if record.compliance %}
    <a href="{% url 'plugins:config_officer:compliance' device=record.pk %}">
        {% if record.compliance.status == 'compliance' %}
            <span class="badge bg-success">{{ record.compliance.status }}</span>
        {% else %}
            <span class="badge bg-danger">{{ record.compliance.status }}</span>
        {% endif %}
    </a>
{% else %}
    &mdash;
{% endif %}
"""

COMPLIANCE_NOTES = """
{% if record.compliance %}
    {% if record.compliance.notes %}
        <span class="text-warning">{{ record.compliance.notes }}</span>
    {% else %}
        <a href="{% url 'plugins:config_officer:compliance' device=record.pk %}">details</a>
    {% endif %}
{% else %}
    &mdash;
{% endif %}
"""

COLLECTION_DELETE = """
<a href="?pk={{ record.pk }}" class="btn btn-danger btn-sm" title="Delete">
    <i class="mdi mdi-trash-can"></i>
</a>
"""

COLLECT_SCHEDULE = """
<a href="{% url 'plugins:config_officer:collectschedule_edit' pk=record.pk %}"
    class="btn btn-sm btn-warning">Edit</a>
<a href="{% url 'plugins:config_officer:collectschedule_delete' pk=record.pk %}"
    class="btn btn-sm btn-danger ms-1">Delete</a>
<a href="{% url 'plugins:config_officer:collectschedule_run_now' pk=record.pk %}"
    class="btn btn-sm btn-primary ms-1">Run now</a>
"""


# ---------------------------------------------------------------------------
# Collection
#
# MUST use plain tables.Table, NOT NetBoxTable.
# NetBoxTable auto-generates links to '<model>_edit' and '<model>_delete' URL
# names via its ActionsColumn. Collection has no standard NetBox CRUD views,
# so those URL names don't exist -> NoReverseMatch crash.
# ---------------------------------------------------------------------------


class CollectionTable(tables.Table):
    pk = ToggleColumn()
    device = tables.Column(
        verbose_name="Hostname",
        linkify=lambda record: record.device.get_absolute_url() if record.device else None,
    )
    status = tables.Column(verbose_name="Status")
    failed_reason = tables.Column(verbose_name="Failed Reason")
    message = tables.Column(verbose_name="Message")

    class Meta:
        model = Collection
        fields = ("pk", "timestamp", "device", "status", "failed_reason", "message")
        attrs = {"class": "table table-hover table-headings"}
        empty_text = "No collection tasks found."


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class TemplateListTable(tables.Table):
    pk = ToggleColumn()
    name = tables.TemplateColumn(
        template_code=TEMPLATE_LINK,
        verbose_name="Template",
        order_by="name",
    )
    description = tables.Column(default="—")
    configuration = tables.TemplateColumn(
        template_code=TEMPLATE_TEXT,
        verbose_name="Config",
        orderable=False,
    )
    services = tables.TemplateColumn(
        template_code=SERVICE_TEMPLATES,
        verbose_name="Services",
        orderable=False,
    )
    actions = tables.TemplateColumn(
        template_code=TEMPLATE_ACTIONS,
        verbose_name="",
        orderable=False,
    )

    class Meta:
        model = Template
        fields = ("pk", "name", "description", "configuration", "services", "actions")
        attrs = {"class": "table table-hover table-headings"}
        empty_text = "No templates found."


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ServiceListTable(tables.Table):
    pk = ToggleColumn()
    name = tables.TemplateColumn(
        template_code=SERVICE_LINK,
        verbose_name="Service",
        order_by="name",
    )
    description = tables.Column(default="—")
    actions = tables.TemplateColumn(
        template_code=SERVICE_ACTIONS,
        verbose_name="",
        orderable=False,
    )

    class Meta:
        model = Service
        fields = ("pk", "name", "description", "actions")
        attrs = {"class": "table table-hover table-headings"}
        empty_text = "No services found."


# ---------------------------------------------------------------------------
# ServiceRule
# ---------------------------------------------------------------------------


class ServiceRuleListTable(tables.Table):
    pk = ToggleColumn()
    service = tables.TemplateColumn(template_code=RULE_SERVICE_LINK, verbose_name="Service")
    device_role = tables.TemplateColumn(template_code=DEVICE_ROLE, verbose_name="Device Role")
    device_type = tables.TemplateColumn(template_code=DEVICE_TYPE, verbose_name="Device Type")
    template = tables.TemplateColumn(template_code=RULE_TEMPLATE_LINK, verbose_name="Template")
    description = tables.Column(default="—")
    actions = tables.TemplateColumn(
        template_code=RULE_ACTIONS,
        verbose_name="",
        orderable=False,
    )

    class Meta:
        model = ServiceRule
        fields = (
            "pk",
            "service",
            "device_role",
            "device_type",
            "template",
            "description",
            "actions",
        )
        attrs = {"class": "table table-hover table-headings"}
        empty_text = "No service rules found."


# ---------------------------------------------------------------------------
# ServiceMapping (Device list with compliance columns)
#
# Uses NetBoxTable because it's based on the standard Device model which DOES
# have all standard NetBox CRUD URLs - NetBoxTable's ActionsColumn works here.
# ---------------------------------------------------------------------------


class ServiceMappingListTable(NetBoxTable):
    pk = ToggleColumn()
    name = tables.TemplateColumn(
        template_code=SERVICE_MAPPING_DEVICE_LINK,
        verbose_name="Device",
        order_by="name",
    )
    service = tables.TemplateColumn(
        template_code=ATTACHED_SERVICES_LIST,
        verbose_name="Service",
        orderable=False,
    )
    tenant = tables.Column()
    device_role = tables.Column(accessor="role", verbose_name="Role")
    device_type = tables.LinkColumn(
        viewname="dcim:devicetype",
        args=[Accessor("device_type.pk")],
        verbose_name="Type",
    )
    tags = TagColumn(url_name="dcim:device_list")
    status = tables.TemplateColumn(
        template_code=COMPLIANCE_STATUS,
        verbose_name="Compliance",
        orderable=False,
    )
    notes = tables.TemplateColumn(
        template_code=COMPLIANCE_NOTES,
        verbose_name="Notes",
        orderable=False,
    )

    class Meta(NetBoxTable.Meta):
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
            "notes",
        )
        default_columns = (
            "pk",
            "name",
            "service",
            "tenant",
            "device_role",
            "device_type",
            "tags",
            "status",
            "notes",
        )


# ---------------------------------------------------------------------------
# Collection Schedules
# ---------------------------------------------------------------------------


class CollectScheduleTable(NetBoxTable):
    name = tables.Column(linkify=True)
    devices = tables.Column(
        empty_values=(),
        orderable=False,
        verbose_name="Devices",
    )
    interval_hours = tables.Column(verbose_name="Interval")
    next_run = tables.DateTimeColumn(
        format="Y-m-d H:i",
        verbose_name="Next run",
    )
    enabled = tables.BooleanColumn(verbose_name="Enabled")
    actions = tables.TemplateColumn(
        template_code=COLLECT_SCHEDULE,
        orderable=False,
        verbose_name="",
    )

    class Meta:
        model = CollectSchedule
        fields = ("name", "devices", "interval_hours", "next_run", "enabled", "actions")
        attrs = {"class": "table table-hover table-headings"}

    def render_devices(self, record):
        count = record.devices.count()
        return f"{count} device{'s' if count != 1 else ''}"

    def render_interval_hours(self, value):
        if value == 1:
            return "Every hour"
        if value < 24:
            return f"Every {value} hours"
        days = value // 24
        return f"Every {days} day{'s' if days != 1 else ''}"
