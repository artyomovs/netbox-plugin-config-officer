"""One collection run over a set of devices.

:func:`run_collection` is called by the background jobs in jobs.py (manual
runs, schedules, API). It is deliberately the *only* place that knows the order
of the steps:

1. resolve the :class:`~.targets.DeviceSelection` to devices and create one
   :class:`~config_officer.models.Collection` result row per device;
2. prepare the git repository (fetch / fast-forward from the remote);
3. talk to the devices in a thread pool (``COLLECTION_CONCURRENCY`` at a time).
   Threads only do network I/O (connection.py); everything that touches the
   database runs in the job's main thread as results arrive:
   serial check -> store config -> sync NetBox -> compliance -> result row;
4. one git commit for the whole run, then push;
5. delete results older than ``RESULT_RETENTION_DAYS``.

Everything that happens is written to the NetBox job log (visible on the run
page) and to the Python logger ``config_officer``. NetBox changes are recorded
in NetBox's change log under the user who started the run, with the job's UUID
as request ID, so "what did this run change?" is one filter away.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import connection as db_connection
from django.utils import timezone
from git import GitCommandError

from config_officer.choices import CollectFailChoices, CollectStatusChoices
from config_officer.compliance.engine import evaluate_device
from config_officer.configuration import PluginSettings, get_settings
from config_officer.models import Collection
from config_officer.storage import CommitResult, ConfigRepository, StorageError

from .connection import CollectionError, collect_output
from .netbox_sync import check_serial, sync_device
from .parsers import parse_device_output
from .sanitize import redact_config
from .targets import DeviceSelection, SkipDevice, build_target

logger = logging.getLogger(__name__)

#: PostgreSQL advisory lock key ("CONF") serialising runs: one writer for the git repository.
RUN_LOCK_KEY = 0x434F4E46
_FLUSH_INTERVAL = 5.0  # seconds between job log writes while a run is in progress


class RunLockTimeout(Exception):
    pass


@dataclass
class DeviceResult:
    device_name: str
    status: str
    failed_reason: str = ""
    message: str = ""
    transport: str = ""
    config_changed: bool | None = None
    duration: float | None = None

    def as_dict(self) -> dict:
        return {
            "device": self.device_name,
            "status": self.status,
            "failed_reason": self.failed_reason,
            "message": self.message,
            "transport": self.transport,
            "config_changed": self.config_changed,
        }


@dataclass
class RunSummary:
    target: str
    trigger: str
    label: str
    started: datetime
    finished: datetime | None = None
    results: list[DeviceResult] = field(default_factory=list)
    commit: CommitResult | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        statuses = Counter(result.status for result in self.results)
        return {
            "total": len(self.results),
            "succeeded": statuses[CollectStatusChoices.STATUS_SUCCEEDED],
            "failed": statuses[CollectStatusChoices.STATUS_FAILED],
            "skipped": statuses[CollectStatusChoices.STATUS_SKIPPED],
            "changed": sum(1 for result in self.results if result.config_changed),
        }

    def headline(self) -> str:
        c = self.counts
        return (
            f"{c['total']} device(s): {c['succeeded']} succeeded, {c['failed']} failed, "
            f"{c['skipped']} skipped; {c['changed']} config(s) changed"
        )

    def as_dict(self) -> dict:
        return {
            "target": self.target,
            "trigger": self.trigger,
            "label": self.label,
            "started": self.started.isoformat(),
            "finished": self.finished.isoformat() if self.finished else None,
            "summary": self.counts,
            "commit": {
                "sha": self.commit.sha,
                "files": len(self.commit.files),
                "pushed": self.commit.pushed,
                "push_error": self.commit.push_error,
            }
            if self.commit
            else None,
            "errors": self.errors,
            "results": [result.as_dict() for result in self.results],
        }


class RunLog:
    """Writes to the NetBox job log (if there is a job) and to the Python logger.

    Must only be used from the job's main thread: flushing saves the Job row.
    """

    def __init__(self, job=None, job_logger: logging.Logger | None = None):
        self.job = job
        self.logger = job_logger or logger
        self._last_flush = time.monotonic()

    def info(self, message: str) -> None:
        self.logger.info(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str) -> None:
        self.logger.error(message)

    def update_data(self, **values) -> None:
        if self.job is not None:
            self.job.data = {**(self.job.data or {}), **values}

    def flush(self, force: bool = False) -> None:
        if self.job is None or self.job.pk is None:
            return
        if force or time.monotonic() - self._last_flush >= _FLUSH_INTERVAL:
            self.job.save(update_fields=["log_entries", "data"])
            self._last_flush = time.monotonic()


@contextmanager
def run_lock(wait_seconds: float, log: RunLog):
    """Serialise runs with a PostgreSQL advisory lock (works across workers and hosts)."""
    deadline = time.monotonic() + wait_seconds
    announced = False
    with db_connection.cursor() as cursor:
        while True:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [RUN_LOCK_KEY])
            if cursor.fetchone()[0]:
                break
            if time.monotonic() > deadline:
                raise RunLockTimeout(
                    f"another collection run kept the lock for more than {wait_seconds:.0f}s"
                )
            if not announced:
                log.info("Another collection run is in progress - waiting for it to finish")
                log.flush(force=True)
                announced = True
            time.sleep(5)
    try:
        yield
    finally:
        with db_connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [RUN_LOCK_KEY])


@contextmanager
def change_logging(user, request_id):
    """Attribute NetBox changes made inside the block to ``user`` (like a web request would)."""
    if user is None:
        yield
        return
    from utilities.request import NetBoxFakeRequest, apply_request_processors

    request = NetBoxFakeRequest(
        {
            "META": {},
            "COOKIES": {},
            "GET": {},
            "POST": {},
            "FILES": {},
            "user": user,
            "method": "POST",
            "path": "",
            "path_info": "",
            "id": request_id,
        }
    )
    with apply_request_processors(request):
        yield


def commit_label(
    selection: DeviceSelection, trigger: str, when: datetime, schedule_name: str = ""
) -> str:
    """Git commit message / webhook label; same formats as plugin 0.1.x."""
    stamp = timezone.localtime(when).strftime("%Y_%m_%d_%H_%M_%S")
    if schedule_name:
        return f"schedule_{schedule_name}_{stamp}"
    if selection.all_devices:
        return f"global_{stamp}"
    return f"{trigger}_{stamp}"


def _finish(row: Collection, result: DeviceResult, details: dict | None = None) -> DeviceResult:
    """Copy ``result`` onto the device's result row and save it."""
    row.status = result.status
    row.failed_reason = result.failed_reason or None
    row.message = result.message[:512]
    row.transport = result.transport
    row.config_changed = result.config_changed
    row.duration = result.duration
    row.details = details or {}
    row.save()
    return result


