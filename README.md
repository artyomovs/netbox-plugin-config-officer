# Config Officer - NetBox plugin


NetBox plugin that deals with Cisco device configuration (collects running config from Cisco devices, indicates config changes and checks templates compliance).

A plugin for [NetBox](https://github.com/netbox-community/netbox) to work with running-configurations of Cisco devices.

- Collect actual information from Cisco devices (running_config, version, ip addresses, etc.) and shows it on a dedicated NetBox page.
- Save Cisco running configuration in local directory and display all changes with git-like diffs.
- Set up configuration templates for distinct device roles, types.
- Audit whether devices are configured according to appropriate template.
- Export template compliance detailed information to Excel.

## Installation and configuration

>Watch [YouTube](https://www.youtube.com/watch?v=O5kayrkuC1E) video about installation and usage of the plugin

This instruction only describes how to install this plugin into [Docker-compose](https://github.com/netbox-community/netbox-docker) instance of NetBox.
>General installation steps and considerations follow the [official guidelines](https://netbox.readthedocs.io/en/stable/plugins/).
>The plugin is available as a Python package from [PyPi](https://pypi.org/project/netbox-plugin-config-officer/) or from [GitHub](https://github.com/artyomovs/netbox-plugin-config-officer).

### 0.Pull NetBox docker-compose version from GitHub

```shell
mkdir ~/netbox && cd "$_"
git clone https://github.com/netbox-community/netbox-docker
```

### 1.Create new docker container based on latest netbox image

```shell
cd ~/netbox
git clone https://github.com/artyomovs/netbox-plugin-config-officer
cd netbox-plugin-config-officer
sudo docker build -t netbox-myplugins .
```

>What's in the Dockerfile:
>
>```dockerfile
>FROM netboxcommunity/netbox:latest
>RUN apk add iputils bind-tools openssh-client git
>COPY ./requirements.txt /
>COPY . /netbox-plugin-config-officer/
>RUN /opt/netbox/venv/bin/pip install install -r /requirements.txt
>RUN /opt/netbox/venv/bin/pip install  --no-warn-script-location /netbox-plugin-config-officer/
>```

### 2.Create local git repository and perform first commit

```shell
mkdir ~/netbox/netbox-docker/device_configs && cd "$_"
git init 
echo hello > hello.txt
git add .
git commit -m "Initial"
```

### 3. Change **netbox** service in docker-compose.yml (do not delete, just add new lines and change image name)

```dockerfile
version: '3.4'
services:
  netbox: &netbox
    # Change image name to netbox-myplugins (old name is netboxcommunity/netbox:${VERSION-latest})
    image: netbox-myplugins
    ...
    #...Add environment variables for git:
    environment: 
      - GIT_PYTHON_GIT_EXECUTABLE=/usr/bin/git
      - GIT_COMMITTER_NAME=netbox
      - GIT_COMMITTER_EMAIL=netbox@example.com
    # user: '101' <---   Comment this. I don't know how to make ssh work with this line as for now.
    volumes:    
    #...add this volume:...
      - ./device_configs:/device_configs:z
    ports:
    - 8080:8080      
```

### 4. Update the *PLUGINS* parameter in the global Netbox **configuration.py** config file in *netbox-docker/configuration* directory

```python
PLUGINS = [
    "config_officer"
]
```

Update a PLUGINS_CONFIG parameter in **configuration.py** to change plugin's options:

```python
PLUGINS_CONFIG = {
    "config_officer": {
        # Credentials to cisco devices:
        "DEVICE_USERNAME": "cisco",
        "DEVICE_PASSWORD": "cisco",

        # Mount this directory to NetBox on docker-compose.yml
        "NETBOX_DEVICES_CONFIGS_DIR": "/device_configs",

        # Add these custom fields to NetBox in advance. 
        "CF_NAME_SW_VERSION": "version",
        "CF_NAME_SSH": "ssh",
        "CF_NAME_LAST_COLLECT_DATE": "last_collect_date",
        "CF_NAME_LAST_COLLECT_TIME": "last_collect_time",
        "CF_NAME_COLLECTION_STATUS": "collection_status",        
    }
}
```

### 6. Start Docker-compose

```shell
$ cd ~/netbox/netbox-docker/
sudo docker-compose up -d
```

### 7. When NetBox is started - open the web interface `http://NETBOX_IP:8080` and open Admin panel in right top corner and create elements

#### Custom Links

| Name                  | Content type  | URL                                                                            |
|-----------------------|---------------|--------------------------------------------------------------------------------|
| collect_device_data   | dcim > device | *`http://NETBOX_IP:8080/plugins/config_officer/collect_device_config/{{ obj }}`* |
| show_running_config   | dcim > device | *`http://NETBOX_IP:8080/plugins/config_officer/running_config/{{ obj.name }}`*   |

#### Custom Fields (optional)

| Name                  | Label                     | Object(s)     |
|-----------------------|---------------------------|---------------|
| collection_status     | Last collection status    | dcim > device |
| last_collect_date     | Date of last collection   | dcim > device |
| last_collect_time     | Time of last collection   | dcim > device |
| ssh                   | SSH enabled               | dcim > device |
| version               | Software version          | dcim > device |

# Usage

It was a challenge to write down the plugin usage instruction. Now you could check it on [YouTube](https://www.youtube.com/watch?v=O5kayrkuC1E) video about installation and usage of the plugin