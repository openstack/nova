# Copyright (c) 2011 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Compute-related Utilities and helpers."""

import itertools
import string
import traceback

import netifaces
from oslo_config import cfg
from oslo_log import log
import six

from nova import block_device
from nova.compute import power_state
from nova.compute import task_states
from nova import exception
from nova.i18n import _LW
from nova.network import model as network_model
from nova import notifications
from nova import objects
from nova import rpc
from nova import utils
from nova.virt import driver

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')
LOG = log.getLogger(__name__)


def exception_to_dict(fault, message=None):
    """Converts exceptions to a dict for use in notifications."""
    # TODO(johngarbutt) move to nova/exception.py to share with wrap_exception

    code = 500
    if hasattr(fault, "kwargs"):
        code = fault.kwargs.get('code', 500)

    # get the message from the exception that was thrown
    # if that does not exist, use the name of the exception class itself
    try:
        if not message:
            message = fault.format_message()
    # These exception handlers are broad so we don't fail to log the fault
    # just because there is an unexpected error retrieving the message
    except Exception:
        try:
            message = six.text_type(fault)
        except Exception:
            message = None
    if not message:
        message = fault.__class__.__name__
    # NOTE(dripton) The message field in the database is limited to 255 chars.
    # MySQL silently truncates overly long messages, but PostgreSQL throws an
    # error if we don't truncate it.
    u_message = utils.safe_truncate(message, 255)
    fault_dict = dict(exception=fault)
    fault_dict["message"] = u_message
    fault_dict["code"] = code
    return fault_dict


def _get_fault_details(exc_info, error_code):
    details = ''
    if exc_info and error_code == 500:
        tb = exc_info[2]
        if tb:
            details = ''.join(traceback.format_tb(tb))
    return six.text_type(details)


def add_instance_fault_from_exc(context, instance, fault, exc_info=None,
                                fault_message=None):
    """Adds the specified fault to the database."""

    fault_obj = objects.InstanceFault(context=context)
    fault_obj.host = CONF.host
    fault_obj.instance_uuid = instance.uuid
    fault_obj.update(exception_to_dict(fault, message=fault_message))
    code = fault_obj.code
    fault_obj.details = _get_fault_details(exc_info, code)
    fault_obj.create()


def get_device_name_for_instance(instance, bdms, device):
    """Validates (or generates) a device name for instance.

    This method is a wrapper for get_next_device_name that gets the list
    of used devices and the root device from a block device mapping.
    """
    mappings = block_device.instance_block_mapping(instance, bdms)
    return get_next_device_name(instance, mappings.values(),
                                mappings['root'], device)


def default_device_names_for_instance(instance, root_device_name,
                                      *block_device_lists):
    """Generate missing device names for an instance."""

    dev_list = [bdm.device_name
                for bdm in itertools.chain(*block_device_lists)
                if bdm.device_name]
    if root_device_name not in dev_list:
        dev_list.append(root_device_name)

    for bdm in itertools.chain(*block_device_lists):
        dev = bdm.device_name
        if not dev:
            dev = get_next_device_name(instance, dev_list,
                                       root_device_name)
            bdm.device_name = dev
            bdm.save()
            dev_list.append(dev)


