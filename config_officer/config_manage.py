"""Class for config text functions."""

import diffios
import re


def get_lines_in_section(config, section):
    """Get lines (i.e ip address x.x.x.x) under the section's name (i.e. interface GigabitEthernet0)."""
    
    output = []
    if section in config:
        if config.index(section) == len(config):
            return []

        for i in range(config.index(section)+1, len(config)):
            line = config[i]
            if re.search(r'^ ', line):
                output.append(line)
                if section in config:
                    config[config.index(section)] = "##_##"
                config[i] = "##_##"
            else:
                break
        return output
    else:
        return []


def is_section(config, line):
    """def ines if this line - is section's name. 
    i.e. interface GigabitEthernet 0."""

    if config.index(line) + 1 == len(config):
        return False
    if re.match(r"^ ", line):
        return False
    else:
        if re.match(r"^ ", config[config.index(line) + 1]):
            return True
        else:
            return False    


def merge_configs(config1, config2):
    """Merge to config with the same sections."""

    output = []

    if config1:
        for line in config1:
            output.append(line)
            if line in config2:
                if is_section(config1, line):
                    for conf_2_line in get_lines_in_section(config2, line):
                        output.append(conf_2_line)
        output.append('!')
    if config2:
        for line in config2:
            if line != "##_##":
                output.append(line)
        output.append('!')                
    return output


def get_config_diff(template, config, ignore=None):
    """Get inconsistency between device running config and template."""
    
    if not ignore:
        ignore = [
            "Building configuration",
            "Current configuration",
            "NVRAM config last updated",
            "Last configuration change",
        ]

    diff = diffios.Compare(template, config, ignore)

    # Get lines that exist in device config only
    additional_lines = diff.additional()

    # Get lines that exist in template only
    missing_lines = diff.missing()

    config_diff = list()
    # Go through lines, that does not exist in device running
    #   --config and get other lines from this "block".
    # missing_lines = [list(map(lambda s: re.sub(r"^ ", " --", s), l)) for l in missing_lines]
    # for missing_line in missing_lines:
    #     if any(missing_line[0] in elem for elem in additional_lines):
    #         block_additional = [additional[1:] for additional in additional_lines if missing_line[0] in additional][0]            
    #         block_additional = map(lambda s: s.replace(" ", " ++", 1), block_additional)
    #         missing_line.extend(block_additional)
    #     config_diff.append(missing_line)

    return missing_lines


def generate_templates_config_for_device(templates):
    """Merge config from matched templates and change it due to vars (custom fields, basic fields, hostname, etc."""

    config = []
    for template in templates:
        config = merge_configs(config, template.configuration.splitlines())
    return "\n".join(config)
