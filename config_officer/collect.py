from .custom_exceptions import CollectionException
from .choices import CollectFailChoices
import pytz
from datetime import datetime
import os
import socket
import time
from scrapli.driver.core import IOSXEDriver, NXOSDriver, IOSXRDriver
from django.conf import settings
import re
from netaddr import EUI
from dcim.choices import InterfaceTypeChoices
from ipam.choices import IPAddressRoleChoices, IPAddressStatusChoices
from dcim.models import Interface, DeviceType
from ipam.models import IPAddress, Prefix, VRF
from dcim.fields import mac_unix_expanded_uppercase
import importlib

PLUGIN_SETTINGS = settings.PLUGINS_CONFIG.get("config_officer", dict())
DEVICE_USERNAME = PLUGIN_SETTINGS.get("DEVICE_USERNAME", "cisco")
DEVICE_SSH_PORT = PLUGIN_SETTINGS.get("DEVICE_SSH_PORT", 22)
DEVICE_PASSWORD = PLUGIN_SETTINGS.get("DEVICE_PASSWORD", "cisco")
CF_NAME_SW_VERSION = PLUGIN_SETTINGS.get("CF_NAME_SW_VERSION", "")
CF_NAME_SSH = PLUGIN_SETTINGS.get("CF_NAME_SSH", "")
CF_NAME_LAST_COLLECT_DATE = PLUGIN_SETTINGS.get("CF_NAME_LAST_COLLECT_DATE", "")
CF_NAME_LAST_COLLECT_TIME = PLUGIN_SETTINGS.get("CF_NAME_LAST_COLLECT_TIME", "")
NETBOX_DEVICES_CONFIGS_DIR = PLUGIN_SETTINGS.get(
    "NETBOX_DEVICES_CONFIGS_DIR", "/device_configs"
)
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
NETBOX_DUAL_SIM_PLATFORM = PLUGIN_SETTINGS.get("NETBOX_DUAL_SIM_PLATFORM", "None")
COLLECT_INTERFACES_DATA = PLUGIN_SETTINGS.get("COLLECT_INTERFACES_DATA", False)
REGEX_IP = "\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"

PLATFORMS = {"iosxe": IOSXEDriver, "iosxe": IOSXEDriver, "nxos": NXOSDriver, "iosxr": IOSXRDriver}


class DeviceInterface:
    def __init__(self, name, **kwargs):
        self.name = name
        self.dhcp = False
        self.mtu = 1500
        self.__dict__.update(kwargs)

    def __str__(self):
        return self.name


