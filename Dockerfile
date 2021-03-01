FROM netboxcommunity/netbox:latest
RUN apk add iputils bind-tools openssh-client git

COPY ./requirements.txt /
COPY . /netbox-plugin-config-officer/

RUN /opt/netbox/venv/bin/pip install install -r /requirements.txt
RUN /opt/netbox/venv/bin/pip install  --no-warn-script-location /netbox-plugin-config-officer/