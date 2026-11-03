"""NetBox Config Officer plugin.

What the plugin does, end to end:

1. **Collect** - connects to Cisco devices (IOS-XE, NX-OS, IOS-XR) over SSH or
   Telnet, runs a fixed set of read-only ``show`` commands and fetches the
   running configuration (``collection/``).
2. **Sync** - writes what it learned back into NetBox: serial number, software
   version custom fields, interfaces, LAG membership, IP and MAC addresses
   (``collection/netbox_sync.py``).
3. **Store** - saves the sanitised running configuration as a file in a Git
   repository so every change is versioned (``storage.py``).
4. **Audit** - compares the running configuration against compliance
   templates assigned to the device through services (``compliance/``).

Collections run as NetBox background jobs (``jobs.py``), started from the UI,
the REST API or a recurring schedule. See ARCHITECTURE.md for the full map.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

from netbox.plugins import PluginConfig

try:
    # Single source of truth for the version: pyproject.toml.
    __version__ = _package_version("netbox-plugin-config-officer-2")
except PackageNotFoundError:  # running from a source checkout that is not installed
    __version__ = "0.0.0+unknown"


class ConfigOfficerConfig(PluginConfig):
    name = "config_officer"
    verbose_name = "Config Officer"
    description = (
        "Collects Cisco device configurations, tracks changes in Git and audits compliance"
    )
    version = __version__
    author = "Sergei Artemov, Michal Juskiewicz"
    author_email = "artemov.sergey1989@gmail.com, m.juskiewicz66@gmail.com"
    base_url = "config_officer"
    min_version = "4.7.0"
    # All settings are optional and documented in README.md. They are parsed and
    # validated by configuration.py, so no defaults are declared here.
    required_settings = []
    default_settings = {}

    def ready(self):
        super().ready()

        from . import signals  # noqa: F401 - connects the schedule signal handlers
        from .configuration import get_settings
        from .permissions import register_device_actions

        register_device_actions()
        # Surface configuration mistakes (unknown keys, bad values) in the logs at startup.
        get_settings().log_warnings()


config = ConfigOfficerConfig
