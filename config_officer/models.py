"""Models for config_officer plugin."""

from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.urls import reverse
from .choices import (
    ServiceComplianceChoices,
    CollectFailChoices,
    CollectStatusChoices
    
)
from .config_manager import generate_templates_config_for_device
from django.db.models import Q


class Collection(models.Model):
    """Device Collecthronization (collecting configuration) records."""

    device = models.ForeignKey(
        to="dcim.Device", on_delete=models.SET_NULL, blank=True, null=True
    )
    status = models.CharField(
        max_length=255,
        choices=CollectStatusChoices,
        default=CollectStatusChoices.STATUS_PENDING,
        null=True,
    )
    message = models.CharField(max_length=512, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    failed_reason = models.CharField(max_length=255, choices=CollectFailChoices, null=True)
    
    csv_headers = [
        "device",
    ]

    def __str__(self):
        if not self.device:
            return "n/a"
        else:
            return str(self.device)

    class Meta:
        ordering = ["timestamp"]


class Template(models.Model):
    """Network device configuration template."""

    name = models.CharField(max_length=512, blank=True, null=True)
    description = models.CharField(max_length=512, blank=True, null=True)
    configuration = models.TextField(null=True, blank=True)

    def get_absolute_url(self):
        return reverse("plugins:config_officer:template", args=[self.pk])

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.name

    def get_services_list(self):
        return list(
            set([rule.service for rule in ServiceRule.objects.filter(template=self)])
        )


class Service(models.Model):
    """Service, that is provided by device."""

    name = models.CharField(max_length=200)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.name

    def get_service_rules_count(self):
        return ServiceRule.objects.filter(service=self).count()

    def get_service_rules(self):
        return ServiceRule.objects.filter(service=self)

    def get_absolute_url(self):
        return reverse("plugins:config_officer:service", args=[self.pk])

    # Get templates, matched with the device
    def get_device_templates(self, device):
        rules = self.get_service_rules()

        if len(ServiceMapping.objects.filter(service=self, device=device)) == 0:
            return None
        else:
            rules = self.get_service_rules()
            if len(rules) == 0:
                return None
            device_rules = rules.filter(
                (
                    Q(device_role__exact=device.device_role)
                    & Q(device_type__exact=device.device_type)
                )
                | (
                    Q(device_role__exact=device.device_role)
                    & Q(device_type__isnull=True)
                )
                | (
                    Q(device_role__isnull=True)
                    & Q(device_type__exact=device.device_type)
                )
                | (Q(device_role__isnull=True) & Q(device_type__isnull=True))
            )
            templates = [rule.template for rule in device_rules]
            if len(templates) == 0:
                return []
            else:
                return templates

    # Count of devices with this 
    def get_devices_count(self):
        return ServiceMapping.objects.filter(service__exact=self).count()

    def get_compliant_devices_count(self):
        devices = [ mapping.device for mapping in ServiceMapping.objects.filter(service__exact=self)]
        return Compliance.objects.filter(device__in=devices, status=ServiceComplianceChoices.STATUS_COMPLIANCE).count()


class ServiceRule(models.Model):
    """Service rule for particular role and type."""

    service = models.ForeignKey(to="Service", on_delete=models.CASCADE, related_name="service_rules")
    description = models.CharField(max_length=512, blank=True, null=True)
    device_role = models.ManyToManyField(to="dcim.DeviceRole", blank=False)
    device_type = models.ManyToManyField(to="dcim.DeviceType", blank=True)
    template = models.ForeignKey(to="Template", on_delete=models.CASCADE, blank=True)


class ServiceMapping(models.Model):
    """Map service for device."""

    device = models.ForeignKey(to="dcim.Device", on_delete=models.CASCADE)
    service = models.ForeignKey(to="Service", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.device}:{self.service}"


class ServiceManager(models.Manager):
    def get_services(self):
        return [m.service for m in ServiceMapping.objects.filter(device=self.device)]


class Compliance(models.Model):
    """Model to store compliance status for devices.
    Templates from all attached services will be merged and compared with running-config."""

    device = models.OneToOneField(to="dcim.Device", on_delete=models.CASCADE, related_name="compliance")
    status = models.CharField(
        max_length=50,
        choices=ServiceComplianceChoices,
        null=False,
        default=ServiceComplianceChoices.STATUS_NON_COMPLIANCE,
    )
    notes = models.CharField(max_length=512, blank=True, null=True, default=None)
    generated_config = models.TextField(null=True, blank=True)
    diff = models.TextField(null=True, blank=True)
    services = ArrayField(
        models.CharField(max_length=512, blank=True, null=True),
        blank=True,
        null=True,
        default=list,
        verbose_name="services",
    )

    def __str__(self):
        return f"{self.device}:{self.status}:{self.notes}"

    def get_device_templates(self):
        """Get applicable templates for device."""

        services = [
            m.service for m in ServiceMapping.objects.filter(device=self.device)
        ]
        if len(services) == 0:
            return []

        # device = self.device
        templates = []
        for service in services:
            rules = service.get_service_rules()
            if len(rules) != 0:
                device_rules = rules.filter(
                    (
                        Q(device_role__exact=self.device.device_role)
                        & Q(device_type__exact=self.device.device_type)
                    )
                    | (
                        Q(device_role__exact=self.device.device_role)
                        & Q(device_type__isnull=True)
                    )
                    | (
                        Q(device_role__isnull=True)
                        & Q(device_type__exact=self.device.device_type)
                    )
                    | (Q(device_role__isnull=True) & Q(device_type__isnull=True))
                )
                templates.extend([rule.template for rule in device_rules])
        return list(set(templates))

    def get_generated_config(self):
        self.generated_config = generate_templates_config_for_device(
            self.get_device_templates()
        )
        return self.generated_config

    def get_absolute_url(self):
        return reverse("plugins:config_officer:compliance", args=[self.pk])

    def get_services_list_for_device(self):
        return [m.service for m in ServiceMapping.objects.filter(device=self.device)]