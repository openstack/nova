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

import contextlib
import functools
import inspect
import itertools
import math
import string
import traceback

import netifaces
from oslo_log import log
import six

from nova import block_device
from nova.compute import power_state
from nova.compute import task_states
import nova.conf
from nova import exception
from nova import notifications
from nova.notifications.objects import aggregate as aggregate_notification
from nova.notifications.objects import base as notification_base
from nova.notifications.objects import exception as notification_exception
from nova.notifications.objects import flavor as flavor_notification
from nova.notifications.objects import instance as instance_notification
from nova.notifications.objects import keypair as keypair_notification
from nova.notifications.objects import server_group as sg_notification
from nova import objects
from nova.objects import fields
from nova import rpc
from nova import safe_utils
from nova import utils
from nova.virt import driver

CONF = nova.conf.CONF
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


def get_root_bdm(context, instance, bdms=None):
    if bdms is None:
        if isinstance(instance, objects.Instance):
            uuid = instance.uuid
        else:
            uuid = instance['uuid']
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, uuid)

    return bdms.root_bdm()


def is_volume_backed_instance(context, instance, bdms=None):
    root_bdm = get_root_bdm(context, instance, bdms)
    if root_bdm is not None:
        return root_bdm.is_volume
    # in case we hit a very old instance without root bdm, we _assume_ that
    # instance is backed by a volume, if and only if image_ref is not set
    if isinstance(instance, objects.Instance):
        return not instance.image_ref

    return not instance['image_ref']


def convert_mb_to_ceil_gb(mb_value):
    gb_int = 0
    if mb_value:
        gb_float = mb_value / 1024.0
        # ensure we reserve/allocate enough space by rounding up to nearest GB
        gb_int = int(math.ceil(gb_float))
    return gb_int


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
        LOG.warning("Metadata value %(value)s for %(key)s is not of "
                    "type %(type)s. Using default value %(default)s.",
                    {'value': value, 'key': key, 'type': type,
                     'default': default}, instance=instance)
        return default


def notify_usage_exists(notifier, context, instance_ref, current_period=False,
                        ignore_missing_network_data=True,
                        system_metadata=None, extra_usage_info=None):
    """Generates 'exists' unversioned legacy notification for an instance for
    usage auditing purposes.

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

    bw = notifications.bandwidth_usage(context, instance_ref, audit_start,
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
    """Send an unversioned legacy notification about an instance.

    All new notifications should use notify_about_instance_action which sends
    a versioned notification.

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
            network_info, system_metadata, populate_image_ref_url=True,
            **extra_usage_info)

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


def _get_fault_and_priority_from_exc(exception):
    fault = None
    priority = fields.NotificationPriority.INFO

    if exception:
        priority = fields.NotificationPriority.ERROR
        fault = notification_exception.ExceptionPayload.from_exception(
            exception)

    return fault, priority


