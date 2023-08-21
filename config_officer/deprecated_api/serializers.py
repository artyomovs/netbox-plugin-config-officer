from rest_framework import serializers
from config_officer.models import Collection


class CollectionSerializer(serializers.ModelSerializer):
    """Serializer for the Collection model."""

    class Meta:
        """Meta class."""

        model = Collection
        fields = [
            "device",
            "status",
            "message",
        ]