# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

"""Functionality related to notifications common to multiple layers of
the system.
"""

import datetime

from oslo_config import cfg
from oslo_context import context as common_context
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import timeutils
import six

import nova.context
from nova import exception
from nova.i18n import _LE
from nova.image import glance
from nova import network
from nova.network import model as network_model
from nova import objects
from nova.objects import base as obj_base
from nova import rpc
from nova import utils

LOG = log.getLogger(__name__)

notify_opts = [
    cfg.StrOpt('notify_on_state_change',
        help='If set, send compute.instance.update notifications on instance '
             'state changes.  Valid values are None for no notifications, '
             '"vm_state" for notifications on VM state changes, or '
             '"vm_and_task_state" for notifications on VM and task state '
             'changes.'),
    cfg.BoolOpt('notify_api_faults', default=False,
        help='If set, send api.fault notifications on caught exceptions '
             'in the API service.'),
    cfg.StrOpt('default_notification_level',
               default='INFO',
               choices=('DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL'),
               help='Default notification level for outgoing notifications'),
    cfg.StrOpt('default_publisher_id',
               help='Default publisher_id for outgoing notifications'),
]


CONF = cfg.CONF
CONF.register_opts(notify_opts)


def notify_decorator(name, fn):
    """Decorator for notify which is used from utils.monkey_patch().

        :param name: name of the function
        :param fn: - object of the function
        :returns: fn -- decorated function

    """
    def wrapped_func(*args, **kwarg):
        body = {}
        body['args'] = []
        body['kwarg'] = {}
        for arg in args:
            body['args'].append(arg)
        for key in kwarg:
            body['kwarg'][key] = kwarg[key]

        ctxt = (common_context.get_context_from_function_and_args(
                    fn, args, kwarg) or
                common_context.get_current() or
                nova.context.RequestContext())

        notifier = rpc.get_notifier('api',
                                    publisher_id=(CONF.default_publisher_id
                                                  or CONF.host))
        method = getattr(notifier, CONF.default_notification_level.lower(),
                         'info')
        method(ctxt, name, body)

        return fn(*args, **kwarg)
    return wrapped_func


def send_api_fault(url, status, exception):
    """Send an api.fault notification."""

    if not CONF.notify_api_faults:
        return

    payload = {'url': url, 'exception': six.text_type(exception),
               'status': status}

    rpc.get_notifier('api').error(common_context.get_current() or
                                  nova.context.get_admin_context(),
                                  'api.fault',
                                  payload)


def send_update(context, old_instance, new_instance, service="compute",
                host=None):
    """Send compute.instance.update notification to report any changes occurred
    in that instance
    """

    if not CONF.notify_on_state_change:
        # skip all this if updates are disabled
        return

    update_with_state_change = False

    old_vm_state = old_instance["vm_state"]
    new_vm_state = new_instance["vm_state"]
    old_task_state = old_instance["task_state"]
    new_task_state = new_instance["task_state"]

    # we should check if we need to send a state change or a regular
    # notification
    if old_vm_state != new_vm_state:
        # yes, the vm state is changing:
        update_with_state_change = True
    elif (CONF.notify_on_state_change.lower() == "vm_and_task_state" and
          old_task_state != new_task_state):
        # yes, the task state is changing:
        update_with_state_change = True

    if update_with_state_change:
        # send a notification with state changes
        # value of verify_states need not be True as the check for states is
        # already done here
        send_update_with_states(context, new_instance, old_vm_state,
                new_vm_state, old_task_state, new_task_state, service, host)

    else:
        try:
            old_display_name = None
            if new_instance["display_name"] != old_instance["display_name"]:
                old_display_name = old_instance["display_name"]
            _send_instance_update_notification(context, new_instance,
                    service=service, host=host,
                    old_display_name=old_display_name)
        except exception.InstanceNotFound:
            LOG.debug('Failed to send instance update notification. The '
                      'instance could not be found and was most likely '
                      'deleted.', instance=new_instance)
        except Exception:
            LOG.exception(_LE("Failed to send state update notification"),
                    instance=new_instance)


