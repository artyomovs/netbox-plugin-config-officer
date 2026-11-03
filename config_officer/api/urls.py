from django.urls import path
from netbox.api.routers import NetBoxRouter

from . import views

router = NetBoxRouter()
router.register("templates", views.TemplateViewSet)
router.register("services", views.ServiceViewSet)
router.register("service-rules", views.ServiceRuleViewSet)
router.register("schedules", views.CollectScheduleViewSet)
router.register("results", views.CollectionViewSet)
router.register("compliance", views.ComplianceViewSet)

urlpatterns = [
    path("runs/", views.RunCollectionView.as_view(), name="run"),
    path("collection/", views.LegacyGlobalCollectionView.as_view(), name="legacy-collection"),
    *router.urls,
]
