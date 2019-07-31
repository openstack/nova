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
import traceback

import netifaces
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import excutils
import six

from nova.accelerator import cyborg
from nova import block_device
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova import exception
from nova import notifications
from nova.notifications.objects import aggregate as aggregate_notification
from nova.notifications.objects import base as notification_base
from nova.notifications.objects import compute_task as task_notification
from nova.notifications.objects import exception as notification_exception
from nova.notifications.objects import flavor as flavor_notification
from nova.notifications.objects import instance as instance_notification
from nova.notifications.objects import keypair as keypair_notification
from nova.notifications.objects import libvirt as libvirt_notification
from nova.notifications.objects import metrics as metrics_notification
from nova.notifications.objects import request_spec as reqspec_notification
from nova.notifications.objects import scheduler as scheduler_notification
from nova.notifications.objects import server_group as sg_notification
from nova.notifications.objects import volume as volume_notification
from nova import objects
from nova.objects import fields
from nova import rpc
from nova import safe_utils
from nova import utils
from nova.virt import driver

CONF = nova.conf.CONF
LOG = log.getLogger(__name__)

# These properties are specific to a particular image by design.  It
# does not make sense for them to be inherited by server snapshots.
# This list is distinct from the configuration option of the same
# (lowercase) name.
NON_INHERITABLE_IMAGE_PROPERTIES = frozenset([
    'cinder_encryption_key_id',
    'cinder_encryption_key_deletion_policy',
    'img_signature',
    'img_signature_hash_method',
    'img_signature_key_type',
    'img_signature_certificate_uuid'])


def exception_to_dict(fault, message=None):
    """Converts exceptions to a dict for use in notifications.

    :param fault: Exception that occurred
    :param message: Optional fault message, otherwise the message is derived
        from the fault itself.
    :returns: dict with the following items:

        - exception: the fault itself
        - message: one of (in priority order):
                   - the provided message to this method
                   - a formatted NovaException message
                   - the fault class name
        - code: integer code for the fault (defaults to 500)
    """
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
        # In this case either we have a NovaException which failed to format
        # the message or we have a non-nova exception which could contain
        # sensitive details. Since we're not sure, be safe and set the message
        # to the exception class name. Note that we don't guard on
        # context.is_admin here because the message is always shown in the API,
        # even to non-admin users (e.g. NoValidHost) but only the traceback
        # details are shown to users with the admin role. Checking for admin
        # context here is also not helpful because admins can perform
        # operations on a tenant user's server (migrations, reboot, etc) and
        # service startup and periodic tasks could take actions on a server
        # and those use an admin context.
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
    # TODO(mriedem): Why do we only include the details if the code is 500?
    # Though for non-nova exceptions the code will probably be 500.
    if exc_info and error_code == 500:
        # We get the full exception details including the value since
        # the fault message may not contain that information for non-nova
        # exceptions (see exception_to_dict).
        details = ''.join(traceback.format_exception(
            exc_info[0], exc_info[1], exc_info[2]))
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

    :raises TooManyDiskDevices: if the maxmimum allowed devices to attach to a
                                single instance is exceeded.
    """
    mappings = block_device.instance_block_mapping(instance, bdms)
    return get_next_device_name(instance, mappings.values(),
                                mappings['root'], device)


def default_device_names_for_instance(instance, root_device_name,
                                      *block_device_lists):
    """Generate missing device names for an instance.


    :raises TooManyDiskDevices: if the maxmimum allowed devices to attach to a
                                single instance is exceeded.
    """

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


def check_max_disk_devices_to_attach(num_devices):
    maximum = CONF.compute.max_disk_devices_to_attach
    if maximum < 0:
        return

    if num_devices > maximum:
        raise exception.TooManyDiskDevices(maximum=maximum)


def get_next_device_name(instance, device_name_list,
                         root_device_name=None, device=None):
    """Validates (or generates) a device name for instance.

    If device is not set, it will generate a unique device appropriate
    for the instance. It uses the root_device_name (if provided) and
    the list of used devices to find valid device names. If the device
    name is valid but applicable to a different backend (for example
    /dev/vdc is specified but the backend uses /dev/xvdc), the device
    name will be converted to the appropriate format.

    :raises TooManyDiskDevices: if the maxmimum allowed devices to attach to a
                                single instance is exceeded.
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

    check_max_disk_devices_to_attach(len(used_letters) + 1)

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


