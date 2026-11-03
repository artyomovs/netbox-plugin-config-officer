"""Talking to devices over SSH/Telnet with scrapli.

One collection opens one CLI session per device and runs a fixed, read-only
command set (:data:`COMMANDS`). The raw text is returned unparsed: parsing is
done by parsers.py and NetBox updates by netbox_sync.py. This module never
touches the database, which is what makes it safe to run in worker threads.

Connection strategy:

1. TCP check of the SSH port (``DEVICE_SSH_PORT`` or the per-device override).
2. SSH session with scrapli's system transport (OpenSSH).
3. If the SSH port is closed or the SSH session fails and ``TELNET_FALLBACK`` is
   enabled: the same on Telnet port 23.

Every attempt is recorded in :attr:`DeviceOutput.attempts` / :attr:`CollectionError.attempts`,
which end up in the job log, so it is always visible *why* a device failed.
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field

from config_officer.choices import CollectFailChoices, TransportChoices
from config_officer.configuration import PluginSettings

from .targets import DeviceTarget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandSet:
    version: str
    interfaces: str | None
    ip_interfaces: str | None
    running_config: str = "show running-config"


COMMANDS = {
    "iosxe": CommandSet("show version", "show interfaces", "show ip interface"),
    "nxos": CommandSet("show version", "show interface", None),
    "iosxr": CommandSet("show version", "show interfaces", None),
}


@dataclass
class DeviceOutput:
    """Raw CLI output of one successful device session."""

    transport: str
    port: int
    show_version: str
    running_config: str
    show_interfaces: str = ""
    show_ip_interface: str = ""
    attempts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration: float = 0.0


class CollectionError(Exception):
    """A device could not be collected. ``reason`` is a CollectFailChoices value."""

    def __init__(self, reason: str, message: str, attempts: list[str] | None = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.attempts = attempts or []


class _SessionError(Exception):
    """Internal: a session attempt failed; ``reason`` says at which stage."""

    def __init__(self, reason: str, error: Exception):
        super().__init__(f"{type(error).__name__}: {error}")
        self.reason = reason


def port_is_open(host: str, port: int, timeout: float) -> tuple[bool, str]:
    """TCP connect check. Returns ``(open, explanation)``."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "port open"
    except TimeoutError:
        return False, f"timeout after {timeout}s"
    except ConnectionRefusedError:
        return False, "connection refused"
    except OSError as exc:
        return False, str(exc)


def open_connection(target: DeviceTarget, transport: str, port: int, settings: PluginSettings):
    """Open a scrapli session; tests replace this function with a fake."""
    from scrapli.driver.core import IOSXEDriver, IOSXRDriver, NXOSDriver

    drivers = {"iosxe": IOSXEDriver, "nxos": NXOSDriver, "iosxr": IOSXRDriver}
    kwargs = {
        "host": target.host,
        "port": port,
        "auth_username": target.username,
        "auth_password": target.password,
        "auth_secondary": target.enable_password,
        "auth_strict_key": False,
        "timeout_socket": settings.connect_timeout,
        "timeout_transport": settings.command_timeout,
        "timeout_ops": settings.command_timeout,
        "transport": "telnet" if transport == TransportChoices.TRANSPORT_TELNET else "system",
    }
    if transport == TransportChoices.TRANSPORT_SSH and settings.ssh_config_file:
        kwargs["ssh_config_file"] = settings.ssh_config_file
    connection = drivers[target.driver](**kwargs)
    connection.open()
    return connection


def _send(connection, command: str) -> str:
    response = connection.send_command(command)
    if getattr(response, "failed", False):
        raise RuntimeError(
            f"{command!r} was rejected by the device: {response.result.strip()[:200]}"
        )
    return response.result


def _run_session(
    target: DeviceTarget, transport: str, port: int, settings: PluginSettings
) -> DeviceOutput:
    commands = COMMANDS[target.driver]
    try:
        connection = open_connection(target, transport, port, settings)
    except Exception as exc:
        raise _SessionError(CollectFailChoices.FAIL_LOGIN, exc) from exc

    warnings: list[str] = []
    try:
        try:
            show_version = _send(connection, commands.version)
            running_config = _send(connection, commands.running_config)
        except Exception as exc:
            raise _SessionError(CollectFailChoices.FAIL_CONFIG, exc) from exc

        # Interface data is optional: a failure here must not lose the config backup.
        show_interfaces = show_ip_interface = ""
        if settings.collect_interfaces_data and commands.interfaces:
            try:
                show_interfaces = _send(connection, commands.interfaces)
                if commands.ip_interfaces:
                    show_ip_interface = _send(connection, commands.ip_interfaces)
            except Exception as exc:
                warnings.append(f"interface data not collected: {exc}")
    finally:
        try:
            connection.close()
        except Exception:  # closing a broken session must never hide the real result
            logger.debug("Error while closing the session to %s", target.host, exc_info=True)

    return DeviceOutput(
        transport=transport,
        port=port,
        show_version=show_version,
        running_config=running_config,
        show_interfaces=show_interfaces,
        show_ip_interface=show_ip_interface,
        warnings=warnings,
    )


def collect_output(target: DeviceTarget, settings: PluginSettings) -> DeviceOutput:
    """Connect to ``target`` and return its raw output, or raise :class:`CollectionError`."""
    started = time.monotonic()
    plans = [(TransportChoices.TRANSPORT_SSH, target.port)]
    if settings.telnet_fallback and target.port != 23:
        plans.append((TransportChoices.TRANSPORT_TELNET, 23))

    attempts: list[str] = []
    session_error: _SessionError | None = None
    for transport, port in plans:
        label = f"{transport} {target.host}:{port}"
        reachable, explanation = port_is_open(target.host, port, settings.connect_timeout)
        if not reachable:
            attempts.append(f"{label}: {explanation}")
            continue
        try:
            output = _run_session(target, transport, port, settings)
        except _SessionError as exc:
            attempts.append(f"{label}: {exc}")
            session_error = exc
            logger.info("[%s] %s failed: %s", target.name, label, exc)
            continue
        attempts.append(f"{label}: OK")
        output.attempts = attempts
        output.duration = time.monotonic() - started
        return output

    if session_error is None:
        raise CollectionError(
            CollectFailChoices.FAIL_CONNECT,
            "Device unreachable: " + "; ".join(attempts),
            attempts,
        )
    stage = (
        "Login failed"
        if session_error.reason == CollectFailChoices.FAIL_LOGIN
        else "Command failed"
    )
    raise CollectionError(session_error.reason, f"{stage}: " + "; ".join(attempts), attempts)