def get_next_device_name(instance, device_name_list,
                         root_device_name=None, device=None):
    """Validates (or generates) a device name for instance.

    If device is not set, it will generate a unique device appropriate
    for the instance. It uses the root_device_name (if provided) and
    the list of used devices to find valid device names. If the device
    name is valid but applicable to a different backend (for example
    /dev/vdc is specified but the backend uses /dev/xvdc), the device
    name will be converted to the appropriate format.
    """

    req_prefix = None
    req_letter = None

    if device:
        try:
            req_prefix, req_letter = block_device.match_device(device)
        except (TypeError, AttributeError, ValueError):
            raise exception.InvalidDevicePath(path=device)

    if not root_device_name:
        root_device_name = block_device.DEFAULT_ROOT_DEV_NAME

    try:
        prefix = block_device.match_device(
                block_device.prepend_dev(root_device_name))[0]
    except (TypeError, AttributeError, ValueError):
        raise exception.InvalidDevicePath(path=root_device_name)

    # NOTE(vish): remove this when xenapi is setting default_root_device
    if driver.is_xenapi():
        prefix = '/dev/xvd'

    if req_prefix != prefix:
        LOG.debug("Using %(prefix)s instead of %(req_prefix)s",
                  {'prefix': prefix, 'req_prefix': req_prefix})

    used_letters = set()
    for device_path in device_name_list:
        letter = block_device.get_device_letter(device_path)
        used_letters.add(letter)

    # NOTE(vish): remove this when xenapi is properly setting
    #             default_ephemeral_device and default_swap_device
    if driver.is_xenapi():
        flavor = instance.get_flavor()
        if flavor.ephemeral_gb:
            used_letters.add('b')

        if flavor.swap:
            used_letters.add('c')

    if not req_letter:
        req_letter = _get_unused_letter(used_letters)

    if req_letter in used_letters:
        raise exception.DevicePathInUse(path=device)

    return prefix + req_letter


def _get_unused_letter(used_letters):
    doubles = [first + second for second in string.ascii_lowercase
               for first in string.ascii_lowercase]
    all_letters = set(list(string.ascii_lowercase) + doubles)
    letters = list(all_letters - used_letters)
    # NOTE(vish): prepend ` so all shorter sequences sort first
    letters.sort(key=lambda x: x.rjust(2, '`'))
    return letters[0]


def get_value_from_system_metadata(instance, key, type, default):
    """Get a value of a specified type from image metadata.

    @param instance: The instance object
    @param key: The name of the property to get
    @param type: The python type the value is be returned as
    @param default: The value to return if key is not set or not the right type
    """
    value = instance.system_metadata.get(key, default)
    try:
        return type(value)
    except ValueError:
        LOG.warning(_LW("Metadata value %(value)s for %(key)s is not of "
                        "type %(type)s. Using default value %(default)s."),
                    {'value': value, 'key': key, 'type': type,
                     'default': default}, instance=instance)
        return default


def notify_usage_exists(notifier, context, instance_ref, current_period=False,
                        ignore_missing_network_data=True,
                        system_metadata=None, extra_usage_info=None):
    """Generates 'exists' notification for an instance for usage auditing
    purposes.

    :param notifier: a messaging.Notifier

    :param current_period: if True, this will generate a usage for the
        current usage period; if False, this will generate a usage for the
        previous audit period.

    :param ignore_missing_network_data: if True, log any exceptions generated
        while getting network info; if False, raise the exception.
    :param system_metadata: system_metadata DB entries for the instance,
        if not None.  *NOTE*: Currently unused here in trunk, but needed for
        potential custom modifications.
    :param extra_usage_info: Dictionary containing extra values to add or
        override in the notification if not None.
    """

    audit_start, audit_end = notifications.audit_period_bounds(current_period)

    bw = notifications.bandwidth_usage(instance_ref, audit_start,
            ignore_missing_network_data)

    if system_metadata is None:
        system_metadata = utils.instance_sys_meta(instance_ref)

    # add image metadata to the notification:
    image_meta = notifications.image_meta(system_metadata)

    extra_info = dict(audit_period_beginning=str(audit_start),
                      audit_period_ending=str(audit_end),
                      bandwidth=bw, image_meta=image_meta)

    if extra_usage_info:
        extra_info.update(extra_usage_info)

    notify_about_instance_usage(notifier, context, instance_ref, 'exists',
            system_metadata=system_metadata, extra_usage_info=extra_info)


def notify_about_instance_usage(notifier, context, instance, event_suffix,
                                network_info=None, system_metadata=None,
                                extra_usage_info=None, fault=None):
    """Send a notification about an instance.

    :param notifier: a messaging.Notifier
    :param event_suffix: Event type like "delete.start" or "exists"
    :param network_info: Networking information, if provided.
    :param system_metadata: system_metadata DB entries for the instance,
        if provided.
    :param extra_usage_info: Dictionary containing extra values to add or
        override in the notification.
    """
    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = notifications.info_from_instance(context, instance,
            network_info, system_metadata, **extra_usage_info)

    if fault:
        # NOTE(johngarbutt) mirrors the format in wrap_exception
        fault_payload = exception_to_dict(fault)
        LOG.debug(fault_payload["message"], instance=instance)
        usage_info.update(fault_payload)

    if event_suffix.endswith("error"):
        method = notifier.error
    else:
        method = notifier.info

    method(context, 'compute.instance.%s' % event_suffix, usage_info)


