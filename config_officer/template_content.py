"""Additions to NetBox's device page: a "Collect config" button and a status panel.

The "Configuration" and "Compliance" tabs on the device page are views, see
views.DeviceConfigView and views.DeviceComplianceView.
"""

from netbox.plugins import PluginTemplateExtension

from .models import Collection, Compliance
from .permissions import COLLECT_CONFIG, VIEW_CONFIG


class DeviceConfigOfficer(PluginTemplateExtension):
    models = ["dcim.device"]

    def buttons(self):
        device = self.context["object"]
        user = self.context["request"].user
        if not user.has_perm(COLLECT_CONFIG, device):
            return ""
        return self.render(
            "config_officer/inc/collect_button.html", extra_context={"device": device}
        )

    def right_page(self):
        device = self.context["object"]
        user = self.context["request"].user
        can_view_results = user.has_perm("config_officer.view_collection")
        can_view_compliance = user.has_perm("config_officer.view_compliance")
        if not (can_view_results or can_view_compliance):
            return ""
        return self.render(
            "config_officer/inc/device_panel.html",
            extra_context={
                "device": device,
                "latest_result": Collection.objects.filter(device=device).first()
                if can_view_results
                else None,
                "compliance": Compliance.objects.filter(device=device).first()
                if can_view_compliance
                else None,
                "can_view_results": can_view_results,
                "can_view_compliance": can_view_compliance,
                "can_view_config": user.has_perm(VIEW_CONFIG, device),
            },
        )


template_extensions = [DeviceConfigOfficer]
