# Contributing to Config Officer

Thank you for taking the time to contribute. This document covers everything you need to get a working development environment, run tests, and submit changes.

---

## Table of Contents

- [Requirements](#requirements)
- [Repository layout](#repository-layout)
- [Development environment](#development-environment)
  - [1. Clone the repository](#1-clone-the-repository)
  - [2. One-time setup](#2-one-time-setup)
  - [3. Start the stack](#3-start-the-stack)
  - [4. Applying code changes](#4-applying-code-changes)
  - [5. Tearing down](#5-tearing-down)
- [Pre-commit hooks](#pre-commit-hooks)
- [Running tests](#running-tests)
- [Commit messages](#commit-messages)
- [Submitting changes](#submitting-changes)

---

## Requirements

| Tool | Minimum version | Notes |
|---|---|---|
| Docker | 24+ | Tested with Docker Engine; Docker Desktop works too |
| Docker Compose | v2 (`docker compose`) | The v1 `docker-compose` binary is not supported |
| Git | any recent | Required locally for commits and hooks |
| Python | 3.10+ | Only needed for pre-commit and pytest - not inside the container |
| Poetry | 1.8+ | Manages the local venv for pre-commit and tests |

---

## Repository layout

```
.
├── config_officer/               # Plugin source code (mounted live into the container)
├── tests/
│   ├── conftest.py               # netbox.plugins stub - unit tests run without a live NetBox
│   └── unit/test_*.py
├── scripts/
│   └── run_tests_for_changed.py  # Pre-commit helper: maps changed files → relevant tests
├── configuration/
│   └── configuration.py          # NetBox config file mounted into the dev container
├── plugin_dev/                   # Symlink or copy of config_officer/ - see step 2
├── device_configs/               # Git repo for storing device configs (created in step 2)
├── Dockerfile.dev                # Dev image built by docker-compose.yaml
├── docker-compose.yaml
├── pyproject.toml                # Dependencies, Ruff, pytest, Commitizen config
└── .pre-commit-config.yaml
```

---

## Development environment

The dev stack runs a full NetBox instance (NetBox + RQ worker + PostgreSQL + Redis) via Docker Compose. The plugin source is mounted directly into the container so code changes are reflected without rebuilding the image.

### 1. Clone the repository

```shell
git clone https://github.com/Juzekkk/netbox-plugin-config-officer-2
cd netbox-plugin-config-officer-2
```

### 2. One-time setup

**Install local Python dependencies** (pre-commit hooks and pytest run outside the container):

```shell
poetry install
```

**Prepare the device config directory.** The plugin will initialise a Git repository here on first run - you just need the directory to exist and be writable:

```shell
mkdir -p device_configs
```

**Prepare `plugin_dev/`.** The container mounts `./plugin_dev` as the installed plugin source. Point it at the actual package directory so edits to `config_officer/` are reflected immediately:

```shell
# Option A - symlink (recommended on Linux/macOS)
ln -s config_officer plugin_dev

# Option B - on Windows or if symlinks cause issues, just copy the directory
cp -r config_officer plugin_dev
```

> If you use Option B you will need to re-copy after structural changes (new files, moved modules). Day-to-day edits to existing `.py` files do not require a re-copy.

**Install pre-commit hooks:**

```shell
poetry run pre-commit install
poetry run pre-commit install --hook-type commit-msg
```

### 3. Start the stack

```shell
docker compose up -d --build
```

The first build takes a few minutes. Subsequent starts are fast unless `Dockerfile.dev` or `requirements.txt` changes.

NetBox will be available at **http://localhost:8000** once the `netbox` container is healthy. You can follow startup logs with:

```shell
docker compose logs -f netbox
```

On first start, NetBox runs database migrations automatically. When the migrations finish you should be able to log in with the default superuser. If no superuser was created automatically, create one:

```shell
docker compose exec netbox /opt/netbox/venv/bin/python \
    /opt/netbox/netbox/manage.py createsuperuser
```

### 4. Applying code changes

Because `./plugin_dev` is mounted into the container, most Python changes take effect after a container restart - no rebuild required:

```shell
docker compose restart netbox netbox-worker
```

Rebuild the image only when you change `Dockerfile.dev` or add a new Python dependency:

```shell
docker compose up -d --build
```

If you add a new Django migration, run it inside the container:

```shell
docker compose exec netbox /opt/netbox/venv/bin/python \
    /opt/netbox/netbox/manage.py migrate config_officer
```

### 5. Tearing down

Stop and remove containers (data volumes are preserved):

```shell
docker compose down
```

Remove everything including the database:

```shell
docker compose down -v
```

---

## Pre-commit hooks

Pre-commit runs automatically before every `git commit`. The hooks cover:

- **Ruff** - linting and import sorting (replaces flake8 + isort)
- **Ruff formatter** - opinionated code formatting (replaces Black)
- **pytest-changed** - runs only the tests relevant to the files you are staging
- **commitizen** - validates the commit message format (see [Commit messages](#commit-messages))

Run all hooks manually against every file at any time:

```shell
poetry run pre-commit run --all-files
```

Run a single hook by name:

```shell
poetry run pre-commit run ruff --all-files
```

If a hook modifies files (e.g. the formatter rewrites a file), stage the changes and commit again - the hooks will re-run on the updated files.

---

## Running tests

Unit tests live in `tests/` and do not require a running NetBox instance. A lightweight stub in `tests/conftest.py` satisfies the `netbox.plugins` import at collection time.

Run the full suite:

```shell
poetry run pytest
```

Run a specific file:

```shell
poetry run pytest tests/unit/test_diff.py -v
```

Run tests matching a name pattern:

```shell
poetry run pytest -k "diff" -v
```

### Test file mapping

The `pytest-changed` pre-commit hook automatically selects which tests to run based on what you are committing. The mapping logic is:

- A changed test file (e.g. `tests/unit/test_diff.py`) → runs that file directly.
- A changed production module (e.g. `config_officer/compliance/diff.py`) → looks for `tests/**/test_diff.py`.
- Django migration files and non-Python files are skipped entirely.

### Writing tests

- Place new test files in `tests/` following the `test_<module_name>.py` naming convention.
- Keep unit tests free of external dependencies - no live database, no SSH, no filesystem writes outside `tmp_path`.
- Use `pytest.mark.unit`, `pytest.mark.integration`, or `pytest.mark.slow` to categorise tests. Unknown markers are rejected (configured via `--strict-markers` in `pyproject.toml`).

---

## Commit messages

This project follows the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification, enforced by the `commitizen` hook on every commit.

**Format:**

```
<type>(<scope>): <subject>
```

**Valid types:**

| Type | When to use |
|---|---|
| `feat` | A new feature visible to users |
| `fix` | A bug fix |
| `docs` | Documentation changes only |
| `style` | Formatting, whitespace - no logic change |
| `refactor` | Code restructuring with no behaviour change |
| `perf` | Performance improvements |
| `test` | Adding or fixing tests |
| `build` | Build system or dependency changes |
| `ci` | CI/CD configuration changes |
| `chore` | Maintenance tasks (e.g. updating pre-commit hooks) |
| `revert` | Reverting a previous commit |

**Examples:**

```
feat(collection): add support for NX-OS platform detection
fix(diff): handle empty running config without crashing
docs: update installation instructions for NetBox 4.x
test(cisco_diff): add edge case for ACL-only configs
```

Commits that do not follow this format are rejected by the `commit-msg` hook.

> **Breaking changes** - append `!` after the type/scope and add a `BREAKING CHANGE:` footer:
> ```
> feat(config)!: rename NETBOX_DEVICES_CONFIGS_DIR to NETBOX_DEVICES_CONFIGS_REPO_DIR
>
> BREAKING CHANGE: update PLUGINS_CONFIG in configuration.py to use the new key name.
> ```

---

## Submitting changes

1. **Open an issue first** for anything non-trivial - bugs, new features, or significant refactors. This avoids duplicate work and lets us align on the approach before you invest time in a PR.
2. **Branch off `main`** using a short descriptive name, e.g. `fix/diff-empty-config` or `feat/nxos-platform`.
3. **Keep PRs focused** - one logical change per PR makes review faster and history cleaner.
4. **Make sure all hooks pass** (`pre-commit run --all-files`) and the test suite is green (`pytest`) before opening a PR.
5. **Write a clear PR description** - what the change does, why it is needed, and how to test it.
