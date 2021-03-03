from rest_framework.viewsets import ModelViewSet
from .serializers import CollectionSerializer
from django.http import HttpResponse
from config_officer.models import Collection
from config_officer.views import global_collection


class GlobalDataCollectionView(ModelViewSet):
    queryset = Collection.objects.all()
    serializer_class = CollectionSerializer

    def create(self, request):
        """POST request."""
        task = request.POST.get("task")
        if task == "global_collection":
            message = global_collection()
        else:
            message = "wrong task"
        return HttpResponse(message)

    def list(self, request):
        """GET request."""
        return HttpResponse("not allowed")
