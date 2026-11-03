<p align="center">
<img width="200" height="200" src="./static/logo.png">
</p>

# NetBox Config Officer Plugin

[![PyPI version](https://img.shields.io/pypi/v/netbox-plugin-config-officer-2)](https://pypi.org/project/netbox-plugin-config-officer-2/)
[![Python](https://img.shields.io/pypi/pyversions/netbox-plugin-config-officer-2)](https://pypi.org/project/netbox-plugin-config-officer-2/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

A [NetBox](https://github.com/netbox-community/netbox) plugin that collects running configurations from Cisco devices (IOS-XE, NX-OS, IOS-XR), versions them in Git, writes what it learns back into NetBox and audits the configurations against compliance templates. Forked from [artyomovs/netbox-plugin-config-officer](https://github.com/artyomovs/netbox-plugin-config-officer).

**Features**

- Collect all devices, devices **by tag** or selected devices - on demand or on a schedule
- Every run is a NetBox background job with a readable log; every device gets a result that lists exactly what changed
- Running configs are sanitised and stored in a Git repository (optionally pushed to a remote); history and diffs on the device page
- NetBox is updated from the device: serial number, software version custom fields, interfaces, LAGs, IP and MAC addresses - recorded in NetBox's change log
- Compliance: templates are applied to devices through services and rules (by role / device type); missing lines are reported per device
- Optional signed webhook with a summary after scheduled runs
- NetBox-native permissions, including per-device constraints

| Plugin version | NetBox version |
|---|---|
| 0.2.x | 4.7 (tested with 4.7.2) |
| 0.1.26 | 4.7 (hotfix release of 0.1.25) |
| 0.1.25 and older | 4.6 and older |

---

## Installation

The plugin connects to devices over SSH/Telnet and runs `git`. Install the system packages on every host that runs the NetBox **worker** (and the web server, if it should read configs directly):

```shell
apt-get install -y git openssh-client
```

Install the plugin into NetBox's virtual environment (and add it to `local_requirements.txt` so upgrades keep it):

```shell
source /opt/netbox/venv/bin/activate
pip install netbox-plugin-config-officer-2
echo netbox-plugin-config-officer-2 >> /opt/netbox/local_requirements.txt
```

Enable it in `configuration.py` (all settings are optional, see [Configuration](#configuration)):

```python
PLUGINS = ["config_officer"]
PLUGINS_CONFIG = {
    "config_officer": {
        "CONFIGS_REPO_DIR": "/opt/device_configs",
        "DEVICE_USERNAME": "netbox",
        "DEVICE_PASSWORD": "secret",
    }
}
```

Create the storage directory (the plugin initialises the Git repository itself), run the migrations and restart NetBox **and its worker**:

```shell
mkdir -p /opt/device_configs && chown -R <netbox-user>: /opt/device_configs
cd /opt/netbox/netbox && python manage.py migrate config_officer
systemctl restart netbox netbox-rqworker
```

> The directory must be writable by the NetBox worker. If the web server cannot see it (e.g. only the worker container mounts the volume), the device page asks the worker for the config instead.

Optionally create these **custom fields** on *DCIM > Device*; the plugin fills those that exist after every collection:

| Name | Type | Content |
|---|---|---|
| `version` | Text | Software version |
| `ssh` | Boolean | Collected over SSH (false = Telnet) |
| `last_collect_date` | Text | Date of the last successful collection |
| `last_collect_time` | Text | Time of the last successful collection |

---

## Permissions

The plugin uses NetBox's own permission system (*Admin > Object Permissions*). Superusers can do everything.

| To... | Grant |
|---|---|
| Start a collection (run page, device button, schedules, API) | action **`collect_config`** on *DCIM > Device* |
| See a device's running config and its history | action **`view_config`** on *DCIM > Device* |
| See runs and per-device results | `view` on *Config Officer > collection result* |
| Manage schedules | `view/add/change/delete` on *collection schedule* (plus `collect_config`) |
| Manage compliance templates / services / rules | `view/add/change/delete` on the respective model |
| See compliance status | `view` on *compliance status* |
| Assign / remove services on devices | `add` / `delete` on *service assignment* |
| Re-check compliance | `change` on *compliance status* |

`collect_config` and `view_config` are custom actions on devices, so they honour constraints - e.g. `{"site__slug": "waw1"}` lets a team collect only its own devices. A collection run started by a user only touches the devices that user may collect.

Showing a NetBox change log link on the run page requires `core.view_objectchange`.

---

## Usage

- **Config Officer > Collection > Run & monitor** - start a collection of all devices, devices with tags, or selected devices; see recent runs and the latest status of all devices.
- **Run page** - progress (auto-refresh), the log of the run, the result of every device, the Git commit and a link to all NetBox changes made by the run.
- **Device page** - *Collect config* button, a *Config Officer* panel with the last result and compliance, and the tabs *Configuration* (running config + Git history with diffs) and *Compliance*.
- **Schedules** - recurring collections of all devices, devices with tags (resolved at each run) and/or selected devices, optionally with a webhook. *Run now* runs a schedule once.
- **Compliance** - 1) create *Templates*, 2) create a *Service* with *Rules* (template + optional roles / device types), 3) assign services to devices in *Device status*. The verdict is updated after every collection; *Re-check compliance* recomputes it from the stored configs.

### REST API

Under `/api/plugins/config_officer/`: `templates/`, `services/`, `service-rules/`, `schedules/` (CRUD), `results/` and `compliance/` (read-only), and

```shell
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     https://netbox/api/plugins/config_officer/runs/ -d '{"tags": ["core"]}'
# {"job_id": 123, "job_uuid": "...", "run_url": "https://netbox/plugins/config_officer/runs/123/"}
```

The body accepts `all_devices` (bool), `tags` (slugs), `devices` (IDs) and `statuses`. The 0.1.x endpoint `POST collection/` with `task=global_collection` still works.

### Webhook

After a scheduled run (and *Run now*) the summary is POSTed as JSON to the schedule's webhook URL: `event`, `schedule`, `target`, `commit`, `job`, `summary` (`total`, `succeeded`, `failed`, `skipped`, `changed`), `results` and `diffs`. With a secret, the header `X-Webhook-Signature: sha256=<HMAC-SHA256 of the body>` is added.

---

## Configuration

Every setting can be given in `PLUGINS_CONFIG["config_officer"]` or as an environment variable `CO_<SETTING>` (environment wins). `GIT_REMOTE` keys use `CO_GIT_REMOTE_<KEY>`. Lists may be given as comma-separated values or JSON, dicts as JSON. Unknown or invalid settings are reported in the NetBox log at startup.

**Devices**

| Setting | Default | Description |
|---|---|---|
| `DEVICE_USERNAME` / `DEVICE_PASSWORD` | `cisco` / `cisco` | Credentials for all devices |
| `DEVICE_ENABLE_PASSWORD` | empty | Enable secret, if the login does not land in privileged mode |
| `DEVICE_SSH_PORT` | `22` | SSH port |
| `DEVICE_SPECIFIC_CONF` | `{}` | Per-hostname overrides: `{"sw1": {"DEVICE_USERNAME": "...", "DEVICE_PASSWORD": "...", "DEVICE_SSH_PORT": 2222}}` |
| `TELNET_FALLBACK` | `True` | Try Telnet (port 23) when SSH fails |
| `DEFAULT_PLATFORM` | `nxos` | Driver for devices without a recognised platform: `iosxe`, `nxos` or `iosxr` |
| `PLATFORM_MAP` | `{}` | NetBox platform slug -> driver, e.g. `{"c9k": "iosxe"}`. Common slugs such as `cisco-ios-xe`, `ios`, `nx-os` are recognised automatically |
| `SSH_CONFIG_FILE` | empty | OpenSSH config file, e.g. to enable legacy ciphers/kex for old devices |
| `CONNECT_TIMEOUT` / `COMMAND_TIMEOUT` | `20` / `60` | Seconds |

**Collection runs**

| Setting | Default | Description |
|---|---|---|
| `COLLECTION_CONCURRENCY` | `8` | Devices collected in parallel within one run |
| `COLLECTION_JOB_TIMEOUT` | `7200` | Seconds before the background job is stopped |
| `RESULT_RETENTION_DAYS` | `90` | Per-device results older than this are deleted (`0` = keep) |
| `COLLECT_INTERFACES_DATA` | `True` | Collect interfaces and update interfaces, IP and MAC addresses in NetBox |
| `COLLECT_PORT_CHANNEL_DATA` | `True` | Create LAGs and LAG membership |

**Storage**

| Setting | Default | Description |
|---|---|---|
| `CONFIGS_REPO_DIR` | `/device_configs` | Git work tree for the configs |
| `CONFIGS_SUBPATH` | `netbox` | Sub-directory for `<hostname>_running.txt` files |
| `SENSITIVE_PREFIXES` | `username`, `ssh`, `snmp-server user`, `crypto`, `key`, `password` | Lines starting with these words are removed before storing; a removed top-level line takes its indented block with it |
| `VOLATILE_LINE_PATTERNS` | timestamp lines, `ntp clock-period` | Regexes; lines that are ignored when deciding whether a config changed |
| `GIT_REMOTE` | `{}` | Remote push: `ENABLED` (`True`), `URL`, `NAME` (`origin`), `BRANCH` (`netbox`), `SSH_KEY_PATH`, `AUTHOR` (`Netbox <netbox@example.com>`) |

**Other**

| Setting | Default | Description |
|---|---|---|
| `CF_NAME_SW_VERSION`, `CF_NAME_SSH`, `CF_NAME_LAST_COLLECT_DATE`, `CF_NAME_LAST_COLLECT_TIME` | `version`, `ssh`, `last_collect_date`, `last_collect_time` | Custom field names (empty = do not write) |
| `COMPLIANCE_MAX_CONFIG_AGE_DAYS` | `7` | Older configs are reported as stale instead of being checked |

### Operational notes

- A collection run is one background job; it talks to up to `COLLECTION_CONCURRENCY` devices at a time and makes **one Git commit per run**. While a long run is in progress it occupies one RQ worker, so run at least two workers if other background tasks (webhooks, scripts) must not wait. Runs never overlap; a second run waits for the first.
- The plugin expects to be the only writer of the Git branch. A commit that could not be pushed is kept and pushed by the next run.
- Changes the plugin makes in NetBox appear in the change log under the user who started the run (scheduled runs: the user who saved the schedule). They can trigger event rules like any other change.

---

## How the code is organised

| Module | Responsibility |
|---|---|
| `__init__.py` | Plugin registration (`PluginConfig`) |
| `configuration.py` | All settings, parsed and validated once (`get_settings()`) |
| `permissions.py` | Permission names; registers `collect_config` / `view_config` on devices |
| `models.py` | Database models: compliance templates, services, rules, assignments, results, schedules |
| `collection/targets.py` | Which devices a run touches and how to reach them (address, driver, credentials) |
| `collection/connection.py` | One SSH/Telnet session per device with scrapli; raw command output, no database access |
| `collection/parsers.py` | Command output -> plain dataclasses |
| `collection/sanitize.py` | Removing secrets from configs |
| `collection/netbox_sync.py` | Writing device data into NetBox, with a report of what changed |
| `collection/runner.py` | One run end to end: threads for device I/O, then storage, NetBox, compliance, Git commit, job log |
| `storage.py` | Config files and everything Git (commit, push, history) |
| `compliance/diff.py`, `compliance/engine.py` | Config diff engine; templates that apply to a device and the verdict |
| `jobs.py` | Background jobs: manual runs, schedules, compliance checks |
| `signals.py` | Keeps each schedule's recurring job in sync with the schedule |
| `webhook.py` | Schedule summary webhook |
| `views.py`, `urls.py`, `forms.py`, `tables.py`, `filtersets.py`, `navigation.py`, `template_content.py`, `templates/` | Web UI |
| `api/` | REST API |

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Upgrade notes are in [CHANGELOG.md](CHANGELOG.md).

## License

[Apache License 2.0](LICENSE)
