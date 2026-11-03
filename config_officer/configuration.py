"""Plugin settings: one parsed, validated, immutable object.

Where values come from (highest priority first):

1. Environment variable ``CO_<KEY>`` (``CO_GIT_REMOTE_<KEY>`` for keys of the
   ``GIT_REMOTE`` dict). Handy for containers and secrets.
2. ``PLUGINS_CONFIG["config_officer"]`` in NetBox's ``configuration.py``.
3. The defaults in ``_SCHEMA`` below.

Every other module calls :func:`get_settings` instead of reading Django
settings, so parsing and validation live only here. Mistakes (unknown keys,
values of the wrong type, invalid regexes) never crash NetBox: the default is
used and a warning is logged at startup (see ``ConfigOfficerConfig.ready``).
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLUGIN_NAME = "config_officer"
ENV_PREFIX = "CO_"

#: Platform drivers the collector knows how to talk to (keys of collection.connection.DRIVERS).
SUPPORTED_DRIVERS = ("iosxe", "nxos", "iosxr")

DEFAULT_SENSITIVE_PREFIXES = ("username", "ssh", "snmp-server user", "crypto", "key", "password")
DEFAULT_VOLATILE_LINE_PATTERNS = (
    r"^!Time:",
    r"^!Running configuration last done at:",
    r"^!NVRAM config last updated",
    r"^! Last configuration change",
    r"^ntp clock-period",
)

# key -> (type, default). The type drives parsing of environment variables.
_SCHEMA: dict[str, tuple[type, Any]] = {
    # How to reach devices
    "DEVICE_USERNAME": (str, "cisco"),
    "DEVICE_PASSWORD": (str, "cisco"),
    "DEVICE_ENABLE_PASSWORD": (str, ""),
    "DEVICE_SSH_PORT": (int, 22),
    "DEVICE_SPECIFIC_CONF": (dict, {}),
    "DEFAULT_PLATFORM": (str, "nxos"),
    "PLATFORM_MAP": (dict, {}),
    "TELNET_FALLBACK": (bool, True),
    "SSH_CONFIG_FILE": (str, ""),
    "CONNECT_TIMEOUT": (int, 20),
    "COMMAND_TIMEOUT": (int, 60),
    # Collection runs
    "COLLECTION_CONCURRENCY": (int, 8),
    "COLLECTION_JOB_TIMEOUT": (int, 7200),
    "RESULT_RETENTION_DAYS": (int, 90),
    "COLLECT_INTERFACES_DATA": (bool, True),
    "COLLECT_PORT_CHANNEL_DATA": (bool, True),
    # Where configs are stored
    "CONFIGS_REPO_DIR": (str, "/device_configs"),
    "CONFIGS_SUBPATH": (str, "netbox"),
    "GIT_REMOTE": (dict, {}),
    "SENSITIVE_PREFIXES": (list, list(DEFAULT_SENSITIVE_PREFIXES)),
    "VOLATILE_LINE_PATTERNS": (list, list(DEFAULT_VOLATILE_LINE_PATTERNS)),
    # Device custom fields updated after each successful collection
    "CF_NAME_SW_VERSION": (str, "version"),
    "CF_NAME_SSH": (str, "ssh"),
    "CF_NAME_LAST_COLLECT_DATE": (str, "last_collect_date"),
    "CF_NAME_LAST_COLLECT_TIME": (str, "last_collect_time"),
    # Compliance
    "COMPLIANCE_MAX_CONFIG_AGE_DAYS": (int, 7),
}

_GIT_REMOTE_SCHEMA: dict[str, tuple[type, Any]] = {
    "ENABLED": (bool, True),
    "URL": (str, ""),
    "NAME": (str, "origin"),
    "BRANCH": (str, "netbox"),
    "SSH_KEY_PATH": (str, ""),
    "AUTHOR": (str, "Netbox <netbox@example.com>"),
}

# Keys people commonly set by mistake, with a hint that explains what to do instead.
_KNOWN_MISTAKES = {
    "NETBOX_DEVICES_CONFIGS_REPO_DIR": (
        "'NETBOX_DEVICES_CONFIGS_REPO_DIR' is not a setting of this plugin and is ignored "
        "(older README versions mentioned it by mistake). Use 'CONFIGS_REPO_DIR'. "
        "Configs are currently stored in {repo_dir!r}."
    ),
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class _InvalidValue(ValueError):
    pass


@dataclass(frozen=True)
class GitRemoteSettings:
    """Optional remote the configs repository is pushed to after each run."""

    enabled: bool
    url: str
    name: str
    branch: str
    ssh_key_path: str
    author: str

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.url)


@dataclass(frozen=True)
class DeviceCredentials:
    username: str
    password: str
    enable_password: str
    port: int


@dataclass(frozen=True)
class PluginSettings:
    # Device access
    device_username: str
    device_password: str
    device_enable_password: str
    device_ssh_port: int
    device_specific_conf: dict
    default_platform: str
    platform_map: dict
    telnet_fallback: bool
    ssh_config_file: str
    connect_timeout: int
    command_timeout: int
    # Collection runs
    collection_concurrency: int
    collection_job_timeout: int
    result_retention_days: int
    collect_interfaces_data: bool
    collect_port_channel_data: bool
    # Storage
    configs_repo_dir: str
    configs_subpath: str
    git_remote: GitRemoteSettings
    sensitive_prefixes: tuple[str, ...]
    volatile_line_patterns: tuple[str, ...]
    # Custom field names (an empty name disables that field)
    cf_sw_version: str
    cf_ssh: str
    cf_last_collect_date: str
    cf_last_collect_time: str
    # Compliance
    compliance_max_config_age_days: int
    # Problems found while parsing; logged once at startup
    warnings: tuple[str, ...] = field(default=(), compare=False)

    @property
    def configs_path(self) -> Path:
        """Directory holding the ``<hostname>_running.txt`` files."""
        return Path(self.configs_repo_dir) / self.configs_subpath

    @functools.cached_property
    def volatile_regexes(self) -> tuple[re.Pattern, ...]:
        return tuple(re.compile(p) for p in self.volatile_line_patterns)

    def credentials_for(self, hostname: str) -> DeviceCredentials:
        """Global credentials, overridden per device by ``DEVICE_SPECIFIC_CONF[hostname]``."""
        override = self.device_specific_conf.get(hostname) or {}
        return DeviceCredentials(
            username=override.get("DEVICE_USERNAME", self.device_username),
            password=override.get("DEVICE_PASSWORD", self.device_password),
            enable_password=override.get("DEVICE_ENABLE_PASSWORD", self.device_enable_password),
            port=int(override.get("DEVICE_SSH_PORT", self.device_ssh_port)),
        )

    def log_warnings(self) -> None:
        for message in self.warnings:
            logger.warning("[config_officer] %s", message)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise _InvalidValue(f"expected a boolean, got {value!r}")


def _to_int(value: Any) -> int:
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        raise _InvalidValue(f"expected an integer, got {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise _InvalidValue(f"expected an integer, got {value!r}") from None


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str | int | float):
        return str(value)
    raise _InvalidValue(f"expected a string, got {value!r}")


def _to_list(value: Any) -> list[str]:
    """A list, or a comma-separated / JSON string (environment variables)."""
    if isinstance(value, str):
        text = value.strip()
        value = (
            _parse_json(text, list)
            if text.startswith("[")
            else [item.strip() for item in text.split(",")]
        )
    if not isinstance(value, list | tuple):
        raise _InvalidValue(f"expected a list, got {value!r}")
    return [str(item) for item in value if str(item).strip()]


def _to_dict(value: Any) -> dict:
    """A dict, or a JSON object string (environment variables)."""
    if isinstance(value, str):
        value = _parse_json(value, dict)
    if not isinstance(value, Mapping):
        raise _InvalidValue(f"expected a dict, got {value!r}")
    return dict(value)


_COERCERS = {bool: _to_bool, int: _to_int, str: _to_str, list: _to_list, dict: _to_dict}


def _coerce(value: Any, expected: type) -> Any:
    """Convert a PLUGINS_CONFIG or environment value to ``expected``; raise _InvalidValue."""
    return _COERCERS[expected](value)


def _parse_json(text: str, expected: type) -> Any:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _InvalidValue(f"invalid JSON ({exc})") from None
    if not isinstance(value, expected):
        raise _InvalidValue(f"expected a JSON {expected.__name__}")
    return value


def _resolve(
    schema: dict[str, tuple[type, Any]],
    configured: Mapping,
    environ: Mapping,
    env_prefix: str,
    label_prefix: str,
    warnings: list[str],
) -> dict[str, Any]:
    values = {}
    for key, (expected, default) in schema.items():
        env_name = f"{env_prefix}{key}"
        if env_name in environ:
            raw, source = environ[env_name], f"environment variable {env_name}"
        elif key in configured:
            raw, source = configured[key], f"setting {label_prefix}{key}"
        else:
            values[key] = default
            continue
        try:
            values[key] = _coerce(raw, expected)
        except _InvalidValue as exc:
            warnings.append(f"Invalid {source}: {exc}. Using the default {default!r}.")
            values[key] = default
    return values


def load_settings(plugin_config: Mapping | None, environ: Mapping | None = None) -> PluginSettings:
    """Build :class:`PluginSettings` from a PLUGINS_CONFIG dict and an environment mapping.

    Pure function (no Django access) so it can be unit tested directly.
    """
    plugin_config = dict(plugin_config or {})
    environ = environ if environ is not None else {}
    warnings: list[str] = []

    values = _resolve(_SCHEMA, plugin_config, environ, ENV_PREFIX, "", warnings)
    remote = _resolve(
        _GIT_REMOTE_SCHEMA,
        values["GIT_REMOTE"],
        environ,
        f"{ENV_PREFIX}GIT_REMOTE_",
        "GIT_REMOTE.",
        warnings,
    )

    for key in sorted(plugin_config.keys() - _SCHEMA.keys()):
        hint = _KNOWN_MISTAKES.get(key, "Unknown setting {key!r} is ignored (typo?).")
        warnings.append(hint.format(key=key, repo_dir=values["CONFIGS_REPO_DIR"]))
    for key in sorted(values["GIT_REMOTE"].keys() - _GIT_REMOTE_SCHEMA.keys()):
        warnings.append(f"Unknown setting 'GIT_REMOTE.{key}' is ignored (typo?).")

    default_platform = values["DEFAULT_PLATFORM"].lower()
    if default_platform not in SUPPORTED_DRIVERS:
        warnings.append(
            f"DEFAULT_PLATFORM {default_platform!r} is not one of {SUPPORTED_DRIVERS}; using 'nxos'."
        )
        default_platform = "nxos"

    platform_map = {}
    for platform, driver in values["PLATFORM_MAP"].items():
        if str(driver).lower() in SUPPORTED_DRIVERS:
            platform_map[str(platform).lower()] = str(driver).lower()
        else:
            warnings.append(
                f"PLATFORM_MAP[{platform!r}]: unknown driver {driver!r}; entry ignored."
            )

    volatile_patterns = []
    for pattern in values["VOLATILE_LINE_PATTERNS"]:
        try:
            re.compile(pattern)
            volatile_patterns.append(pattern)
        except re.error as exc:
            warnings.append(f"VOLATILE_LINE_PATTERNS: invalid regex {pattern!r} ({exc}); ignored.")

    concurrency = values["COLLECTION_CONCURRENCY"]
    if not 1 <= concurrency <= 64:
        warnings.append(
            f"COLLECTION_CONCURRENCY must be between 1 and 64, got {concurrency}; using 8."
        )
        concurrency = 8

    return PluginSettings(
        device_username=values["DEVICE_USERNAME"],
        device_password=values["DEVICE_PASSWORD"],
        device_enable_password=values["DEVICE_ENABLE_PASSWORD"],
        device_ssh_port=values["DEVICE_SSH_PORT"],
        device_specific_conf=values["DEVICE_SPECIFIC_CONF"],
        default_platform=default_platform,
        platform_map=platform_map,
        telnet_fallback=values["TELNET_FALLBACK"],
        ssh_config_file=values["SSH_CONFIG_FILE"],
        connect_timeout=values["CONNECT_TIMEOUT"],
        command_timeout=values["COMMAND_TIMEOUT"],
        collection_concurrency=concurrency,
        collection_job_timeout=max(values["COLLECTION_JOB_TIMEOUT"], 60),
        result_retention_days=max(values["RESULT_RETENTION_DAYS"], 0),
        collect_interfaces_data=values["COLLECT_INTERFACES_DATA"],
        collect_port_channel_data=values["COLLECT_PORT_CHANNEL_DATA"],
        configs_repo_dir=values["CONFIGS_REPO_DIR"],
        configs_subpath=values["CONFIGS_SUBPATH"],
        git_remote=GitRemoteSettings(
            enabled=remote["ENABLED"],
            url=remote["URL"],
            name=remote["NAME"],
            branch=remote["BRANCH"],
            ssh_key_path=remote["SSH_KEY_PATH"],
            author=remote["AUTHOR"],
        ),
        sensitive_prefixes=tuple(values["SENSITIVE_PREFIXES"]),
        volatile_line_patterns=tuple(volatile_patterns),
        cf_sw_version=values["CF_NAME_SW_VERSION"],
        cf_ssh=values["CF_NAME_SSH"],
        cf_last_collect_date=values["CF_NAME_LAST_COLLECT_DATE"],
        cf_last_collect_time=values["CF_NAME_LAST_COLLECT_TIME"],
        compliance_max_config_age_days=values["COMPLIANCE_MAX_CONFIG_AGE_DAYS"],
        warnings=tuple(warnings),
    )


@functools.cache
def get_settings() -> PluginSettings:
    """Settings of the running NetBox instance (parsed once per process)."""
    from django.conf import settings

    return load_settings(settings.PLUGINS_CONFIG.get(PLUGIN_NAME, {}), os.environ)
