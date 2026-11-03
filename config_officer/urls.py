"""UI routes (mounted under /plugins/config_officer/).

Model views are registered with ``@register_model_view`` in views.py and pulled
in with ``get_model_urls``, which also adds the change log / journal / jobs tabs.
The device tabs ("Configuration", "Compliance") live under /dcim/devices/<pk>/.
"""

from django.urls import include, path
from django.views.generic import RedirectView
from utilities.urls import get_model_urls

from . import views


def model_urls(prefix: str, model_name: str):
    return [
        path(f"{prefix}/", include(get_model_urls("config_officer", model_name, detail=False))),
        path(f"{prefix}/<int:pk>/", include(get_model_urls("config_officer", model_name))),
    ]


urlpatterns = [
    # Collection
    path("collection/", views.CollectionDashboardView.as_view(), name="collection_dashboard"),
    path("runs/<int:pk>/", views.CollectionRunView.as_view(), name="run"),
    *model_urls("results", "collection"),
    *model_urls("schedules", "collectschedule"),
    path(
        "schedules/<int:pk>/run/",
        views.CollectScheduleRunView.as_view(),
        name="collectschedule_run",
    ),
    path("devices/<int:pk>/collect/", views.DeviceCollectView.as_view(), name="device_collect"),
    path(
        "devices/<int:pk>/config-status/",
        views.DeviceConfigStatusView.as_view(),
        name="device_config_status",
    ),
    # Compliance
    *model_urls("templates", "template"),
    *model_urls("services", "service"),
    *model_urls("service-rules", "servicerule"),
    path("compliance/", views.ComplianceListView.as_view(), name="compliance_list"),
    path("compliance/assign/", views.AssignServicesView.as_view(), name="compliance_assign"),
    path("compliance/detach/", views.DetachServicesView.as_view(), name="compliance_detach"),
    path("compliance/recheck/", views.RecheckComplianceView.as_view(), name="compliance_recheck"),
    # 0.1.x addresses (bookmarks, custom links)
    path(
        "running_config/<str:hostname>/",
        views.LegacyRunningConfigRedirect.as_view(),
        name="running_config",
    ),
    path("compliance/<int:device>/", views.LegacyComplianceRedirect.as_view(), name="compliance"),
    path(
        "collection_status/",
        RedirectView.as_view(pattern_name="plugins:config_officer:collection_list"),
    ),
    path(
        "service_mapping/",
        RedirectView.as_view(pattern_name="plugins:config_officer:compliance_list"),
    ),
]