def notify_about_server_group_update(context, event_suffix, sg_payload):
    """Send a notification about server group update.

    :param event_suffix: Event type like "create.start" or "create.end"
    :param sg_payload: payload for server group update
    """
    notifier = rpc.get_notifier(service='servergroup')

    notifier.info(context, 'servergroup.%s' % event_suffix, sg_payload)


def notify_about_aggregate_update(context, event_suffix, aggregate_payload):
    """Send a notification about aggregate update.

    :param event_suffix: Event type like "create.start" or "create.end"
    :param aggregate_payload: payload for aggregate update
    """
    aggregate_identifier = aggregate_payload.get('aggregate_id', None)
    if not aggregate_identifier:
        aggregate_identifier = aggregate_payload.get('name', None)
        if not aggregate_identifier:
            LOG.debug("No aggregate id or name specified for this "
                      "notification and it will be ignored")
            return

    notifier = rpc.get_notifier(service='aggregate',
                                host=aggregate_identifier)

    notifier.info(context, 'aggregate.%s' % event_suffix, aggregate_payload)


def notify_about_host_update(context, event_suffix, host_payload):
    """Send a notification about host update.

    :param event_suffix: Event type like "create.start" or "create.end"
    :param host_payload: payload for host update. It is a dict and there
                         should be at least the 'host_name' key in this
                         dict.
    """
    host_identifier = host_payload.get('host_name')
    if not host_identifier:
        LOG.warning(_LW("No host name specified for the notification of "
                        "HostAPI.%s and it will be ignored"), event_suffix)
        return

    notifier = rpc.get_notifier(service='api', host=host_identifier)

    notifier.info(context, 'HostAPI.%s' % event_suffix, host_payload)


def get_nw_info_for_instance(instance):
    if instance.info_cache is None:
        return network_model.NetworkInfo.hydrate([])
    return instance.info_cache.network_info


def refresh_info_cache_for_instance(context, instance):
    """Refresh the info cache for an instance.

    :param instance: The instance object.
    """
    if instance.info_cache is not None:
        instance.info_cache.refresh()


def usage_volume_info(vol_usage):
    def null_safe_str(s):
        return str(s) if s else ''

    tot_refreshed = vol_usage.tot_last_refreshed
    curr_refreshed = vol_usage.curr_last_refreshed
    if tot_refreshed and curr_refreshed:
        last_refreshed_time = max(tot_refreshed, curr_refreshed)
    elif tot_refreshed:
        last_refreshed_time = tot_refreshed
    else:
        # curr_refreshed must be set
        last_refreshed_time = curr_refreshed

    usage_info = dict(
          volume_id=vol_usage.volume_id,
          tenant_id=vol_usage.project_id,
          user_id=vol_usage.user_id,
          availability_zone=vol_usage.availability_zone,
          instance_id=vol_usage.instance_uuid,
          last_refreshed=null_safe_str(last_refreshed_time),
          reads=vol_usage.tot_reads + vol_usage.curr_reads,
          read_bytes=vol_usage.tot_read_bytes +
                vol_usage.curr_read_bytes,
          writes=vol_usage.tot_writes + vol_usage.curr_writes,
          write_bytes=vol_usage.tot_write_bytes +
                vol_usage.curr_write_bytes)

    return usage_info


def get_reboot_type(task_state, current_power_state):
    """Checks if the current instance state requires a HARD reboot."""
    if current_power_state != power_state.RUNNING:
        return 'HARD'
    soft_types = [task_states.REBOOT_STARTED, task_states.REBOOT_PENDING,
                  task_states.REBOOTING]
    reboot_type = 'SOFT' if task_state in soft_types else 'HARD'
    return reboot_type


