"""Background jobs. Everything here runs in the NetBox RQ worker.

====================  ============================================  =========================================
Job                   Started by                                    What it does
====================  ============================================  =========================================
CollectDevicesJob     "Run collection" page, device "Collect" button,  one collection run (collection.runner)
                      REST API
CollectScheduleJob    recurring, one per enabled CollectSchedule     a run for the schedule's targets + webhook
CheckComplianceJob    "Re-check compliance", (re)assigning services  compliance from the stored configs
====================  ============================================  =========================================

All three are NetBox ``JobRunner`` jobs: they appear under Operations > Jobs
and keep a log. ``load_device_config_view`` is a plain RQ function the web UI
uses when the web process cannot read the configs repository itself.

.. warning::
   Never rename ``CollectScheduleJob`` or change its ``Meta.name``: recurring
   jobs already waiting in Redis refer to this class path and name.
"""

from __future__ import annotations

from core.choices import JobStatusChoices
from core.exceptions import JobFailed
from dcim.models import Device
from netbox.jobs import JobRunner

from .collection.runner import run_collection
from .collection.targets import DeviceSelection
from .compliance.engine import evaluate_device
from .configuration import get_settings
from .models import CollectSchedule
from .storage import ConfigRepository, device_config_snapshot
from .webhook import build_payload, send

#: Names of the jobs that represent collection runs (used to list runs in the UI).
COLLECTION_JOB_NAMES = ("Config Officer - Collection", "Config Officer - Collect Schedule")


class _CollectionJobBase(JobRunner):
    """Gives every enqueued run (including rescheduled recurring ones) the configured timeout."""

    @classmethod
    def enqueue(cls, *args, **kwargs):
        kwargs.setdefault("job_timeout", get_settings().collection_job_timeout)
        return super().enqueue(*args, **kwargs)

    def _send_webhook(self, schedule, summary) -> None:
        if schedule is not None and schedule.webhook_url:
            payload = build_payload(
                schedule.name, summary, ConfigRepository.from_settings(), self.job
            )
            self.logger.info(
                f"Webhook: {send(schedule.webhook_url, schedule.webhook_secret, payload)}"
            )

    def _fail_if_nothing_worked(self, summary) -> None:
        counts = summary.counts
        attempted = counts["total"] - counts["skipped"]
        if attempted and counts["succeeded"] == 0:
            raise JobFailed()


class CollectDevicesJob(_CollectionJobBase):
    class Meta:
        name = "Config Officer - Collection"

    def run(self, selection: dict | None = None, trigger: str = "manual", **kwargs):
        # "Run now" on a schedule enqueues this job with instance=<schedule>.
        schedule = self.job.object if isinstance(self.job.object, CollectSchedule) else None
        summary = run_collection(
            DeviceSelection.from_dict(selection or {}),
            job=self.job,
            job_logger=self.logger,
            user=self.job.user,
            trigger=trigger,
            schedule_name=schedule.name if schedule else "",
        )
        self._send_webhook(schedule, summary)
        self._fail_if_nothing_worked(summary)


class CollectScheduleJob(_CollectionJobBase):
    class Meta:
        name = "Config Officer - Collect Schedule"

    def run(self, *args, **kwargs):
        schedule = CollectSchedule.objects.filter(pk=self.job.object_id).first()
        if schedule is None or not schedule.enabled:
            reason = "no longer exists" if schedule is None else "is disabled"
            self.logger.warning(f"Schedule {self.job.object_id} {reason}; not rescheduling it")
            self.job.interval = None  # stops JobRunner.handle() from scheduling the next run
            return

        summary = run_collection(
            schedule.get_selection(),
            job=self.job,
            job_logger=self.logger,
            user=self.job.user,  # None for schedules created by plugin 0.1.x: no restriction
            trigger="schedule",
            schedule_name=schedule.name,
        )
        self._send_webhook(schedule, summary)
        self._fail_if_nothing_worked(summary)


class CheckComplianceJob(JobRunner):
    class Meta:
        name = "Config Officer - Compliance check"

    def run(self, device_ids=(), **kwargs):
        settings = get_settings()
        repo = ConfigRepository.from_settings(settings)
        for device in Device.objects.filter(pk__in=device_ids).order_by("name"):
            compliance = evaluate_device(
                device, repo.read_config(device.name), repo.config_updated_at(device.name), settings
            )
            if compliance is None:
                self.logger.info(f"[{device.name}] no service assigned - nothing to check")
            else:
                note = f" ({compliance.notes})" if compliance.notes else ""
                self.logger.info(f"[{device.name}] {compliance.get_status_display()}{note}")


# ---------------------------------------------------------------------------
# Helpers used by views, API and signals
# ---------------------------------------------------------------------------


def enqueue_collection(selection: DeviceSelection, user, trigger: str = "manual"):
    """Start a collection run in the background; returns the NetBox Job."""
    return CollectDevicesJob.enqueue(user=user, selection=selection.as_dict(), trigger=trigger)


def enqueue_compliance_check(device_ids, user):
    return CheckComplianceJob.enqueue(user=user, device_ids=list(device_ids))


def sync_schedule_job(schedule: CollectSchedule, user=None):
    """Create, move or remove the recurring job so that it matches the schedule."""
    if not schedule.enabled:
        cancel_schedule_jobs(schedule)
        return None
    return CollectScheduleJob.enqueue_once(
        instance=schedule,
        schedule_at=schedule.next_occurrence(),
        interval=schedule.interval_hours * 60,
        user=user,
    )


def cancel_schedule_jobs(schedule: CollectSchedule) -> None:
    """Delete waiting runs of the schedule (Job.delete() also cancels the RQ job)."""
    waiting = (JobStatusChoices.STATUS_PENDING, JobStatusChoices.STATUS_SCHEDULED)
    for job in CollectScheduleJob.get_jobs(schedule).filter(status__in=waiting):
        job.delete()


def next_scheduled_job(schedule: CollectSchedule):
    return (
        CollectScheduleJob.get_jobs(schedule)
        .filter(status=JobStatusChoices.STATUS_SCHEDULED)
        .order_by("scheduled")
        .first()
    )


def load_device_config_view(device_id: int) -> dict:
    """RQ task: config + history of a device, read from the worker's filesystem."""
    device = Device.objects.get(pk=device_id)
    return {
        "device_id": device_id,
        **device_config_snapshot(ConfigRepository.from_settings(), device.name),
    }
