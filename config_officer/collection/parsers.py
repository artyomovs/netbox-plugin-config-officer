"""CLI output parsers: raw ``show`` text in, plain dataclasses out.

Pure functions without Django or network access, so they are easy to unit test
with captured device output (see tests/fixtures/). The parsed result is turned
into NetBox objects by netbox_sync.py.

Supported commands:

* IOS-XE (also used for IOS-XR): ``show version``, ``show interfaces``,
  ``show ip interface``
* NX-OS: ``show version``, ``show interface``
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: IPv4 address with prefix length, e.g. 10.0.0.1/24
REGEX_IPP = r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}"


@dataclass
class ParsedInterface:
    """Everything we know about a single interface after parsing CLI output."""

    name: str
    ip: str | None = None  # primary IP/prefix, e.g. "10.0.0.1/24"
    secondary: list[str] = field(default_factory=list)  # secondary IPs/prefix
    mac: str | None = None  # dotted-hex, e.g. "aabb.ccdd.eeff"
    description: str | None = None
    mtu: int | None = None
    vrf: str | None = None
    dhcp: bool = False
    speed: str | None = None  # e.g. "1000Mbps"
    duplex: str | None = None  # "full" | "half"
    admin_up: bool | None = None
    link_up: bool | None = None
    is_mgmt: bool = False
    lag: str | None = None  # normalised LAG name, e.g. "port-channel1"

    def __str__(self) -> str:
        return self.name


@dataclass
class ParsedDevice:
    """Identity information from ``show version`` plus the parsed interfaces."""

    hostname: str = ""
    version: str = ""
    pid: str = ""  # product ID / hardware model
    serial: str = ""
    interfaces: dict[str, ParsedInterface] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_lag_name(raw: str) -> str:
    """Convert NX-OS shorthand (e.g. 'Po103') to NetBox canonical form."""
    number = raw.lower().replace("po", "").strip()
    return f"port-channel{number}"


# ---------------------------------------------------------------------------
# IOS-XE / IOS-XR parser
# ---------------------------------------------------------------------------


class IOSXEParser:
    """
    Parses plain 'show' output from IOS-XE (and most IOS / IOS-XR) devices.
    Raw output is parsed without pipe-filtering so nothing is silently dropped.
    """

    @staticmethod
    def parse_show_version(output: str) -> ParsedDevice:
        logger.debug("[PARSER][IOSXE] parse_show_version: %d chars", len(output))
        result = ParsedDevice()

        for line in output.splitlines():
            if not result.hostname:
                m = re.search(r"^(\S+)\s+uptime is", line)
                if m:
                    result.hostname = m.group(1)
                    logger.debug("[PARSER][IOSXE] hostname=%r", result.hostname)

            if not result.version:
                m = re.search(r"(?:Cisco IOS.*?|)Version\s+([\w.\(\):]+)", line, re.IGNORECASE)
                if m:
                    result.version = m.group(1)
                    logger.debug("[PARSER][IOSXE] version=%r", result.version)

            if not result.pid:
                m = re.search(r"[Cc]isco\s+([\w\-]+).*?(?:[Pp]rocessor|bytes of memory)", line)
                if m:
                    result.pid = m.group(1)
                    logger.debug("[PARSER][IOSXE] pid=%r", result.pid)

            if not result.serial:
                m = re.search(r"[Pp]rocessor [Bb]oard ID\s+(\S+)", line)
                if m:
                    result.serial = m.group(1)
                    logger.debug("[PARSER][IOSXE] serial=%r", result.serial)

        return result

    @staticmethod
    def parse_show_interfaces(output: str, mgmt_ip: str) -> dict[str, ParsedInterface]:  # noqa: PLR0915
        """
        Parse 'show interfaces' full output.
        Returns a mapping of interface-name -> ParsedInterface.
        """
        logger.debug("[PARSER][IOSXE] parse_show_interfaces: %d chars", len(output))
        ifaces: dict[str, ParsedInterface] = {}
        current: ParsedInterface | None = None

        for line in output.splitlines():
            # Every new interface block starts at column 0 with the name
            m = re.match(
                r"^(\S+.*?)\s+is\s+(administratively\s+)?(up|down),\s+line protocol is\s+(up|down)",
                line,
                re.IGNORECASE,
            )
            if m:
                name = m.group(1).strip()
                current = ParsedInterface(name=name)
                current.admin_up = ("administratively" not in line.lower()) and m.group(3) == "up"
                current.link_up = m.group(4) == "up"
                ifaces[name] = current
                logger.debug(
                    "[PARSER][IOSXE] Interface=%r admin_up=%s link_up=%s",
                    name,
                    current.admin_up,
                    current.link_up,
                )
                continue

            if current is None:
                continue

            # Description
            m = re.match(r"^\s+Description:\s+(.*)", line)
            if m:
                current.description = m.group(1).strip()
                continue

            # Hardware / MAC  (IOS prints "address is" or "BIA")
            m = re.match(
                r"^\s+Hardware is.*?(?:address is|BIA)\s+([\da-f]{4}\.[\da-f]{4}\.[\da-f]{4})",
                line,
                re.IGNORECASE,
            )
            if m and not current.mac:
                current.mac = m.group(1)
                continue

            # Duplex / speed, as printed by IOS / IOS-XE:
            #   "  Full-duplex, 1000Mb/s, media type is ..."  or  "  Full Duplex, 1000Mbps, link type ..."
            m = re.match(
                r"^\s+(Full|Half|Auto)[- ]duplex,\s+(\d+)\s*(Kb|Mb|Gb)(?:/s|ps)",
                line,
                re.IGNORECASE,
            )
            if m:
                current.duplex = m.group(1).lower()
                current.speed = f"{m.group(2)}{m.group(3).capitalize()}ps"
                continue
            # Older format: "  ... 1000Mbps, full-duplex"
            m = re.match(r"^\s+.*?(\d+(?:Mb|Gb|Kb)?ps),?\s+([\w-]+)-duplex", line, re.IGNORECASE)
            if m:
                current.speed = m.group(1)
                current.duplex = m.group(2).lower()
                continue

            # MTU
            m = re.search(r"MTU\s+(\d+)\s+bytes.*?BW\s+(\d+)\s+Kbit", line)
            if m:
                current.mtu = int(m.group(1))
                continue

            # Primary IP
            m = re.match(rf"^\s+Internet address is\s+({REGEX_IPP})", line)
            if m:
                current.ip = m.group(1)
                current.is_mgmt = m.group(1).split("/")[0] == mgmt_ip
                continue

            # Secondary IP
            m = re.match(rf"^\s+Secondary address\s+({REGEX_IPP})", line)
            if m:
                current.secondary.append(m.group(1))
                continue

            # DHCP
            if re.search(r"address determined by (DHCP|IPCP)", line, re.IGNORECASE):
                current.dhcp = True
                continue

            # VRF
            m = re.match(r'^\s+VPN Routing.*?"(\S+)"', line)
            if m:
                current.vrf = m.group(1)
                continue

        logger.debug("[PARSER][IOSXE] Parsed %d interfaces", len(ifaces))
        return ifaces

    @staticmethod
    def parse_show_ip_interface(output: str, ifaces: dict[str, ParsedInterface]) -> None:
        """
        Supplement interface data from 'show ip interface'.
        Adds VRF / DHCP info that may be absent from 'show interfaces'.
        Mutates *ifaces* in place.
        """
        logger.debug("[PARSER][IOSXE] parse_show_ip_interface: %d chars", len(output))
        current_name: str | None = None

        for line in output.splitlines():
            m = re.match(r"^(\S+.*?)\s+is\s+(?:up|down|administratively)", line)
            if m:
                name = m.group(1).strip()
                current_name = name if name in ifaces else None
                continue

            if current_name is None:
                continue

            iface = ifaces[current_name]

            m = re.match(rf"^\s+.*?Internet address is\s+({REGEX_IPP})", line)
            if m and not iface.ip:
                iface.ip = m.group(1)
                continue

            m = re.match(r'^\s+VPN Routing.*?"(\S+)"', line)
            if m:
                iface.vrf = m.group(1)
                continue

            if re.search(r"address determined by (DHCP|IPCP)", line, re.IGNORECASE):
                iface.dhcp = True
                continue


# ---------------------------------------------------------------------------
# NX-OS parser
# ---------------------------------------------------------------------------


class NXOSParser:
    """
    Parses 'show' output from NX-OS (Nexus) devices.
    NX-OS output format differs significantly from IOS-XE.
    """

    @staticmethod
    def parse_show_version(output: str) -> ParsedDevice:
        logger.debug("[PARSER][NXOS] parse_show_version: %d chars", len(output))
        result = ParsedDevice()

        for line in output.splitlines():
            if not result.hostname:
                m = re.search(r"^\s*Device name:\s+(\S+)", line, re.IGNORECASE)
                if m:
                    result.hostname = m.group(1)
                    logger.debug("[PARSER][NXOS] hostname=%r", result.hostname)

            if not result.version:
                m = re.search(r"(?:NXOS|system):\s+version\s+(\S+)", line, re.IGNORECASE)
                if m:
                    result.version = m.group(1)
                    logger.debug("[PARSER][NXOS] version=%r", result.version)

            if not result.pid:
                m = re.search(
                    r"cisco\s+(Nexus[\s\w]+?)\s+(?:Chassis|processor)",
                    line,
                    re.IGNORECASE,
                )
                if m:
                    result.pid = m.group(1).strip()
                    logger.debug("[PARSER][NXOS] pid=%r", result.pid)

            if not result.serial:
                m = re.search(r"Processor Board ID\s+(\S+)", line, re.IGNORECASE)
                if m:
                    result.serial = m.group(1)
                    logger.debug("[PARSER][NXOS] serial=%r", result.serial)

        return result

    @staticmethod
    def parse_show_interfaces(output: str, mgmt_ip: str) -> dict[str, ParsedInterface]:
        """
        Parse 'show interface' (NX-OS) full output.
        Returns a mapping of interface-name -> ParsedInterface.
        """
        logger.debug("[PARSER][NXOS] parse_show_interfaces: %d chars", len(output))
        ifaces: dict[str, ParsedInterface] = {}
        current: ParsedInterface | None = None

        for line in output.splitlines():
            # NX-OS header: "Ethernet1/3 is up"  (no "line protocol" clause)
            m = re.match(r"^(\S+)\s+is\s+(up|down)", line, re.IGNORECASE)
            if m:
                name = m.group(1)
                current = ParsedInterface(name=name)
                current.link_up = m.group(2).lower() == "up"
                ifaces[name] = current
                logger.debug("[PARSER][NXOS] Interface=%s link_up=%s", name, current.link_up)
                continue

            if current is None:
                continue

            # Admin state
            m = re.match(r"^\s*admin state is (up|down)", line, re.IGNORECASE)
            if m:
                current.admin_up = m.group(1).lower() == "up"
                continue

            # Description
            m = re.match(r"^\s+Description:\s+(.*)", line)
            if m:
                current.description = m.group(1).strip()
                continue

            # Port-channel membership
            m = re.match(r"^\s+Belongs to (Po\d+)", line)
            if m:
                current.lag = normalize_lag_name(m.group(1))
                continue

            # MAC
            m = re.search(r"address:\s+([\da-f]{4}\.[\da-f]{4}\.[\da-f]{4})", line, re.IGNORECASE)
            if m:
                current.mac = m.group(1)
                continue

            # MTU + bandwidth
            m = re.match(r"^\s+MTU\s+(\d+)\s+bytes,\s+BW\s+(\d+)\s+Kbit", line)
            if m:
                current.mtu = int(m.group(1))
                current.speed = f"{int(m.group(2)) // 1000}Mbps"
                continue

            # Duplex / speed (separate NX-OS line)
            m = re.match(r"^\s+(full|half)-duplex,\s+(\d+)\s+Mb/s", line, re.IGNORECASE)
            if m:
                current.duplex = m.group(1).lower()
                current.speed = f"{m.group(2)}Mbps"
                continue

            # IP
            m = re.match(rf"^\s+Internet Address is\s+({REGEX_IPP})", line, re.IGNORECASE)
            if m:
                current.ip = m.group(1)
                current.is_mgmt = m.group(1).split("/")[0] == mgmt_ip
                continue

        logger.debug("[PARSER][NXOS] Parsed %d interfaces", len(ifaces))
        return ifaces


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_device_output(driver: str, output, mgmt_ip: str) -> ParsedDevice:
    """Parse the raw output collected by connection.collect_output for ``driver``."""
    if driver == "nxos":
        device = NXOSParser.parse_show_version(output.show_version)
        if output.show_interfaces:
            device.interfaces = NXOSParser.parse_show_interfaces(output.show_interfaces, mgmt_ip)
        return device

    # IOS-XE and IOS-XR share the IOS-style output format closely enough.
    device = IOSXEParser.parse_show_version(output.show_version)
    if output.show_interfaces:
        device.interfaces = IOSXEParser.parse_show_interfaces(output.show_interfaces, mgmt_ip)
        if output.show_ip_interface:
            IOSXEParser.parse_show_ip_interface(output.show_ip_interface, device.interfaces)
    return device