def send_update_with_states(context, instance, old_vm_state, new_vm_state,
        old_task_state, new_task_state, service="compute", host=None,
        verify_states=False):
    """Send compute.instance.update notification to report changes if there
    are any, in the instance
    """

    if not CONF.notify_on_state_change:
        # skip all this if updates are disabled
        return

    fire_update = True
    # send update notification by default

    if verify_states:
        # check whether we need to send notification related to state changes
        fire_update = False
        # do not send notification if the conditions for vm and(or) task state
        # are not satisfied
        if old_vm_state != new_vm_state:
            # yes, the vm state is changing:
            fire_update = True
        elif (CONF.notify_on_state_change.lower() == "vm_and_task_state" and
              old_task_state != new_task_state):
            # yes, the task state is changing:
            fire_update = True

    if fire_update:
        # send either a state change or a regular notification
        try:
            _send_instance_update_notification(context, instance,
                    old_vm_state=old_vm_state, old_task_state=old_task_state,
                    new_vm_state=new_vm_state, new_task_state=new_task_state,
                    service=service, host=host)
        except exception.InstanceNotFound:
            LOG.debug('Failed to send instance update notification. The '
                      'instance could not be found and was most likely '
                      'deleted.', instance=instance)
        except Exception:
            LOG.exception(_LE("Failed to send state update notification"),
                    instance=instance)


def _compute_states_payload(instance, old_vm_state=None,
            old_task_state=None, new_vm_state=None, new_task_state=None):
    # If the states were not specified we assume the current instance
    # states are the correct information. This is important to do for
    # both old and new states because otherwise we create some really
    # confusing nofications like:
    #
    #   None(None) => Building(none)
    #
    # When we really were just continuing to build
    if new_vm_state is None:
        new_vm_state = instance["vm_state"]
    if new_task_state is None:
        new_task_state = instance["task_state"]
    if old_vm_state is None:
        old_vm_state = instance["vm_state"]
    if old_task_state is None:
        old_task_state = instance["task_state"]

    states_payload = {
        "old_state": old_vm_state,
        "state": new_vm_state,
        "old_task_state": old_task_state,
        "new_task_state": new_task_state,
    }
    return states_payload


def _send_instance_update_notification(context, instance, old_vm_state=None,
            old_task_state=None, new_vm_state=None, new_task_state=None,
            service="compute", host=None, old_display_name=None):
    """Send 'compute.instance.update' notification to inform observers
    about instance state changes.
    """

    payload = info_from_instance(context, instance, None, None)

    # determine how we'll report states
    payload.update(
        _compute_states_payload(
            instance, old_vm_state, old_task_state,
            new_vm_state, new_task_state))

    # add audit fields:
    (audit_start, audit_end) = audit_period_bounds(current_period=True)
    payload["audit_period_beginning"] = audit_start
    payload["audit_period_ending"] = audit_end

    # add bw usage info:
    bw = bandwidth_usage(instance, audit_start)
    payload["bandwidth"] = bw

    # add old display name if it is changed
    if old_display_name:
        payload["old_display_name"] = old_display_name

    rpc.get_notifier(service, host).info(context,
                                         'compute.instance.update', payload)


def audit_period_bounds(current_period=False):
    """Get the start and end of the relevant audit usage period

    :param current_period: if True, this will generate a usage for the
        current usage period; if False, this will generate a usage for the
        previous audit period.
    """

    begin, end = utils.last_completed_audit_period()
    if current_period:
        audit_start = end
        audit_end = timeutils.utcnow()
    else:
        audit_start = begin
        audit_end = end

    return (audit_start, audit_end)


def bandwidth_usage(instance_ref, audit_start,
        ignore_missing_network_data=True):
    """Get bandwidth usage information for the instance for the
    specified audit period.
    """
    admin_context = nova.context.get_admin_context(read_deleted='yes')

    def _get_nwinfo_old_skool():
        """Support for getting network info without objects."""
        if (instance_ref.get('info_cache') and
                instance_ref['info_cache'].get('network_info') is not None):
            cached_info = instance_ref['info_cache']['network_info']
            if isinstance(cached_info, network_model.NetworkInfo):
                return cached_info
            return network_model.NetworkInfo.hydrate(cached_info)
        try:
            return network.API().get_instance_nw_info(admin_context,
                                                      instance_ref)
        except Exception:
            try:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_LE('Failed to get nw_info'),
                                  instance=instance_ref)
            except Exception:
                if ignore_missing_network_data:
                    return
                raise

    # FIXME(comstud): Temporary as we transition to objects.
    if isinstance(instance_ref, obj_base.NovaObject):
        nw_info = instance_ref.info_cache.network_info
        if nw_info is None:
            nw_info = network_model.NetworkInfo()
    else:
        nw_info = _get_nwinfo_old_skool()

    macs = [vif['address'] for vif in nw_info]
    uuids = [instance_ref["uuid"]]

    bw_usages = objects.BandwidthUsageList.get_by_uuids(admin_context, uuids,
                                                        audit_start)
    bw = {}

    for b in bw_usages:
        if b.mac in macs:
            label = 'net-name-not-found-%s' % b.mac
            for vif in nw_info:
                if vif['address'] == b.mac:
                    label = vif['network']['label']
                    break

            bw[label] = dict(bw_in=b.bw_in, bw_out=b.bw_out)

    return bw


