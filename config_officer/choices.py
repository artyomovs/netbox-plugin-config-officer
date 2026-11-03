"""Choice sets used by the models. Values are stored in the database, so never rename them."""

from django.utils.translation import gettext_lazy as _
from utilities.choices import ChoiceSet


class CollectStatusChoices(ChoiceSet):
    """State of one device inside one collection run."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    CHOICES = (
        (STATUS_PENDING, _("Pending"), "cyan"),
        (STATUS_RUNNING, _("Running"), "blue"),
        (STATUS_SUCCEEDED, _("Succeeded"), "green"),
        (STATUS_FAILED, _("Failed"), "red"),
        (STATUS_SKIPPED, _("Skipped"), "gray"),
    )


class CollectFailChoices(ChoiceSet):
    """Why a device collection failed (see collection.connection and collection.runner)."""

    FAIL_CONNECT = "fail-connect"  # device not reachable on the SSH/Telnet port
    FAIL_LOGIN = "fail-login"  # reachable, but authentication / CLI session failed
    FAIL_CONFIG = "fail-config"  # session opened, but a command or the config fetch failed
    FAIL_UPDATE = "fail-update"  # NetBox could not be updated (e.g. serial number mismatch)
    FAIL_STORAGE = "fail-storage"  # config could not be written to the repository
    FAIL_GENERAL = "fail-general"  # anything else; see the result message and the job log
    FAIL_ADD = "fail-add"  # not used any more, kept for results created by plugin 0.1.x

    CHOICES = (
        (FAIL_CONNECT, _("Unreachable")),
        (FAIL_LOGIN, _("Login failed")),
        (FAIL_CONFIG, _("Command failed")),
        (FAIL_UPDATE, _("NetBox update failed")),
        (FAIL_STORAGE, _("Storage failed")),
        (FAIL_GENERAL, _("Unexpected error")),
        (FAIL_ADD, _("Add failed (legacy)")),
    )


class TransportChoices(ChoiceSet):
    TRANSPORT_SSH = "ssh"
    TRANSPORT_TELNET = "telnet"

    CHOICES = (
        (TRANSPORT_SSH, "SSH"),
        (TRANSPORT_TELNET, "Telnet"),
    )


class ServiceComplianceChoices(ChoiceSet):
    STATUS_COMPLIANCE = "compliance"
    STATUS_NON_COMPLIANCE = "non-compliance"

    CHOICES = (
        (STATUS_COMPLIANCE, _("Compliant"), "green"),
        (STATUS_NON_COMPLIANCE, _("Non-compliant"), "red"),
    )
