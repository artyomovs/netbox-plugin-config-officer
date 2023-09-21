"""
* Collection Cisco device show-running configuration and save to the local git repo
* Show diffs in device's configuraions duing the period.
* Set up device templates and check which devices are compliant with predefined templates.
"""

from extras.plugins import PluginConfig


class NetboxConfigOfficer(PluginConfig):
    name = "config_officer"
    verbose_name = "Config officer"
    description = "Template compliance and diff reveal"
    version = "0.1.12"
    author = "Sergei Artemov"
    base_url = "config_officer"
    author_email = "artemov.sergey1989@gmail.com"
    base_url = "config_officer"


config = NetboxConfigOfficer
