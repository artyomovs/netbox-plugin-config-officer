"""Compliance evaluation for one device.

How templates reach a device::

    device --ServiceMapping--> Service --ServiceRule(role/type filter)--> Template

All templates that apply are merged into one *expected* configuration
(sections with the same header are combined), and every expected line that is
missing from the running config makes the device non-compliant. Placeholders
like ``{{ ip }}`` match any value (see diff.py).
"""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from config_officer.choices import ServiceComplianceChoices
from config_officer.configuration import PluginSettings
from config_officer.models import Compliance, Service, ServiceRule, Template

from .diff import Compare

#: Banner lines Cisco prints at the top of "show running-config"; never part of a template.
IGNORED_LINES = [
    "Building configuration",
    "Current configuration",
    "NVRAM config last updated",
    "Last configuration change",
]


def templates_for_device(device) -> list[Template]:
    """Templates of all rules (of all services assigned to the device) that match it."""
    rules = (
        ServiceRule.objects.filter(service__servicemapping__device=device, template__isnull=False)
        .select_related("template", "service")
        .prefetch_related("device_roles", "device_types")
        .order_by("service__name", "pk")
    )
    templates: list[Template] = []
    for rule in rules:
        if rule.matches(device) and rule.template not in templates:
            templates.append(rule.template)
    return templates


def _sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split config lines into (top-level line, indented children) pairs; drop '!' and blanks."""
    sections: list[tuple[str, list[str]]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        if line[:1] in (" ", "\t") and sections:
            sections[-1][1].append(line.rstrip())
        else:
            sections.append((line.rstrip(), []))
    return sections


def merge_templates(templates: list[Template]) -> str:
    """Merge template texts into one config; repeated section headers are combined."""
    merged: dict[str, list[str]] = {}
    for template in templates:
        for header, children in _sections((template.configuration or "").splitlines()):
            bucket = merged.setdefault(header, [])
            bucket.extend(child for child in children if child not in bucket)
    lines: list[str] = []
    for header, children in merged.items():
        lines.append(header)
        lines.extend(children)
    return "\n".join(lines)


def missing_lines(expected: str, running: str) -> list[list[str]]:
    """Blocks (section header + missing children) required by ``expected`` but absent in ``running``."""
    return Compare(expected.splitlines(), running.splitlines(), IGNORED_LINES).missing()


def evaluate_device(
    device,
    running_config: str | None,
    config_updated_at: datetime | None,
    settings: PluginSettings,
    now: datetime | None = None,
) -> Compliance | None:
    """Recompute and save the device's Compliance row. Returns None if no service is assigned."""
    now = now or timezone.now()
    services = list(Service.objects.filter(servicemapping__device=device).order_by("name"))
    if not services:
        return None

    compliance, _ = Compliance.objects.get_or_create(device=device)
    compliance.services = [service.name for service in services]
    compliance.last_checked = now
    compliance.status = ServiceComplianceChoices.STATUS_NON_COMPLIANCE
    compliance.diff = ""

    templates = templates_for_device(device)
    compliance.generated_config = merge_templates(templates)
    if not templates:
        compliance.notes = "No templates match this device (check the service rules' roles/types)"
    elif running_config is None:
        compliance.notes = "Running config not found in the repository - collect the device first"
    elif (
        config_updated_at
        and (now - config_updated_at).days > settings.compliance_max_config_age_days
    ):
        age = (now - config_updated_at).days
        compliance.notes = (
            f"Running config is stale ({age} days since the last successful collection)"
        )
    else:
        missing = missing_lines(compliance.generated_config, running_config)
        compliance.notes = None
        if missing:
            compliance.diff = "\n".join("\n".join(block) for block in missing)
        else:
            compliance.status = ServiceComplianceChoices.STATUS_COMPLIANCE
    compliance.save()
    return compliance
