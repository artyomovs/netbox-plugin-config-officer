from extras.plugins import PluginMenuButton, PluginMenuItem
from utilities.choices import ButtonColorChoices

menu_items = (
    PluginMenuItem(
        link='plugins:config_officer:collection_status',
        link_text='Running-config collection status',
    ),      
    PluginMenuItem(
        link='plugins:config_officer:template_list',
        link_text='Configure services and templates',
    ), 
    PluginMenuItem(
        link='plugins:config_officer:service_mapping_list',
        link_text='Check compliance status',         
    ),              
    # PluginMenuItem(
    #     link='plugins:config_officer:template_list',
    #     link_text='Configure services and templates',
    # ), 
    # PluginMenuItem(
    #     link='plugins:config_officer:service_mapping_list',
    #     link_text='Compliance status',  
    #     # buttons=(
    #     #     PluginMenuButton('plugins:config_officer:service_mapping_list', 'Service assignment', 'fa fa-list-ol', ButtonColorChoices.BLUE),                                  
            
    #     # )             
    # ),                          
)
