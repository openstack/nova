# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
# Copyright 2012 Red Hat, Inc.
# All Rights Reserved.
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

"""Handles all requests relating to compute resources (e.g. guest VMs,
networking and storage of VMs, and compute hosts on which they run)."""

import base64
import functools
import re
import string
import time
import urllib

from nova import block_device
from nova.compute import instance_types
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import crypto
from nova.db import base
from nova import exception
from nova import flags
from nova.image import glance
from nova import network
from nova import notifications
from nova.openstack.common import excutils
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
import nova.policy
from nova import quota
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import utils
from nova import volume


LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS
flags.DECLARE('consoleauth_topic', 'nova.consoleauth')

MAX_USERDATA_SIZE = 65535
QUOTAS = quota.QUOTAS


def check_instance_state(vm_state=None, task_state=(None,)):
    """Decorator to check VM and/or task state before entry to API functions.

    If the instance is in the wrong state, the wrapper will raise an exception.
    """

    if vm_state is not None and not isinstance(vm_state, set):
        vm_state = set(vm_state)
    if task_state is not None and not isinstance(task_state, set):
        task_state = set(task_state)

    def outer(f):
        @functools.wraps(f)
        def inner(self, context, instance, *args, **kw):
            if vm_state is not None and instance['vm_state'] not in vm_state:
                raise exception.InstanceInvalidState(
                    attr='vm_state',
                    instance_uuid=instance['uuid'],
                    state=instance['vm_state'],
                    method=f.__name__)
            if (task_state is not None and
                instance['task_state'] not in task_state):
                raise exception.InstanceInvalidState(
                    attr='task_state',
                    instance_uuid=instance['uuid'],
                    state=instance['task_state'],
                    method=f.__name__)

            return f(self, context, instance, *args, **kw)
        return inner
    return outer


def check_instance_lock(function):
    @functools.wraps(function)
    def inner(self, context, instance, *args, **kwargs):
        if instance['locked'] and not context.is_admin:
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])
        return function(self, context, instance, *args, **kwargs)
    return inner


def policy_decorator(scope):
    """Check corresponding policy prior of wrapped method to execution"""
    def outer(func):
        @functools.wraps(func)
        def wrapped(self, context, target, *args, **kwargs):
            check_policy(context, func.__name__, target, scope)
            return func(self, context, target, *args, **kwargs)
        return wrapped
    return outer

wrap_check_policy = policy_decorator(scope='compute')
wrap_check_security_groups_policy = policy_decorator(
                                     scope='compute:security_groups')


