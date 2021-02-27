"""There are the purposes of this plugin:
* Collection Cisco device show-running configuration and save to the local git repo
* Show diffs in device's configuraions duing the period.
* Set up device templates and check which devices are compliant with predefined templates.

This plugin is available only for Cisco devices as for now."""

from extras.plugins import PluginConfig


class NetboxConfigOfficer(PluginConfig):
    name = "config_officer"
    verbose_name = "Config officer"
    description = "Cisco configuration monitoring and template compliance"
    version = "0.0.1"
    author = "Sergei Artemov"
    base_url = "config_officer"
    author_email = "artemov.sergey1989@gmail.com"
    required_settings = []
    default_settings = {}
    base_url = "config_officer"
    caching_config = {}


config = NetboxConfigOfficer