@rpc.if_notifications_enabled
def notify_about_instance_action(context, instance, host, action, phase=None,
                                 source=fields.NotificationSource.COMPUTE,
                                 exception=None, bdms=None):
    """Send versioned notification about the action made on the instance
    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param action: the name of the action
    :param phase: the phase of the action
    :param source: the source of the notification
    :param exception: the thrown exception (used in error notifications)
    :param bdms: BlockDeviceMappingList object for the instance. If it is not
                provided then we will load it from the db if so configured
    """
    fault, priority = _get_fault_and_priority_from_exc(exception)
    payload = instance_notification.InstanceActionPayload(
            instance=instance,
            fault=fault,
            bdms=bdms)
    notification = instance_notification.InstanceActionNotification(
            context=context,
            priority=priority,
            publisher=notification_base.NotificationPublisher(
                host=host, source=source),
            event_type=notification_base.EventType(
                    object='instance',
                    action=action,
                    phase=phase),
            payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_instance_create(context, instance, host, phase=None,
                                 source=fields.NotificationSource.COMPUTE,
                                 exception=None, bdms=None):
    """Send versioned notification about instance creation

    :param context: the request context
    :param instance: the instance being created
    :param host: the host emitting the notification
    :param phase: the phase of the creation
    :param source: the source of the notification
    :param exception: the thrown exception (used in error notifications)
    :param bdms: BlockDeviceMappingList object for the instance. If it is not
                provided then we will load it from the db if so configured
    """
    fault, priority = _get_fault_and_priority_from_exc(exception)
    payload = instance_notification.InstanceCreatePayload(
        instance=instance,
        fault=fault,
        bdms=bdms)
    notification = instance_notification.InstanceCreateNotification(
        context=context,
        priority=priority,
        publisher=notification_base.NotificationPublisher(
            host=host, source=source),
        event_type=notification_base.EventType(
            object='instance',
            action=fields.NotificationAction.CREATE,
            phase=phase),
        payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_volume_attach_detach(context, instance, host, action, phase,
                                      source=fields.NotificationSource.COMPUTE,
                                      volume_id=None, exception=None):
    """Send versioned notification about the action made on the instance
    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param action: the name of the action
    :param phase: the phase of the action
    :param source: the source of the notification
    :param volume_id: id of the volume will be attached
    :param exception: the thrown exception (used in error notifications)
    """
    fault, priority = _get_fault_and_priority_from_exc(exception)
    payload = instance_notification.InstanceActionVolumePayload(
            instance=instance,
            fault=fault,
            volume_id=volume_id)
    notification = instance_notification.InstanceActionVolumeNotification(
            context=context,
            priority=priority,
            publisher=notification_base.NotificationPublisher(
                    host=host, source=source),
            event_type=notification_base.EventType(
                    object='instance',
                    action=action,
                    phase=phase),
            payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_instance_rescue_action(
        context, instance, host, rescue_image_ref, action, phase=None,
        source=fields.NotificationSource.COMPUTE, exception=None):
    """Send versioned notification about the action made on the instance

    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param rescue_image_ref: the rescue image ref
    :param action: the name of the action
    :param phase: the phase of the action
    :param source: the source of the notification
    :param exception: the thrown exception (used in error notifications)
    """
    fault, priority = _get_fault_and_priority_from_exc(exception)
    payload = instance_notification.InstanceActionRescuePayload(
            instance=instance,
            fault=fault,
            rescue_image_ref=rescue_image_ref)

    notification = instance_notification.InstanceActionRescueNotification(
            context=context,
            priority=priority,
            publisher=notification_base.NotificationPublisher(
                host=host, source=source),
            event_type=notification_base.EventType(
                    object='instance',
                    action=action,
                    phase=phase),
            payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_keypair_action(context, keypair, action, phase):
    """Send versioned notification about the keypair action on the instance

    :param context: the request context
    :param keypair: the keypair which the action performed on
    :param action: the name of the action
    :param phase: the phase of the action
    """
    payload = keypair_notification.KeypairPayload(keypair=keypair)
    notification = keypair_notification.KeypairNotification(
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=CONF.host, source=fields.NotificationSource.API),
        event_type=notification_base.EventType(
            object='keypair',
            action=action,
            phase=phase),
        payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_volume_swap(context, instance, host, action, phase,
                             old_volume_id, new_volume_id, exception=None):
    """Send versioned notification about the volume swap action
       on the instance

    :param context: the request context
    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param action: the name of the action
    :param phase: the phase of the action
    :param old_volume_id: the ID of the volume that is copied from and detached
    :param new_volume_id: the ID of the volume that is copied to and attached
    :param exception: an exception
    """
    fault, priority = _get_fault_and_priority_from_exc(exception)
    payload = instance_notification.InstanceActionVolumeSwapPayload(
        instance=instance,
        fault=fault,
        old_volume_id=old_volume_id,
        new_volume_id=new_volume_id)

    instance_notification.InstanceActionVolumeSwapNotification(
        context=context,
        priority=priority,
        publisher=notification_base.NotificationPublisher(
            host=host, source=fields.NotificationSource.COMPUTE),
        event_type=notification_base.EventType(
            object='instance', action=action, phase=phase),
        payload=payload).emit(context)


@rpc.if_notifications_enabled
def notify_about_instance_snapshot(context, instance, host, phase,
                                   snapshot_image_id):
    """Send versioned notification about the snapshot action executed on the
       instance

    :param context: the request context
    :param instance: the instance from which a snapshot image is being created
    :param host: the host emitting the notification
    :param phase: the phase of the action
    :param snapshot_image_id: the ID of the snapshot
    """
    payload = instance_notification.InstanceActionSnapshotPayload(
        instance=instance,
        fault=None,
        snapshot_image_id=snapshot_image_id)

    instance_notification.InstanceActionSnapshotNotification(
        context=context,
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=host, source=fields.NotificationSource.COMPUTE),
        event_type=notification_base.EventType(
            object='instance',
            action=fields.NotificationAction.SNAPSHOT,
            phase=phase),
        payload=payload).emit(context)


@rpc.if_notifications_enabled
def notify_about_resize_prep_instance(context, instance, host, phase,
                                      new_flavor):
    """Send versioned notification about the instance resize action
       on the instance

    :param context: the request context
    :param instance: the instance which the resize action performed on
    :param host: the host emitting the notification
    :param phase: the phase of the action
    :param new_flavor: new flavor
    """

    payload = instance_notification.InstanceActionResizePrepPayload(
        instance=instance,
        fault=None,
        new_flavor=flavor_notification.FlavorPayload(flavor=new_flavor))

    instance_notification.InstanceActionResizePrepNotification(
        context=context,
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=host, source=fields.NotificationSource.COMPUTE),
        event_type=notification_base.EventType(
            object='instance',
            action=fields.NotificationAction.RESIZE_PREP,
            phase=phase),
        payload=payload).emit(context)


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


@rpc.if_notifications_enabled
def notify_about_aggregate_action(context, aggregate, action, phase):
    payload = aggregate_notification.AggregatePayload(aggregate)
    notification = aggregate_notification.AggregateNotification(
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=CONF.host, source=fields.NotificationSource.API),
        event_type=notification_base.EventType(
            object='aggregate',
            action=action,
            phase=phase),
        payload=payload)
    notification.emit(context)


def notify_about_host_update(context, event_suffix, host_payload):
    """Send a notification about host update.

    :param event_suffix: Event type like "create.start" or "create.end"
    :param host_payload: payload for host update. It is a dict and there
                         should be at least the 'host_name' key in this
                         dict.
    """
    host_identifier = host_payload.get('host_name')
    if not host_identifier:
        LOG.warning("No host name specified for the notification of "
                    "HostAPI.%s and it will be ignored", event_suffix)
        return

    notifier = rpc.get_notifier(service='api', host=host_identifier)

    notifier.info(context, 'HostAPI.%s' % event_suffix, host_payload)


@rpc.if_notifications_enabled
def notify_about_server_group_action(context, group, action):
    payload = sg_notification.ServerGroupPayload(group)
    notification = sg_notification.ServerGroupNotification(
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=CONF.host, source=fields.NotificationSource.API),
        event_type=notification_base.EventType(
            object='server_group',
            action=action),
        payload=payload)
    notification.emit(context)