class CiscoDevice:
    """Cisco Device object. Functions to work with device actual data."""

    def __init__(self, task, platform="iosxe"):
        self.hostname = ""
        self.pid = ""
        self.sn = ""
        self.sw = ""
        self.task = task
        self.mgmt_if = ""
        self.interfaces = {}

    def check_reachability(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.device["host"], 22))
        except Exception:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((self.device["host"], 23))
            except Exception:
                raise CollectionException(
                    reason=CollectFailChoices.FAIL_CONNECT,
                    message="Device unreachable",
                )
        time.sleep(1)

    # Get interfaces information (IP, MTU, etc.)
    def parse_show_interfaces(self, connection):
        outputs = connection.send_commands(
            [
                "show ip interface brief | include [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+",
                "show ip interface | include (VPN)|(line protocol)|(nternet address is)|(ddress determined)|(MTU is)|(Secondary address)",
                "show interfaces | include (line protocol)|(ardware is)|(escription)",
            ]
        )

        ifaces = re.split(r"\n(?=\S)", outputs[0].result)
        for iface in ifaces:
            r = re.match(rf"^(\S+)\s+({REGEX_IP})", iface)
            if r:
                self.interfaces.setdefault(
                    r.group(1), DeviceInterface(name=r.group(1), ip=r.group(2))
                )
                if r.group(2) == self.device["host"]:
                    self.mgmt_if = r.group(1)
            r = re.match(rf"^(\S+)\s+(unassigned)", iface)
            if r:
                self.interfaces.setdefault(r.group(1), DeviceInterface(name=r.group(1)))

        ifaces = re.split(r"\n(?=\S)", outputs[1].result)
        for iface in ifaces:
            i = ""
            for line in iface.splitlines():
                r = re.match(r"^(\S+)\s+is\s+.*protocol\s+is\s.*", line)
                if r:
                    if r.group(1) in self.interfaces:
                        i = r.group(1)
                        continue
                    else:
                        break
                r = re.match(rf"^\s+.*address\s+is\s+({REGEX_IP}/\d+)", line)
                if r:
                    self.interfaces[i].address = r.group(1)
                    continue
                r = re.match(r"^\s+.*determined\s+by\s+(DHCP|IPCP){1}", line)
                if r:
                    self.interfaces[i].dhcp = True
                    continue
                r = re.match(r"^\s+.*MTU\s+is\s+(\d+)\s+bytes", line)
                if r:
                    self.interfaces[i].mtu = int(r.group(1))
                    continue
                r = re.match(r"^\s+VPN\s+Routing.*\"(\S+)\"", line)
                if r:
                    self.interfaces[i].vrf = r.group(1)
                    continue
                r = re.match(rf"^\s+Secondary\s+address\s+({REGEX_IP}/\d+)", line)
                if r:
                    if not hasattr(self.interfaces[i], "secondary"):
                        self.interfaces[i].secondary = [r.group(1)]
                    else:
                        self.interfaces[i].secondary.append(r.group(1))
                    continue

        ifaces = re.split(r"\n(?=\S)", outputs[2].result)
        for iface in ifaces:
            i = ""
            for line in iface.splitlines():
                r = re.match(r"^(\S+)\s+is\s+.*protocol\s+is\s.*", line)
                if r:
                    if r.group(1) in self.interfaces:
                        i = r.group(1)
                        continue
                    else:
                        break
                r = re.match(r"^\s+Description:\s+(.*)", line)
                if r:
                    self.interfaces[i].description = r.group(1)
                    continue
                r = re.match(r"^\s+Hardware\s+.*\(bia\s+(\S{14})\)", line)
                if r:
                    self.interfaces[i].mac = r.group(1)
                    continue

    def parse_sim_info(self, connection):
        """Get SIM info."""
        outputs = connection.send_commands(
            [
                "show controllers cellular 0 | s (^SIM [0|1])",
            ]
        )

        for line in outputs[0].result.splitlines():
            r = re.match(r"^SIM\s+\d+\s+is\s+present", line)
            if r:
                self.sim_count += 1
                continue
            r = re.match(r"^SIM\s+(\d)+\s+is\s+active\s+SIM", line)
            if r:
                self.sim_active = r.group(1)
                continue

    def get_device_info(self, connection):
        """Gather and parse information from device."""
        if self.platform == "iosxe":
            parsed = connection.send_command("show version").textfsm_parse_output()[0]
            self.hostname = parsed["hostname"]
            self.pid = parsed["hardware"][0]
            self.sn = parsed["serial"][0]
            self.sw = parsed["version"]
        elif self.platform == "nxos":
            parsed = connection.send_command("show version").textfsm_parse_output()[0]
            self.hostname = parsed["hostname"]
            self.pid = parsed["platform"]
            self.sn = parsed["serial"]
            self.sw = parsed["os"]
        elif self.platform == "iosxr":
            result = connection.send_command("show version").result
            r_search = re.search(r"\n(.*)uptime", result)
            if r_search:
                self.hostname = r_search.group(1)
            r_search = re.search(r"Version\s(.*)\n", result)
            if r_search:
                self.sw = r_search.group(1)
            self.sn = ""
            r_search = re.search(r"cisco\s(.*)\sprocessor", result)
            if r_search:
                self.pid = r_search.group(1)
        if COLLECT_INTERFACES_DATA:
            self.parse_show_interfaces(connection)
        if self.pid in NETBOX_DUAL_SIM_PLATFORM:
            self.parse_sim_info(connection)

    def update_custom_field(self, cf_name, cf_value):
        """Update netbox custom_field value."""
        device_netbox = self.task.device
        device_netbox.custom_field_data[cf_name] = cf_value
        device_netbox.save()