def heal_reqspec_is_bfv(ctxt, request_spec, instance):
    """Calculates the is_bfv flag for a RequestSpec created before Rocky.

    Starting in Rocky, new instances have their RequestSpec created with
    the "is_bfv" flag to indicate if they are volume-backed which is used
    by the scheduler when determining root disk resource allocations.

    RequestSpecs created before Rocky will not have the is_bfv flag set
    so we need to calculate it here and update the RequestSpec.

    :param ctxt: nova.context.RequestContext auth context
    :param request_spec: nova.objects.RequestSpec used for scheduling
    :param instance: nova.objects.Instance being scheduled
    """
    if 'is_bfv' in request_spec:
        return
    # Determine if this is a volume-backed instance and set the field
    # in the request spec accordingly.
    request_spec.is_bfv = is_volume_backed_instance(ctxt, instance)
    request_spec.save()


def convert_mb_to_ceil_gb(mb_value):
    gb_int = 0
    if mb_value:
        gb_float = mb_value / 1024.0
        # ensure we reserve/allocate enough space by rounding up to nearest GB
        gb_int = int(math.ceil(gb_float))
    return gb_int


def _get_unused_letter(used_letters):
    # Return the first unused device letter
    index = 0
    while True:
        letter = block_device.generate_device_letter(index)
        if letter not in used_letters:
            return letter
        index += 1


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


