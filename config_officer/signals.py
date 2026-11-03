"""Keeps the recurring NetBox job of each CollectSchedule in step with the schedule.

Saving a schedule from anywhere (UI, REST API, bulk edit, shell) creates, moves
or removes its job; deleting a schedule cancels the waiting job first.
"""

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from netbox.context import current_request

from .jobs import cancel_schedule_jobs, sync_schedule_job
from .models import CollectSchedule


def _request_user():
    """The user of the current web/API request, if any (becomes the owner of the job)."""
    request = current_request.get()
    user = getattr(request, "user", None)
    return user if getattr(user, "is_authenticated", False) else None


@receiver(post_save, sender=CollectSchedule)
def schedule_saved(sender, instance, **kwargs):
    sync_schedule_job(instance, user=_request_user())


@receiver(pre_delete, sender=CollectSchedule)
def schedule_deleted(sender, instance, **kwargs):
    # pre_delete: the related jobs still exist, so Job.delete() can cancel them in Redis.
    cancel_schedule_jobs(instance)