class _DeviceFailed(Exception):
    """Internal: stops processing one device; turned into a "failed" result by _process_device."""

    def __init__(self, reason: str, message: str, log_level: str = "warning"):
        super().__init__(message)
        self.reason, self.message, self.log_level = reason, message, log_level


def _store_and_sync(
    device, target, output, repo, settings: PluginSettings, base: dict, details: dict
):
    """Steps after a successful session: parse -> serial check -> store config -> NetBox -> compliance.

    The order matters: a serial mismatch stops *before* anything is stored, and the
    config is stored *before* NetBox is touched, so a NetBox error never loses a backup.
    """
    name = device.name
    try:
        parsed = parse_device_output(target.driver, output, target.host)
    except Exception as exc:
        logger.exception("[%s] could not parse the device output", name)
        raise _DeviceFailed(
            CollectFailChoices.FAIL_CONFIG, f"Could not parse the device output: {exc}", "error"
        ) from exc
    details["device"] = {
        "hostname": parsed.hostname,
        "version": parsed.version,
        "model": parsed.pid,
        "serial": parsed.serial,
        "interfaces": len(parsed.interfaces),
    }
    try:
        check_serial(device, parsed)
    except CollectionError as exc:
        raise _DeviceFailed(exc.reason, exc.message) from exc

    running_config = redact_config(output.running_config, settings.sensitive_prefixes)
    try:
        base["config_changed"] = repo.write_config(name, running_config)
    except OSError as exc:
        message = f"Could not store the config in {repo.configs_path}: {exc}"
        raise _DeviceFailed(CollectFailChoices.FAIL_STORAGE, message, "error") from exc

    try:
        report = sync_device(device, parsed, output.transport, settings)
    except Exception as exc:
        logger.exception("[%s] NetBox update failed", name)
        message = f"Config stored, but updating NetBox failed: {exc}"
        raise _DeviceFailed(CollectFailChoices.FAIL_UPDATE, message, "error") from exc
    details["netbox"] = report.as_dict()
    details["warnings"] += report.warnings

    try:
        compliance = evaluate_device(device, running_config, repo.config_updated_at(name), settings)
        if compliance is not None:
            details["compliance"] = compliance.status
    except Exception as exc:  # noqa: BLE001 - compliance problems never fail a collection
        logger.exception("[%s] compliance check failed", name)
        details["warnings"].append(f"compliance check failed: {exc}")
    return report


def _process_device(
    future, device, target, row, repo, settings: PluginSettings, log: RunLog
) -> DeviceResult:
    """Handle one finished device session in the main thread. Never raises."""
    name = device.name
    base: dict = {}
    details: dict = {"attempts": [], "warnings": []}
    try:
        try:
            output = future.result()
        except CollectionError as exc:
            details["attempts"] = exc.attempts
            raise _DeviceFailed(exc.reason, exc.message) from exc
        except Exception as exc:
            logger.exception("[%s] unexpected error while collecting", name)
            raise _DeviceFailed(
                CollectFailChoices.FAIL_GENERAL, f"Unexpected error: {exc}", "error"
            ) from exc

        base.update(transport=output.transport, duration=round(output.duration, 2))
        details.update(attempts=output.attempts, warnings=list(output.warnings))
        report = _store_and_sync(device, target, output, repo, settings, base, details)
    except _DeviceFailed as failure:
        getattr(log, failure.log_level)(f"[{name}] FAILED - {failure.message}")
        result = DeviceResult(
            name, CollectStatusChoices.STATUS_FAILED, failure.reason, failure.message, **base
        )
        return _finish(row, result, details)

    config_text = "config changed" if base["config_changed"] else "config unchanged"
    message = f"Collected via {output.transport.upper()} in {output.duration:.1f}s; {config_text}; NetBox: {report.summary()}"
    log.info(f"[{name}] OK - {message}")
    for warning in details["warnings"]:
        log.warning(f"[{name}] {warning}")
    return _finish(
        row,
        DeviceResult(name, CollectStatusChoices.STATUS_SUCCEEDED, message=message, **base),
        details,
    )