def notify_usage_exists(notifier, context, instance_ref, host,
                        current_period=False, ignore_missing_network_data=True,
                        system_metadata=None, extra_usage_info=None):
    """Generates 'exists' unversioned legacy and transformed notification
    for an instance for usage auditing purposes.

    :param notifier: a messaging.Notifier
    :param context: request context for the current operation
    :param instance_ref: nova.objects.Instance object from which to report
        usage
    :param host: the host emitting the notification
    :param current_period: if True, this will generate a usage for the
        current usage period; if False, this will generate a usage for the
        previous audit period.
    :param ignore_missing_network_data: if True, log any exceptions generated
        while getting network info; if False, raise the exception.
    :param system_metadata: system_metadata override for the instance. If
        None, the instance_ref.system_metadata will be used.
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
                                extra_usage_info=extra_info)

    audit_period = instance_notification.AuditPeriodPayload(
            audit_period_beginning=audit_start,
            audit_period_ending=audit_end)

    bandwidth = [instance_notification.BandwidthPayload(
                    network_name=label,
                    in_bytes=b['bw_in'],
                    out_bytes=b['bw_out'])
                 for label, b in bw.items()]

    payload = instance_notification.InstanceExistsPayload(
        context=context,
        instance=instance_ref,
        audit_period=audit_period,
        bandwidth=bandwidth)

    notification = instance_notification.InstanceExistsNotification(
        context=context,
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=host, source=fields.NotificationSource.COMPUTE),
        event_type=notification_base.EventType(
            object='instance',
            action=fields.NotificationAction.EXISTS),
        payload=payload)
    notification.emit(context)


def notify_about_instance_usage(notifier, context, instance, event_suffix,
                                network_info=None, extra_usage_info=None,
                                fault=None):
    """Send an unversioned legacy notification about an instance.

    All new notifications should use notify_about_instance_action which sends
    a versioned notification.

    :param notifier: a messaging.Notifier
    :param event_suffix: Event type like "delete.start" or "exists"
    :param network_info: Networking information, if provided.
    :param extra_usage_info: Dictionary containing extra values to add or
        override in the notification.
    """
    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = notifications.info_from_instance(context, instance,
            network_info, populate_image_ref_url=True, **extra_usage_info)

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


def _get_fault_and_priority_from_exc_and_tb(exception, tb):
    fault = None
    priority = fields.NotificationPriority.INFO

    if exception:
        priority = fields.NotificationPriority.ERROR
        fault = notification_exception.ExceptionPayload.from_exc_and_traceback(
            exception, tb)

    return fault, priority


@rpc.if_notifications_enabled
def notify_about_instance_action(context, instance, host, action, phase=None,
                                 source=fields.NotificationSource.COMPUTE,
                                 exception=None, bdms=None, tb=None):
    """Send versioned notification about the action made on the instance
    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param action: the name of the action
    :param phase: the phase of the action
    :param source: the source of the notification
    :param exception: the thrown exception (used in error notifications)
    :param bdms: BlockDeviceMappingList object for the instance. If it is not
                provided then we will load it from the db if so configured
    :param tb: the traceback (used in error notifications)
    """
    fault, priority = _get_fault_and_priority_from_exc_and_tb(exception, tb)
    payload = instance_notification.InstanceActionPayload(
            context=context,
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
                                 exception=None, bdms=None, tb=None):
    """Send versioned notification about instance creation

    :param context: the request context
    :param instance: the instance being created
    :param host: the host emitting the notification
    :param phase: the phase of the creation
    :param exception: the thrown exception (used in error notifications)
    :param bdms: BlockDeviceMappingList object for the instance. If it is not
                provided then we will load it from the db if so configured
    :param tb: the traceback (used in error notifications)
    """
    fault, priority = _get_fault_and_priority_from_exc_and_tb(exception, tb)
    payload = instance_notification.InstanceCreatePayload(
        context=context,
        instance=instance,
        fault=fault,
        bdms=bdms)
    notification = instance_notification.InstanceCreateNotification(
        context=context,
        priority=priority,
        publisher=notification_base.NotificationPublisher(
            host=host, source=fields.NotificationSource.COMPUTE),
        event_type=notification_base.EventType(
            object='instance',
            action=fields.NotificationAction.CREATE,
            phase=phase),
        payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_scheduler_action(context, request_spec, action, phase=None,
                                  source=fields.NotificationSource.SCHEDULER):
    """Send versioned notification about the action made by the scheduler
    :param context: the RequestContext object
    :param request_spec: the RequestSpec object
    :param action: the name of the action
    :param phase: the phase of the action
    :param source: the source of the notification
    """
    payload = reqspec_notification.RequestSpecPayload(
        request_spec=request_spec)
    notification = scheduler_notification.SelectDestinationsNotification(
        context=context,
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=CONF.host, source=source),
        event_type=notification_base.EventType(
            object='scheduler',
            action=action,
            phase=phase),
        payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_volume_attach_detach(context, instance, host, action, phase,
                                      volume_id=None, exception=None, tb=None):
    """Send versioned notification about the action made on the instance
    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param action: the name of the action
    :param phase: the phase of the action
    :param volume_id: id of the volume will be attached
    :param exception: the thrown exception (used in error notifications)
    :param tb: the traceback (used in error notifications)
    """
    fault, priority = _get_fault_and_priority_from_exc_and_tb(exception, tb)
    payload = instance_notification.InstanceActionVolumePayload(
            context=context,
            instance=instance,
            fault=fault,
            volume_id=volume_id)
    notification = instance_notification.InstanceActionVolumeNotification(
            context=context,
            priority=priority,
            publisher=notification_base.NotificationPublisher(
                    host=host, source=fields.NotificationSource.COMPUTE),
            event_type=notification_base.EventType(
                    object='instance',
                    action=action,
                    phase=phase),
            payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_instance_rescue_action(context, instance, host,
                                        rescue_image_ref, phase=None,
                                        exception=None, tb=None):
    """Send versioned notification about the action made on the instance

    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param rescue_image_ref: the rescue image ref
    :param phase: the phase of the action
    :param exception: the thrown exception (used in error notifications)
    :param tb: the traceback (used in error notifications)
    """
    fault, priority = _get_fault_and_priority_from_exc_and_tb(exception, tb)
    payload = instance_notification.InstanceActionRescuePayload(
            context=context,
            instance=instance,
            fault=fault,
            rescue_image_ref=rescue_image_ref)

    notification = instance_notification.InstanceActionRescueNotification(
            context=context,
            priority=priority,
            publisher=notification_base.NotificationPublisher(
                host=host, source=fields.NotificationSource.COMPUTE),
            event_type=notification_base.EventType(
                    object='instance',
                    action=fields.NotificationAction.RESCUE,
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
def notify_about_volume_swap(context, instance, host, phase,
                             old_volume_id, new_volume_id, exception=None,
                             tb=None):
    """Send versioned notification about the volume swap action
       on the instance

    :param context: the request context
    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param phase: the phase of the action
    :param old_volume_id: the ID of the volume that is copied from and detached
    :param new_volume_id: the ID of the volume that is copied to and attached
    :param exception: an exception
    :param tb: the traceback (used in error notifications)
    """
    fault, priority = _get_fault_and_priority_from_exc_and_tb(exception, tb)
    payload = instance_notification.InstanceActionVolumeSwapPayload(
        context=context,
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
            object='instance',
            action=fields.NotificationAction.VOLUME_SWAP,
            phase=phase),
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
        context=context,
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
        context=context,
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


@rpc.if_notifications_enabled
def notify_about_aggregate_cache(context, aggregate, host, image_status,
                                 index, total):
    """Send a notification about aggregate cache_images progress.

    :param context: The RequestContext
    :param aggregate: The target aggregate
    :param host: The host within the aggregate for which to report status
    :param image_status: The result from the compute host, which is a dict
                         of {image_id: status}
    :param index: An integer indicating progress toward completion, between
                  1 and $total
    :param total: The total number of hosts being processed in this operation,
                  to bound $index
    """
    success_statuses = ('cached', 'existing')
    payload = aggregate_notification.AggregateCachePayload(aggregate,
                                                           host,
                                                           index,
                                                           total)
    payload.images_cached = []
    payload.images_failed = []
    for img, status in image_status.items():
        if status in success_statuses:
            payload.images_cached.append(img)
        else:
            payload.images_failed.append(img)
    notification = aggregate_notification.AggregateCacheNotification(
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=CONF.host, source=fields.NotificationSource.CONDUCTOR),
        event_type=notification_base.EventType(
            object='aggregate',
            action=fields.NotificationAction.IMAGE_CACHE,
            phase=fields.NotificationPhase.PROGRESS),
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


@rpc.if_notifications_enabled
def notify_about_server_group_add_member(context, group_id):
    group = objects.InstanceGroup.get_by_uuid(context, group_id)
    payload = sg_notification.ServerGroupPayload(group)
    notification = sg_notification.ServerGroupNotification(
        priority=fields.NotificationPriority.INFO,
        publisher=notification_base.NotificationPublisher(
            host=CONF.host, source=fields.NotificationSource.API),
        event_type=notification_base.EventType(
            object='server_group',
            action=fields.NotificationAction.ADD_MEMBER),
        payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_instance_rebuild(context, instance, host,
                                  action=fields.NotificationAction.REBUILD,
                                  phase=None,
                                  source=fields.NotificationSource.COMPUTE,
                                  exception=None, bdms=None, tb=None):
    """Send versioned notification about instance rebuild

    :param instance: the instance which the action performed on
    :param host: the host emitting the notification
    :param action: the name of the action
    :param phase: the phase of the action
    :param source: the source of the notification
    :param exception: the thrown exception (used in error notifications)
    :param bdms: BlockDeviceMappingList object for the instance. If it is not
                provided then we will load it from the db if so configured
    :param tb: the traceback (used in error notifications)
    """
    fault, priority = _get_fault_and_priority_from_exc_and_tb(exception, tb)
    payload = instance_notification.InstanceActionRebuildPayload(
            context=context,
            instance=instance,
            fault=fault,
            bdms=bdms)
    notification = instance_notification.InstanceActionRebuildNotification(
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
def notify_about_metrics_update(context, host, host_ip, nodename,
                                monitor_metric_list):
    """Send versioned notification about updating metrics

    :param context: the request context
    :param host: the host emitting the notification
    :param host_ip: the IP address of the host
    :param nodename: the node name
    :param monitor_metric_list: the MonitorMetricList object
    """
    payload = metrics_notification.MetricsPayload(
            host=host,
            host_ip=host_ip,
            nodename=nodename,
            monitor_metric_list=monitor_metric_list)
    notification = metrics_notification.MetricsNotification(
            context=context,
            priority=fields.NotificationPriority.INFO,
            publisher=notification_base.NotificationPublisher(
                host=host, source=fields.NotificationSource.COMPUTE),
            event_type=notification_base.EventType(
                object='metrics',
                action=fields.NotificationAction.UPDATE),
            payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_libvirt_connect_error(context, ip, exception, tb):
    """Send a versioned notification about libvirt connect error.

    :param context: the request context
    :param ip: the IP address of the host
    :param exception: the thrown exception
    :param tb: the traceback
    """
    fault, _ = _get_fault_and_priority_from_exc_and_tb(exception, tb)
    payload = libvirt_notification.LibvirtErrorPayload(ip=ip, reason=fault)
    notification = libvirt_notification.LibvirtErrorNotification(
        priority=fields.NotificationPriority.ERROR,
        publisher=notification_base.NotificationPublisher(
            host=CONF.host, source=fields.NotificationSource.COMPUTE),
        event_type=notification_base.EventType(
            object='libvirt',
            action=fields.NotificationAction.CONNECT,
            phase=fields.NotificationPhase.ERROR),
        payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_volume_usage(context, vol_usage, host):
    """Send versioned notification about the volume usage

    :param context: the request context
    :param vol_usage: the volume usage object
    :param host: the host emitting the notification
    """
    payload = volume_notification.VolumeUsagePayload(
            vol_usage=vol_usage)
    notification = volume_notification.VolumeUsageNotification(
            context=context,
            priority=fields.NotificationPriority.INFO,
            publisher=notification_base.NotificationPublisher(
                host=host, source=fields.NotificationSource.COMPUTE),
            event_type=notification_base.EventType(
                object='volume',
                action=fields.NotificationAction.USAGE),
            payload=payload)
    notification.emit(context)


@rpc.if_notifications_enabled
def notify_about_compute_task_error(context, action, instance_uuid,
                                    request_spec, state, exception, tb):
    """Send a versioned notification about compute task error.

    :param context: the request context
    :param action: the name of the action
    :param instance_uuid: the UUID of the instance
    :param request_spec: the request spec object or
                         the dict includes request spec information
    :param state: the vm state of the instance
    :param exception: the thrown exception
    :param tb: the traceback
    """
    if (request_spec is not None and
            not isinstance(request_spec, objects.RequestSpec)):
        request_spec = objects.RequestSpec.from_primitives(
            context, request_spec, {})

    fault, _ = _get_fault_and_priority_from_exc_and_tb(exception, tb)
    payload = task_notification.ComputeTaskPayload(
        instance_uuid=instance_uuid, request_spec=request_spec, state=state,
        reason=fault)
    notification = task_notification.ComputeTaskNotification(
        priority=fields.NotificationPriority.ERROR,
        publisher=notification_base.NotificationPublisher(
            host=CONF.host, source=fields.NotificationSource.CONDUCTOR),
        event_type=notification_base.EventType(
            object='compute_task',
            action=action,
            phase=fields.NotificationPhase.ERROR),
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


def upsize_quota_delta(new_flavor, old_flavor):
    """Calculate deltas required to adjust quota for an instance upsize.

    :param new_flavor: the target instance type
    :param old_flavor: the original instance type
    """
    def _quota_delta(resource):
        return (new_flavor[resource] - old_flavor[resource])

    deltas = {}
    if _quota_delta('vcpus') > 0:
        deltas['cores'] = _quota_delta('vcpus')
    if _quota_delta('memory_mb') > 0:
        deltas['ram'] = _quota_delta('memory_mb')

    return deltas


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


def create_image(context, instance, name, image_type, image_api,
                 extra_properties=None):
    """Create new image entry in the image service.  This new image
    will be reserved for the compute manager to upload a snapshot
    or backup.

    :param context: security context
    :param instance: nova.objects.instance.Instance object
    :param name: string for name of the snapshot
    :param image_type: snapshot | backup
    :param image_api: instance of nova.image.glance.API
    :param extra_properties: dict of extra image properties to include

    """
    properties = {
        'instance_uuid': instance.uuid,
        'user_id': str(context.user_id),
        'image_type': image_type,
    }
    properties.update(extra_properties or {})

    image_meta = initialize_instance_snapshot_metadata(
        context, instance, name, properties)
    # if we're making a snapshot, omit the disk and container formats,
    # since the image may have been converted to another format, and the
    # original values won't be accurate.  The driver will populate these
    # with the correct values later, on image upload.
    if image_type == 'snapshot':
        image_meta.pop('disk_format', None)
        image_meta.pop('container_format', None)
    return image_api.create(context, image_meta)


def initialize_instance_snapshot_metadata(context, instance, name,
                                          extra_properties=None):
    """Initialize new metadata for a snapshot of the given instance.

    :param context: authenticated RequestContext; note that this may not
            be the owner of the instance itself, e.g. an admin creates a
            snapshot image of some user instance
    :param instance: nova.objects.instance.Instance object
    :param name: string for name of the snapshot
    :param extra_properties: dict of extra metadata properties to include

    :returns: the new instance snapshot metadata
    """
    image_meta = utils.get_image_from_system_metadata(
        instance.system_metadata)
    image_meta['name'] = name

    # If the user creating the snapshot is not in the same project as
    # the owner of the instance, then the image visibility should be
    # "shared" so the owner of the instance has access to the image, like
    # in the case of an admin creating a snapshot of another user's
    # server, either directly via the createImage API or via shelve.
    extra_properties = extra_properties or {}
    if context.project_id != instance.project_id:
        # The glance API client-side code will use this to add the
        # instance project as a member of the image for access.
        image_meta['visibility'] = 'shared'
        extra_properties['instance_owner'] = instance.project_id
        # TODO(mriedem): Should owner_project_name and owner_user_name
        # be removed from image_meta['properties'] here, or added to
        # [DEFAULT]/non_inheritable_image_properties? It is confusing
        # otherwise to see the owner project not match those values.
    else:
        # The request comes from the owner of the instance so make the
        # image private.
        image_meta['visibility'] = 'private'

    # Delete properties that are non-inheritable
    properties = image_meta['properties']
    keys_to_pop = set(CONF.non_inheritable_image_properties).union(
        NON_INHERITABLE_IMAGE_PROPERTIES)
    for key in keys_to_pop:
        properties.pop(key, None)

    # The properties in extra_properties have precedence
    properties.update(extra_properties)

    return image_meta


def delete_image(context, instance, image_api, image_id, log_exc_info=False):
    """Deletes the image if it still exists.

    Ignores ImageNotFound if the image is already gone.

    :param context: the nova auth request context where the context.project_id
        matches the owner of the image
    :param instance: the instance for which the snapshot image was created
    :param image_api: the image API used to delete the image
    :param image_id: the ID of the image to delete
    :param log_exc_info: True if this is being called from an exception handler
        block and traceback should be logged at DEBUG level, False otherwise.
    """
    LOG.debug("Cleaning up image %s", image_id, instance=instance,
              log_exc_info=log_exc_info)
    try:
        image_api.delete(context, image_id)
    except exception.ImageNotFound:
        # Since we're trying to cleanup an image, we don't care if
        # if it's already gone.
        pass
    except Exception:
        LOG.exception("Error while trying to clean up image %s",
                      image_id, instance=instance)


def may_have_ports_or_volumes(instance):
    """Checks to see if an instance may have ports or volumes based on vm_state

    This is primarily only useful when instance.host is None.

    :param instance: The nova.objects.Instance in question.
    :returns: True if the instance may have ports of volumes, False otherwise
    """
    # NOTE(melwitt): When an instance build fails in the compute manager,
    # the instance host and node are set to None and the vm_state is set
    # to ERROR. In the case, the instance with host = None has actually
    # been scheduled and may have ports and/or volumes allocated on the
    # compute node.
    if instance.vm_state in (vm_states.SHELVED_OFFLOADED, vm_states.ERROR):
        return True
    return False


def get_stashed_volume_connector(bdm, instance):
    """Lookup a connector dict from the bdm.connection_info if set

    Gets the stashed connector dict out of the bdm.connection_info if set
    and the connector host matches the instance host.

    :param bdm: nova.objects.block_device.BlockDeviceMapping
    :param instance: nova.objects.instance.Instance
    :returns: volume connector dict or None
    """
    if 'connection_info' in bdm and bdm.connection_info is not None:
        # NOTE(mriedem): We didn't start stashing the connector in the
        # bdm.connection_info until Mitaka so it might not be there on old
        # attachments. Also, if the volume was attached when the instance
        # was in shelved_offloaded state and it hasn't been unshelved yet
        # we don't have the attachment/connection information either.
        connector = jsonutils.loads(bdm.connection_info).get('connector')
        if connector:
            if connector.get('host') == instance.host:
                return connector
            LOG.debug('Found stashed volume connector for instance but '
                      'connector host %(connector_host)s does not match '
                      'the instance host %(instance_host)s.',
                      {'connector_host': connector.get('host'),
                       'instance_host': instance.host}, instance=instance)
            if (instance.host is None and
                    may_have_ports_or_volumes(instance)):
                LOG.debug('Allowing use of stashed volume connector with '
                          'instance host None because instance with '
                          'vm_state %(vm_state)s has been scheduled in '
                          'the past.', {'vm_state': instance.vm_state},
                          instance=instance)
                return connector


class EventReporter(object):
    """Context manager to report instance action events.

    If constructed with ``graceful_exit=True`` the __exit__ function will
    handle and not re-raise on InstanceActionNotFound.
    """

    def __init__(self, context, event_name, host, *instance_uuids,
                 graceful_exit=False):
        self.context = context
        self.event_name = event_name
        self.instance_uuids = instance_uuids
        self.host = host
        self.graceful_exit = graceful_exit

    def __enter__(self):
        for uuid in self.instance_uuids:
            objects.InstanceActionEvent.event_start(
                self.context, uuid, self.event_name, want_result=False,
                host=self.host)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for uuid in self.instance_uuids:
            try:
                objects.InstanceActionEvent.event_finish_with_failure(
                    self.context, uuid, self.event_name, exc_val=exc_val,
                    exc_tb=exc_tb, want_result=False)
            except exception.InstanceActionNotFound:
                # If the instance action was not found then determine if we
                # should re-raise based on the graceful_exit attribute.
                with excutils.save_and_reraise_exception(
                        reraise=not self.graceful_exit):
                    if self.graceful_exit:
                        return True
        return False


def wrap_instance_event(prefix, graceful_exit=False):
    """Wraps a method to log the event taken on the instance, and result.

    This decorator wraps a method to log the start and result of an event, as
    part of an action taken on an instance.

    :param prefix: prefix for the event name, usually a service binary like
        "compute" or "conductor" to indicate the origin of the event.
    :param graceful_exit: True if the decorator should gracefully handle
        InstanceActionNotFound errors, False otherwise. This should rarely be
        True.
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
            host = self.host if hasattr(self, 'host') else None
            with EventReporter(context, event_name, host, instance_uuid,
                               graceful_exit=graceful_exit):
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


