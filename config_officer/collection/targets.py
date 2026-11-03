"""Which devices a collection run touches, and how to reach each of them.

* :class:`DeviceSelection` - the user's choice ("all devices", "devices tagged
  core", "these three devices"). It is small and picklable, so it travels
  inside the background job arguments, and it is resolved to a queryset only
  when the job runs (new devices with a tag are picked up automatically).
* :class:`DeviceTarget` - everything the connection layer needs for one device
  (address, platform driver, credentials). Plain data, no ORM objects, so it can
  be handed to worker threads safely.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

from config_officer.configuration import SUPPORTED_DRIVERS, PluginSettings
from config_officer.permissions import COLLECT_CONFIG_ACTION

# Platform slugs/names that map to a driver without configuration. Matching is
# case-insensitive; PLATFORM_MAP in the settings extends or overrides this.
PLATFORM_ALIASES = {
    "iosxe": "iosxe",
    "ios-xe": "iosxe",
    "ios_xe": "iosxe",
    "cisco-ios-xe": "iosxe",
    "cisco_iosxe": "iosxe",
    "ios": "iosxe",
    "cisco-ios": "iosxe",
    "cisco_ios": "iosxe",
    "nxos": "nxos",
    "nx-os": "nxos",
    "cisco-nx-os": "nxos",
    "cisco-nxos": "nxos",
    "cisco_nxos": "nxos",
    "iosxr": "iosxr",
    "ios-xr": "iosxr",
    "cisco-ios-xr": "iosxr",
    "cisco_iosxr": "iosxr",
}


class SkipDevice(Exception):  # noqa: N818 - it is a signal, not an error
    """The device cannot be collected at all (e.g. no primary IPv4). Recorded as "skipped"."""


@dataclass(frozen=True)
class DeviceSelection:
    all_devices: bool = False
    device_ids: tuple[int, ...] = ()
    tag_slugs: tuple[str, ...] = ()
    statuses: tuple[str, ...] = field(default=())

    def is_empty(self) -> bool:
        return not (self.all_devices or self.device_ids or self.tag_slugs)

    def describe(self) -> str:
        """Human description used in job logs and the runs table."""
        if self.all_devices:
            parts = ["all devices"]
        else:
            parts = []
            if self.tag_slugs:
                parts.append("tags: " + ", ".join(self.tag_slugs))
            if self.device_ids:
                parts.append(f"{len(self.device_ids)} selected device(s)")
        text = " + ".join(parts) or "no devices"
        if self.statuses:
            text += f" (status: {', '.join(self.statuses)})"
        return text

    def as_dict(self) -> dict:
        return {
            "all_devices": self.all_devices,
            "device_ids": list(self.device_ids),
            "tag_slugs": list(self.tag_slugs),
            "statuses": list(self.statuses),
        }

    @classmethod
    def from_dict(cls, data: dict) -> DeviceSelection:
        return cls(
            all_devices=bool(data.get("all_devices")),
            device_ids=tuple(int(pk) for pk in data.get("device_ids") or ()),
            tag_slugs=tuple(data.get("tag_slugs") or ()),
            statuses=tuple(data.get("statuses") or ()),
        )

    def queryset(self, user=None):
        """Devices matching the selection; limited to what ``user`` may collect, if given."""
        from dcim.models import Device
        from django.db.models import Q

        devices = Device.objects.all()
        if user is not None:
            devices = devices.restrict(user, COLLECT_CONFIG_ACTION)
        if not self.all_devices:
            match = Q(pk__in=self.device_ids) | Q(tags__slug__in=self.tag_slugs)
            devices = (
                devices.filter(match) if (self.device_ids or self.tag_slugs) else devices.none()
            )
        if self.statuses:
            devices = devices.filter(status__in=self.statuses)
        return devices.distinct().select_related("platform", "primary_ip4").order_by("name")


@dataclass(frozen=True)
class DeviceTarget:
    device_id: int
    name: str
    host: str
    driver: str
    port: int
    username: str
    password: str = field(repr=False)
    enable_password: str = field(default="", repr=False)


def resolve_driver(platform, settings: PluginSettings) -> tuple[str, str | None]:
    """Pick the scrapli driver for a NetBox platform.

    Returns ``(driver, note)`` where ``note`` explains a fallback, for the job log.
    """
    if platform is None:
        return (
            settings.default_platform,
            f"no platform set, using default '{settings.default_platform}'",
        )
    for candidate in (platform.slug, platform.name):
        key = (candidate or "").lower()
        if key in settings.platform_map:
            return settings.platform_map[key], None
        if key in PLATFORM_ALIASES:
            return PLATFORM_ALIASES[key], None
        if key in SUPPORTED_DRIVERS:
            return key, None
    return (
        settings.default_platform,
        f"platform '{platform}' is not recognised, using default '{settings.default_platform}' "
        f"(map it with PLATFORM_MAP)",
    )


def build_target(device, settings: PluginSettings) -> tuple[DeviceTarget, str | None]:
    """Turn a Device into a :class:`DeviceTarget`; raise :class:`SkipDevice` if impossible."""
    if not device.name:
        raise SkipDevice("device has no name (configs are stored by hostname)")
    if device.primary_ip4 is None:
        raise SkipDevice("no primary IPv4 address in NetBox")
    host = str(ipaddress.ip_interface(str(device.primary_ip4.address)).ip)
    driver, note = resolve_driver(device.platform, settings)
    credentials = settings.credentials_for(device.name)
    target = DeviceTarget(
        device_id=device.pk,
        name=device.name,
        host=host,
        driver=driver,
        port=credentials.port,
        username=credentials.username,
        password=credentials.password,
        enable_password=credentials.enable_password,
    )
    return target, note
