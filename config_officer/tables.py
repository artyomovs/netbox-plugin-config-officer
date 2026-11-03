"""Tables rendered by the list views (all support column configuration and CSV export)."""

import django_tables2 as tables
from core.models import Job
from dcim.models import Device
from django.utils.translation import gettext_lazy as _
from netbox.tables import NetBoxTable, columns

from .models import Collection, CollectSchedule, Service, ServiceRule, Template


class TemplateTable(NetBoxTable):
    name = tables.Column(linkify=True)
    services = tables.TemplateColumn(
        template_code="""{% for s in record.get_services %}<a href="{{ s.get_absolute_url }}">{{ s }}</a>{% if not forloop.last %}, {% endif %}{% empty %}&mdash;{% endfor %}""",
        orderable=False,
        verbose_name=_("Used by services"),
    )
    tags = columns.TagColumn(url_name="plugins:config_officer:template_list")

    class Meta(NetBoxTable.Meta):
        model = Template
        fields = (
            "pk",
            "id",
            "name",
            "description",
            "services",
            "tags",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = ("pk", "name", "description", "services")


class ServiceTable(NetBoxTable):
    name = tables.Column(linkify=True)
    rule_count = columns.LinkedCountColumn(
        viewname="plugins:config_officer:servicerule_list",
        url_params={"service_id": "pk"},
        verbose_name=_("Rules"),
    )
    device_count = columns.LinkedCountColumn(
        viewname="plugins:config_officer:compliance_list",
        url_params={"compliance_service_id": "pk"},
        verbose_name=_("Devices"),
    )
    tags = columns.TagColumn(url_name="plugins:config_officer:service_list")

    class Meta(NetBoxTable.Meta):
        model = Service
        fields = (
            "pk",
            "id",
            "name",
            "description",
            "rule_count",
            "device_count",
            "tags",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = ("pk", "name", "description", "rule_count", "device_count")


class ServiceRuleTable(NetBoxTable):
    id = tables.Column(linkify=True, verbose_name=_("ID"))
    service = tables.Column(linkify=True)
    template = tables.Column(linkify=True)
    device_roles = columns.ManyToManyColumn(
        linkify_item=True, verbose_name=_("Roles"), default=_("any")
    )
    device_types = columns.ManyToManyColumn(
        linkify_item=True, verbose_name=_("Device types"), default=_("any")
    )
    tags = columns.TagColumn(url_name="plugins:config_officer:servicerule_list")

    class Meta(NetBoxTable.Meta):
        model = ServiceRule
        fields = (
            "pk",
            "id",
            "service",
            "template",
            "device_roles",
            "device_types",
            "description",
            "tags",
            "actions",
        )
        default_columns = (
            "pk",
            "id",
            "service",
            "template",
            "device_roles",
            "device_types",
            "description",
        )


SCHEDULE_TARGETS = """
{% if record.all_devices %}<span class="badge text-bg-blue">all devices</span>{% endif %}
{% for tag in record.device_tags.all %}{% tag tag %}{% endfor %}
{% with count=record.devices.count %}{% if count %}<span class="text-secondary">{{ count }} device{{ count|pluralize }}</span>{% endif %}{% endwith %}
"""


class CollectScheduleTable(NetBoxTable):
    name = tables.Column(linkify=True)
    enabled = columns.BooleanColumn()
    targets = tables.TemplateColumn(
        template_code=SCHEDULE_TARGETS, orderable=False, verbose_name=_("Devices")
    )
    interval_hours = tables.Column(verbose_name=_("Interval"))
    next_run = columns.DateTimeColumn(verbose_name=_("Start at"))
    webhook_url = columns.BooleanColumn(verbose_name=_("Webhook"))
    tags = columns.TagColumn(url_name="plugins:config_officer:collectschedule_list")

    class Meta(NetBoxTable.Meta):
        model = CollectSchedule
        fields = (
            "pk",
            "id",
            "name",
            "enabled",
            "targets",
            "interval_hours",
            "next_run",
            "webhook_url",
            "tags",
            "actions",
        )
        default_columns = (
            "pk",
            "name",
            "enabled",
            "targets",
            "interval_hours",
            "next_run",
            "webhook_url",
        )

    def render_interval_hours(self, value):
        if value % 24 == 0:
            days = value // 24
            return _("every day") if days == 1 else _("every {n} days").format(n=days)
        return _("every hour") if value == 1 else _("every {n} hours").format(n=value)


RESULT_RUN = """{% if record.job_id %}<a href="{% url 'plugins:config_officer:run' pk=record.job_id %}">#{{ record.job_id }}</a>{% else %}&mdash;{% endif %}"""


class CollectionTable(NetBoxTable):
    timestamp = columns.DateTimeColumn(linkify=True, verbose_name=_("Time"))
    device = tables.Column(linkify=True)
    status = columns.ChoiceFieldColumn()
    failed_reason = columns.ChoiceFieldColumn(verbose_name=_("Failure"))
    transport = columns.ChoiceFieldColumn()
    config_changed = columns.BooleanColumn(verbose_name=_("Config changed"))
    duration = tables.Column(verbose_name=_("Duration (s)"))
    run = tables.TemplateColumn(template_code=RESULT_RUN, order_by="job_id", verbose_name=_("Run"))
    actions = columns.ActionsColumn(actions=("delete",))

    class Meta(NetBoxTable.Meta):
        model = Collection
        fields = (
            "pk",
            "id",
            "timestamp",
            "device",
            "status",
            "failed_reason",
            "transport",
            "config_changed",
            "duration",
            "message",
            "run",
            "actions",
        )
        default_columns = (
            "pk",
            "timestamp",
            "device",
            "status",
            "config_changed",
            "message",
            "run",
        )

    def render_duration(self, value):
        return f"{value:.1f}"


DEVICE_SERVICES = """{% for m in record.servicemapping_set.all %}<a href="{{ m.service.get_absolute_url }}">{{ m.service }}</a>{% if not forloop.last %}, {% endif %}{% empty %}&mdash;{% endfor %}"""
DEVICE_COMPLIANCE = """{% if record.compliance %}<a href="{% url 'dcim:device_config_officer_compliance' pk=record.pk %}">{% badge record.compliance.get_status_display bg_color=record.compliance.get_status_color %}</a>{% else %}&mdash;{% endif %}"""


class DeviceComplianceTable(NetBoxTable):
    name = tables.Column(linkify=True, verbose_name=_("Device"))
    site = tables.Column(linkify=True)
    role = tables.Column(linkify=True)
    device_type = tables.Column(linkify=True, verbose_name=_("Type"))
    tenant = tables.Column(linkify=True)
    primary_ip4 = tables.Column(linkify=True, verbose_name=_("IPv4"))
    services = tables.TemplateColumn(
        template_code=DEVICE_SERVICES, orderable=False, verbose_name=_("Services")
    )
    compliance = tables.TemplateColumn(
        template_code=DEVICE_COMPLIANCE, order_by="compliance__status", verbose_name=_("Compliance")
    )
    notes = tables.Column(accessor="compliance__notes", verbose_name=_("Notes"))
    last_checked = columns.DateTimeColumn(
        accessor="compliance__last_checked", verbose_name=_("Last checked")
    )
    diff = tables.Column(accessor="compliance__diff", verbose_name=_("Missing lines"))
    tags = columns.TagColumn(url_name="dcim:device_list")
    actions = columns.ActionsColumn(actions=())

    class Meta(NetBoxTable.Meta):
        model = Device
        fields = (
            "pk",
            "id",
            "name",
            "site",
            "role",
            "device_type",
            "tenant",
            "primary_ip4",
            "services",
            "compliance",
            "notes",
            "last_checked",
            "diff",
            "tags",
        )
        default_columns = (
            "pk",
            "name",
            "role",
            "device_type",
            "services",
            "compliance",
            "notes",
            "last_checked",
        )


RUN_STATUS = """{% badge record.get_status_display bg_color=record.get_status_color %}"""
RUN_SUMMARY = """{% with s=record.data.summary %}{% if s %}<span class="text-success">{{ s.succeeded }} ok</span> &middot; <span class="{% if s.failed %}text-danger{% else %}text-secondary{% endif %}">{{ s.failed }} failed</span> &middot; {{ s.changed }} changed{% elif record.data.progress %}{{ record.data.progress.done }} / {{ record.data.progress.total }}{% else %}&mdash;{% endif %}{% endwith %}"""


class RunTable(tables.Table):
    """Collection runs (NetBox core Jobs) on the collection page."""

    id = tables.TemplateColumn(
        template_code="""<a href="{% url 'plugins:config_officer:run' pk=record.pk %}">#{{ record.pk }}</a>""",
        verbose_name=_("Run"),
    )
    trigger = tables.TemplateColumn(
        template_code="""{% if record.object %}{{ record.object|linkify }}{% else %}{{ record.data.trigger|default:"manual" }}{% endif %}""",
        verbose_name=_("Started by"),
        orderable=False,
    )
    target = tables.Column(
        accessor="data__target", verbose_name=_("Devices"), default="", orderable=False
    )
    status = tables.TemplateColumn(template_code=RUN_STATUS)
    summary = tables.TemplateColumn(
        template_code=RUN_SUMMARY, orderable=False, verbose_name=_("Result")
    )
    user = tables.Column()
    created = columns.DateTimeColumn()
    completed = columns.DateTimeColumn()

    class Meta:
        model = Job
        fields = ("id", "trigger", "target", "status", "summary", "user", "created", "completed")
        attrs = {"class": "table table-hover"}
        empty_text = _("No collection has run yet.")