def _prepare_repository(repo: ConfigRepository, summary: RunSummary, log: RunLog) -> None:
    try:
        for note in repo.prepare():
            log.info(f"Git: {note}")
    except StorageError as exc:
        summary.errors.append(str(exc))
        log.error(f"Git repository not usable: {exc} - configs may not be stored")


def _create_targets(
    devices, job, settings: PluginSettings, summary: RunSummary, log: RunLog
) -> list[tuple]:
    """One result row per device; devices that cannot be collected are recorded as skipped."""
    pending = []
    for device in devices:
        row = Collection.objects.create(
            device=device, job=job, status=CollectStatusChoices.STATUS_PENDING
        )
        try:
            target, note = build_target(device, settings)
        except SkipDevice as exc:
            label = device.name or str(device.pk)
            log.info(f"[{label}] skipped - {exc}")
            summary.results.append(
                _finish(
                    row, DeviceResult(label, CollectStatusChoices.STATUS_SKIPPED, message=str(exc))
                )
            )
            continue
        if note:
            log.info(f"[{device.name}] {note}")
        pending.append((device, target, row))
    Collection.objects.filter(pk__in=[row.pk for _, _, row in pending]).update(
        status=CollectStatusChoices.STATUS_RUNNING
    )
    return pending


def _collect_all(
    pending, repo, settings: PluginSettings, summary: RunSummary, total: int, log: RunLog
) -> None:
    """Device I/O in a thread pool; results are processed here, in the main thread, as they arrive."""
    workers = max(1, min(settings.collection_concurrency, len(pending)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="config_officer") as pool:
        futures = {
            pool.submit(collect_output, target, settings): (device, target, row)
            for device, target, row in pending
        }
        for future in as_completed(futures):
            device, target, row = futures[future]
            summary.results.append(
                _process_device(future, device, target, row, repo, settings, log)
            )
            log.update_data(progress={"done": len(summary.results), "total": total})
            log.flush()


def _commit(repo: ConfigRepository, summary: RunSummary, log: RunLog) -> None:
    try:
        summary.commit = repo.commit(summary.label)
    except (StorageError, GitCommandError, OSError) as exc:
        summary.errors.append(f"commit failed: {exc}")
        log.error(f"Git: commit failed - {exc}")
        return
    log.info(f"Git: {summary.commit.describe()}")
    for note in summary.commit.notes:
        log.warning(f"Git: {note}")
    if summary.commit.pushed is False:
        summary.errors.append(f"push failed: {summary.commit.push_error}")


def _delete_old_results(settings: PluginSettings, log: RunLog) -> None:
    if not settings.result_retention_days:
        return
    cutoff = timezone.now() - timedelta(days=settings.result_retention_days)
    deleted, _ = Collection.objects.filter(timestamp__lt=cutoff).delete()
    if deleted:
        log.info(
            f"Deleted {deleted} collection result(s) older than {settings.result_retention_days} days"
        )


def run_collection(
    selection: DeviceSelection,
    *,
    job=None,
    job_logger: logging.Logger | None = None,
    user=None,
    restrict_to_user: bool = True,
    trigger: str = "manual",
    schedule_name: str = "",
    settings: PluginSettings | None = None,
) -> RunSummary:
    """Collect every device in ``selection``. See the module docstring for the steps."""
    settings = settings or get_settings()
    log = RunLog(job, job_logger)
    started = timezone.now()
    summary = RunSummary(
        target=selection.describe(),
        trigger=trigger,
        label=commit_label(selection, trigger, started, schedule_name),
        started=started,
    )

    devices = list(selection.queryset(user=user if restrict_to_user else None))
    log.info(
        f"Target: {summary.target} -> {len(devices)} device(s); up to {settings.collection_concurrency} in parallel"
    )
    log.update_data(
        target=summary.target, trigger=trigger, progress={"done": 0, "total": len(devices)}
    )
    log.flush(force=True)

    if devices:
        with run_lock(settings.collection_job_timeout / 2, log):
            repo = ConfigRepository.from_settings(settings)
            _prepare_repository(repo, summary, log)
            pending = _create_targets(devices, job, settings, summary, log)
            with change_logging(user, job.job_id if job is not None else None):
                _collect_all(pending, repo, settings, summary, len(devices), log)
            _commit(repo, summary, log)
        _delete_old_results(settings, log)
    else:
        log.warning("No devices match the selection (or you lack the permission to collect them)")

    summary.finished = timezone.now()
    log.info(f"Done: {summary.headline()}")
    log.update_data(**summary.as_dict())
    return summary
