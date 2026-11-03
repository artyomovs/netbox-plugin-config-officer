"""There are the purposes of this plugin:
* Collection Cisco device show-running configuration and save to the local git repo
* Show diffs in device's configurations during the period.
* Set up device templates and check which devices are compliant with predefined templates.

This plugin is available only for Cisco devices as for now."""

from netbox.plugins import PluginConfig


class NetboxConfigOfficer(PluginConfig):
    name = "config_officer"
    verbose_name = "Config officer"
    description = "Cisco configuration collector and template compliance"
    version = "0.1.26"
    author = "Sergei Artemov, Michal Juskiewicz"
    author_email = "artemov.sergey1989@gmail.com, m.juskiewicz66@gmail.com"
    base_url = "config_officer"
    required_settings = []
    default_settings = {}
    caching_config = {}


config = NetboxConfigOfficer
