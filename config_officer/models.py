"""Database models.

Two groups of models live here:

* **Configuration objects**, edited by users: :class:`Template`,
  :class:`Service`, :class:`ServiceRule` and :class:`CollectSchedule`. They
  are full NetBox models (change log, tags, custom fields, journal).
* **Results**, written by background jobs: :class:`Collection` (one row per
  device per collection run), :class:`Compliance` (latest compliance verdict
  per device) and :class:`ServiceMapping` (which services a device must
  follow). They use NetBox's ``RestrictedQuerySet`` so object permissions apply.

Models hold data and small helpers only. Collecting, syncing and compliance
logic lives in ``collection/`` and ``compliance/``.
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from netbox.models import NetBoxModel
from netbox.models.features import JobsMixin
from utilities.querysets import RestrictedQuerySet

from .choices import (
    CollectFailChoices,
    CollectStatusChoices,
    ServiceComplianceChoices,
    TransportChoices,
)

# ---------------------------------------------------------------------------
# Compliance configuration: templates -> rules -> services -> devices
# ---------------------------------------------------------------------------


class Template(NetBoxModel):
    """A block of configuration that compliant devices must contain.

    ``{{ anything }}`` placeholders match any value, e.g. ``ntp server {{ ip }}``.
    """

    name = models.CharField(max_length=512)
    description = models.CharField(max_length=512, blank=True, null=True)
    configuration = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("compliance template")
        verbose_name_plural = _("compliance templates")

    def __str__(self):
        return self.name or ""

    def get_absolute_url(self):
        return reverse("plugins:config_officer:template", args=[self.pk])

    def get_services(self):
        """Services whose rules use this template."""
        return Service.objects.filter(service_rules__template=self).distinct()


class Service(NetBoxModel):
    """A named set of rules ("what a device of role X / type Y must contain")."""

    name = models.CharField(max_length=200)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("compliance service")
        verbose_name_plural = _("compliance services")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("plugins:config_officer:service", args=[self.pk])


class ServiceRule(NetBoxModel):
    """Applies a template to the devices of a service, optionally narrowed by role and type.

    An empty ``device_roles`` (or ``device_types``) means "any role" (or "any type").
    """

    service = models.ForeignKey(
        to="config_officer.Service",
        on_delete=models.CASCADE,
        related_name="service_rules",
    )
    description = models.CharField(max_length=512, blank=True, null=True)
    device_roles = models.ManyToManyField("dcim.DeviceRole", blank=True)
    device_types = models.ManyToManyField("dcim.DeviceType", blank=True)
    template = models.ForeignKey(
        to="config_officer.Template",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["service", "pk"]
        verbose_name = _("service rule")
        verbose_name_plural = _("service rules")

    def __str__(self):
        return f"{self.service}: {self.template or '-'}"

    def get_absolute_url(self):
        return reverse("plugins:config_officer:servicerule", args=[self.pk])

    def matches(self, device) -> bool:
        """True if the rule applies to ``device`` (role and type filters, empty = any)."""
        roles = {r.pk for r in self.device_roles.all()}
        types = {t.pk for t in self.device_types.all()}
        return (not roles or device.role_id in roles) and (
            not types or device.device_type_id in types
        )


class ServiceMapping(models.Model):
    """Assignment of a service to a device."""

    device = models.ForeignKey("dcim.Device", on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)

    objects = RestrictedQuerySet.as_manager()

    class Meta:
        unique_together = ("device", "service")
        verbose_name = _("service assignment")
        verbose_name_plural = _("service assignments")

    def __str__(self):
        return f"{self.device}:{self.service}"


class Compliance(models.Model):
    """Latest compliance verdict of a device, written by compliance.engine."""

    device = models.OneToOneField(
        "dcim.Device",
        on_delete=models.CASCADE,
        related_name="compliance",
    )
    status = models.CharField(
        max_length=50,
        choices=ServiceComplianceChoices,
        default=ServiceComplianceChoices.STATUS_NON_COMPLIANCE,
    )
    #: Why the check could not be completed (e.g. "running config not found"); empty when it ran.
    notes = models.CharField(max_length=512, blank=True, null=True)
    #: Merged configuration of all templates that apply to the device.
    generated_config = models.TextField(blank=True, null=True)
    #: Template lines missing from the running config, one block per section.
    diff = models.TextField(blank=True, null=True)
    #: Names of the services assigned at check time (informational snapshot).
    services = ArrayField(models.CharField(max_length=512), default=list, blank=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    objects = RestrictedQuerySet.as_manager()

    class Meta:
        verbose_name = _("compliance status")
        verbose_name_plural = _("compliance statuses")

    def __str__(self):
        return f"{self.device}:{self.status}"

    def get_absolute_url(self):
        return reverse("dcim:device_config_officer_compliance", args=[self.device_id])

    def get_status_color(self):
        return ServiceComplianceChoices.colors.get(self.status)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


class Collection(models.Model):
    """Result of collecting one device in one collection run.

    The run itself is a NetBox ``core.Job`` (see jobs.py); ``job`` links to it.
    ``details`` holds the structured report of what was changed in NetBox,
    see ``collection.netbox_sync.SyncReport.as_dict``.
    """

    device = models.ForeignKey(
        to="dcim.Device",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    job = models.ForeignKey(
        to="core.Job",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    status = models.CharField(
        max_length=255,
        choices=CollectStatusChoices,
        default=CollectStatusChoices.STATUS_PENDING,
        null=True,
    )
    failed_reason = models.CharField(
        max_length=255,
        choices=CollectFailChoices,
        null=True,
        blank=True,
    )
    #: One-line human summary ("Collected via SSH; config changed; 2 interfaces created").
    message = models.CharField(max_length=512, blank=True, null=True)
    transport = models.CharField(max_length=16, choices=TransportChoices, blank=True)
    config_changed = models.BooleanField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True, help_text=_("Seconds"))
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    objects = RestrictedQuerySet.as_manager()

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = _("collection result")
        verbose_name_plural = _("collection results")

    def __str__(self):
        device = self.device.name if self.device else "n/a"
        return f"{device} @ {timezone.localtime(self.timestamp):%Y-%m-%d %H:%M}"

    def get_absolute_url(self):
        return reverse("plugins:config_officer:collection", args=[self.pk])

    def get_status_color(self):
        return CollectStatusChoices.colors.get(self.status)


class CollectSchedule(JobsMixin, NetBoxModel):
    """Recurring collection of a set of devices.

    Targets are resolved at run time, so devices added to a tag later are picked
    up automatically: ``all_devices`` OR any device in ``devices`` OR any device
    with at least one of ``device_tags``.

    The recurring NetBox job is created / updated by ``jobs.sync_schedule_job``
    whenever the schedule is saved (see signals.py).
    """

    name = models.CharField(
        max_length=128,
        unique=True,
        help_text=_("Human-readable label, e.g. 'Core switches - nightly'."),
    )
    all_devices = models.BooleanField(
        default=False,
        help_text=_("Collect every device in NetBox (subject to the owner's permissions)."),
    )
    devices = models.ManyToManyField(
        "dcim.Device",
        related_name="collect_schedules",
        blank=True,
        help_text=_("Devices to collect configuration from."),
    )
    device_tags = models.ManyToManyField(
        "extras.Tag",
        related_name="+",
        blank=True,
        help_text=_("Also collect every device that has at least one of these tags."),
    )
    interval_hours = models.PositiveIntegerField(
        default=24,
        help_text=_("How often to run, in hours (e.g. 6, 12, 24)."),
    )
    next_run = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("start at"),
        help_text=_("First run. Later runs follow every interval from this point in time."),
    )
    enabled = models.BooleanField(
        default=True,
        help_text=_("Uncheck to pause this schedule without deleting it."),
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    webhook_url = models.URLField(
        max_length=512,
        blank=True,
        help_text=_("Optional URL to POST a summary to after each run."),
    )
    webhook_secret = models.CharField(
        max_length=256,
        blank=True,
        help_text=_("Optional HMAC-SHA256 secret for the X-Webhook-Signature header."),
    )

    class Meta:
        ordering = ["name"]
        verbose_name = _("collection schedule")
        verbose_name_plural = _("collection schedules")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self):
        return reverse("plugins:config_officer:collectschedule", args=[self.pk])

    def clean(self):
        super().clean()
        if self.interval_hours is not None and self.interval_hours < 1:
            raise ValidationError({"interval_hours": _("The interval must be at least one hour.")})

    def next_occurrence(self, now=None):
        """First run time >= ``now`` on the cadence anchored at ``next_run``."""
        now = now or timezone.now()
        if self.next_run >= now:
            return self.next_run
        interval = timedelta(hours=self.interval_hours)
        periods = math.ceil((now - self.next_run) / interval)
        return self.next_run + periods * interval

    def get_selection(self):
        """The devices this schedule targets, as a collection.targets.DeviceSelection."""
        from .collection.targets import DeviceSelection

        return DeviceSelection(
            all_devices=self.all_devices,
            device_ids=tuple(self.devices.values_list("pk", flat=True)),
            tag_slugs=tuple(self.device_tags.values_list("slug", flat=True)),
        )