def refresh_info_cache_for_instance(context, instance):
    """Refresh the info cache for an instance.

    :param instance: The instance object.
    """
    if instance.info_cache is not None and not instance.deleted:
        # Catch the exception in case the instance got deleted after the check
        # instance.deleted was executed
        try:
            instance.info_cache.refresh()
        except exception.InstanceInfoCacheNotFound:
            LOG.debug("Can not refresh info_cache because instance "
                      "was not found", instance=instance)


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
    if task_state in task_states.soft_reboot_states:
        return 'SOFT'
    return 'HARD'


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


def reverse_upsize_quota_delta(context, instance):
    """Calculate deltas required to reverse a prior upsizing
    quota adjustment.
    """
    return resize_quota_delta(context, instance.new_flavor,
                              instance.old_flavor, -1, -1)


def downsize_quota_delta(context, instance):
    """Calculate deltas required to adjust quota for an instance downsize.
    """
    old_flavor = instance.get_flavor('old')
    new_flavor = instance.get_flavor('new')
    return resize_quota_delta(context, new_flavor, old_flavor, 1, -1)


def get_headroom(quotas, usages, deltas):
    headroom = {res: quotas[res] - usages[res]
                for res in quotas.keys()}
    # If quota_cores is unlimited [-1]:
    # - set cores headroom based on instances headroom:
    if quotas.get('cores') == -1:
        if deltas.get('cores'):
            hc = headroom.get('instances', 1) * deltas['cores']
            headroom['cores'] = hc / deltas.get('instances', 1)
        else:
            headroom['cores'] = headroom.get('instances', 1)

    # If quota_ram is unlimited [-1]:
    # - set ram headroom based on instances headroom:
    if quotas.get('ram') == -1:
        if deltas.get('ram'):
            hr = headroom.get('instances', 1) * deltas['ram']
            headroom['ram'] = hr / deltas.get('instances', 1)
        else:
            headroom['ram'] = headroom.get('instances', 1)

    return headroom


