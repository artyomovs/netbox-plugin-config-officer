"""Plugin menu. Items are only shown to users holding the listed permissions."""

from django.utils.translation import gettext_lazy as _
from netbox.choices import ButtonColorChoices
from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem


def _add_button(link: str, permission: str) -> PluginMenuButton:
    return PluginMenuButton(
        link=link,
        title=_("Add"),
        icon_class="mdi mdi-plus-thick",
        color=ButtonColorChoices.GREEN,
        permissions=[permission],
    )


menu = PluginMenu(
    label="Config Officer",
    icon_class="mdi mdi-account-tie-hat",
    groups=(
        (
            _("Collection"),
            (
                PluginMenuItem(
                    link="plugins:config_officer:collection_dashboard",
                    link_text=_("Run & monitor"),
                    permissions=["config_officer.view_collection"],
                ),
                PluginMenuItem(
                    link="plugins:config_officer:collection_list",
                    link_text=_("Results"),
                    permissions=["config_officer.view_collection"],
                ),
                PluginMenuItem(
                    link="plugins:config_officer:collectschedule_list",
                    link_text=_("Schedules"),
                    permissions=["config_officer.view_collectschedule"],
                    buttons=(
                        _add_button(
                            "plugins:config_officer:collectschedule_add",
                            "config_officer.add_collectschedule",
                        ),
                    ),
                ),
            ),
        ),
        (
            _("Compliance"),
            (
                PluginMenuItem(
                    link="plugins:config_officer:compliance_list",
                    link_text=_("Device status"),
                    permissions=["config_officer.view_compliance"],
                ),
                PluginMenuItem(
                    link="plugins:config_officer:template_list",
                    link_text=_("Templates"),
                    permissions=["config_officer.view_template"],
                    buttons=(
                        _add_button(
                            "plugins:config_officer:template_add", "config_officer.add_template"
                        ),
                    ),
                ),
                PluginMenuItem(
                    link="plugins:config_officer:service_list",
                    link_text=_("Services"),
                    permissions=["config_officer.view_service"],
                    buttons=(
                        _add_button(
                            "plugins:config_officer:service_add", "config_officer.add_service"
                        ),
                    ),
                ),
                PluginMenuItem(
                    link="plugins:config_officer:servicerule_list",
                    link_text=_("Service rules"),
                    permissions=["config_officer.view_servicerule"],
                    buttons=(
                        _add_button(
                            "plugins:config_officer:servicerule_add",
                            "config_officer.add_servicerule",
                        ),
                    ),
                ),
            ),
        ),
    ),
)
