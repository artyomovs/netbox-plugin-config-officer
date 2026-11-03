"""Permission names used by the plugin.

Standard model permissions (``config_officer.view_template`` and friends) cover
the plugin's own objects. Two actions are about *devices* rather than plugin
objects, so they are registered as custom actions on ``dcim.Device``. That way
administrators grant them in a regular NetBox ObjectPermission and can limit
them with constraints, e.g. "collect configs only for devices in site WAW1".

=====================================  ==================================================
Permission                             Allows
=====================================  ==================================================
``dcim.collect_config_device``         Start a collection run for the device(s)
``dcim.view_config_device``            See the collected running config and its history
``config_officer.view_collection``     See collection runs and per-device results
``config_officer.view_compliance``     See compliance status
``config_officer.add_servicemapping``  Assign compliance services to devices
=====================================  ==================================================
"""

from django.utils.translation import gettext_lazy as _

COLLECT_CONFIG_ACTION = "collect_config"
VIEW_CONFIG_ACTION = "view_config"

COLLECT_CONFIG = f"dcim.{COLLECT_CONFIG_ACTION}_device"
VIEW_CONFIG = f"dcim.{VIEW_CONFIG_ACTION}_device"


def register_device_actions():
    """Register the custom device actions so they show up in the ObjectPermission form."""
    from dcim.models import Device
    from utilities.permissions import ModelAction, register_model_actions

    register_model_actions(
        Device,
        [
            ModelAction(
                COLLECT_CONFIG_ACTION,
                help_text=_("Config Officer: collect the running configuration from the device"),
            ),
            ModelAction(
                VIEW_CONFIG_ACTION,
                help_text=_("Config Officer: view the collected configuration and its history"),
            ),
        ],
    )
