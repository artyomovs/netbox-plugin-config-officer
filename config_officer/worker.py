from django_rq import job, get_queue
from dcim.models import Device
from .models import Collection
from datetime import datetime
import time
from .choices import CollectFailChoices, CollectStatusChoices
import ipaddress
from .collect import CollectDeviceData
from .custom_exceptions import CollectionException
from django.db.models import Q
from git import Repo


CF_NAME_COLLECTION_STATUS = "collection_status"
GLOBAL_TASK_INIT_MESSAGE = "global sync task"
NETBOX_DEVICES_CONFIGS_DIR = '/configs'


def get_active_collect_task_count():
    """ Get count of pending collection tasks."""
    return  Collection.objects.filter((Q(status__iexact=CollectStatusChoices.STATUS_PENDING)
            | Q(status__iexact=CollectStatusChoices.STATUS_RUNNING)) & Q(message__iexact=GLOBAL_TASK_INIT_MESSAGE)).count()


@job("default")
def collect_device_config_hostname(hostname):
    """Collect device configuration by name. Task started with hostname param."""

    device = Device.objects.get(name__iexact=hostname)
    collect_task = Collection.objects.create(device=device, message="device collection task")
    collect_task.save()

    now = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    commit_msg = f"device_{hostname}_{now}"      
    get_queue("default").enqueue("config_officer.worker.collect_device_config_task", collect_task.pk, commit_msg)

    # # Check device template after collect
    # get_queue("configmonitor").enqueue("config_monitor.worker.check_device_config_compliance", device=device)

    # # Upload compliance information into InfluxDB
    # get_queue("default").enqueue("config_monitor.worker.upload_compliance_status_into_influxdb")    


@job("default")
def collect_device_config_task(task_id, commit_msg=""):
    """Worker - collect a particular device."""

    # Get collection task by pk. If not found - wait a little.
    time.sleep(1)
    try:
        collect_task = Collection.objects.get(id=task_id)
    except Collection.DoesNotExist:
        time.sleep(5)
        collect_task = Collection.objects.get(id=task_id)

    collect_task.status = CollectStatusChoices.STATUS_RUNNING
    collect_task.save()

    if not (commit_msg):
        now = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        commit_msg = f"{now}"   

    # If needed to fill custom fields   
    try:
        device_netbox = collect_task.device
        device_netbox.custom_field_data[CF_NAME_COLLECTION_STATUS] = False
        device_netbox.save()
        ip = str(ipaddress.ip_interface(device_netbox.primary_ip4).ip)
        device_collect = CollectDeviceData(collect_task, ip=ip, hostname_ipam=str(device_netbox.name))
        device_collect.collect_information()
    except CollectionException as exc:
        collect_task.status = CollectStatusChoices.STATUS_FAILED
        collect_task.failed_reason = exc.reason
        collect_task.message = exc.message
        collect_task.save()    
        if get_active_collect_task_count() < 11:    
            get_queue("default").enqueue("config_officer.worker.git_commit_configs_changes", commit_msg)        
        raise            
    except Exception as exc:
        collect_task.status = CollectStatusChoices.STATUS_FAILED
        collect_task.failed_reason = CollectFailChoices.FAIL_GENERAL
        collect_task.message = f"Unknown error {exc}"
        collect_task.save()
        if get_active_collect_task_count() < 11:
            get_queue("default").enqueue("config_officer.worker.git_commit_configs_changes", commit_msg)           
        raise
    collect_task.status = CollectStatusChoices.STATUS_SUCCEEDED
    device_netbox.custom_field_data[CF_NAME_COLLECTION_STATUS] = True
    collect_task.save()

    # try:
    #     get_queue("configmonitor").enqueue("config_monitor.worker.check_device_config_compliance", device=st.device)        
    # except:
    #     pass
        
    if get_active_collect_task_count() < 11:
        get_queue("default").enqueue("config_officer.worker.git_commit_configs_changes", commit_msg)       
    return f"{collect_task.device.name} {ip} running config was collected."


@job("default")
def git_commit_configs_changes(msg):
    """Commit changes in devices show-run."""

    if get_active_collect_task_count() > 0:
        return    
    message = ""
    try:
        repo = Repo(NETBOX_DEVICES_CONFIGS_DIR)
        repo.git.add("*")

        # check if there are any changes
        if len(repo.index.diff("HEAD")) > 0:
            commit_hash = repo.git.commit("-m", msg, author="Netbox Netbox <netbox@example.com>")
            message = f"Commited. Response={commit_hash}."
        else:
            message = "No changes for commit"
    except Exception as e:
        message = e
    return message
