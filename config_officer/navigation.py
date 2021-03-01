from extras.plugins import PluginMenuButton, PluginMenuItem
from utilities.choices import ButtonColorChoices

menu_items = (
    PluginMenuItem(
        link='plugins:config_officer:collection_status',
        link_text='Device data collection',
        buttons=(
            PluginMenuButton(
                link = 'plugins:config_officer:collect_all_cisco_configs', 
                title = 'Start global collection', 
                icon_class = 'mdi mdi-earth', 
                color = ButtonColorChoices.BLUE
            ),                                  
            
        )         
    ),      
    PluginMenuItem(
        link='plugins:config_officer:template_list',
        link_text='Templates configuration',
    ), 
    PluginMenuItem(
        link='plugins:config_officer:service_mapping_list',
        link_text='Templates compliance status',         
    ),                                     
)