def check_policy(context, action, target, scope='compute'):
    _action = '%s:%s' % (scope, action)
    nova.policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with the compute manager."""

    def __init__(self, image_service=None, network_api=None, volume_api=None,
                 security_group_api=None, **kwargs):
        self.image_service = (image_service or
                              glance.get_default_image_service())

        self.network_api = network_api or network.API()
        self.volume_api = volume_api or volume.API()
        self.security_group_api = security_group_api or SecurityGroupAPI()
        self.sgh = importutils.import_object(FLAGS.security_group_handler)
        self.consoleauth_rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        super(API, self).__init__(**kwargs)

    def _instance_update(self, context, instance_uuid, **kwargs):
        """Update an instance in the database using kwargs as value."""

        (old_ref, instance_ref) = self.db.instance_update_and_get_original(
                context, instance_uuid, kwargs)
        notifications.send_update(context, old_ref, instance_ref)

        return instance_ref

    def _check_injected_file_quota(self, context, injected_files):
        """Enforce quota limits on injected files.

        Raises a QuotaError if any limit is exceeded.
        """
        if injected_files is None:
            return

        # Check number of files first
        try:
            QUOTAS.limit_check(context, injected_files=len(injected_files))
        except exception.OverQuota:
            raise exception.OnsetFileLimitExceeded()

        # OK, now count path and content lengths; we're looking for
        # the max...
        max_path = 0
        max_content = 0
        for path, content in injected_files:
            max_path = max(max_path, len(path))
            max_content = max(max_content, len(content))

        try:
            QUOTAS.limit_check(context, injected_file_path_bytes=max_path,
                               injected_file_content_bytes=max_content)
        except exception.OverQuota as exc:
            # Favor path limit over content limit for reporting
            # purposes
            if 'injected_file_path_bytes' in exc.kwargs['overs']:
                raise exception.OnsetFilePathLimitExceeded()
            else:
                raise exception.OnsetFileContentLimitExceeded()

    def _check_num_instances_quota(self, context, instance_type, min_count,
                                   max_count):
        """Enforce quota limits on number of instances created."""

        # Determine requested cores and ram
        req_cores = max_count * instance_type['vcpus']
        req_ram = max_count * instance_type['memory_mb']

        # Check the quota
        try:
            reservations = QUOTAS.reserve(context, instances=max_count,
                                          cores=req_cores, ram=req_ram)
        except exception.OverQuota as exc:
            # OK, we exceeded quota; let's figure out why...
            quotas = exc.kwargs['quotas']
            usages = exc.kwargs['usages']
            overs = exc.kwargs['overs']

            headroom = dict((res, quotas[res] -
                             (usages[res]['in_use'] + usages[res]['reserved']))
                            for res in quotas.keys())

            allowed = headroom['instances']
            # Reduce 'allowed' instances in line with the cores & ram headroom
            if instance_type['vcpus']:
                allowed = min(allowed,
                              headroom['cores'] // instance_type['vcpus'])
            if instance_type['memory_mb']:
                allowed = min(allowed,
                              headroom['ram'] // instance_type['memory_mb'])

            # Convert to the appropriate exception message
            if allowed <= 0:
                msg = _("Cannot run any more instances of this type.")
                allowed = 0
            elif min_count <= allowed <= max_count:
                # We're actually OK, but still need reservations
                return self._check_num_instances_quota(context, instance_type,
                                                       min_count, allowed)
            else:
                msg = (_("Can only run %s more instances of this type.") %
                       allowed)

            resource = overs[0]
            used = quotas[resource] - headroom[resource]
            total_allowed = used + headroom[resource]
            overs = ','.join(overs)

            pid = context.project_id
            LOG.warn(_("%(overs)s quota exceeded for %(pid)s,"
                       " tried to run %(min_count)s instances. %(msg)s"),
                     locals())
            requested = dict(instances=min_count, cores=req_cores, ram=req_ram)
            raise exception.TooManyInstances(overs=overs,
                                             req=requested[resource],
                                             used=used, allowed=total_allowed,
                                             resource=resource)

        return max_count, reservations

    def _check_metadata_properties_quota(self, context, metadata=None):
        """Enforce quota limits on metadata properties."""
        if not metadata:
            metadata = {}
        num_metadata = len(metadata)
        try:
            QUOTAS.limit_check(context, metadata_items=num_metadata)
        except exception.OverQuota as exc:
            pid = context.project_id
            LOG.warn(_("Quota exceeded for %(pid)s, tried to set "
                       "%(num_metadata)s metadata properties") % locals())
            quota_metadata = exc.kwargs['quotas']['metadata_items']
            raise exception.MetadataLimitExceeded(allowed=quota_metadata)

        # Because metadata is stored in the DB, we hard-code the size limits
        # In future, we may support more variable length strings, so we act
        #  as if this is quota-controlled for forwards compatibility
        for k, v in metadata.iteritems():
            if len(k) == 0:
                msg = _("Metadata property key blank")
                LOG.warn(msg)
                raise exception.InvalidMetadata(reason=msg)
            if len(k) > 255:
                msg = _("Metadata property key greater than 255 characters")
                LOG.warn(msg)
                raise exception.InvalidMetadataSize(reason=msg)
            if len(v) > 255:
                msg = _("Metadata property value greater than 255 characters")
                LOG.warn(msg)
                raise exception.InvalidMetadataSize(reason=msg)

    def _check_requested_networks(self, context, requested_networks):
        """ Check if the networks requested belongs to the project
            and the fixed IP address for each network provided is within
            same the network block
        """
        if requested_networks is None:
            return

        self.network_api.validate_networks(context, requested_networks)

    @staticmethod
    def _handle_kernel_and_ramdisk(context, kernel_id, ramdisk_id, image,
                                   image_service):
        """Choose kernel and ramdisk appropriate for the instance.

        The kernel and ramdisk can be chosen in one of three ways:

            1. Passed in with create-instance request.

            2. Inherited from image.

            3. Forced to None by using `null_kernel` FLAG.
        """
        # Inherit from image if not specified
        if kernel_id is None:
            kernel_id = image['properties'].get('kernel_id')

        if ramdisk_id is None:
            ramdisk_id = image['properties'].get('ramdisk_id')

        # Force to None if using null_kernel
        if kernel_id == str(FLAGS.null_kernel):
            kernel_id = None
            ramdisk_id = None

        # Verify kernel and ramdisk exist (fail-fast)
        if kernel_id is not None:
            image_service.show(context, kernel_id)

        if ramdisk_id is not None:
            image_service.show(context, ramdisk_id)

        return kernel_id, ramdisk_id

    @staticmethod
    def _handle_availability_zone(availability_zone):
        # NOTE(vish): We have a legacy hack to allow admins to specify hosts
        #             via az using az:host. It might be nice to expose an
        #             api to specify specific hosts to force onto, but for
        #             now it just supports this legacy hack.
        forced_host = None
        if availability_zone and ':' in availability_zone:
            availability_zone, forced_host = availability_zone.split(':')

        if not availability_zone:
            availability_zone = FLAGS.default_schedule_zone

        return availability_zone, forced_host

    @staticmethod
    def _inherit_properties_from_image(image, auto_disk_config):
        def prop(prop_, prop_type=None):
            """Return the value of an image property."""
            value = image['properties'].get(prop_)

            if value is not None:
                if prop_type == 'bool':
                    value = utils.bool_from_str(value)

            return value

        options_from_image = {'os_type': prop('os_type'),
                              'architecture': prop('arch'),
                              'vm_mode': prop('vm_mode')}

        # If instance doesn't have auto_disk_config overridden by request, use
        # whatever the image indicates
        if auto_disk_config is None:
            auto_disk_config = prop('auto_disk_config', prop_type='bool')

        options_from_image['auto_disk_config'] = auto_disk_config
        return options_from_image

    def _create_instance(self, context, instance_type,
               image_href, kernel_id, ramdisk_id,
               min_count, max_count,
               display_name, display_description,
               key_name, key_data, security_group,
               availability_zone, user_data, metadata,
               injected_files, admin_password,
               access_ip_v4, access_ip_v6,
               requested_networks, config_drive,
               block_device_mapping, auto_disk_config,
               reservation_id=None, scheduler_hints=None):
        """Verify all the input parameters regardless of the provisioning
        strategy being performed and schedule the instance(s) for
        creation."""

        if not metadata:
            metadata = {}
        if not security_group:
            security_group = 'default'

        if not instance_type:
            instance_type = instance_types.get_default_instance_type()
        if not min_count:
            min_count = 1
        if not max_count:
            max_count = min_count

        block_device_mapping = block_device_mapping or []

        if instance_type['disabled']:
            raise exception.InstanceTypeNotFound(
                    instance_type_id=instance_type['id'])

        # Reserve quotas
        num_instances, quota_reservations = self._check_num_instances_quota(
                context, instance_type, min_count, max_count)

        # Try to create the instance
        try:
            instances = []
            instance_uuids = []

            self._check_metadata_properties_quota(context, metadata)
            self._check_injected_file_quota(context, injected_files)
            self._check_requested_networks(context, requested_networks)

            (image_service, image_id) = glance.get_remote_image_service(
                    context, image_href)
            image = image_service.show(context, image_id)

            if instance_type['memory_mb'] < int(image.get('min_ram') or 0):
                raise exception.InstanceTypeMemoryTooSmall()
            if instance_type['root_gb'] < int(image.get('min_disk') or 0):
                raise exception.InstanceTypeDiskTooSmall()

            # Handle config_drive
            config_drive_id = None
            if config_drive and config_drive is not True:
                # config_drive is volume id
                config_drive_id = config_drive
                config_drive = None

                # Ensure config_drive image exists
                image_service.show(context, config_drive_id)

            kernel_id, ramdisk_id = self._handle_kernel_and_ramdisk(
                    context, kernel_id, ramdisk_id, image, image_service)

            if key_data is None and key_name:
                key_pair = self.db.key_pair_get(context, context.user_id,
                        key_name)
                key_data = key_pair['public_key']

            if reservation_id is None:
                reservation_id = utils.generate_uid('r')

            # grab the architecture from glance
            architecture = image['properties'].get('architecture', 'Unknown')

            root_device_name = block_device.properties_root_device_name(
                image['properties'])

            availability_zone, forced_host = self._handle_availability_zone(
                    availability_zone)

            base_options = {
                'reservation_id': reservation_id,
                'image_ref': image_href,
                'kernel_id': kernel_id or '',
                'ramdisk_id': ramdisk_id or '',
                'power_state': power_state.NOSTATE,
                'vm_state': vm_states.BUILDING,
                'config_drive_id': config_drive_id or '',
                'config_drive': config_drive or '',
                'user_id': context.user_id,
                'project_id': context.project_id,
                'launch_time': time.strftime('%Y-%m-%dT%H:%M:%SZ',
                    time.gmtime()),
                'instance_type_id': instance_type['id'],
                'memory_mb': instance_type['memory_mb'],
                'vcpus': instance_type['vcpus'],
                'root_gb': instance_type['root_gb'],
                'ephemeral_gb': instance_type['ephemeral_gb'],
                'display_name': display_name,
                'display_description': display_description or '',
                'user_data': user_data,
                'key_name': key_name,
                'key_data': key_data,
                'locked': False,
                'metadata': metadata,
                'access_ip_v4': access_ip_v4,
                'access_ip_v6': access_ip_v6,
                'availability_zone': availability_zone,
                'root_device_name': root_device_name,
                'architecture': architecture,
                'progress': 0}

            if user_data:
                l = len(user_data)
                if l > MAX_USERDATA_SIZE:
                    # NOTE(mikal): user_data is stored in a text column, and
                    # the database might silently truncate if its over length.
                    raise exception.InstanceUserDataTooLarge(
                        length=l, maxsize=MAX_USERDATA_SIZE)

                try:
                    base64.decodestring(user_data)
                except base64.binascii.Error:
                    raise exception.InstanceUserDataMalformed()

            options_from_image = self._inherit_properties_from_image(
                    image, auto_disk_config)

            base_options.update(options_from_image)

            LOG.debug(_("Going to run %s instances...") % num_instances)

            filter_properties = dict(scheduler_hints=scheduler_hints)
            if context.is_admin and forced_host:
                filter_properties['force_hosts'] = [forced_host]

            for i in xrange(num_instances):
                options = base_options.copy()
                instance = self.create_db_entry_for_new_instance(
                        context, instance_type, image, options,
                        security_group, block_device_mapping)
                instances.append(instance)
                instance_uuids.append(instance['uuid'])
                self._validate_bdm(context, instance)
                # send a state update notification for the initial create to
                # show it going from non-existent to BUILDING
                notifications.send_update_with_states(context, instance, None,
                        vm_states.BUILDING, None, None, service="api")

        # In the case of any exceptions, attempt DB cleanup and rollback the
        # quota reservations.
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    for instance_uuid in instance_uuids:
                        self.db.instance_destroy(context, instance_uuid)
                finally:
                    QUOTAS.rollback(context, quota_reservations)

        # Commit the reservations
        QUOTAS.commit(context, quota_reservations)

        request_spec = {
            'image': jsonutils.to_primitive(image),
            'instance_properties': base_options,
            'instance_type': instance_type,
            'instance_uuids': instance_uuids,
            'block_device_mapping': block_device_mapping,
            'security_group': security_group,
        }

        self.scheduler_rpcapi.run_instance(context,
                request_spec=request_spec,
                admin_password=admin_password, injected_files=injected_files,
                requested_networks=requested_networks, is_first_time=True,
                filter_properties=filter_properties)

        return (instances, reservation_id)

    @staticmethod
    def _volume_size(instance_type, virtual_name):
        size = 0
        if virtual_name == 'swap':
            size = instance_type.get('swap', 0)
        elif block_device.is_ephemeral(virtual_name):
            num = block_device.ephemeral_num(virtual_name)

            # TODO(yamahata): ephemeralN where N > 0
            # Only ephemeral0 is allowed for now because InstanceTypes
            # table only allows single local disk, ephemeral_gb.
            # In order to enhance it, we need to add a new columns to
            # instance_types table.
            if num > 0:
                return 0

            size = instance_type.get('ephemeral_gb')

        return size

    def _update_image_block_device_mapping(self, elevated_context,
                                           instance_type, instance_uuid,
                                           mappings):
        """tell vm driver to create ephemeral/swap device at boot time by
        updating BlockDeviceMapping
        """
        for bdm in block_device.mappings_prepend_dev(mappings):
            LOG.debug(_("bdm %s"), bdm, instance_uuid=instance_uuid)

            virtual_name = bdm['virtual']
            if virtual_name == 'ami' or virtual_name == 'root':
                continue

            if not block_device.is_swap_or_ephemeral(virtual_name):
                continue

            size = self._volume_size(instance_type, virtual_name)
            if size == 0:
                continue

            values = {
                'instance_uuid': instance_uuid,
                'device_name': bdm['device'],
                'virtual_name': virtual_name,
                'volume_size': size}
            self.db.block_device_mapping_update_or_create(elevated_context,
                                                          values)

    def _update_block_device_mapping(self, elevated_context,
                                     instance_type, instance_uuid,
                                     block_device_mapping):
        """tell vm driver to attach volume at boot time by updating
        BlockDeviceMapping
        """
        LOG.debug(_("block_device_mapping %s"), block_device_mapping,
                  instance_uuid=instance_uuid)
        for bdm in block_device_mapping:
            assert 'device_name' in bdm

            values = {'instance_uuid': instance_uuid}
            for key in ('device_name', 'delete_on_termination', 'virtual_name',
                        'snapshot_id', 'volume_id', 'volume_size',
                        'no_device'):
                values[key] = bdm.get(key)

            virtual_name = bdm.get('virtual_name')
            if (virtual_name is not None and
                block_device.is_swap_or_ephemeral(virtual_name)):
                size = self._volume_size(instance_type, virtual_name)
                if size == 0:
                    continue
                values['volume_size'] = size

            # NOTE(yamahata): NoDevice eliminates devices defined in image
            #                 files by command line option.
            #                 (--block-device-mapping)
            if virtual_name == 'NoDevice':
                values['no_device'] = True
                for k in ('delete_on_termination', 'virtual_name',
                          'snapshot_id', 'volume_id', 'volume_size'):
                    values[k] = None

            self.db.block_device_mapping_update_or_create(elevated_context,
                                                          values)

    def _validate_bdm(self, context, instance):
        for bdm in self.db.block_device_mapping_get_all_by_instance(
                context, instance['uuid']):
            # NOTE(vish): For now, just make sure the volumes are accessible.
            snapshot_id = bdm.get('snapshot_id')
            volume_id = bdm.get('volume_id')
            if volume_id is not None:
                try:
                    self.volume_api.get(context, volume_id)
                except Exception:
                    raise exception.InvalidBDMVolume(id=volume_id)
            elif snapshot_id is not None:
                try:
                    self.volume_api.get_snapshot(context, snapshot_id)
                except Exception:
                    raise exception.InvalidBDMSnapshot(id=snapshot_id)

    def _populate_instance_for_bdm(self, context, instance, instance_type,
            image, block_device_mapping):
        """Populate instance block device mapping information."""
        # FIXME(comstud): Why do the block_device_mapping DB calls
        # require elevated context?
        elevated = context.elevated()
        instance_uuid = instance['uuid']
        mappings = image['properties'].get('mappings', [])
        if mappings:
            self._update_image_block_device_mapping(elevated,
                    instance_type, instance_uuid, mappings)

        image_bdm = image['properties'].get('block_device_mapping', [])
        for mapping in (image_bdm, block_device_mapping):
            if not mapping:
                continue
            self._update_block_device_mapping(elevated,
                    instance_type, instance_uuid, mapping)

    def _populate_instance_shutdown_terminate(self, instance, image,
                                              block_device_mapping):
        """Populate instance shutdown_terminate information."""
        if (block_device_mapping or
            image['properties'].get('mappings') or
            image['properties'].get('block_device_mapping')):
            instance['shutdown_terminate'] = False

    def _populate_instance_names(self, instance):
        """Populate instance display_name and hostname."""
        display_name = instance.get('display_name')
        hostname = instance.get('hostname')

        if display_name is None:
            display_name = self._default_display_name(instance['uuid'])
            instance['display_name'] = display_name
        if hostname is None:
            hostname = display_name
        instance['hostname'] = utils.sanitize_hostname(hostname)

    def _default_display_name(self, instance_uuid):
        return "Server %s" % instance_uuid

    def _populate_instance_for_create(self, base_options, image,
            security_groups):
        """Build the beginning of a new instance."""

        instance = base_options
        if not instance.get('uuid'):
            # Generate the instance_uuid here so we can use it
            # for additional setup before creating the DB entry.
            instance['uuid'] = str(utils.gen_uuid())

        instance['launch_index'] = 0
        instance['vm_state'] = vm_states.BUILDING
        instance['task_state'] = task_states.SCHEDULING
        instance['architecture'] = image['properties'].get('architecture')
        instance['info_cache'] = {'network_info': '[]'}

        # Store image properties so we can use them later
        # (for notifications, etc).  Only store what we can.
        instance.setdefault('system_metadata', {})
        for key, value in image['properties'].iteritems():
            new_value = str(value)[:255]
            instance['system_metadata']['image_%s' % key] = new_value

        # Keep a record of the original base image that this
        # image's instance is derived from:
        base_image_ref = image['properties'].get('base_image_ref')
        if not base_image_ref:
            # base image ref property not previously set through a snapshot.
            # default to using the image ref as the base:
            base_image_ref = base_options['image_ref']

        instance['system_metadata']['image_base_image_ref'] = base_image_ref

        # Use 'default' security_group if none specified.
        if security_groups is None:
            security_groups = ['default']
        elif not isinstance(security_groups, list):
            security_groups = [security_groups]
        instance['security_groups'] = security_groups

        return instance

    #NOTE(bcwaldon): No policy check since this is only used by scheduler and
    # the compute api. That should probably be cleaned up, though.
    def create_db_entry_for_new_instance(self, context, instance_type, image,
            base_options, security_group, block_device_mapping):
        """Create an entry in the DB for this new instance,
        including any related table updates (such as security group,
        etc).

        This is called by the scheduler after a location for the
        instance has been determined.
        """
        instance = self._populate_instance_for_create(base_options,
                image, security_group)

        self._populate_instance_names(instance)

        self._populate_instance_shutdown_terminate(instance, image,
                                                   block_device_mapping)

        # ensure_default security group is called before the instance
        # is created so the creation of the default security group is
        # proxied to the sgh.
        self.security_group_api.ensure_default(context)
        instance = self.db.instance_create(context, instance)

        self._populate_instance_for_bdm(context, instance,
                instance_type, image, block_device_mapping)

        return instance

    def _check_create_policies(self, context, availability_zone,
            requested_networks, block_device_mapping):
        """Check policies for create()."""
        target = {'project_id': context.project_id,
                  'user_id': context.user_id,
                  'availability_zone': availability_zone}
        check_policy(context, 'create', target)

        if requested_networks:
            check_policy(context, 'create:attach_network', target)

        if block_device_mapping:
            check_policy(context, 'create:attach_volume', target)

    def create(self, context, instance_type,
               image_href, kernel_id=None, ramdisk_id=None,
               min_count=None, max_count=None,
               display_name=None, display_description=None,
               key_name=None, key_data=None, security_group=None,
               availability_zone=None, user_data=None, metadata=None,
               injected_files=None, admin_password=None,
               block_device_mapping=None, access_ip_v4=None,
               access_ip_v6=None, requested_networks=None, config_drive=None,
               auto_disk_config=None, scheduler_hints=None):
        """
        Provision instances, sending instance information to the
        scheduler.  The scheduler will determine where the instance(s)
        go and will handle creating the DB entries.

        Returns a tuple of (instances, reservation_id)
        """

        self._check_create_policies(context, availability_zone,
                requested_networks, block_device_mapping)

        return self._create_instance(
                               context, instance_type,
                               image_href, kernel_id, ramdisk_id,
                               min_count, max_count,
                               display_name, display_description,
                               key_name, key_data, security_group,
                               availability_zone, user_data, metadata,
                               injected_files, admin_password,
                               access_ip_v4, access_ip_v6,
                               requested_networks, config_drive,
                               block_device_mapping, auto_disk_config,
                               scheduler_hints=scheduler_hints)

    def trigger_provider_fw_rules_refresh(self, context):
        """Called when a rule is added/removed from a provider firewall"""

        hosts = [x['host'] for (x, idx)
                           in self.db.service_get_all_compute_sorted(context)]
        for host in hosts:
            self.compute_rpcapi.refresh_provider_fw_rules(context, host)

    @wrap_check_policy
    def update(self, context, instance, **kwargs):
        """Updates the instance in the datastore.

        :param context: The security context
        :param instance: The instance to update
        :param kwargs: All additional keyword args are treated
                       as data fields of the instance to be
                       updated

        :returns: None
        """
        _, updated = self._update(context, instance, **kwargs)
        return updated

    def _update(self, context, instance, **kwargs):
        # Update the instance record and send a state update notification
        # if task or vm state changed
        old_ref, instance_ref = self.db.instance_update_and_get_original(
                context, instance['uuid'], kwargs)
        notifications.send_update(context, old_ref, instance_ref,
                service="api")

        return dict(old_ref.iteritems()), dict(instance_ref.iteritems())

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=None, task_state=None)
    def soft_delete(self, context, instance):
        """Terminate an instance."""
        LOG.debug(_('Going to try to soft delete instance'),
                  instance=instance)

        if instance['disable_terminate']:
            return

        # NOTE(jerdfelt): The compute daemon handles reclaiming instances
        # that are in soft delete. If there is no host assigned, there is
        # no daemon to reclaim, so delete it immediately.
        if instance['host']:
            instance = self.update(context, instance,
                                   task_state=task_states.POWERING_OFF,
                                   expected_task_state=None,
                                   deleted_at=timeutils.utcnow())

            self.compute_rpcapi.power_off_instance(context, instance)
        else:
            LOG.warning(_('No host for instance, deleting immediately'),
                        instance=instance)
            try:
                self.db.instance_destroy(context, instance['uuid'])
            except exception.InstanceNotFound:
                # NOTE(comstud): Race condition.  Instance already gone.
                pass

    def _delete(self, context, instance):
        host = instance['host']
        reservations = None
        try:

            #Note(maoy): no expected_task_state needs to be set
            old, updated = self._update(context,
                                        instance,
                                        task_state=task_states.DELETING,
                                        progress=0)

            # Avoid double-counting the quota usage reduction
            # where delete is already in progress
            if old['task_state'] != task_states.DELETING:
                reservations = QUOTAS.reserve(context,
                                              instances=-1,
                                              cores=-instance['vcpus'],
                                              ram=-instance['memory_mb'])

            if not host:
                # Just update database, nothing else we can do
                constraint = self.db.constraint(host=self.db.equal_any(host))
                try:
                    result = self.db.instance_destroy(context,
                                                      instance['uuid'],
                                                      constraint)
                    if reservations:
                        QUOTAS.commit(context, reservations)
                    return result
                except exception.ConstraintNotMet:
                    # Refresh to get new host information
                    instance = self.get(context, instance['uuid'])

            if instance['vm_state'] == vm_states.RESIZED:
                # If in the middle of a resize, use confirm_resize to
                # ensure the original instance is cleaned up too
                get_migration = self.db.migration_get_by_instance_and_status
                try:
                    migration_ref = get_migration(context.elevated(),
                            instance['uuid'], 'finished')
                except exception.MigrationNotFoundByStatus:
                    migration_ref = None
                if migration_ref:
                    src_host = migration_ref['source_compute']
                    # Call since this can race with the terminate_instance.
                    # The resize is done but awaiting confirmation/reversion,
                    # so there are two cases:
                    # 1. up-resize: here -instance['vcpus'/'memory_mb'] match
                    #    the quota usages accounted for this instance,
                    #    so no further quota adjustment is needed
                    # 2. down-resize: here -instance['vcpus'/'memory_mb'] are
                    #    shy by delta(old, new) from the quota usages accounted
                    #    for this instance, so we must adjust
                    deltas = self._downsize_quota_delta(context,
                                                        migration_ref)
                    downsize_reservations = self._reserve_quota_delta(context,
                                                                      deltas)
                    self.compute_rpcapi.confirm_resize(context.elevated(),
                            instance, migration_ref['id'],
                            host=src_host, cast=False,
                            reservations=downsize_reservations)

            is_up = False
            bdms = self.db.block_device_mapping_get_all_by_instance(
                    context, instance["uuid"])
            #Note(jogo): db allows for multiple compute services per host
            try:
                services = self.db.service_get_all_compute_by_host(
                        context.elevated(), instance['host'])
            except exception.ComputeHostNotFound:
                services = []
            for service in services:
                if utils.service_is_up(service):
                    is_up = True
                    self.compute_rpcapi.terminate_instance(context, instance)
                    break
            if not is_up:
                # If compute node isn't up, just delete from DB
                self._local_delete(context, instance, bdms)
            if reservations:
                QUOTAS.commit(context, reservations)
        except exception.InstanceNotFound:
            # NOTE(comstud): Race condition. Instance already gone.
            if reservations:
                QUOTAS.rollback(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                if reservations:
                    QUOTAS.rollback(context, reservations)

    def _local_delete(self, context, instance, bdms):
        LOG.warning(_('host for instance is down, deleting from '
                      'database'), instance=instance)
        instance_uuid = instance['uuid']
        self.db.instance_info_cache_delete(context, instance_uuid)
        compute_utils.notify_about_instance_usage(
            context, instance, "delete.start")

        elevated = context.elevated()
        self.network_api.deallocate_for_instance(elevated,
                instance)
        system_meta = self.db.instance_system_metadata_get(context,
                instance_uuid)

        # cleanup volumes
        for bdm in bdms:
            if bdm['volume_id']:
                volume = self.volume_api.get(context, bdm['volume_id'])
                # NOTE(vish): We don't have access to correct volume
                #             connector info, so just pass a fake
                #             connector. This can be improved when we
                #             expose get_volume_connector to rpc.
                connector = {'ip': '127.0.0.1', 'initiator': 'iqn.fake'}
                self.volume_api.terminate_connection(context,
                                                     volume,
                                                     connector)
                self.volume_api.detach(elevated, volume)
                if bdm['delete_on_termination']:
                    self.volume_api.delete(context, volume)
            self.db.block_device_mapping_destroy(context, bdm['id'])
        instance = self._instance_update(context,
                                         instance_uuid,
                                         vm_state=vm_states.DELETED,
                                         task_state=None,
                                         terminated_at=timeutils.utcnow())
        self.db.instance_destroy(context, instance_uuid)
        compute_utils.notify_about_instance_usage(
            context, instance, "delete.end", system_metadata=system_meta)

    # NOTE(maoy): we allow delete to be called no matter what vm_state says.
    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=None, task_state=None)
    def delete(self, context, instance):
        """Terminate an instance."""
        LOG.debug(_("Going to try to terminate instance"), instance=instance)

        if instance['disable_terminate']:
            return

        self._delete(context, instance)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.SOFT_DELETED])
    def restore(self, context, instance):
        """Restore a previously deleted (but not reclaimed) instance."""
        if instance['host']:
            instance = self.update(context, instance,
                        task_state=task_states.POWERING_ON,
                        expected_task_state=None,
                        deleted_at=None)
            self.compute_rpcapi.power_on_instance(context, instance)
        else:
            self.update(context,
                        instance,
                        vm_state=vm_states.ACTIVE,
                        task_state=None,
                        expected_task_state=None,
                        deleted_at=None)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.SOFT_DELETED])
    def force_delete(self, context, instance):
        """Force delete a previously deleted (but not reclaimed) instance."""
        self._delete(context, instance)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.RESCUED,
                                    vm_states.ERROR, vm_states.STOPPED],
                          task_state=[None])
    def stop(self, context, instance, do_cast=True):
        """Stop an instance."""
        LOG.debug(_("Going to try to stop instance"), instance=instance)

        instance = self.update(context, instance,
                    task_state=task_states.STOPPING,
                    expected_task_state=None,
                    progress=0)

        self.compute_rpcapi.stop_instance(context, instance, cast=do_cast)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.STOPPED])
    def start(self, context, instance):
        """Start an instance."""
        LOG.debug(_("Going to try to start instance"), instance=instance)

        instance = self.update(context, instance,
                               task_state=task_states.STARTING,
                               expected_task_state=None)

        # TODO(yamahata): injected_files isn't supported right now.
        #                 It is used only for osapi. not for ec2 api.
        #                 availability_zone isn't used by run_instance.
        self.compute_rpcapi.start_instance(context, instance)

    #NOTE(bcwaldon): no policy check here since it should be rolled in to
    # search_opts in get_all
    def get_active_by_window(self, context, begin, end=None, project_id=None):
        """Get instances that were continuously active over a window."""
        return self.db.instance_get_active_by_window(context, begin, end,
                                                     project_id)

    #NOTE(bcwaldon): this doesn't really belong in this class
    def get_instance_type(self, context, instance_type_id):
        """Get an instance type by instance type id."""
        return instance_types.get_instance_type(instance_type_id, ctxt=context)

    def get(self, context, instance_id):
        """Get a single instance with the given instance_id."""
        # NOTE(ameade): we still need to support integer ids for ec2
        if utils.is_uuid_like(instance_id):
            instance = self.db.instance_get_by_uuid(context, instance_id)
        else:
            instance = self.db.instance_get(context, instance_id)

        check_policy(context, 'get', instance)

        inst = dict(instance.iteritems())
        # NOTE(comstud): Doesn't get returned with iteritems
        inst['name'] = instance['name']
        return inst

    def get_all(self, context, search_opts=None, sort_key='created_at',
                sort_dir='desc', limit=None, marker=None):
        """Get all instances filtered by one of the given parameters.

        If there is no filter and the context is an admin, it will retrieve
        all instances in the system.

        Deleted instances will be returned by default, unless there is a
        search option that says otherwise.

        The results will be returned sorted in the order specified by the
        'sort_dir' parameter using the key specified in the 'sort_key'
        parameter.
        """

        #TODO(bcwaldon): determine the best argument for target here
        target = {
            'project_id': context.project_id,
            'user_id': context.user_id,
        }

        check_policy(context, "get_all", target)

        if search_opts is None:
            search_opts = {}

        LOG.debug(_("Searching by: %s") % str(search_opts))

        # Fixups for the DB call
        filters = {}

        def _remap_flavor_filter(flavor_id):
            try:
                instance_type = instance_types.get_instance_type_by_flavor_id(
                        flavor_id)
            except exception.FlavorNotFound:
                raise ValueError()

            filters['instance_type_id'] = instance_type['id']

        def _remap_fixed_ip_filter(fixed_ip):
            # Turn fixed_ip into a regexp match. Since '.' matches
            # any character, we need to use regexp escaping for it.
            filters['ip'] = '^%s$' % fixed_ip.replace('.', '\\.')

        # search_option to filter_name mapping.
        filter_mapping = {
                'image': 'image_ref',
                'name': 'display_name',
                'tenant_id': 'project_id',
                'flavor': _remap_flavor_filter,
                'fixed_ip': _remap_fixed_ip_filter}

        # copy from search_opts, doing various remappings as necessary
        for opt, value in search_opts.iteritems():
            # Do remappings.
            # Values not in the filter_mapping table are copied as-is.
            # If remapping is None, option is not copied
            # If the remapping is a string, it is the filter_name to use
            try:
                remap_object = filter_mapping[opt]
            except KeyError:
                filters[opt] = value
            else:
                # Remaps are strings to translate to, or functions to call
                # to do the translating as defined by the table above.
                if isinstance(remap_object, basestring):
                    filters[remap_object] = value
                else:
                    try:
                        remap_object(value)

                    # We already know we can't match the filter, so
                    # return an empty list
                    except ValueError:
                        return []

        inst_models = self._get_instances_by_filters(context, filters,
                                                     sort_key, sort_dir,
                                                     limit=limit,
                                                     marker=marker)

        # Convert the models to dictionaries
        instances = []
        for inst_model in inst_models:
            instance = dict(inst_model.iteritems())
            # NOTE(comstud): Doesn't get returned by iteritems
            instance['name'] = inst_model['name']
            instances.append(instance)

        return instances

    def _get_instances_by_filters(self, context, filters,
                                  sort_key, sort_dir,
                                  limit=None,
                                  marker=None):
        if 'ip6' in filters or 'ip' in filters:
            res = self.network_api.get_instance_uuids_by_ip_filter(context,
                                                                   filters)
            # NOTE(jkoelker) It is possible that we will get the same
            #                instance uuid twice (one for ipv4 and ipv6)
            uuids = set([r['instance_uuid'] for r in res])
            filters['uuid'] = uuids

        return self.db.instance_get_all_by_filters(context, filters,
                                                   sort_key, sort_dir,
                                                   limit=limit, marker=marker)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED])
    def backup(self, context, instance, name, backup_type, rotation,
               extra_properties=None):
        """Backup the given instance

        :param instance: nova.db.sqlalchemy.models.Instance
        :param name: name of the backup or snapshot
            name = backup_type  # daily backups are called 'daily'
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        :param extra_properties: dict of extra image properties to include
        """
        recv_meta = self._create_image(context, instance, name, 'backup',
                            backup_type=backup_type, rotation=rotation,
                            extra_properties=extra_properties)
        return recv_meta

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED])
    def snapshot(self, context, instance, name, extra_properties=None):
        """Snapshot the given instance.

        :param instance: nova.db.sqlalchemy.models.Instance
        :param name: name of the backup or snapshot
        :param extra_properties: dict of extra image properties to include

        :returns: A dict containing image metadata
        """
        return self._create_image(context, instance, name, 'snapshot',
                                  extra_properties=extra_properties)

    def _create_image(self, context, instance, name, image_type,
                      backup_type=None, rotation=None, extra_properties=None):
        """Create snapshot or backup for an instance on this host.

        :param context: security context
        :param instance: nova.db.sqlalchemy.models.Instance
        :param name: string for name of the snapshot
        :param image_type: snapshot | backup
        :param backup_type: daily | weekly
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        :param extra_properties: dict of extra image properties to include

        """
        instance_uuid = instance['uuid']

        if image_type == "snapshot":
            task_state = task_states.IMAGE_SNAPSHOT
        elif image_type == "backup":
            task_state = task_states.IMAGE_BACKUP
        else:
            raise Exception(_('Image type not recognized %s') % image_type)

        properties = {
            'instance_uuid': instance_uuid,
            'user_id': str(context.user_id),
            'image_type': image_type,
        }

        # Persist base image ref as a Glance image property
        system_meta = self.db.instance_system_metadata_get(
                context, instance_uuid)
        base_image_ref = system_meta.get('image_base_image_ref')
        if base_image_ref:
            properties['base_image_ref'] = base_image_ref

        sent_meta = {'name': name, 'is_public': False}

        if image_type == 'backup':
            properties['backup_type'] = backup_type

        elif image_type == 'snapshot':
            min_ram, min_disk = self._get_minram_mindisk_params(context,
                                                                instance)
            if min_ram is not None:
                sent_meta['min_ram'] = min_ram
            if min_disk is not None:
                sent_meta['min_disk'] = min_disk

        properties.update(extra_properties or {})
        sent_meta['properties'] = properties

        recv_meta = self.image_service.create(context, sent_meta)

        # change instance state and notify
        old_vm_state = instance["vm_state"]
        old_task_state = instance["task_state"]

        self.db.instance_test_and_set(
                context, instance_uuid, 'task_state', [None], task_state)

        notifications.send_update_with_states(context, instance, old_vm_state,
                instance["vm_state"], old_task_state, instance["task_state"],
                service="api", verify_states=True)

        self.compute_rpcapi.snapshot_instance(context, instance=instance,
                image_id=recv_meta['id'], image_type=image_type,
                backup_type=backup_type, rotation=rotation)
        return recv_meta

    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED])
    def snapshot_volume_backed(self, context, instance, image_meta, name,
                               extra_properties=None):
        """Snapshot the given volume-backed instance.

        :param instance: nova.db.sqlalchemy.models.Instance
        :param image_meta: metadata for the new image
        :param name: name of the backup or snapshot
        :param extra_properties: dict of extra image properties to include

        :returns: the new image metadata
        """
        image_meta['name'] = name
        properties = image_meta['properties']
        if instance['root_device_name']:
            properties['root_device_name'] = instance['root_device_name']
        properties.update(extra_properties or {})

        bdms = self.get_instance_bdms(context, instance)

        mapping = []
        for bdm in bdms:
            if bdm.no_device:
                continue
            m = {}
            for attr in ('device_name', 'snapshot_id', 'volume_id',
                         'volume_size', 'delete_on_termination', 'no_device',
                         'virtual_name'):
                val = getattr(bdm, attr)
                if val is not None:
                    m[attr] = val

            volume_id = m.get('volume_id')
            if volume_id:
                # create snapshot based on volume_id
                volume = self.volume_api.get(context, volume_id)
                # NOTE(yamahata): Should we wait for snapshot creation?
                #                 Linux LVM snapshot creation completes in
                #                 short time, it doesn't matter for now.
                name = _('snapshot for %s') % image_meta['name']
                snapshot = self.volume_api.create_snapshot_force(
                    context, volume, name, volume['display_description'])
                m['snapshot_id'] = snapshot['id']
                del m['volume_id']

            if m:
                mapping.append(m)

        for m in block_device.mappings_prepend_dev(properties.get('mappings',
                                                                  [])):
            virtual_name = m['virtual']
            if virtual_name in ('ami', 'root'):
                continue

            assert block_device.is_swap_or_ephemeral(virtual_name)
            device_name = m['device']
            if device_name in [b['device_name'] for b in mapping
                               if not b.get('no_device', False)]:
                continue

            # NOTE(yamahata): swap and ephemeral devices are specified in
            #                 AMI, but disabled for this instance by user.
            #                 So disable those device by no_device.
            mapping.append({'device_name': device_name, 'no_device': True})

        if mapping:
            properties['block_device_mapping'] = mapping

        for attr in ('status', 'location', 'id'):
            image_meta.pop(attr, None)

        # the new image is simply a bucket of properties (particularly the
        # block device mapping, kernel and ramdisk IDs) with no image data,
        # hence the zero size
        image_meta['size'] = 0

        return self.image_service.create(context, image_meta, data='')

    def _get_minram_mindisk_params(self, context, instance):
        try:
            #try to get source image of the instance
            orig_image = self.image_service.show(context,
                                                 instance['image_ref'])
        except exception.ImageNotFound:
            return None, None

        #disk format of vhd is non-shrinkable
        if orig_image.get('disk_format') == 'vhd':
            min_ram = instance['instance_type']['memory_mb']
            min_disk = instance['instance_type']['root_gb']
        else:
            #set new image values to the original image values
            min_ram = orig_image.get('min_ram')
            min_disk = orig_image.get('min_disk')

        return min_ram, min_disk

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.RESCUED],
                          task_state=[None, task_states.REBOOTING])
    def reboot(self, context, instance, reboot_type):
        """Reboot the given instance."""
        if (reboot_type == 'SOFT' and
            instance['task_state'] == task_states.REBOOTING):
            raise exception.InstanceInvalidState(
                attr='task_state',
                instance_uuid=instance['uuid'],
                state=instance['task_state'])
        state = {'SOFT': task_states.REBOOTING,
                 'HARD': task_states.REBOOTING_HARD}[reboot_type]
        instance = self.update(context, instance, vm_state=vm_states.ACTIVE,
                               task_state=state,
                               expected_task_state=[None,
                                                    task_states.REBOOTING])
        self.compute_rpcapi.reboot_instance(context, instance=instance,
                reboot_type=reboot_type)

    def _get_image(self, context, image_href):
        """Throws an ImageNotFound exception if image_href does not exist."""
        (image_service, image_id) = glance.get_remote_image_service(context,
                                                                 image_href)
        return image_service.show(context, image_id)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED],
                          task_state=[None])
    def rebuild(self, context, instance, image_href, admin_password, **kwargs):
        """Rebuild the given instance with the provided attributes."""

        orig_image_ref = instance['image_ref']
        image = self._get_image(context, image_href)

        files_to_inject = kwargs.pop('files_to_inject', [])
        self._check_injected_file_quota(context, files_to_inject)

        metadata = kwargs.get('metadata', {})
        self._check_metadata_properties_quota(context, metadata)

        instance_type = instance['instance_type']
        if instance_type['memory_mb'] < int(image.get('min_ram') or 0):
            raise exception.InstanceTypeMemoryTooSmall()
        if instance_type['root_gb'] < int(image.get('min_disk') or 0):
            raise exception.InstanceTypeDiskTooSmall()

        (image_service, image_id) = glance.get_remote_image_service(context,
                                                                 image_href)
        image = image_service.show(context, image_id)
        kernel_id, ramdisk_id = self._handle_kernel_and_ramdisk(
                context, None, None, image, image_service)

        def _reset_image_metadata():
            """
            Remove old image properties that we're storing as instance
            system metadata.  These properties start with 'image_'.
            Then add the properites for the new image.
            """

            # FIXME(comstud): There's a race condition here in that
            # if the system_metadata for this instance is updated
            # after we do the get and before we update.. those other
            # updates will be lost. Since this problem exists in a lot
            # of other places, I think it should be addressed in a DB
            # layer overhaul.
            sys_metadata = self.db.instance_system_metadata_get(context,
                    instance['uuid'])
            orig_sys_metadata = dict(sys_metadata)
            # Remove the old keys
            for key in sys_metadata.keys():
                if key.startswith('image_'):
                    del sys_metadata[key]
            # Add the new ones
            for key, value in image['properties'].iteritems():
                new_value = str(value)[:255]
                sys_metadata['image_%s' % key] = new_value
            self.db.instance_system_metadata_update(context,
                    instance['uuid'], sys_metadata, True)
            return orig_sys_metadata

        instance = self.update(context, instance,
                               task_state=task_states.REBUILDING,
                               expected_task_state=None,
                               # Unfortunately we need to set image_ref early,
                               # so API users can see it.
                               image_ref=image_href, kernel_id=kernel_id or "",
                               ramdisk_id=ramdisk_id or "",
                               progress=0, **kwargs)

        # On a rebuild, since we're potentially changing images, we need to
        # wipe out the old image properties that we're storing as instance
        # system metadata... and copy in the properties for the new image.
        orig_sys_metadata = _reset_image_metadata()

        self.compute_rpcapi.rebuild_instance(context, instance=instance,
                new_pass=admin_password, injected_files=files_to_inject,
                image_ref=image_href, orig_image_ref=orig_image_ref,
                orig_sys_metadata=orig_sys_metadata)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.RESIZED])
    def revert_resize(self, context, instance):
        """Reverts a resize, deleting the 'new' instance in the process."""
        context = context.elevated()
        migration_ref = self.db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'finished')
        if not migration_ref:
            raise exception.MigrationNotFoundByStatus(
                    instance_id=instance['uuid'], status='finished')

        # reverse quota reservation for increased resource usage
        deltas = self._reverse_upsize_quota_delta(context, migration_ref)
        reservations = self._reserve_quota_delta(context, deltas)

        instance = self.update(context, instance,
                               task_state=task_states.RESIZE_REVERTING,
                               expected_task_state=None)

        self.compute_rpcapi.revert_resize(context,
                instance=instance, migration_id=migration_ref['id'],
                host=migration_ref['dest_compute'], reservations=reservations)

        self.db.migration_update(context, migration_ref['id'],
                                 {'status': 'reverted'})

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.RESIZED])
    def confirm_resize(self, context, instance):
        """Confirms a migration/resize and deletes the 'old' instance."""
        context = context.elevated()
        migration_ref = self.db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'finished')
        if not migration_ref:
            raise exception.MigrationNotFoundByStatus(
                    instance_id=instance['uuid'], status='finished')

        # reserve quota only for any decrease in resource usage
        deltas = self._downsize_quota_delta(context, migration_ref)
        reservations = self._reserve_quota_delta(context, deltas)

        instance = self.update(context, instance, vm_state=vm_states.ACTIVE,
                               task_state=None,
                               expected_task_state=None)

        self.compute_rpcapi.confirm_resize(context,
                instance=instance, migration_id=migration_ref['id'],
                host=migration_ref['source_compute'],
                reservations=reservations)

        self.db.migration_update(context, migration_ref['id'],
                {'status': 'confirmed'})

    @staticmethod
    def _resize_quota_delta(context, new_instance_type,
                            old_instance_type, sense, compare):
        """
        Calculate any quota adjustment required at a particular point
        in the resize cycle.

        :param context: the request context
        :param new_instance_type: the target instance type
        :param old_instance_type: the original instance type
        :param sense: the sense of the adjustment, 1 indicates a
                      forward adjustment, whereas -1 indicates a
                      reversal of a prior adjustment
        :param compare: the direction of the comparison, 1 indicates
                        we're checking for positive deltas, whereas
                        -1 indicates negative deltas
        """
        def _quota_delta(resource):
            return sense * (new_instance_type[resource] -
                            old_instance_type[resource])

        deltas = {}
        if compare * _quota_delta('vcpus') > 0:
            deltas['cores'] = _quota_delta('vcpus')
        if compare * _quota_delta('memory_mb') > 0:
            deltas['ram'] = _quota_delta('memory_mb')

        return deltas

    @staticmethod
    def _upsize_quota_delta(context, new_instance_type, old_instance_type):
        """
        Calculate deltas required to adjust quota for an instance upsize.
        """
        return API._resize_quota_delta(context, new_instance_type,
                                       old_instance_type, 1, 1)

    @staticmethod
    def _reverse_upsize_quota_delta(context, migration_ref):
        """
        Calculate deltas required to reverse a prior upsizing
        quota adjustment.
        """
        old_instance_type = instance_types.get_instance_type(
            migration_ref['old_instance_type_id'])
        new_instance_type = instance_types.get_instance_type(
            migration_ref['new_instance_type_id'])

        return API._resize_quota_delta(context, new_instance_type,
                                       old_instance_type, -1, -1)

    @staticmethod
    def _downsize_quota_delta(context, migration_ref):
        """
        Calculate deltas required to adjust quota for an instance downsize.
        """
        old_instance_type = instance_types.get_instance_type(
            migration_ref['old_instance_type_id'])
        new_instance_type = instance_types.get_instance_type(
            migration_ref['new_instance_type_id'])

        return API._resize_quota_delta(context, new_instance_type,
                                       old_instance_type, 1, -1)

    @staticmethod
    def _reserve_quota_delta(context, deltas):
        return QUOTAS.reserve(context, **deltas) if deltas else None

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED],
                          task_state=[None])
    def resize(self, context, instance, flavor_id=None, **kwargs):
        """Resize (ie, migrate) a running instance.

        If flavor_id is None, the process is considered a migration, keeping
        the original flavor_id. If flavor_id is not None, the instance should
        be migrated to a new host and resized to the new flavor_id.
        """
        current_instance_type = instance['instance_type']

        # If flavor_id is not provided, only migrate the instance.
        if not flavor_id:
            LOG.debug(_("flavor_id is None. Assuming migration."),
                      instance=instance)
            new_instance_type = current_instance_type
        else:
            new_instance_type = instance_types.get_instance_type_by_flavor_id(
                    flavor_id)

        current_instance_type_name = current_instance_type['name']
        new_instance_type_name = new_instance_type['name']
        LOG.debug(_("Old instance type %(current_instance_type_name)s, "
                    " new instance type %(new_instance_type_name)s"),
                  locals(), instance=instance)

        # FIXME(sirp): both of these should raise InstanceTypeNotFound instead
        if not new_instance_type:
            raise exception.FlavorNotFound(flavor_id=flavor_id)

        same_instance_type = (current_instance_type['id'] ==
                              new_instance_type['id'])

        # NOTE(sirp): We don't want to force a customer to change their flavor
        # when Ops is migrating off of a failed host.
        if new_instance_type['disabled'] and not same_instance_type:
            raise exception.FlavorNotFound(flavor_id=flavor_id)

        # NOTE(markwash): look up the image early to avoid auth problems later
        image = self.image_service.show(context, instance['image_ref'])

        if same_instance_type and flavor_id:
            raise exception.CannotResizeToSameFlavor()

        # ensure there is sufficient headroom for upsizes
        deltas = self._upsize_quota_delta(context, new_instance_type,
                                          current_instance_type)
        try:
            reservations = self._reserve_quota_delta(context, deltas)
        except exception.OverQuota as exc:
            quotas = exc.kwargs['quotas']
            usages = exc.kwargs['usages']
            overs = exc.kwargs['overs']

            headroom = dict((res, quotas[res] -
                             (usages[res]['in_use'] + usages[res]['reserved']))
                            for res in quotas.keys())

            resource = overs[0]
            used = quotas[resource] - headroom[resource]
            total_allowed = used + headroom[resource]
            overs = ','.join(overs)

            pid = context.project_id
            LOG.warn(_("%(overs)s quota exceeded for %(pid)s,"
                       " tried to resize instance. %(msg)s"), locals())
            raise exception.TooManyInstances(overs=overs,
                                             req=deltas[resource],
                                             used=used, allowed=total_allowed,
                                             resource=resource)

        instance = self.update(context, instance,
                task_state=task_states.RESIZE_PREP,
                expected_task_state=None,
                progress=0, **kwargs)

        request_spec = {
                'instance_type': new_instance_type,
                'instance_uuids': [instance['uuid']],
                'instance_properties': instance}

        filter_properties = {'ignore_hosts': []}

        if not FLAGS.allow_resize_to_same_host:
            filter_properties['ignore_hosts'].append(instance['host'])

        args = {
            "instance": instance,
            "instance_type": new_instance_type,
            "image": image,
            "request_spec": jsonutils.to_primitive(request_spec),
            "filter_properties": filter_properties,
            "reservations": reservations,
        }
        self.scheduler_rpcapi.prep_resize(context, **args)

    @wrap_check_policy
    @check_instance_lock
    def add_fixed_ip(self, context, instance, network_id):
        """Add fixed_ip from specified network to given instance."""
        self.compute_rpcapi.add_fixed_ip_to_instance(context,
                instance=instance, network_id=network_id)

    @wrap_check_policy
    @check_instance_lock
    def remove_fixed_ip(self, context, instance, address):
        """Remove fixed_ip from specified network to given instance."""
        self.compute_rpcapi.remove_fixed_ip_from_instance(context,
                instance=instance, address=address)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.RESCUED])
    def pause(self, context, instance):
        """Pause the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=task_states.PAUSING,
                    expected_task_state=None)
        self.compute_rpcapi.pause_instance(context, instance=instance)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.PAUSED])
    def unpause(self, context, instance):
        """Unpause the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.PAUSED,
                    task_state=task_states.UNPAUSING,
                    expected_task_state=None)
        self.compute_rpcapi.unpause_instance(context, instance=instance)

    @wrap_check_policy
    def get_diagnostics(self, context, instance):
        """Retrieve diagnostics for the given instance."""
        return self.compute_rpcapi.get_diagnostics(context, instance=instance)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.RESCUED])
    def suspend(self, context, instance):
        """Suspend the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=task_states.SUSPENDING,
                    expected_task_state=None)
        self.compute_rpcapi.suspend_instance(context, instance=instance)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.SUSPENDED])
    def resume(self, context, instance):
        """Resume the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.SUSPENDED,
                    task_state=task_states.RESUMING,
                    expected_task_state=None)
        self.compute_rpcapi.resume_instance(context, instance=instance)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED])
    def rescue(self, context, instance, rescue_password=None):
        """Rescue the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=task_states.RESCUING,
                    expected_task_state=None)

        self.compute_rpcapi.rescue_instance(context, instance=instance,
                rescue_password=rescue_password)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.RESCUED])
    def unrescue(self, context, instance):
        """Unrescue the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.RESCUED,
                    task_state=task_states.UNRESCUING,
                    expected_task_state=None)
        self.compute_rpcapi.unrescue_instance(context, instance=instance)

    @wrap_check_policy
    @check_instance_lock
    @check_instance_state(vm_state=[vm_states.ACTIVE])
    def set_admin_password(self, context, instance, password=None):
        """Set the root/admin password for the given instance."""
        self.update(context,
                    instance,
                    task_state=task_states.UPDATING_PASSWORD,
                    expected_task_state=None)

        self.compute_rpcapi.set_admin_password(context,
                                               instance=instance,
                                               new_pass=password)

    @wrap_check_policy
    @check_instance_lock
    def inject_file(self, context, instance, path, file_contents):
        """Write a file to the given instance."""
        self.compute_rpcapi.inject_file(context, instance=instance, path=path,
                file_contents=file_contents)

    @wrap_check_policy
    def get_vnc_console(self, context, instance, console_type):
        """Get a url to an instance Console."""
        if not instance['host']:
            raise exception.InstanceNotReady(instance=instance)

        connect_info = self.compute_rpcapi.get_vnc_console(context,
                instance=instance, console_type=console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type, connect_info['host'],
                connect_info['port'], connect_info['internal_access_path'],
                instance["uuid"])

        return {'url': connect_info['access_url']}

    @wrap_check_policy
    def get_console_output(self, context, instance, tail_length=None):
        """Get console output for an instance."""
        return self.compute_rpcapi.get_console_output(context,
                instance=instance, tail_length=tail_length)

    @wrap_check_policy
    def lock(self, context, instance):
        """Lock the given instance."""
        context = context.elevated()
        instance_uuid = instance['uuid']
        LOG.debug(_('Locking'), context=context, instance_uuid=instance_uuid)
        self._instance_update(context, instance_uuid, locked=True)

    @wrap_check_policy
    def unlock(self, context, instance):
        """Unlock the given instance."""
        context = context.elevated()
        instance_uuid = instance['uuid']
        LOG.debug(_('Unlocking'), context=context, instance_uuid=instance_uuid)
        self._instance_update(context, instance_uuid, locked=False)

    @wrap_check_policy
    def get_lock(self, context, instance):
        """Return the boolean state of given instance's lock."""
        return self.get(context, instance['uuid'])['locked']

    @wrap_check_policy
    @check_instance_lock
    def reset_network(self, context, instance):
        """Reset networking on the instance."""
        self.compute_rpcapi.reset_network(context, instance=instance)

    @wrap_check_policy
    @check_instance_lock
    def inject_network_info(self, context, instance):
        """Inject network info for the instance."""
        self.compute_rpcapi.inject_network_info(context, instance=instance)

    @wrap_check_policy
    @check_instance_lock
    def attach_volume(self, context, instance, volume_id, device=None):
        """Attach an existing volume to an existing instance."""
        # NOTE(vish): Fail fast if the device is not going to pass. This
        #             will need to be removed along with the test if we
        #             change the logic in the manager for what constitutes
        #             a valid device.
        if device and not block_device.match_device(device):
            raise exception.InvalidDevicePath(path=device)
        # NOTE(vish): This is done on the compute host because we want
        #             to avoid a race where two devices are requested at
        #             the same time. When db access is removed from
        #             compute, the bdm will be created here and we will
        #             have to make sure that they are assigned atomically.
        device = self.compute_rpcapi.reserve_block_device_name(
            context, device=device, instance=instance)
        try:
            volume = self.volume_api.get(context, volume_id)
            self.volume_api.check_attach(context, volume)
            self.volume_api.reserve_volume(context, volume)
            self.compute_rpcapi.attach_volume(context, instance=instance,
                    volume_id=volume_id, mountpoint=device)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.block_device_mapping_destroy_by_instance_and_device(
                        context, instance['uuid'], device)

        return device

    @check_instance_lock
    def _detach_volume(self, context, instance, volume_id):
        check_policy(context, 'detach_volume', instance)

        volume = self.volume_api.get(context, volume_id)
        self.volume_api.check_detach(context, volume)
        self.volume_api.begin_detaching(context, volume)

        self.compute_rpcapi.detach_volume(context, instance=instance,
                volume_id=volume_id)
        return instance

    # FIXME(comstud): I wonder if API should pull in the instance from
    # the volume ID via volume API and pass it and the volume object here
    def detach_volume(self, context, volume_id):
        """Detach a volume from an instance."""
        volume = self.volume_api.get(context, volume_id)
        if volume['attach_status'] == 'detached':
            msg = _("Volume must be attached in order to detach.")
            raise exception.InvalidVolume(reason=msg)

        instance_uuid = volume['instance_uuid']
        instance = self.db.instance_get_by_uuid(context.elevated(),
                                                instance_uuid)
        if not instance:
            raise exception.VolumeUnattached(volume_id=volume_id)
        self._detach_volume(context, instance, volume_id)

    @wrap_check_policy
    def get_instance_metadata(self, context, instance):
        """Get all metadata associated with an instance."""
        rv = self.db.instance_metadata_get(context, instance['uuid'])
        return dict(rv.iteritems())

    @wrap_check_policy
    @check_instance_lock
    def delete_instance_metadata(self, context, instance, key):
        """Delete the given metadata item from an instance."""
        self.db.instance_metadata_delete(context, instance['uuid'], key)
        instance['metadata'] = {}
        notifications.send_update(context, instance, instance)
        self.compute_rpcapi.change_instance_metadata(context,
                                                     instance=instance,
                                                     diff={key: ['-']})

    @wrap_check_policy
    @check_instance_lock
    def update_instance_metadata(self, context, instance,
                                 metadata, delete=False):
        """Updates or creates instance metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        orig = self.get_instance_metadata(context, instance)
        if delete:
            _metadata = metadata
        else:
            _metadata = orig.copy()
            _metadata.update(metadata)

        self._check_metadata_properties_quota(context, _metadata)
        metadata = self.db.instance_metadata_update(context, instance['uuid'],
                                         _metadata, True)
        instance['metadata'] = metadata
        notifications.send_update(context, instance, instance)
        diff = utils.diff_dict(orig, _metadata)
        self.compute_rpcapi.change_instance_metadata(context,
                                                     instance=instance,
                                                     diff=diff)
        return _metadata

    def get_instance_faults(self, context, instances):
        """Get all faults for a list of instance uuids."""

        if not instances:
            return {}

        for instance in instances:
            check_policy(context, 'get_instance_faults', instance)

        uuids = [instance['uuid'] for instance in instances]
        return self.db.instance_fault_get_by_instance_uuids(context, uuids)

    def get_instance_bdms(self, context, instance):
        """Get all bdm tables for specified instance."""
        return self.db.block_device_mapping_get_all_by_instance(context,
                instance['uuid'])

    def is_volume_backed_instance(self, context, instance, bdms):
        bdms = bdms or self.get_instance_bdms(context, instance)
        for bdm in bdms:
            if (block_device.strip_dev(bdm.device_name) ==
                block_device.strip_dev(instance['root_device_name'])):
                return True
        else:
            return False

    @check_instance_state(vm_state=[vm_states.ACTIVE])
    def live_migrate(self, context, instance, block_migration,
                     disk_over_commit, host):
        """Migrate a server lively to a new host."""
        LOG.debug(_("Going to try to live migrate instance to %s"),
                  host, instance=instance)

        instance = self.update(context, instance,
                               task_state=task_states.MIGRATING,
                               expected_task_state=None)

        self.scheduler_rpcapi.live_migration(context, block_migration,
                disk_over_commit, instance, host)


class HostAPI(base.Base):
    def __init__(self):
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        super(HostAPI, self).__init__()

    """Sub-set of the Compute Manager API for managing host operations."""
    def set_host_enabled(self, context, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        return self.compute_rpcapi.set_host_enabled(context, enabled=enabled,
                host=host)

    def get_host_uptime(self, context, host):
        """Returns the result of calling "uptime" on the target host."""
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        return self.compute_rpcapi.get_host_uptime(context, host=host)

    def host_power_action(self, context, host, action):
        """Reboots, shuts down or powers up the host."""
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        return self.compute_rpcapi.host_power_action(context, action=action,
                host=host)

    def set_host_maintenance(self, context, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation."""
        return self.compute_rpcapi.host_maintenance_mode(context,
                host_param=host, mode=mode, host=host)


