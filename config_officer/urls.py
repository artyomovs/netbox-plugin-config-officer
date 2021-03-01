from django.urls import path
from . import views

urlpatterns = [
    # Collect configuration
    path('collect_all_cisco_configs/', views.GlobalCollectionDeviceConfigs.as_view(), name='collect_all_cisco_configs'),
    path('collection_status/', views.CollectStatusListView.as_view(), name='collection_status'),
    path('collect_device_config/<slug:slug>/', views.collect_device_config, name='collect_device_config'),
    path('collection_task_delete/', views.CollectTaskDelete.as_view(), name='collection_task_delete'),

    
    # Templates
    path("templates/", views.TemplateListView.as_view(), name="template_list"),    
    path("templates/add/", views.TemplateCreateView.as_view(), name="template_add"),
    path("templates/delete/", views.TemplateBulkDeleteView.as_view(), name="templates_bulk_delete"),    
    path("templates/<int:pk>", views.TemplateView.as_view(), name="template"),
    path("templates/<int:pk>/edit", views.TemplateEditView.as_view(), name="template_edit"),
    path("templates/<int:pk>/delete", views.TemplateDeleteView.as_view(), name="template_delete"),

    # Services
    path("service_list/", views.ServiceListView.as_view(), name="service_list"),
    path("services/add/", views.ServiceCreateView.as_view(), name="service_add"),
    path("services/delete/", views.ServiceBulkDeleteView.as_view(), name="services_bulk_delete"),    
    path("services/<int:pk>", views.ServiceView.as_view(), name="service"),
    path("services/<int:pk>/edit", views.ServiceEditView.as_view(), name="service_edit"),
    path("services/<int:pk>/delete", views.ServiceDeleteView.as_view(), name="service_delete"),

    # Service rules
    path('service_rules/', views.ServiceRuleListView.as_view(), name='service_rules_list'),
    path('service_rules/add/', views.ServiceRuleCreateView.as_view(), name='service_rule_add'),
    path('service_rules/<int:pk>/edit/', views.ServiceRuleEditView.as_view(), name='service_rule_edit'),
    path('service_rules/<int:pk>/delete/', views.ServiceRuleDeleteView.as_view(), name='service_rule_delete'),    

    # Compliance
    path("service_mapping/", views.ServiceMappingListView.as_view(), name="service_mapping_list"),
    path("service_mapping/add/", views.ServiceMappingCreateView.as_view(), name="service_mapping_add"),
    path("service_mapping/assign", views.ServiceAssign.as_view(), name="assign_service"),    
    path("service_mapping/remove", views.ServiceDetach.as_view(), name="remove_assignment"),    
    path("service_mapping/<int:pk>/delete", views.ServiceMappingDeleteView.as_view(), name="service_mapping_delete"),      

    path('compliance/<int:device>', views.ComplianceView.as_view(), name='compliance'),  

    #Show running-config information page
    path("running_config/<slug:hostname>/", views.running_config, name="running_config"),    
]   