# This semaphore is used to enforce a limit on disk-IO-intensive operations
# (image downloads, image conversions) at any given time.
# It is initialized at ComputeManager.init_host()
disk_ops_semaphore = UnlimitedSemaphore()


@contextlib.contextmanager
def notify_about_instance_delete(notifier, context, instance,
                                 delete_type='delete',
                                 source=fields.NotificationSource.API):
    try:
        notify_about_instance_usage(notifier, context, instance,
                                    "%s.start" % delete_type)
        # Note(gibi): force_delete types will be handled in a
        # subsequent patch
        if delete_type in ['delete', 'soft_delete']:
            notify_about_instance_action(
                context,
                instance,
                host=CONF.host,
                source=source,
                action=delete_type,
                phase=fields.NotificationPhase.START)

        yield
    finally:
        notify_about_instance_usage(notifier, context, instance,
                                    "%s.end" % delete_type)
        if delete_type in ['delete', 'soft_delete']:
            notify_about_instance_action(
                context,
                instance,
                host=CONF.host,
                source=source,
                action=delete_type,
                phase=fields.NotificationPhase.END)


def update_pci_request_spec_with_allocated_interface_name(
        context, report_client, instance, provider_mapping):
    """Update the instance's PCI request based on the request group -
    resource provider mapping and the device RP name from placement.

    :param context: the request context
    :param report_client: a SchedulerReportClient instance
    :param instance: an Instance object to be updated
    :param provider_mapping: the request group - resource provider mapping
        in the form returned by the RequestSpec.get_request_group_mapping()
        call.
    :raises AmbigousResourceProviderForPCIRequest: if more than one
        resource provider provides resource for the given PCI request.
    :raises UnexpectResourceProviderNameForPCIRequest: if the resource
        provider, which provides resource for the pci request, does not
        have a well formatted name so we cannot parse the parent interface
        name out of it.
    """
    if not instance.pci_requests:
        return

    def needs_update(pci_request, mapping):
        return (pci_request.requester_id and
                pci_request.requester_id in mapping)

    for pci_request in instance.pci_requests.requests:
        if needs_update(pci_request, provider_mapping):

            provider_uuids = provider_mapping[pci_request.requester_id]
            if len(provider_uuids) != 1:
                raise exception.AmbiguousResourceProviderForPCIRequest(
                    providers=provider_uuids,
                    requester=pci_request.requester_id)

            dev_rp_name = report_client.get_resource_provider_name(
                context,
                provider_uuids[0])

            # NOTE(gibi): the device RP name reported by neutron is
            # structured like <hostname>:<agentname>:<interfacename>
            rp_name_pieces = dev_rp_name.split(':')
            if len(rp_name_pieces) != 3:
                ex = exception.UnexpectedResourceProviderNameForPCIRequest
                raise ex(
                    provider=provider_uuids[0],
                    requester=pci_request.requester_id,
                    provider_name=dev_rp_name)

            for spec in pci_request.spec:
                spec['parent_ifname'] = rp_name_pieces[2]


def delete_arqs_if_needed(context, instance):
    """Delete Cyborg ARQs for the instance."""
    dp_name = instance.flavor.extra_specs.get('accel:device_profile')
    if dp_name is None:
        return
    cyclient = cyborg.get_client(context)
    LOG.debug('Calling Cyborg to delete ARQs for instance %(instance)s',
              {'instance': instance.uuid})
    try:
        cyclient.delete_arqs_for_instance(instance.uuid)
    except exception.AcceleratorRequestOpFailed as e:
        LOG.exception('Failed to delete accelerator requests for '
                      'instance %s. Exception: %s', instance.uuid, e)