class AggregateAPI(base.Base):
    """Sub-set of the Compute Manager API for managing host aggregates."""
    def __init__(self, **kwargs):
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        super(AggregateAPI, self).__init__(**kwargs)

    def create_aggregate(self, context, aggregate_name, availability_zone):
        """Creates the model for the aggregate."""
        zones = [s.availability_zone for s in
                 self.db.service_get_all_by_topic(context,
                                                  FLAGS.compute_topic)]
        if availability_zone in zones:
            values = {"name": aggregate_name,
                      "availability_zone": availability_zone}
            aggregate = self.db.aggregate_create(context, values)
            aggregate = self._get_aggregate_info(context, aggregate)
            # To maintain the same API result as before.
            del aggregate['hosts']
            del aggregate['metadata']
            return aggregate
        else:
            raise exception.InvalidAggregateAction(action='create_aggregate',
                                                   aggregate_id="'N/A'",
                                                   reason='invalid zone')

    def get_aggregate(self, context, aggregate_id):
        """Get an aggregate by id."""
        aggregate = self.db.aggregate_get(context, aggregate_id)
        return self._get_aggregate_info(context, aggregate)

    def get_aggregate_list(self, context):
        """Get all the aggregates."""
        aggregates = self.db.aggregate_get_all(context)
        return [self._get_aggregate_info(context, a) for a in aggregates]

    def update_aggregate(self, context, aggregate_id, values):
        """Update the properties of an aggregate."""
        aggregate = self.db.aggregate_update(context, aggregate_id, values)
        return self._get_aggregate_info(context, aggregate)

    def update_aggregate_metadata(self, context, aggregate_id, metadata):
        """Updates the aggregate metadata.

        If a key is set to None, it gets removed from the aggregate metadata.
        """
        for key in metadata.keys():
            if not metadata[key]:
                try:
                    self.db.aggregate_metadata_delete(context,
                                                      aggregate_id, key)
                    metadata.pop(key)
                except exception.AggregateMetadataNotFound, e:
                    LOG.warn(e.message)
        self.db.aggregate_metadata_add(context, aggregate_id, metadata)
        return self.get_aggregate(context, aggregate_id)

    def delete_aggregate(self, context, aggregate_id):
        """Deletes the aggregate."""
        hosts = self.db.aggregate_host_get_all(context, aggregate_id)
        if len(hosts) > 0:
            raise exception.InvalidAggregateAction(action='delete',
                                                   aggregate_id=aggregate_id,
                                                   reason='not empty')
        self.db.aggregate_delete(context, aggregate_id)

    def add_host_to_aggregate(self, context, aggregate_id, host):
        """Adds the host to an aggregate."""
        # validates the host; ComputeHostNotFound is raised if invalid
        service = self.db.service_get_all_compute_by_host(context, host)[0]
        aggregate = self.db.aggregate_get(context, aggregate_id)
        if service.availability_zone != aggregate.availability_zone:
            raise exception.InvalidAggregateAction(
                    action='add host',
                    aggregate_id=aggregate_id,
                    reason='availability zone mismatch')
        self.db.aggregate_host_add(context, aggregate_id, host)
        #NOTE(jogo): Send message to host to support resource pools
        self.compute_rpcapi.add_aggregate_host(context,
                aggregate_id=aggregate_id, host_param=host, host=host)
        return self.get_aggregate(context, aggregate_id)

    def remove_host_from_aggregate(self, context, aggregate_id, host):
        """Removes host from the aggregate."""
        # validates the host; ComputeHostNotFound is raised if invalid
        service = self.db.service_get_all_compute_by_host(context, host)[0]
        self.db.aggregate_host_delete(context, aggregate_id, host)
        self.compute_rpcapi.remove_aggregate_host(context,
                aggregate_id=aggregate_id, host_param=host, host=host)
        return self.get_aggregate(context, aggregate_id)

    def _get_aggregate_info(self, context, aggregate):
        """Builds a dictionary with aggregate props, metadata and hosts."""
        metadata = self.db.aggregate_metadata_get(context, aggregate.id)
        hosts = self.db.aggregate_host_get_all(context, aggregate.id)
        result = dict(aggregate.iteritems())
        result["metadata"] = metadata
        result["hosts"] = hosts
        return result


