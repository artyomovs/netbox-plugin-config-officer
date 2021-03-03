"""REST API URLs for compliance."""

from rest_framework import routers
from .views import GlobalDataCollectionView

router = routers.DefaultRouter()
router.register(r"collection", GlobalDataCollectionView)
urlpatterns = router.urls
