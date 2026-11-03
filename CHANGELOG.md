# Changelog

## 0.2.0

A restructuring of the whole plugin: every module now has one job (see "How the code is organised" in the README), the UI uses NetBox's native views, and collection is observable end to end.

### New

- **Collection page** (*Config Officer > Run & monitor*): collect all devices, devices with tags or selected devices, filter by device status, and follow recent runs.
- **Runs as NetBox jobs** with a readable log: per device which transport was used, whether the config changed and what was changed in NetBox; Git commit / push result; webhook delivery.
- **Per-device results** list what changed in NetBox (interfaces, IP/MAC addresses, LAGs, VRFs, serial, custom fields), all connection attempts and warnings.
- **Tag-based schedules**: a schedule can target all devices, devices with tags (resolved at every run) and/or selected devices. Next run time is shown; *Run now* sends the webhook too.
- **Device page**: *Configuration* tab (running config + Git history with diffs), *Compliance* tab, *Collect config* button, status panel.
- Changes made in NetBox are recorded in NetBox's change log, attributed to the user who started the run; the run page links to them.
- REST API for templates, services, rules, schedules, results, compliance and `POST runs/` to start a collection.
- New settings: `DEVICE_ENABLE_PASSWORD`, `PLATFORM_MAP`, `TELNET_FALLBACK`, `SSH_CONFIG_FILE`, `CONNECT_TIMEOUT`, `COMMAND_TIMEOUT`, `COLLECTION_CONCURRENCY`, `COLLECTION_JOB_TIMEOUT`, `RESULT_RETENTION_DAYS`, `COMPLIANCE_MAX_CONFIG_AGE_DAYS`.

### Fixed

- Plugin pages and device actions were reachable without login (running config, starting collections).
- Every action, including deleting objects, only required `dcim.view_device`.
- `GIT_REMOTE.ENABLED` in `PLUGINS_CONFIG` was ignored; the README documented a non-existent `NETBOX_DEVICES_CONFIGS_REPO_DIR` setting (now reported in the log).
- A commit that failed to push could be lost on the next collection.
- A new copy of the Git SSH key was written to `/tmp` on every collection.
- The reachability check ignored a custom `DEVICE_SSH_PORT`; the `ssh` custom field was false for custom SSH ports.
- Interfaces with a label were not matched and could not be synced; full `GigabitEthernet...` names got the type "other".
- Speed and duplex were never parsed from IOS / IOS-XE output.
- Primary MAC addresses were created without being assigned to their interface (existing records are repaired on the next collection).
- A device IP that is in a VRF on the device was not matched against the existing record in NetBox.
- Compliance filters on the device list (status, role, tenant, type) did not work; root-commit diffs were not shown.
- Schedules: "next run" never updated; disabled schedules kept firing; deleting a schedule left its job in the queue; the webhook secret was cleared when editing a schedule.
- Removing a sensitive top-level line (e.g. `crypto pki certificate chain`) left its indented lines behind.

### Changed - please read before upgrading

- **Permissions**: grant users NetBox permissions as described in the README. `dcim.view_device` alone no longer gives access to the plugin. Superusers are not affected.
- **One job and one Git commit per run** (instead of one job per device). A large run occupies an RQ worker for its duration; consider a second worker.
- **Interface types** are only set when the plugin creates an interface; existing interface types are no longer overwritten.
- **Redaction** removes whole sensitive blocks, so the first collection after the upgrade can show those blocks as removed in the Git history.
- **Background tasks of 0.1.x are gone**: let the RQ queues drain before upgrading. Scheduled collections continue to work.
- Collection results are kept for `RESULT_RETENTION_DAYS` (90) days instead of being wiped before each global run.
- URLs moved to NetBox's conventions; the old running-config and compliance URLs redirect to the device tabs.
- Requires NetBox 4.7 and Python 3.12+.

### Upgrade

```shell
pip install --upgrade netbox-plugin-config-officer-2
cd /opt/netbox/netbox && python manage.py migrate config_officer
systemctl restart netbox netbox-rqworker
```

The migrations only add fields and rename two many-to-many fields; existing data is kept.

## 0.1.26

- Fix crashes on NetBox 4.7: schedule list (`'str' object has no attribute 'permissions_required'`), schedule jobs tab and compliance CSV export (`device_role`).