def get_machine_ips():
    """Get the machine's ip addresses

    :returns: list of Strings of ip addresses
    """
    addresses = []
    for interface in netifaces.interfaces():
        try:
            iface_data = netifaces.ifaddresses(interface)
            for family in iface_data:
                if family not in (netifaces.AF_INET, netifaces.AF_INET6):
                    continue
                for address in iface_data[family]:
                    addr = address['addr']

                    # If we have an ipv6 address remove the
                    # %ether_interface at the end
                    if family == netifaces.AF_INET6:
                        addr = addr.split('%')[0]
                    addresses.append(addr)
        except ValueError:
            pass
    return addresses


def resize_quota_delta(context, new_flavor, old_flavor, sense, compare):
    """Calculate any quota adjustment required at a particular point
    in the resize cycle.

    :param context: the request context
    :param new_flavor: the target instance type
    :param old_flavor: the original instance type
    :param sense: the sense of the adjustment, 1 indicates a
                  forward adjustment, whereas -1 indicates a
                  reversal of a prior adjustment
    :param compare: the direction of the comparison, 1 indicates
                    we're checking for positive deltas, whereas
                    -1 indicates negative deltas
    """
    def _quota_delta(resource):
        return sense * (new_flavor[resource] - old_flavor[resource])

    deltas = {}
    if compare * _quota_delta('vcpus') > 0:
        deltas['cores'] = _quota_delta('vcpus')
    if compare * _quota_delta('memory_mb') > 0:
        deltas['ram'] = _quota_delta('memory_mb')

    return deltas


def upsize_quota_delta(context, new_flavor, old_flavor):
    """Calculate deltas required to adjust quota for an instance upsize.
    """
    return resize_quota_delta(context, new_flavor, old_flavor, 1, 1)


def reverse_upsize_quota_delta(context, migration_ref):
    """Calculate deltas required to reverse a prior upsizing
    quota adjustment.
    """
    old_flavor = objects.Flavor.get_by_id(
        context, migration_ref['old_instance_type_id'])
    new_flavor = objects.Flavor.get_by_id(
        context, migration_ref['new_instance_type_id'])

    return resize_quota_delta(context, new_flavor, old_flavor, -1, -1)


def downsize_quota_delta(context, instance):
    """Calculate deltas required to adjust quota for an instance downsize.
    """
    old_flavor = instance.get_flavor('old')
    new_flavor = instance.get_flavor('new')
    return resize_quota_delta(context, new_flavor, old_flavor, 1, -1)


def reserve_quota_delta(context, deltas, instance):
    """If there are deltas to reserve, construct a Quotas object and
    reserve the deltas for the given project.

    :param context:    The nova request context.
    :param deltas:     A dictionary of the proposed delta changes.
    :param instance:   The instance we're operating on, so that
                       quotas can use the correct project_id/user_id.
    :return: nova.objects.quotas.Quotas
    """
    quotas = objects.Quotas(context=context)
    if deltas:
        project_id, user_id = objects.quotas.ids_from_instance(context,
                                                               instance)
        quotas.reserve(project_id=project_id, user_id=user_id,
                       **deltas)
    return quotas


def remove_shelved_keys_from_system_metadata(instance):
    # Delete system_metadata for a shelved instance
    for key in ['shelved_at', 'shelved_image_id', 'shelved_host']:
        if key in instance.system_metadata:
            del (instance.system_metadata[key])


class EventReporter(object):
    """Context manager to report instance action events."""

    def __init__(self, context, event_name, *instance_uuids):
        self.context = context
        self.event_name = event_name
        self.instance_uuids = instance_uuids

    def __enter__(self):
        for uuid in self.instance_uuids:
            objects.InstanceActionEvent.event_start(
                self.context, uuid, self.event_name, want_result=False)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for uuid in self.instance_uuids:
            objects.InstanceActionEvent.event_finish_with_failure(
                self.context, uuid, self.event_name, exc_val=exc_val,
                exc_tb=exc_tb, want_result=False)
        return False


class UnlimitedSemaphore(object):
    def __enter__(self):
        pass

    def __exit__(self):
        pass

    @property
    def balance(self):
        return 0
