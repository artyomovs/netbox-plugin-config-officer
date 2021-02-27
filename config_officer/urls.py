from django.urls import path
from . import views

urlpatterns = [
    path('collect_all_cisco_configs/', views.GetConfigFromAllCiscoDevices.as_view(), name='collect_all_cisco_configs'),
    path('collection_status/', views.CollectStatusListView.as_view(), name='collection_status'),
    path('collect_device_config/<slug:slug>/', views.collect_device_config, name='collect_device_config'),
]
