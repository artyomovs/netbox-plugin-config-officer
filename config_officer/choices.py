from utilities.choices import ChoiceSet


class ConfigComplianceChoices(ChoiceSet):
    STATUS_Collect_FAIL = "Collect_fail"
    STATUS_NON_COMPLIANCE = "non-compliance"
    STATUS_COMPLIANCE = 'compliance'    # Collected with device. everything is ok.

    CHOICES = (
        (STATUS_Collect_FAIL, "Collect_fail"),  
        (STATUS_NON_COMPLIANCE, "non-compliance"),
        (STATUS_COMPLIANCE, 'compliance'),
    )    


class ServiceComplianceChoices(ChoiceSet):
    STATUS_NON_COMPLIANCE = "non-compliance"
    STATUS_COMPLIANCE = 'compliance' 

    CHOICES = (
        (STATUS_NON_COMPLIANCE, "non-compliance"),
        (STATUS_COMPLIANCE, 'compliance'),
    )        


class CollectFailChoices(ChoiceSet):
    FAIL_LOGIN = 'fail-login'
    FAIL_CONFIG = 'fail-config'
    FAIL_CONNECT = 'fail-connect'
    FAIL_GENERAL = 'fail-general'
    FAIL_ADD = 'fail-add'
    FAIL_UPDATE = 'fail-update'

    CHOICES = (
        (FAIL_LOGIN, 'fail-login'),
        (FAIL_CONFIG, 'fail-config'),
        (FAIL_CONNECT, 'fail-connect'),
        (FAIL_GENERAL, 'fail-general'),
        (FAIL_ADD, 'fail-add'),
        (FAIL_UPDATE, 'fail-update')
    )


class CollectStatusChoices(ChoiceSet):
    STATUS_FAILED = 'failed'
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_SUCCEEDED = 'succeeded'

    CHOICES = (
        (STATUS_FAILED, 'failed'),
        (STATUS_PENDING, 'pending'),
        (STATUS_RUNNING, 'running'),
        (STATUS_SUCCEEDED, 'succeeded'),
    )

BLANK_CHOICE = (('', '---------'),)