def image_meta(system_metadata):
    """Format image metadata for use in notifications from the instance
    system metadata.
    """
    image_meta = {}
    for md_key, md_value in six.iteritems(system_metadata):
        if md_key.startswith('image_'):
            image_meta[md_key[6:]] = md_value

    return image_meta


def info_from_instance(context, instance, network_info,
                system_metadata, **kw):
    """Get detailed instance information for an instance which is common to all
    notifications.

    :param:instance: nova.objects.Instance
    :param:network_info: network_info provided if not None
    :param:system_metadata: system_metadata DB entries for the instance,
    if not None

    .. note::

        Currently unused here in trunk, but needed for potential custom
        modifications.

    """

    def null_safe_str(s):
        return str(s) if s else ''

    def null_safe_int(s):
        return int(s) if s else ''

    def null_safe_isotime(s):
        if isinstance(s, datetime.datetime):
            return utils.strtime(s)
        else:
            return str(s) if s else ''

    image_ref_url = glance.generate_image_url(instance.image_ref)

    instance_type = instance.get_flavor()
    instance_type_name = instance_type.get('name', '')
    instance_flavorid = instance_type.get('flavorid', '')

    instance_info = dict(
        # Owner properties
        tenant_id=instance.project_id,
        user_id=instance.user_id,

        # Identity properties
        instance_id=instance.uuid,
        display_name=instance.display_name,
        reservation_id=instance.reservation_id,
        hostname=instance.hostname,

        # Type properties
        instance_type=instance_type_name,
        instance_type_id=instance.instance_type_id,
        instance_flavor_id=instance_flavorid,
        architecture=instance.architecture,

        # Capacity properties
        memory_mb=instance.memory_mb,
        disk_gb=instance.root_gb + instance.ephemeral_gb,
        vcpus=instance.vcpus,
        # Note(dhellmann): This makes the disk_gb value redundant, but
        # we are keeping it for backwards-compatibility with existing
        # users of notifications.
        root_gb=instance.root_gb,
        ephemeral_gb=instance.ephemeral_gb,

        # Location properties
        host=instance.host,
        node=instance.node,
        availability_zone=instance.availability_zone,
        cell_name=null_safe_str(instance.cell_name),

        # Date properties
        created_at=str(instance.created_at),
        # Terminated and Deleted are slightly different (although being
        # terminated and not deleted is a transient state), so include
        # both and let the recipient decide which they want to use.
        terminated_at=null_safe_isotime(instance.get('terminated_at', None)),
        deleted_at=null_safe_isotime(instance.get('deleted_at', None)),
        launched_at=null_safe_isotime(instance.get('launched_at', None)),

        # Image properties
        image_ref_url=image_ref_url,
        os_type=instance.os_type,
        kernel_id=instance.kernel_id,
        ramdisk_id=instance.ramdisk_id,

        # Status properties
        state=instance.vm_state,
        state_description=null_safe_str(instance.task_state),
        progress=null_safe_int(instance.progress),

        # accessIPs
        access_ip_v4=instance.access_ip_v4,
        access_ip_v6=instance.access_ip_v6,
        )

    if network_info is not None:
        fixed_ips = []
        for vif in network_info:
            for ip in vif.fixed_ips():
                ip["label"] = vif["network"]["label"]
                ip["vif_mac"] = vif["address"]
                fixed_ips.append(ip)
        instance_info['fixed_ips'] = fixed_ips

    # add image metadata
    image_meta_props = image_meta(instance.system_metadata)
    instance_info["image_meta"] = image_meta_props

    # add instance metadata
    instance_info['metadata'] = instance.metadata

    instance_info.update(kw)
    return instance_info
