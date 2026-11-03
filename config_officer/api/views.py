"""REST API views.

CRUD endpoints for the plugin's objects, read-only endpoints for results, and
``POST runs/`` to start a collection (returns the background job).
"""

from django.http import HttpResponse
from django.urls import reverse
from netbox.api.viewsets import NetBoxModelViewSet, NetBoxReadOnlyModelViewSet
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from config_officer import filtersets
from config_officer.collection.targets import DeviceSelection
from config_officer.jobs import enqueue_collection
from config_officer.models import (
    Collection,
    CollectSchedule,
    Compliance,
    Service,
    ServiceRule,
    Template,
)
from config_officer.permissions import COLLECT_CONFIG

from . import serializers


class TemplateViewSet(NetBoxModelViewSet):
    queryset = Template.objects.prefetch_related("tags")
    serializer_class = serializers.TemplateSerializer
    filterset_class = filtersets.TemplateFilterSet


class ServiceViewSet(NetBoxModelViewSet):
    queryset = Service.objects.prefetch_related("tags")
    serializer_class = serializers.ServiceSerializer
    filterset_class = filtersets.ServiceFilterSet


class ServiceRuleViewSet(NetBoxModelViewSet):
    queryset = ServiceRule.objects.select_related("service", "template").prefetch_related(
        "device_roles", "device_types", "tags"
    )
    serializer_class = serializers.ServiceRuleSerializer
    filterset_class = filtersets.ServiceRuleFilterSet


class CollectScheduleViewSet(NetBoxModelViewSet):
    queryset = CollectSchedule.objects.prefetch_related("devices", "device_tags", "tags")
    serializer_class = serializers.CollectScheduleSerializer
    filterset_class = filtersets.CollectScheduleFilterSet


class CollectionViewSet(NetBoxReadOnlyModelViewSet):
    queryset = Collection.objects.select_related("device", "job").order_by("-timestamp")
    serializer_class = serializers.CollectionSerializer
    filterset_class = filtersets.CollectionFilterSet


class ComplianceViewSet(NetBoxReadOnlyModelViewSet):
    queryset = Compliance.objects.select_related("device").order_by("device__name")
    serializer_class = serializers.ComplianceSerializer


def _start_run(request, selection: DeviceSelection):
    if not request.user.has_perm(COLLECT_CONFIG):
        raise PermissionDenied("The dcim.collect_config_device permission is required.")
    return enqueue_collection(selection, request.user, trigger="api")


class RunCollectionView(APIView):
    """POST {"all_devices": true} | {"tags": ["core"]} | {"devices": [1, 2]} -> 202 + job."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = serializers.RunCollectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        job = _start_run(
            request,
            DeviceSelection(
                all_devices=data["all_devices"],
                tag_slugs=tuple(data["tags"]),
                device_ids=tuple(data["devices"]),
                statuses=tuple(data["statuses"]),
            ),
        )
        return Response(
            {
                "job_id": job.pk,
                "job_uuid": str(job.job_id),
                "run_url": request.build_absolute_uri(
                    reverse("plugins:config_officer:run", kwargs={"pk": job.pk})
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class LegacyGlobalCollectionView(APIView):
    """0.1.x endpoint kept for existing automation: POST task=global_collection."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.data.get("task") != "global_collection":
            return HttpResponse("wrong task")
        job = _start_run(request, DeviceSelection(all_devices=True))
        return HttpResponse(f"Global sync was started (job {job.pk}).")
