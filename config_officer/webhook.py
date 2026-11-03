"""Summary webhook sent after a scheduled collection run.

The JSON body is POSTed to ``CollectSchedule.webhook_url``. With a
``webhook_secret`` the body is signed and the signature is sent as::

    X-Webhook-Signature: sha256=<hex HMAC-SHA256(secret, raw body)>

The payload keeps the 0.1.x fields (``event``, ``schedule``, ``commit``,
``summary``, ``results``, ``diffs``); ``target``, ``job`` and
``summary.skipped`` were added.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

import requests

from .storage import ConfigRepository

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def build_payload(
    schedule_name: str, summary, repo: ConfigRepository | None = None, job=None
) -> dict:
    """Webhook body for a finished run (``summary`` is a collection.runner.RunSummary)."""
    commit = summary.commit
    diffs = []
    for result in summary.results:
        if result.config_changed is None:  # failed or skipped: nothing was stored
            continue
        entry = {"device": result.device_name, "changed": bool(result.config_changed), "diff": ""}
        if result.config_changed and commit and commit.sha:
            entry["commit_hash"] = commit.sha
            entry["commit_date"] = (summary.finished or summary.started).strftime("%Y-%m-%d %H:%M")
            if repo is not None:
                try:
                    entry["diff"] = repo.diff_in_commit(commit.sha, result.device_name)
                except Exception:  # noqa: BLE001 - a missing diff must not stop the webhook
                    logger.exception("Could not read the diff of %s", result.device_name)
        diffs.append(entry)

    return {
        "event": "schedule_complete",
        "schedule": schedule_name,
        "target": summary.target,
        "commit": summary.label,
        "job": {"id": job.pk, "uuid": str(job.job_id)} if job is not None else None,
        "summary": summary.counts,
        "results": [
            {
                "device": r.device_name,
                "status": r.status,
                "failed_reason": r.failed_reason,
                "message": r.message,
            }
            for r in summary.results
        ],
        "diffs": diffs,
    }


def send(url: str, secret: str, payload: dict) -> str:
    """POST ``payload``; returns a short status text for the job log (never raises)."""
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Webhook-Signature"] = sign(body, secret)
    try:
        response = requests.post(url, data=body, headers=headers, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Webhook delivery to %s failed: %s", url, exc)
        return f"delivery to {url} FAILED: {exc}"
    return f"delivered to {url} (HTTP {response.status_code})"