class KeypairAPI(base.Base):
    """Sub-set of the Compute Manager API for managing key pairs."""
    def __init__(self, **kwargs):
        super(KeypairAPI, self).__init__(**kwargs)

    def _validate_keypair_name(self, context, user_id, key_name):
        safechars = "_- " + string.digits + string.ascii_letters
        clean_value = "".join(x for x in key_name if x in safechars)
        if clean_value != key_name:
            msg = _("Keypair name contains unsafe characters")
            raise exception.InvalidKeypair(explanation=msg)

        if not 0 < len(key_name) < 256:
            msg = _('Keypair name must be between 1 and 255 characters long')
            raise exception.InvalidKeypair(explanation=msg)

        # NOTE: check for existing keypairs of same name
        try:
            self.db.key_pair_get(context, user_id, key_name)
            raise exception.KeyPairExists(key_name=key_name)
        except exception.NotFound:
            pass

    def import_key_pair(self, context, user_id, key_name, public_key):
        """Import a key pair using an existing public key."""
        self._validate_keypair_name(context, user_id, key_name)

        count = QUOTAS.count(context, 'key_pairs', user_id)
        try:
            QUOTAS.limit_check(context, key_pairs=count + 1)
        except exception.OverQuota:
            raise exception.KeypairLimitExceeded()

        try:
            fingerprint = crypto.generate_fingerprint(public_key)
        except exception.InvalidKeypair:
            msg = _("Keypair data is invalid")
            raise exception.InvalidKeypair(explanation=msg)

        keypair = {'user_id': user_id,
                   'name': key_name,
                   'fingerprint': fingerprint,
                   'public_key': public_key}

        self.db.key_pair_create(context, keypair)
        return keypair

    def create_key_pair(self, context, user_id, key_name):
        """Create a new key pair."""
        self._validate_keypair_name(context, user_id, key_name)

        count = QUOTAS.count(context, 'key_pairs', user_id)
        try:
            QUOTAS.limit_check(context, key_pairs=count + 1)
        except exception.OverQuota:
            raise exception.KeypairLimitExceeded()

        private_key, public_key, fingerprint = crypto.generate_key_pair()

        keypair = {'user_id': user_id,
                   'name': key_name,
                   'fingerprint': fingerprint,
                   'public_key': public_key,
                   'private_key': private_key}
        self.db.key_pair_create(context, keypair)

        return keypair

    def delete_key_pair(self, context, user_id, key_name):
        """Delete a keypair by name."""
        self.db.key_pair_destroy(context, user_id, key_name)

    def get_key_pairs(self, context, user_id):
        """List key pairs."""
        key_pairs = self.db.key_pair_get_all_by_user(context, user_id)
        rval = []
        for key_pair in key_pairs:
            rval.append({
                'name': key_pair['name'],
                'public_key': key_pair['public_key'],
                'fingerprint': key_pair['fingerprint'],
            })
        return rval

    def get_key_pair(self, context, user_id, key_name):
        """Get a keypair by name."""
        key_pair = self.db.key_pair_get(context, user_id, key_name)
        return {'name': key_pair['name'],
                'public_key': key_pair['public_key'],
                'fingerprint': key_pair['fingerprint']}


