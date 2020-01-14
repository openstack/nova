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

from keystoneauth1 import exceptions as ks_exc
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import timeutils

import nova.conf
import nova.context
from nova import exception
from nova.image import glance
from nova.network import model as network_model
from nova.network import neutron
from nova.notifications.objects import base as notification_base
from nova.notifications.objects import instance as instance_notification
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova import rpc
from nova import utils


LOG = log.getLogger(__name__)

CONF = nova.conf.CONF


def send_update(context, old_instance, new_instance, service="compute",
                host=None):
    """Send compute.instance.update notification to report any changes occurred
    in that instance
    """

    if not CONF.notifications.notify_on_state_change:
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
    elif (CONF.notifications.notify_on_state_change == "vm_and_task_state" and
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
            send_instance_update_notification(context, new_instance,
                    service=service, host=host,
                    old_display_name=old_display_name)
        except exception.InstanceNotFound:
            LOG.debug('Failed to send instance update notification. The '
                      'instance could not be found and was most likely '
                      'deleted.', instance=new_instance)
        except Exception:
            LOG.exception("Failed to send state update notification",
                          instance=new_instance)


def send_update_with_states(context, instance, old_vm_state, new_vm_state,
        old_task_state, new_task_state, service="compute", host=None,
        verify_states=False):
    """Send compute.instance.update notification to report changes if there
    are any, in the instance
    """

    if not CONF.notifications.notify_on_state_change:
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
        elif (CONF.notifications.notify_on_state_change ==
                "vm_and_task_state" and old_task_state != new_task_state):
            # yes, the task state is changing:
            fire_update = True

    if fire_update:
        # send either a state change or a regular notification
        try:
            send_instance_update_notification(context, instance,
                    old_vm_state=old_vm_state, old_task_state=old_task_state,
                    new_vm_state=new_vm_state, new_task_state=new_task_state,
                    service=service, host=host)
        except exception.InstanceNotFound:
            LOG.debug('Failed to send instance update notification. The '
                      'instance could not be found and was most likely '
                      'deleted.', instance=instance)
        except Exception:
            LOG.exception("Failed to send state update notification",
                          instance=instance)


def _compute_states_payload(instance, old_vm_state=None,
            old_task_state=None, new_vm_state=None, new_task_state=None):
    # If the states were not specified we assume the current instance
    # states are the correct information. This is important to do for
    # both old and new states because otherwise we create some really
    # confusing notifications like:
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


def send_instance_update_notification(context, instance, old_vm_state=None,
            old_task_state=None, new_vm_state=None, new_task_state=None,
            service="compute", host=None, old_display_name=None):
    """Send 'compute.instance.update' notification to inform observers
    about instance state changes.
    """
    # NOTE(gibi): The image_ref_url is only used in unversioned notifications.
    # Calling the generate_image_url() could be costly as it calls
    # the Keystone API. So only do the call if the actual value will be
    # used.
    populate_image_ref_url = (CONF.notifications.notification_format in
                              ('both', 'unversioned'))
    payload = info_from_instance(context, instance, None,
                                 populate_image_ref_url=populate_image_ref_url)

    # determine how we'll report states
    payload.update(
        _compute_states_payload(
            instance, old_vm_state, old_task_state,
            new_vm_state, new_task_state))

    # add audit fields:
    (audit_start, audit_end) = audit_period_bounds(current_period=True)
    payload["audit_period_beginning"] = null_safe_isotime(audit_start)
    payload["audit_period_ending"] = null_safe_isotime(audit_end)

    # add bw usage info:
    bw = bandwidth_usage(context, instance, audit_start)
    payload["bandwidth"] = bw

    # add old display name if it is changed
    if old_display_name:
        payload["old_display_name"] = old_display_name

    rpc.get_notifier(service, host).info(context,
                                         'compute.instance.update', payload)

    _send_versioned_instance_update(context, instance, payload, host, service)


@rpc.if_notifications_enabled
def _send_versioned_instance_update(context, instance, payload, host, service):

    def _map_legacy_service_to_source(legacy_service):
        if not legacy_service.startswith('nova-'):
            return 'nova-' + service
        else:
            return service

    state_update = instance_notification.InstanceStateUpdatePayload(
        old_state=payload.get('old_state'),
        state=payload.get('state'),
        old_task_state=payload.get('old_task_state'),
        new_task_state=payload.get('new_task_state'))

    audit_period = instance_notification.AuditPeriodPayload(
            audit_period_beginning=payload.get('audit_period_beginning'),
            audit_period_ending=payload.get('audit_period_ending'))

    bandwidth = [instance_notification.BandwidthPayload(
                    network_name=label,
                    in_bytes=bw['bw_in'],
                    out_bytes=bw['bw_out'])
                 for label, bw in payload['bandwidth'].items()]

    versioned_payload = instance_notification.InstanceUpdatePayload(
        context=context,
        instance=instance,
        state_update=state_update,
        audit_period=audit_period,
        bandwidth=bandwidth,
        old_display_name=payload.get('old_display_name'))

    notification = instance_notification.InstanceUpdateNotification(
        priority=fields.NotificationPriority.INFO,
        event_type=notification_base.EventType(
            object='instance',
            action=fields.NotificationAction.UPDATE),
        publisher=notification_base.NotificationPublisher(
                host=host or CONF.host,
                source=_map_legacy_service_to_source(service)),
        payload=versioned_payload)
    notification.emit(context)


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


def bandwidth_usage(context, instance_ref, audit_start,
        ignore_missing_network_data=True):
    """Get bandwidth usage information for the instance for the
    specified audit period.
    """
    admin_context = context.elevated(read_deleted='yes')

    def _get_nwinfo_old_skool():
        """Support for getting network info without objects."""
        if (instance_ref.get('info_cache') and
                instance_ref['info_cache'].get('network_info') is not None):
            cached_info = instance_ref['info_cache']['network_info']
            if isinstance(cached_info, network_model.NetworkInfo):
                return cached_info
            return network_model.NetworkInfo.hydrate(cached_info)
        try:
            return neutron.API().get_instance_nw_info(admin_context,
                                                      instance_ref)
        except Exception:
            try:
                with excutils.save_and_reraise_exception():
                    LOG.exception('Failed to get nw_info',
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
    for md_key, md_value in system_metadata.items():
        if md_key.startswith('image_'):
            image_meta[md_key[6:]] = md_value

    return image_meta


def null_safe_str(s):
    return str(s) if s else ''


def null_safe_isotime(s):
    if isinstance(s, datetime.datetime):
        return utils.strtime(s)
    else:
        return str(s) if s else ''


def info_from_instance(context, instance, network_info,
                       populate_image_ref_url=False, **kw):
    """Get detailed instance information for an instance which is common to all
    notifications.

    :param:instance: nova.objects.Instance
    :param:network_info: network_info provided if not None
    :param:populate_image_ref_url: If True then the full URL of the image of
                                   the instance is generated and returned.
                                   This, depending on the configuration, might
                                   mean a call to Keystone. If false, None
                                   value is returned in the dict at the
                                   image_ref_url key.
    """
    image_ref_url = None
    if populate_image_ref_url:
        try:
            # NOTE(mriedem): We can eventually drop this when we no longer
            # support legacy notifications since versioned notifications don't
            # use this.
            image_ref_url = glance.API().generate_image_url(
                instance.image_ref, context)

        except ks_exc.EndpointNotFound:
            # We might be running from a periodic task with no auth token and
            # CONF.glance.api_servers isn't set, so we can't get the image API
            # endpoint URL from the service catalog, therefore just use the
            # image id for the URL (yes it's a lie, but it's best effort at
            # this point).
            with excutils.save_and_reraise_exception() as exc_ctx:
                if context.auth_token is None:
                    image_ref_url = instance.image_ref
                    exc_ctx.reraise = False

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
        memory_mb=instance.flavor.memory_mb,
        disk_gb=instance.flavor.root_gb + instance.flavor.ephemeral_gb,
        vcpus=instance.flavor.vcpus,
        # Note(dhellmann): This makes the disk_gb value redundant, but
        # we are keeping it for backwards-compatibility with existing
        # users of notifications.
        root_gb=instance.flavor.root_gb,
        ephemeral_gb=instance.flavor.ephemeral_gb,

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
        # NOTE(gibi): It might seems wrong to default the progress to an empty
        # string but this is how legacy work and this code only used by the
        # legacy notification so try to keep the compatibility here but also
        # keep it contained.
        progress=int(instance.progress) if instance.progress else '',

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
