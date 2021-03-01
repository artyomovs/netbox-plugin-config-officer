from .custom_exceptions import CollectionException
from .choices import CollectFailChoices
import pytz
from datetime import datetime
import os
import socket
import time
from scrapli.driver.core import IOSXEDriver
from django.conf import settings

PLUGIN_SETTINGS = settings.PLUGINS_CONFIG.get("config_officer", dict())
DEVICE_USERNAME = PLUGIN_SETTINGS.get("DEVICE_USERNAME", "")
DEVICE_PASSWORD = PLUGIN_SETTINGS.get("DEVICE_PASSWORD", "")
CF_NAME_SW_VERSION = PLUGIN_SETTINGS.get("CF_NAME_SW_VERSION", "")
CF_NAME_SSH = PLUGIN_SETTINGS.get("CF_NAME_SSH", "")
CF_NAME_LAST_COLLECT_DATE = PLUGIN_SETTINGS.get("CF_NAME_LAST_COLLECT_DATE", "")
CF_NAME_LAST_COLLECT_TIME = PLUGIN_SETTINGS.get("CF_NAME_LAST_COLLECT_TIME", "")
NETBOX_DEVICES_CONFIGS_DIR = PLUGIN_SETTINGS.get("NETBOX_DEVICES_CONFIGS_DIR", "/device_configs")
TIME_ZONE = os.environ.get("TIME_ZONE", "Europe/Moscow")


class CiscoDevice:
    def __init__(self, task):
        self.hostname = ""
        self.pid = ""
        self.sn = ""
        self.sw = ""
        self.task = task
        self.device = {
            "auth_username": DEVICE_USERNAME,
            "auth_password": DEVICE_PASSWORD,
            "auth_strict_key": False,
            "ssh_config_file": "/root/.ssh/config",
            "port": 22,
            "timeout_socket": 5,
        }

    def check_reachability(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(self.device["timeout_socket"])
                s.connect((self.device["host"], 22))
        except Exception:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(self.device["timeout_socket"])
                    s.connect((self.device["host"], 23))
            except Exception:
                raise CollectionException(
                    reason=CollectFailChoices.FAIL_CONNECT,
                    message="Device unreachable",
                )
        time.sleep(1)

    def get_device_info(self, connection):
        """Gather and parse information from device."""
        parsed = connection.send_command("show version").textfsm_parse_output()[0]
        self.hostname = parsed['hostname']
        self.pid = parsed['hardware'][0]
        self.sn = parsed['serial'][0]
        self.sw = parsed['version']


    def update_custom_field(self, cf_name, cf_value):
        """Update netbox custom_field value."""
        device_netbox = self.task.device
        device_netbox.custom_field_data[cf_name] = cf_value
        device_netbox.save()


class CollectDeviceData(CiscoDevice):
    def __init__(self, collect_task, ip="", hostname_ipam=""):
        super().__init__(task=collect_task)
        self.collect_status = False
        self.hostname_ipam = hostname_ipam
        self.device = {
            "host": ip,
            "auth_username": DEVICE_USERNAME,
            "auth_password": DEVICE_PASSWORD,
            "auth_strict_key": False,
            "ssh_config_file": "/root/.ssh/config",
            "port": 22,
            "timeout_socket": 20,
            "timeout_ops": 60,
        }

    # Check if NetBox and Device data are the same
    def check_netbox_sync(self):
        if self.hostname_ipam.lower() != self.hostname.lower():
            raise CollectionException(
                reason=CollectFailChoices.FAIL_UPDATE,
                message=f"Different hostnames in NetBox and device. IPAM: {self.hostname_ipam}. Device: {self.hostname}",
            )

        if self.task.device.serial != "" and self.task.device.serial != self.sn:
            raise CollectionException(
                reason=CollectFailChoices.FAIL_UPDATE,
                message=f"Different SN in NetBox and Device. IPAM: {self.task.device.serial}. Device: {self.sn}",
            )

    def update_in_netbox(self):
        """Update information in NetBox."""
        # Custom fields
        self.update_custom_field(CF_NAME_SSH, self.device["port"] == 22)
        self.update_custom_field(CF_NAME_SW_VERSION, self.sw.upper())
        self.update_custom_field(CF_NAME_LAST_COLLECT_DATE, datetime.now(pytz.timezone(TIME_ZONE)).date())
        self.update_custom_field(CF_NAME_LAST_COLLECT_TIME, datetime.now(pytz.timezone(TIME_ZONE)).strftime("%H:%M:%S"))

    def save_running_config_to_file(self, connection, filename):
        """Save show run config to git repository."""
        connection.send_command("terminal length 0")
        with open(filename, "w") as f:
            output = connection.send_command("show running-config")
            f.write(output.result)

    def collect_information(self):
        """Sync current device."""
        self.check_reachability()

        try:
            with IOSXEDriver(**self.device) as connection:
                self.get_device_info(connection)
        except Exception:
            self.device["port"] = 23
            self.device["transport"] = "telnet"
            try:
                with IOSXEDriver(**self.device) as connection:
                    self.get_device_info(connection)
            except Exception:
                raise CollectionException(
                    reason=CollectFailChoices.FAIL_LOGIN,
                    message="Can not login",
                )

        self.check_netbox_sync()
        self.update_in_netbox()

        # save to git repo        
        filename = f"{NETBOX_DEVICES_CONFIGS_DIR}/{self.hostname}_running.txt"
        with IOSXEDriver(**self.device) as connection:
            self.save_running_config_to_file(connection, filename.lower())
