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

from oslo.config import cfg

from nova import block_device
from nova.compute import flavors
from nova.compute import power_state
from nova.compute import task_states
from nova import exception
from nova.i18n import _LW
from nova.network import model as network_model
from nova import notifications
from nova import objects
from nova.objects import base as obj_base
from nova.openstack.common import log
from nova import rpc
from nova import utils
from nova.virt import driver

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')
LOG = log.getLogger(__name__)


def exception_to_dict(fault):
    """Converts exceptions to a dict for use in notifications."""
    # TODO(johngarbutt) move to nova/exception.py to share with wrap_exception

    code = 500
    if hasattr(fault, "kwargs"):
        code = fault.kwargs.get('code', 500)

    # get the message from the exception that was thrown
    # if that does not exist, use the name of the exception class itself
    try:
        message = fault.format_message()
    # These exception handlers are broad so we don't fail to log the fault
    # just because there is an unexpected error retrieving the message
    except Exception:
        try:
            message = unicode(fault)
        except Exception:
            message = None
    if not message:
        message = fault.__class__.__name__
    # NOTE(dripton) The message field in the database is limited to 255 chars.
    # MySQL silently truncates overly long messages, but PostgreSQL throws an
    # error if we don't truncate it.
    u_message = unicode(message)[:255]

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
    return unicode(details)


def add_instance_fault_from_exc(context, instance, fault, exc_info=None):
    """Adds the specified fault to the database."""

    fault_obj = objects.InstanceFault(context=context)
    fault_obj.host = CONF.host
    fault_obj.instance_uuid = instance['uuid']
    fault_obj.update(exception_to_dict(fault))
    code = fault_obj.code
    fault_obj.details = _get_fault_details(exc_info, code)
    fault_obj.create()


def get_device_name_for_instance(context, instance, bdms, device):
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
    if driver.compute_driver_matches('xenapi.XenAPIDriver'):
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
    if driver.compute_driver_matches('xenapi.XenAPIDriver'):
        flavor = flavors.extract_flavor(instance)
        if flavor['ephemeral_gb']:
            used_letters.add('b')

        if flavor['swap']:
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


def get_image_metadata(context, image_api, image_id_or_uri, instance):
    image_system_meta = {}
    # In case of boot from volume, image_id_or_uri may be None
    if image_id_or_uri is not None:
        # If the base image is still available, get its metadata
        try:
            image = image_api.get(context, image_id_or_uri)
        except (exception.ImageNotAuthorized,
                exception.ImageNotFound,
                exception.Invalid) as e:
            LOG.warning(_LW("Can't access image %(image_id)s: %(error)s"),
                        {"image_id": image_id_or_uri, "error": e},
                        instance=instance)
        else:
            flavor = flavors.extract_flavor(instance)
            image_system_meta = utils.get_system_metadata_from_image(image,
                                                                     flavor)

    # Get the system metadata from the instance
    system_meta = utils.instance_sys_meta(instance)

    # Merge the metadata from the instance with the image's, if any
    system_meta.update(image_system_meta)

    # Convert the system metadata to image metadata
    return utils.get_image_from_system_metadata(system_meta)


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
        LOG.warn(_LW("No host name specified for the notification of "
                   "HostAPI.%s and it will be ignored"), event_suffix)
        return

    notifier = rpc.get_notifier(service='api', host=host_identifier)

    notifier.info(context, 'HostAPI.%s' % event_suffix, host_payload)


def get_nw_info_for_instance(instance):
    if isinstance(instance, obj_base.NovaObject):
        if instance.info_cache is None:
            return network_model.NetworkInfo.hydrate([])
        return instance.info_cache.network_info
    # FIXME(comstud): Transitional while we convert to objects.
    info_cache = instance['info_cache'] or {}
    nw_info = info_cache.get('network_info') or []
    if not isinstance(nw_info, network_model.NetworkInfo):
        nw_info = network_model.NetworkInfo.hydrate(nw_info)
    return nw_info


def has_audit_been_run(context, conductor, host, timestamp=None):
    begin, end = utils.last_completed_audit_period(before=timestamp)
    task_log = conductor.task_log_get(context, "instance_usage_audit",
                                      begin, end, host)
    if task_log:
        return True
    else:
        return False


def start_instance_usage_audit(context, conductor, begin, end, host,
                               num_instances):
    conductor.task_log_begin_task(context, "instance_usage_audit", begin,
                                  end, host, num_instances,
                                  "Instance usage audit started...")


def finish_instance_usage_audit(context, conductor, begin, end, host, errors,
                                message):
    conductor.task_log_end_task(context, "instance_usage_audit", begin, end,
                                host, errors, message)


def usage_volume_info(vol_usage):
    def null_safe_str(s):
        return str(s) if s else ''

    tot_refreshed = vol_usage['tot_last_refreshed']
    curr_refreshed = vol_usage['curr_last_refreshed']
    if tot_refreshed and curr_refreshed:
        last_refreshed_time = max(tot_refreshed, curr_refreshed)
    elif tot_refreshed:
        last_refreshed_time = tot_refreshed
    else:
        # curr_refreshed must be set
        last_refreshed_time = curr_refreshed

    usage_info = dict(
          volume_id=vol_usage['volume_id'],
          tenant_id=vol_usage['project_id'],
          user_id=vol_usage['user_id'],
          availability_zone=vol_usage['availability_zone'],
          instance_id=vol_usage['instance_uuid'],
          last_refreshed=null_safe_str(last_refreshed_time),
          reads=vol_usage['tot_reads'] + vol_usage['curr_reads'],
          read_bytes=vol_usage['tot_read_bytes'] +
                vol_usage['curr_read_bytes'],
          writes=vol_usage['tot_writes'] + vol_usage['curr_writes'],
          write_bytes=vol_usage['tot_write_bytes'] +
                vol_usage['curr_write_bytes'])

    return usage_info


def get_reboot_type(task_state, current_power_state):
    """Checks if the current instance state requires a HARD reboot."""
    if current_power_state != power_state.RUNNING:
        return 'HARD'
    soft_types = [task_states.REBOOT_STARTED, task_states.REBOOT_PENDING,
                  task_states.REBOOTING]
    reboot_type = 'SOFT' if task_state in soft_types else 'HARD'
    return reboot_type


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


def periodic_task_spacing_warn(config_option_name):
    """Decorator to warn about an upcoming breaking change in methods which
    use the @periodic_task decorator.

    Some methods using the @periodic_task decorator specify spacing=0 or
    None to mean "do not call this method", but the decorator itself uses
    0/None to mean "call at the default rate".

    Starting with the K release the Nova methods will be changed to conform
    to the Oslo decorator.  This decorator should be present wherever a
    spacing value from user-supplied config is passed to @periodic_task, and
    there is also a check to skip the method if the value is zero.  It will
    log a warning if the spacing value from config is 0/None.
    """
    # TODO(gilliard) remove this decorator, its usages and the early returns
    # near them after the K release.
    def wrapper(f):
        if (hasattr(f, "_periodic_spacing") and
                (f._periodic_spacing == 0 or f._periodic_spacing is None)):
            LOG.warning(_LW("Value of 0 or None specified for %s."
                " This behaviour will change in meaning in the K release, to"
                " mean 'call at the default rate' rather than 'do not call'."
                " To keep the 'do not call' behaviour, use a negative value."),
                config_option_name)
        return f
    return wrapper