class SecurityGroupAPI(base.Base):
    """
    Sub-set of the Compute API related to managing security groups
    and security group rules
    """
    def __init__(self, **kwargs):
        super(SecurityGroupAPI, self).__init__(**kwargs)
        self.security_group_rpcapi = compute_rpcapi.SecurityGroupAPI()
        self.sgh = importutils.import_object(FLAGS.security_group_handler)

    def validate_property(self, value, property, allowed):
        """
        Validate given security group property.

        :param value:          the value to validate, as a string or unicode
        :param property:       the property, either 'name' or 'description'
        :param allowed:        the range of characters allowed
        """

        try:
            val = value.strip()
        except AttributeError:
            msg = _("Security group %s is not a string or unicode") % property
            self.raise_invalid_property(msg)
        if not val:
            msg = _("Security group %s cannot be empty.") % property
            self.raise_invalid_property(msg)

        if allowed and not re.match(allowed, val):
            # Some validation to ensure that values match API spec.
            # - Alphanumeric characters, spaces, dashes, and underscores.
            # TODO(Daviey): LP: #813685 extend beyond group_name checking, and
            #  probably create a param validator that can be used elsewhere.
            msg = (_("Value (%(value)s) for parameter Group%(property)s is "
                     "invalid. Content limited to '%(allowed)'.") %
                   dict(value=value, allowed=allowed,
                        property=property.capitalize()))
            self.raise_invalid_property(msg)
        if len(val) > 255:
            msg = _("Security group %s should not be greater "
                            "than 255 characters.") % property
            self.raise_invalid_property(msg)

    def ensure_default(self, context):
        """Ensure that a context has a security group.

        Creates a security group for the security context if it does not
        already exist.

        :param context: the security context
        """
        existed, group = self.db.security_group_ensure_default(context)
        if not existed:
            self.sgh.trigger_security_group_create_refresh(context, group)

    def create(self, context, name, description):
        try:
            reservations = QUOTAS.reserve(context, security_groups=1)
        except exception.OverQuota:
            msg = _("Quota exceeded, too many security groups.")
            self.raise_over_quota(msg)

        LOG.audit(_("Create Security Group %s"), name, context=context)

        try:
            self.ensure_default(context)

            if self.db.security_group_exists(context,
                                             context.project_id, name):
                msg = _('Security group %s already exists') % name
                self.raise_group_already_exists(msg)

            group = {'user_id': context.user_id,
                     'project_id': context.project_id,
                     'name': name,
                     'description': description}
            group_ref = self.db.security_group_create(context, group)
            self.sgh.trigger_security_group_create_refresh(context, group)
            # Commit the reservation
            QUOTAS.commit(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                QUOTAS.rollback(context, reservations)

        return group_ref

    def get(self, context, name=None, id=None, map_exception=False):
        self.ensure_default(context)
        try:
            if name:
                return self.db.security_group_get_by_name(context,
                                                          context.project_id,
                                                          name)
            elif id:
                return self.db.security_group_get(context, id)
        except exception.NotFound as exp:
            if map_exception:
                msg = exp.format_message()
                self.raise_not_found(msg)
            else:
                raise

    def list(self, context, names=None, ids=None, project=None,
             search_opts=None):
        self.ensure_default(context)

        groups = []
        if names or ids:
            if names:
                for name in names:
                    groups.append(self.db.security_group_get_by_name(context,
                                                                     project,
                                                                     name))
            if ids:
                for id in ids:
                    groups.append(self.db.security_group_get(context, id))

        elif context.is_admin:
            # TODO(eglynn): support a wider set of search options than just
            # all_tenants, at least include the standard filters defined for
            # the EC2 DescribeSecurityGroups API for the non-admin case also
            if (search_opts and 'all_tenants' in search_opts):
                groups = self.db.security_group_get_all(context)
            else:
                groups = self.db.security_group_get_by_project(context,
                                                               project)

        elif project:
            groups = self.db.security_group_get_by_project(context, project)

        return groups

    def destroy(self, context, security_group):
        if self.db.security_group_in_use(context, security_group.id):
            msg = _("Security group is still in use")
            self.raise_invalid_group(msg)

        # Get reservations
        try:
            reservations = QUOTAS.reserve(context, security_groups=-1)
        except Exception:
            reservations = None
            LOG.exception(_("Failed to update usages deallocating "
                            "security group"))

        LOG.audit(_("Delete security group %s"), security_group.name,
                  context=context)
        self.db.security_group_destroy(context, security_group.id)

        self.sgh.trigger_security_group_destroy_refresh(context,
                                                        security_group.id)

        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations)

    def is_associated_with_server(self, security_group, instance_uuid):
        """Check if the security group is already associated
           with the instance. If Yes, return True.
        """

        if not security_group:
            return False

        instances = security_group.get('instances')
        if not instances:
            return False

        for inst in instances:
            if (instance_uuid == inst['uuid']):
                return True

        return False

    @wrap_check_security_groups_policy
    def add_to_instance(self, context, instance, security_group_name):
        """Add security group to the instance"""
        security_group = self.db.security_group_get_by_name(context,
                context.project_id,
                security_group_name)

        instance_uuid = instance['uuid']

        #check if the security group is associated with the server
        if self.is_associated_with_server(security_group, instance_uuid):
            raise exception.SecurityGroupExistsForInstance(
                                        security_group_id=security_group['id'],
                                        instance_id=instance_uuid)

        #check if the instance is in running state
        if instance['power_state'] != power_state.RUNNING:
            raise exception.InstanceNotRunning(instance_id=instance_uuid)

        self.db.instance_add_security_group(context.elevated(),
                                            instance_uuid,
                                            security_group['id'])
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        self.security_group_rpcapi.refresh_security_group_rules(context,
                security_group['id'], host=instance['host'])

        self.trigger_handler('instance_add_security_group',
                context, instance, security_group_name)

    @wrap_check_security_groups_policy
    def remove_from_instance(self, context, instance, security_group_name):
        """Remove the security group associated with the instance"""
        security_group = self.db.security_group_get_by_name(context,
                context.project_id,
                security_group_name)

        instance_uuid = instance['uuid']

        #check if the security group is associated with the server
        if not self.is_associated_with_server(security_group, instance_uuid):
            raise exception.SecurityGroupNotExistsForInstance(
                                    security_group_id=security_group['id'],
                                    instance_id=instance_uuid)

        #check if the instance is in running state
        if instance['power_state'] != power_state.RUNNING:
            raise exception.InstanceNotRunning(instance_id=instance_uuid)

        self.db.instance_remove_security_group(context.elevated(),
                                               instance_uuid,
                                               security_group['id'])
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        self.security_group_rpcapi.refresh_security_group_rules(context,
                security_group['id'], host=instance['host'])

        self.trigger_handler('instance_remove_security_group',
                context, instance, security_group_name)

    def trigger_handler(self, event, *args):
        handle = getattr(self.sgh, 'trigger_%s_refresh' % event)
        handle(*args)

    def trigger_rules_refresh(self, context, id):
        """Called when a rule is added to or removed from a security_group."""

        security_group = self.db.security_group_get(context, id)

        for instance in security_group['instances']:
            if instance['host'] is not None:
                self.security_group_rpcapi.refresh_instance_security_rules(
                        context, instance['host'], instance)

    def trigger_members_refresh(self, context, group_ids):
        """Called when a security group gains a new or loses a member.

        Sends an update request to each compute node for each instance for
        which this is relevant.
        """
        # First, we get the security group rules that reference these groups as
        # the grantee..
        security_group_rules = set()
        for group_id in group_ids:
            security_group_rules.update(
                self.db.security_group_rule_get_by_security_group_grantee(
                                                                     context,
                                                                     group_id))

        # ..then we distill the rules into the groups to which they belong..
        security_groups = set()
        for rule in security_group_rules:
            security_group = self.db.security_group_get(
                                                    context,
                                                    rule['parent_group_id'])
            security_groups.add(security_group)

        # ..then we find the instances that are members of these groups..
        instances = set()
        for security_group in security_groups:
            for instance in security_group['instances']:
                instances.add(instance)

        # ..then we send a request to refresh the rules for each instance.
        for instance in instances:
            if instance['host']:
                self.security_group_rpcapi.refresh_instance_security_rules(
                        context, instance['host'], instance)

    def parse_cidr(self, cidr):
        if cidr:
            try:
                cidr = urllib.unquote(cidr).decode()
            except Exception as e:
                self.raise_invalid_cidr(cidr, e)

            if not utils.is_valid_cidr(cidr):
                self.raise_invalid_cidr(cidr)

            return cidr
        else:
            return '0.0.0.0/0'

    @staticmethod
    def new_group_ingress_rule(grantee_group_id, protocol, from_port,
                               to_port):
        return SecurityGroupAPI._new_ingress_rule(protocol, from_port,
                                to_port, group_id=grantee_group_id)

    @staticmethod
    def new_cidr_ingress_rule(grantee_cidr, protocol, from_port, to_port):
        return SecurityGroupAPI._new_ingress_rule(protocol, from_port,
                                to_port, cidr=grantee_cidr)

    @staticmethod
    def _new_ingress_rule(ip_protocol, from_port, to_port,
                          group_id=None, cidr=None):
        values = {}

        if group_id:
            values['group_id'] = group_id
            # Open everything if an explicit port range or type/code are not
            # specified, but only if a source group was specified.
            ip_proto_upper = ip_protocol.upper() if ip_protocol else ''
            if (ip_proto_upper == 'ICMP' and
                from_port is None and to_port is None):
                from_port = -1
                to_port = -1
            elif (ip_proto_upper in ['TCP', 'UDP'] and from_port is None
                  and to_port is None):
                from_port = 1
                to_port = 65535

        elif cidr:
            values['cidr'] = cidr

        if ip_protocol and from_port is not None and to_port is not None:

            ip_protocol = str(ip_protocol)
            try:
                # Verify integer conversions
                from_port = int(from_port)
                to_port = int(to_port)
            except ValueError:
                if ip_protocol.upper() == 'ICMP':
                    raise exception.InvalidInput(reason="Type and"
                         " Code must be integers for ICMP protocol type")
                else:
                    raise exception.InvalidInput(reason="To and From ports "
                          "must be integers")

            if ip_protocol.upper() not in ['TCP', 'UDP', 'ICMP']:
                raise exception.InvalidIpProtocol(protocol=ip_protocol)

            # Verify that from_port must always be less than
            # or equal to to_port
            if (ip_protocol.upper() in ['TCP', 'UDP'] and
                (from_port > to_port)):
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="Former value cannot"
                                            " be greater than the later")

            # Verify valid TCP, UDP port ranges
            if (ip_protocol.upper() in ['TCP', 'UDP'] and
                (from_port < 1 or to_port > 65535)):
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="Valid TCP ports should"
                                           " be between 1-65535")

            # Verify ICMP type and code
            if (ip_protocol.upper() == "ICMP" and
                (from_port < -1 or from_port > 255 or
                to_port < -1 or to_port > 255)):
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="For ICMP, the"
                                           " type:code must be valid")

            values['protocol'] = ip_protocol
            values['from_port'] = from_port
            values['to_port'] = to_port

        else:
            # If cidr based filtering, protocol and ports are mandatory
            if cidr:
                return None

        return values

    def rule_exists(self, security_group, values):
        """Indicates whether the specified rule values are already
           defined in the given security group.
        """
        for rule in security_group.rules:
            is_duplicate = True
            keys = ('group_id', 'cidr', 'from_port', 'to_port', 'protocol')
            for key in keys:
                if rule.get(key) != values.get(key):
                    is_duplicate = False
                    break
            if is_duplicate:
                return rule.get('id') or True
        return False

    def get_rule(self, context, id):
        self.ensure_default(context)
        try:
            return self.db.security_group_rule_get(context, id)
        except exception.NotFound:
            msg = _("Rule (%s) not found") % id
            self.raise_not_found(msg)

    def add_rules(self, context, id, name, vals):
        count = QUOTAS.count(context, 'security_group_rules', id)
        try:
            projected = count + len(vals)
            QUOTAS.limit_check(context, security_group_rules=projected)
        except exception.OverQuota:
            msg = _("Quota exceeded, too many security group rules.")
            self.raise_over_quota(msg)

        msg = _("Authorize security group ingress %s")
        LOG.audit(msg, name, context=context)

        rules = [self.db.security_group_rule_create(context, v) for v in vals]

        self.trigger_rules_refresh(context, id=id)
        self.trigger_handler('security_group_rule_create', context,
                             [r['id'] for r in rules])
        return rules

    def remove_rules(self, context, security_group, rule_ids):
        msg = _("Revoke security group ingress %s")
        LOG.audit(msg, security_group['name'], context=context)

        for rule_id in rule_ids:
            self.db.security_group_rule_destroy(context, rule_id)

        # NOTE(vish): we removed some rules, so refresh
        self.trigger_rules_refresh(context, id=security_group['id'])
        self.trigger_handler('security_group_rule_destroy', context, rule_ids)

    @staticmethod
    def raise_invalid_property(msg):
        raise NotImplementedError()

    @staticmethod
    def raise_group_already_exists(msg):
        raise NotImplementedError()

    @staticmethod
    def raise_invalid_group(msg):
        raise NotImplementedError()

    @staticmethod
    def raise_invalid_cidr(cidr, decoding_exception=None):
        raise NotImplementedError()

    @staticmethod
    def raise_over_quota(msg):
        raise NotImplementedError()

    @staticmethod
    def raise_not_found(msg):
        raise NotImplementedError()