class CollectDeviceData(CiscoDevice):
    """Object to parse information from Devices and save to NetBox."""

    global PLATFORMS
    global DEFAULT_PLATFORM

    def __init__(self, collect_task, ip="", hostname_ipam="", platform=""):
        super().__init__(task=collect_task)
        self.collect_status = False
        self.hostname_ipam = hostname_ipam.strip()
        self.device = {
            "host": ip,
            "auth_username": DEVICE_USERNAME,
            "auth_password": DEVICE_PASSWORD,
            "auth_strict_key": False,
            "ssh_config_file": os.path.dirname(
                importlib.util.find_spec("config_officer").origin
            )
            + "/ssh_config",
        }
        self.platform = platform if platform in PLATFORMS else "iosxe"

    # Check if NetBox and Device data are the same
    def check_netbox_sync(self):
        if self.hostname_ipam.lower().strip() != self.hostname.lower().strip():
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
        self.update_custom_field(
            CF_NAME_LAST_COLLECT_DATE, datetime.now(pytz.timezone(TIME_ZONE)).date()
        )
        self.update_custom_field(
            CF_NAME_LAST_COLLECT_TIME,
            datetime.now(pytz.timezone(TIME_ZONE)).strftime("%H:%M:%S"),
        )

        # Update information about interfaces
        if COLLECT_INTERFACES_DATA:
            ipam_interfaces_list = [
                str(x) for x in list(Interface.objects.filter(device=self.task.device))
            ]

            template_interfaces = list(
                map(
                    lambda d: d["name"],
                    DeviceType.objects.get(
                        slug__iexact=self.pid
                    ).interfacetemplates.values("name"),
                )
            )

            # Delete extra interfaces that non-compliant with DeviceType and don't contain in device from netbox
            for inter in Interface.objects.filter(device=self.task.device):
                if (inter.name not in list(self.interfaces.keys())) and (
                    inter.name not in template_interfaces
                ):
                    inter.delete()

            # Write down interfaces into NetBox
            for k, v in self.interfaces.items():
                if k not in ipam_interfaces_list:
                    if re.match(r"^FastEthernet", k, re.IGNORECASE):
                        new_if_type = InterfaceTypeChoices.TYPE_100ME_FIXED
                    elif re.match(r"^GigabitEthernet", k, re.IGNORECASE):
                        new_if_type = InterfaceTypeChoices.TYPE_1GE_FIXED
                    elif re.match(r"^Vlan", k, re.IGNORECASE):
                        new_if_type = InterfaceTypeChoices.TYPE_VIRTUAL
                    elif re.match(r"^Loopback", k, re.IGNORECASE):
                        new_if_type = InterfaceTypeChoices.TYPE_VIRTUAL
                    else:
                        new_if_type = InterfaceTypeChoices.TYPE_OTHER

                    interface_ipam = Interface.objects.create(
                        device=self.task.device, name=k, type=new_if_type
                    )
                else:
                    interface_ipam = Interface.objects.get(
                        device=self.task.device, name__iexact=k
                    )

                # # Delete extra ips from IPAM
                if hasattr(v, "address"):
                    interface_addresses = [v.address]
                else:
                    interface_addresses = list()
                if hasattr(v, "secondary"):
                    interface_addresses.append(v.secondary)

                for ip_ipam in IPAddress.objects.filter(interface=interface_ipam):
                    if str(ip_ipam) not in interface_addresses:
                        ip_ipam.delete()

                # Create address if not exist in IPAM
                if hasattr(v, "address"):
                    ips_ipam_str_list = [
                        str(x.address)
                        for x in IPAddress.objects.filter(interface=interface_ipam)
                    ]
                    if v.address not in ips_ipam_str_list:
                        ip = IPAddress.objects.create(
                            address=v.address, tenant=self.task.device.tenant
                        )
                        interface_ipam.ip_addresses.add(ip)

                        if re.match(r"^Loopback", k, re.IGNORECASE):
                            ip.role = IPAddressRoleChoices.ROLE_LOOPBACK
                    else:
                        ip = IPAddress.objects.get(
                            address=v.address, interface=interface_ipam
                        )

                    if hasattr(v, "vrf"):
                        try:
                            ip.vrf = VRF.objects.get(name__iexact=v.vrf)
                        except VRF.DoesNotExist:
                            new_vrf = VRF.objects.create(
                                name=v.vrf, enforce_unique=False
                            )
                            # new_vrf.tags.add(NETBOX_NONCOMPLIANCE_TAG)
                            new_vrf.save()
                            ip.vrf = new_vrf

                    if v.dhcp:
                        ip.status = IPAddressStatusChoices.STATUS_DHCP
                    ip.save()
                if hasattr(v, "secondary"):
                    for i in v.secondary:
                        ip = IPAddress.objects.create(
                            address=i, role=IPAddressRoleChoices.ROLE_SECONDARY
                        )
                        interface_ipam.ip_addresses.add(ip)
                        # ip.interface = Interface.objects.get(device=self.ot.device, name__iexact=k)
                        if hasattr(v, "vrf"):
                            ip.vrf = VRF.objects.get(name__iexact=v.vrf)
                        # ip.tags.add(NETBOX_NONCOMPLIANCE_TAG)
                        ip.save()

                # Change interface data
                if hasattr(v, "description"):
                    interface_ipam.description = v.description

                if hasattr(v, "mac"):
                    interface_ipam.mac_address = EUI(
                        v.mac, version=48, dialect=mac_unix_expanded_uppercase
                    )

                # if k == self.mgmt_if:
                #     self.task.device.primary_ip4 = ip
                #     self.task.device.save()

                interface_ipam.save()

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
            with PLATFORMS[self.platform](**self.device) as connection:
                self.get_device_info(connection)
        except Exception:
            try:
                with PLATFORMS[self.platform](**self.device) as connection:
                    self.get_device_info(connection)
            except Exception:
                raise CollectionException(
                    reason=CollectFailChoices.FAIL_LOGIN,
                    message="Can not login",
                )

        self.check_netbox_sync()
        self.update_in_netbox()

        # save to git repo
        self.hostname = self.hostname.strip()
        filename = f"{NETBOX_DEVICES_CONFIGS_DIR}/{self.hostname}_running.txt"
        with PLATFORMS[self.platform](**self.device) as connection:
            self.save_running_config_to_file(connection, filename)