def check_num_instances_quota(context, instance_type, min_count,
                              max_count, project_id=None, user_id=None,
                              orig_num_req=None):
    """Enforce quota limits on number of instances created."""
    # project_id is used for the TooManyInstances error message
    if project_id is None:
        project_id = context.project_id
    # Determine requested cores and ram
    req_cores = max_count * instance_type.vcpus
    req_ram = max_count * instance_type.memory_mb
    deltas = {'instances': max_count, 'cores': req_cores, 'ram': req_ram}

    try:
        objects.Quotas.check_deltas(context, deltas,
                                    project_id, user_id=user_id,
                                    check_project_id=project_id,
                                    check_user_id=user_id)
    except exception.OverQuota as exc:
        quotas = exc.kwargs['quotas']
        overs = exc.kwargs['overs']
        usages = exc.kwargs['usages']
        # This is for the recheck quota case where we used a delta of zero.
        if min_count == max_count == 0:
            # orig_num_req is the original number of instances requested in the
            # case of a recheck quota, for use in the over quota exception.
            req_cores = orig_num_req * instance_type.vcpus
            req_ram = orig_num_req * instance_type.memory_mb
            requested = {'instances': orig_num_req, 'cores': req_cores,
                         'ram': req_ram}
            (overs, reqs, total_alloweds, useds) = get_over_quota_detail(
                deltas, overs, quotas, requested)
            msg = "Cannot run any more instances of this type."
            params = {'overs': overs, 'pid': project_id, 'msg': msg}
            LOG.debug("%(overs)s quota exceeded for %(pid)s. %(msg)s",
                      params)
            raise exception.TooManyInstances(overs=overs,
                                             req=reqs,
                                             used=useds,
                                             allowed=total_alloweds)
        # OK, we exceeded quota; let's figure out why...
        headroom = get_headroom(quotas, usages, deltas)

        allowed = headroom.get('instances', 1)
        # Reduce 'allowed' instances in line with the cores & ram headroom
        if instance_type.vcpus:
            allowed = min(allowed,
                          headroom['cores'] // instance_type.vcpus)
        if instance_type.memory_mb:
            allowed = min(allowed,
                          headroom['ram'] // instance_type.memory_mb)

        # Convert to the appropriate exception message
        if allowed <= 0:
            msg = "Cannot run any more instances of this type."
        elif min_count <= allowed <= max_count:
            # We're actually OK, but still need to check against allowed
            return check_num_instances_quota(context, instance_type, min_count,
                                             allowed, project_id=project_id,
                                             user_id=user_id)
        else:
            msg = "Can only run %s more instances of this type." % allowed

        num_instances = (str(min_count) if min_count == max_count else
            "%s-%s" % (min_count, max_count))
        requested = dict(instances=num_instances, cores=req_cores,
                         ram=req_ram)
        (overs, reqs, total_alloweds, useds) = get_over_quota_detail(
            headroom, overs, quotas, requested)
        params = {'overs': overs, 'pid': project_id,
                  'min_count': min_count, 'max_count': max_count,
                  'msg': msg}

        if min_count == max_count:
            LOG.debug("%(overs)s quota exceeded for %(pid)s,"
                      " tried to run %(min_count)d instances. "
                      "%(msg)s", params)
        else:
            LOG.debug("%(overs)s quota exceeded for %(pid)s,"
                      " tried to run between %(min_count)d and"
                      " %(max_count)d instances. %(msg)s",
                      params)
        raise exception.TooManyInstances(overs=overs,
                                         req=reqs,
                                         used=useds,
                                         allowed=total_alloweds)

    return max_count


def get_over_quota_detail(headroom, overs, quotas, requested):
    reqs = []
    useds = []
    total_alloweds = []
    for resource in overs:
        reqs.append(str(requested[resource]))
        useds.append(str(quotas[resource] - headroom[resource]))
        total_alloweds.append(str(quotas[resource]))
    (overs, reqs, useds, total_alloweds) = map(', '.join, (
        overs, reqs, useds, total_alloweds))
    return overs, reqs, total_alloweds, useds


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


def wrap_instance_event(prefix):
    """Wraps a method to log the event taken on the instance, and result.

    This decorator wraps a method to log the start and result of an event, as
    part of an action taken on an instance.
    """
    @utils.expects_func_args('instance')
    def helper(function):

        @functools.wraps(function)
        def decorated_function(self, context, *args, **kwargs):
            wrapped_func = safe_utils.get_wrapped_function(function)
            keyed_args = inspect.getcallargs(wrapped_func, self, context,
                                             *args, **kwargs)
            instance_uuid = keyed_args['instance']['uuid']

            event_name = '{0}_{1}'.format(prefix, function.__name__)
            with EventReporter(context, event_name, instance_uuid):
                return function(self, context, *args, **kwargs)
        return decorated_function
    return helper


class UnlimitedSemaphore(object):
    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @property
    def balance(self):
        return 0


@contextlib.contextmanager
def notify_about_instance_delete(notifier, context, instance,
                                 delete_type='delete'):
    # Pre-load system_metadata because if this context is around an
    # instance.destroy(), lazy-loading it later would result in an
    # InstanceNotFound error.
    system_metadata = instance.system_metadata
    try:
        notify_about_instance_usage(notifier, context, instance,
                                    "%s.start" % delete_type)
        yield
    finally:
        notify_about_instance_usage(notifier, context, instance,
                                    "%s.end" % delete_type,
                                    system_metadata=system_metadata)
