"""Models for config_officer plugin."""

from dataclasses import dataclass, field

from core.choices import JobStatusChoices
from core.models import Job
from dcim.models import Device
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from netbox.models import NetBoxModel
from netbox.models.features import JobsMixin

from .choices import (
    CollectFailChoices,
    CollectStatusChoices,
    ServiceComplianceChoices,
)
from .config_manager import generate_templates_config_for_device


# --------------------------------------------------------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------------------------------------------------------
class Collection(models.Model):
    device = models.ForeignKey(
        to="dcim.Device",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=255,
        choices=CollectStatusChoices,
        default=CollectStatusChoices.STATUS_PENDING,
        null=True,
    )

    message = models.CharField(max_length=512, blank=True, null=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    failed_reason = models.CharField(
        max_length=255,
        choices=CollectFailChoices,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return str(self.device) if self.device else "n/a"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class Template(models.Model):
    name = models.CharField(max_length=512)
    description = models.CharField(max_length=512, blank=True, null=True)
    configuration = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name or ""

    def get_absolute_url(self):
        return reverse("plugins:config_officer:template", args=[self.pk])

    def get_services_list(self):
        return Service.objects.filter(service_rules__template=self).distinct()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class Service(models.Model):
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("plugins:config_officer:service", args=[self.pk])

    def get_service_rules(self):
        return self.service_rules.all()

    def get_devices(self):
        return Device.objects.filter(servicemapping__service=self).distinct()

    def get_device_templates(self, device):
        if not ServiceMapping.objects.filter(service=self, device=device).exists():
            return []

        rules = self.service_rules.all()

        device_rules = rules.filter(
            Q(device_role=device.role) | Q(device_role__isnull=True)
        ).filter(Q(device_type=device.device_type) | Q(device_type__isnull=True))

        return [r.template for r in device_rules if r.template]


# ---------------------------------------------------------------------------
# ServiceRule (FIXED M2M LOGIC)
# ---------------------------------------------------------------------------


class ServiceRule(models.Model):
    service = models.ForeignKey(
        to="config_officer.Service",
        on_delete=models.CASCADE,
        related_name="service_rules",
    )

    description = models.CharField(max_length=512, blank=True, null=True)

    # Keep M2M but FIX usage everywhere
    device_role = models.ManyToManyField("dcim.DeviceRole", blank=True)

    device_type = models.ManyToManyField("dcim.DeviceType", blank=True)

    template = models.ForeignKey(
        to="config_officer.Template",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    def matches_device(self, device):
        """Central matching logic (IMPORTANT FIX)."""

        role_match = not self.device_role.exists() or device.role in self.device_role.all()

        type_match = not self.device_type.exists() or device.device_type in self.device_type.all()

        return role_match and type_match


# ---------------------------------------------------------------------------
# ServiceMapping
# ---------------------------------------------------------------------------


class ServiceMapping(models.Model):
    device = models.ForeignKey("dcim.Device", on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("device", "service")

    def __str__(self):
        return f"{self.device}:{self.service}"


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------


class Compliance(models.Model):
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

    notes = models.CharField(max_length=512, blank=True, null=True)

    generated_config = models.TextField(blank=True, null=True)

    diff = models.TextField(blank=True, null=True)

    services = ArrayField(
        models.CharField(max_length=512),
        default=list,
        blank=True,
    )

    def __str__(self):
        return f"{self.device}:{self.status}"

    def get_services(self):
        return Service.objects.filter(servicemapping__device=self.device).distinct()

    def get_device_templates(self):
        templates = []

        for service in self.get_services():
            for rule in service.get_service_rules():
                if rule.matches_device(self.device) and rule.template:
                    templates.append(rule.template)

        return list(set(templates))

    def get_generated_config(self):
        self.generated_config = generate_templates_config_for_device(self.get_device_templates())
        return self.generated_config

    def get_absolute_url(self):
        return reverse("plugins:config_officer:compliance", args=[self.pk])


# ---------------------------------------------------------------------------
# Collect Schedule
# ---------------------------------------------------------------------------


class CollectSchedule(JobsMixin, NetBoxModel):
    """
    Defines a recurring config-collection job for one or more devices.

    ``next_run`` is updated by the scheduler worker after each execution.
    Setting ``enabled = False`` pauses the schedule without deleting it.
    """

    name = models.CharField(
        max_length=128,
        unique=True,
        help_text="Human-readable label, e.g. 'Core switches - nightly'.",
    )
    devices = models.ManyToManyField(
        Device,
        related_name="collect_schedules",
        help_text="Devices to collect configuration from.",
    )
    interval_hours = models.PositiveIntegerField(
        default=24,
        help_text="How often to run, in hours (e.g. 6, 12, 24).",
    )
    next_run = models.DateTimeField(
        default=timezone.now,
        help_text="When the schedule will next fire. Updated automatically after each run.",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Uncheck to pause this schedule without deleting it.",
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    webhook_url = models.URLField(
        max_length=512,
        blank=True,
        help_text="Optional URL to POST a summary to after the schedule completes.",
    )
    webhook_secret = models.CharField(
        max_length=256,
        blank=True,
        help_text="Optional HMAC-SHA256 secret for X-Webhook-Signature header.",
    )

    class Meta:
        ordering = ["next_run"]
        verbose_name = "Collect Schedule"
        verbose_name_plural = "Collect Schedules"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._schedule_job()

    def _schedule_job(self):
        if self.enabled:
            # import has to be here due to curcular import problem
            from .jobs import CollectScheduleJob  # noqa: PLC0415

            CollectScheduleJob.enqueue_once(
                instance=self,
                schedule_at=self.next_run,
                interval=self.interval_hours * 60,
            )

    def get_absolute_url(self):
        return reverse("plugins:config_officer:collectschedule_edit", args=[self.pk])


@receiver(post_delete, sender=CollectSchedule)
def cancel_schedule_jobs(sender, instance, **kwargs):
    """Delete all jobs related to deleted schedule."""
    ct = ContentType.objects.get_for_model(CollectSchedule)
    deleted, _ = Job.objects.filter(
        object_type=ct,
        object_id=instance.pk,
        status=JobStatusChoices.STATUS_SCHEDULED,  # remove scheduled only
    ).delete()


# ---------------------------------------------------------------------------
# Pure-Python data containers
# ---------------------------------------------------------------------------


@dataclass
class ParsedInterface:
    """Everything we know about a single interface after parsing CLI output."""

    name: str
    ip: str | None = None  # primary IP/prefix, e.g. "10.0.0.1/24"
    secondary: list[str] = field(default_factory=list)  # secondary IPs/prefix
    mac: str | None = None  # dotted-hex, e.g. "aabb.ccdd.eeff"
    description: str | None = None
    mtu: int | None = None
    vrf: str | None = None
    dhcp: bool = False
    speed: str | None = None  # e.g. "1000Mbps"
    duplex: str | None = None  # "full" | "half"
    admin_up: bool | None = None
    link_up: bool | None = None
    is_mgmt: bool = False
    lag: str | None = None  # normalised lag name, e.g. "port-channel1"

    def __str__(self) -> str:
        return self.name


@dataclass
class ParsedDevice:
    """Version / identity information parsed from 'show version'."""

    hostname: str = ""
    version: str = ""
    pid: str = ""  # product-ID / hardware model
    serial: str = ""
