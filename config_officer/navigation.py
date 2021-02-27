from extras.plugins import PluginMenuButton, PluginMenuItem
from utilities.choices import ButtonColorChoices

menu_items = (
    PluginMenuItem(
        link='plugins:config_officer:collect_all_cisco_configs',
        link_text='Test',
    ),     
    PluginMenuItem(
        link='plugins:config_officer:collection_status',
        link_text='Config collection status',
    ),       
    # PluginMenuItem(
    #     link='plugins:config_monitor:template_list',
    #     link_text='Configure services and templates',
    # ), 
    # PluginMenuItem(
    #     link='plugins:config_monitor:service_mapping_list',
    #     link_text='Compliance status',  
    #     # buttons=(
    #     #     PluginMenuButton('plugins:config_monitor:service_mapping_list', 'Service assignment', 'fa fa-list-ol', ButtonColorChoices.BLUE),                                  
            
    #     # )             
    # ),                          
)
