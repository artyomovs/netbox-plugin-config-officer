"""Pytest configuration for the unit tests (they run without a NetBox installation).

Importing anything from ``config_officer`` runs ``config_officer/__init__.py``,
which imports ``netbox.plugins.PluginConfig``. When NetBox is not installed, a
minimal stub of that module is registered so pure-Python modules such as
``config_officer.compliance.diff`` can be imported and tested.
"""

import importlib.util
import sys
import types


def _install_netbox_stub() -> None:
    if importlib.util.find_spec("netbox") is not None:
        return  # real NetBox available
    netbox = types.ModuleType("netbox")
    plugins = types.ModuleType("netbox.plugins")

    class PluginConfig:  # minimal stand-in for netbox.plugins.PluginConfig
        name = ""

    plugins.PluginConfig = PluginConfig
    netbox.plugins = plugins
    sys.modules["netbox"] = netbox
    sys.modules["netbox.plugins"] = plugins


_install_netbox_stub()
