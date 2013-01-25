# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
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

import re
import string
import traceback

from nova import block_device
from nova.compute import instance_types
from nova import db
from nova import exception
from nova.network import model as network_model
from nova import notifications
from nova.openstack.common import cfg
from nova.openstack.common import log
from nova.openstack.common.notifier import api as notifier_api
from nova import utils
from nova.virt import driver

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')
LOG = log.getLogger(__name__)


def add_instance_fault_from_exc(context, instance, fault, exc_info=None):
    """Adds the specified fault to the database."""

    code = 500
    message = fault.__class__.__name__

    if hasattr(fault, "kwargs"):
        code = fault.kwargs.get('code', 500)
        # get the message from the exception that was thrown
        # if that does not exist, use the name of the exception class itself
        message = fault.kwargs.get('value', message)

    details = unicode(fault)
    if exc_info and code == 500:
        tb = exc_info[2]
        details += '\n' + ''.join(traceback.format_tb(tb))

    values = {
        'instance_uuid': instance['uuid'],
        'code': code,
        'message': unicode(message),
        'details': unicode(details),
        'host': CONF.host
    }
    db.instance_fault_create(context, values)


def get_device_name_for_instance(context, instance, bdms, device):
    """Validates (or generates) a device name for instance.

    If device is not set, it will generate a unique device appropriate
    for the instance. It uses the block device mapping table to find
    valid device names. If the device name is valid but applicable to
    a different backend (for example /dev/vdc is specified but the
    backend uses /dev/xvdc), the device name will be converted to the
    appropriate format.
    """
    req_prefix = None
    req_letters = None
    if device:
        try:
            req_prefix, req_letters = block_device.match_device(device)
        except (TypeError, AttributeError, ValueError):
            raise exception.InvalidDevicePath(path=device)
    mappings = block_device.instance_block_mapping(instance, bdms)
    try:
        prefix = block_device.match_device(mappings['root'])[0]
    except (TypeError, AttributeError, ValueError):
        raise exception.InvalidDevicePath(path=mappings['root'])
    # NOTE(vish): remove this when xenapi is setting default_root_device
    if driver.compute_driver_matches('xenapi.XenAPIDriver'):
        prefix = '/dev/xvd'
    if req_prefix != prefix:
        LOG.debug(_("Using %(prefix)s instead of %(req_prefix)s") % locals())
    letters_list = []
    for _name, device in mappings.iteritems():
        letter = block_device.strip_prefix(device)
        # NOTE(vish): delete numbers in case we have something like
        #             /dev/sda1
        letter = re.sub("\d+", "", letter)
        letters_list.append(letter)
    used_letters = set(letters_list)

    # NOTE(vish): remove this when xenapi is properly setting
    #             default_ephemeral_device and default_swap_device
    if driver.compute_driver_matches('xenapi.XenAPIDriver'):
        instance_type_id = instance['instance_type_id']
        instance_type = instance_types.get_instance_type(instance_type_id)
        if instance_type['ephemeral_gb']:
            used_letters.update('b')
        if instance_type['swap']:
            used_letters.update('c')

    if not req_letters:
        req_letters = _get_unused_letters(used_letters)
    if req_letters in used_letters:
        raise exception.DevicePathInUse(path=device)
    return prefix + req_letters


def _get_unused_letters(used_letters):
    doubles = [first + second for second in string.ascii_lowercase
               for first in string.ascii_lowercase]
    all_letters = set(list(string.ascii_lowercase) + doubles)
    letters = list(all_letters - used_letters)
    # NOTE(vish): prepend ` so all shorter sequences sort first
    letters.sort(key=lambda x: x.rjust(2, '`'))
    return letters[0]


def notify_usage_exists(context, instance_ref, current_period=False,
                        ignore_missing_network_data=True,
                        system_metadata=None, extra_usage_info=None):
    """Generates 'exists' notification for an instance for usage auditing
    purposes.

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
        system_metadata = utils.metadata_to_dict(
                instance_ref['system_metadata'])

    # add image metadata to the notification:
    image_meta = notifications.image_meta(system_metadata)

    extra_info = dict(audit_period_beginning=str(audit_start),
                      audit_period_ending=str(audit_end),
                      bandwidth=bw, image_meta=image_meta)

    if extra_usage_info:
        extra_info.update(extra_usage_info)

    notify_about_instance_usage(context, instance_ref, 'exists',
            system_metadata=system_metadata, extra_usage_info=extra_info)


def notify_about_instance_usage(context, instance, event_suffix,
                                network_info=None, system_metadata=None,
                                extra_usage_info=None, host=None):
    """
    Send a notification about an instance.

    :param event_suffix: Event type like "delete.start" or "exists"
    :param network_info: Networking information, if provided.
    :param system_metadata: system_metadata DB entries for the instance,
        if provided.
    :param extra_usage_info: Dictionary containing extra values to add or
        override in the notification.
    :param host: Compute host for the instance, if specified.  Default is
        CONF.host
    """

    if not host:
        host = CONF.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = notifications.info_from_instance(context, instance,
            network_info, system_metadata, **extra_usage_info)

    notifier_api.notify(context, 'compute.%s' % host,
                        'compute.instance.%s' % event_suffix,
                        notifier_api.INFO, usage_info)


def get_nw_info_for_instance(instance):
    info_cache = instance['info_cache'] or {}
    cached_nwinfo = info_cache.get('network_info') or []
    return network_model.NetworkInfo.hydrate(cached_nwinfo)


def has_audit_been_run(context, host, timestamp=None):
    begin, end = utils.last_completed_audit_period(before=timestamp)
    task_log = db.task_log_get(context, "instance_usage_audit",
                               begin, end, host)
    if task_log:
        return True
    else:
        return False


def start_instance_usage_audit(context, begin, end, host, num_instances):
    db.task_log_begin_task(context, "instance_usage_audit", begin, end, host,
                           num_instances, "Instance usage audit started...")


def finish_instance_usage_audit(context, begin, end, host, errors, message):
    db.task_log_end_task(context, "instance_usage_audit", begin, end, host,
                         errors, message)


def usage_volume_info(vol_usage):
    def null_safe_str(s):
        return str(s) if s else ''

    tot_refreshed = vol_usage['tot_last_refreshed']
    curr_refreshed = vol_usage['curr_last_refreshed']
    last_refreshed_time = (tot_refreshed if tot_refreshed > curr_refreshed
                           else curr_refreshed)

    usage_info = dict(
          volume_id=vol_usage['volume_id'],
          instance_id=vol_usage['instance_id'],
          last_refreshed=null_safe_str(last_refreshed_time),
          reads=vol_usage['tot_reads'] + vol_usage['curr_reads'],
          read_bytes=vol_usage['tot_read_bytes'] +
                vol_usage['curr_read_bytes'],
          writes=vol_usage['tot_writes'] + vol_usage['curr_writes'],
          write_bytes=vol_usage['tot_write_bytes'] +
                vol_usage['curr_write_bytes'])

    return usage_info
