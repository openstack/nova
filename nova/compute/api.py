# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
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

"""Handles all requests relating to compute resources (e.g. guest vms,
networking and storage of vms, and compute hosts on which they run)."""

import functools
import re
import time

import webob.exc

from nova import block_device
from nova.compute import aggregate_states
from nova.compute import instance_types
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova.db import base
from nova import exception
from nova import flags
import nova.image
from nova import log as logging
from nova import network
from nova.openstack.common import cfg
import nova.policy
from nova import quota
from nova import rpc
from nova.scheduler import api as scheduler_api
from nova import utils
from nova import volume


LOG = logging.getLogger(__name__)

find_host_timeout_opt = cfg.StrOpt('find_host_timeout',
        default=30,
        help='Timeout after NN seconds when looking for a host.')

FLAGS = flags.FLAGS
FLAGS.register_opt(find_host_timeout_opt)
flags.DECLARE('consoleauth_topic', 'nova.consoleauth')


def check_instance_state(vm_state=None, task_state=None):
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


def wrap_check_policy(func):
    """Check corresponding policy prior of wrapped method to execution"""
    @functools.wraps(func)
    def wrapped(self, context, target, *args, **kwargs):
        check_policy(context, func.__name__, target)
        return func(self, context, target, *args, **kwargs)
    return wrapped


def check_policy(context, action, target):
    _action = 'compute:%s' % action
    nova.policy.enforce(context, _action, target)


class BaseAPI(base.Base):
    """Base API class."""
    def __init__(self, **kwargs):
        super(BaseAPI, self).__init__(**kwargs)

    def _cast_or_call_compute_message(self, rpc_method, compute_method,
            context, instance=None, host=None, params=None):
        """Generic handler for RPC casts and calls to compute.

        :param rpc_method: RPC method to use (rpc.call or rpc.cast)
        :param compute_method: Compute manager method to call
        :param context: RequestContext of caller
        :param instance: The instance object to use to find host to send to
                         Can be None to not include instance_uuid in args
        :param host: Optional host to send to instead of instance['host']
                     Must be specified if 'instance' is None
        :param params: Optional dictionary of arguments to be passed to the
                       compute worker

        :returns: None
        """
        if not params:
            params = {}
        if not host:
            if not instance:
                raise exception.Error(_("No compute host specified"))
            host = instance['host']
            if not host:
                raise exception.Error(_("Unable to find host for "
                                        "Instance %s") % instance['uuid'])
        queue = self.db.queue_get_for(context, FLAGS.compute_topic, host)
        if instance:
            params['instance_uuid'] = instance['uuid']
        kwargs = {'method': compute_method, 'args': params}
        return rpc_method(context, queue, kwargs)

    def _cast_compute_message(self, *args, **kwargs):
        """Generic handler for RPC casts to compute."""
        self._cast_or_call_compute_message(rpc.cast, *args, **kwargs)

    def _call_compute_message(self, *args, **kwargs):
        """Generic handler for RPC calls to compute."""
        return self._cast_or_call_compute_message(rpc.call, *args, **kwargs)

    @staticmethod
    def _cast_scheduler_message(context, args):
        """Generic handler for RPC calls to the scheduler."""
        rpc.cast(context, FLAGS.scheduler_topic, args)


class API(BaseAPI):
    """API for interacting with the compute manager."""

    def __init__(self, image_service=None, network_api=None, volume_api=None,
                 **kwargs):
        self.image_service = (image_service or
                              nova.image.get_default_image_service())

        self.network_api = network_api or network.API()
        self.volume_api = volume_api or volume.API()
        super(API, self).__init__(**kwargs)

    def _check_injected_file_quota(self, context, injected_files):
        """Enforce quota limits on injected files.

        Raises a QuotaError if any limit is exceeded.
        """
        if injected_files is None:
            return
        limit = quota.allowed_injected_files(context, len(injected_files))
        if len(injected_files) > limit:
            raise exception.QuotaError(code="OnsetFileLimitExceeded")
        path_limit = quota.allowed_injected_file_path_bytes(context)
        for path, content in injected_files:
            if len(path) > path_limit:
                raise exception.QuotaError(code="OnsetFilePathLimitExceeded")
            content_limit = quota.allowed_injected_file_content_bytes(
                                                    context, len(content))
            if len(content) > content_limit:
                code = "OnsetFileContentLimitExceeded"
                raise exception.QuotaError(code=code)

    def _check_metadata_properties_quota(self, context, metadata=None):
        """Enforce quota limits on metadata properties."""
        if not metadata:
            metadata = {}
        num_metadata = len(metadata)
        quota_metadata = quota.allowed_metadata_items(context, num_metadata)
        if quota_metadata < num_metadata:
            pid = context.project_id
            msg = _("Quota exceeded for %(pid)s, tried to set "
                    "%(num_metadata)s metadata properties") % locals()
            LOG.warn(msg)
            raise exception.QuotaError(code="MetadataLimitExceeded")

        # Because metadata is stored in the DB, we hard-code the size limits
        # In future, we may support more variable length strings, so we act
        #  as if this is quota-controlled for forwards compatibility
        for k, v in metadata.iteritems():
            if len(k) > 255 or len(v) > 255:
                pid = context.project_id
                msg = _("Quota exceeded for %(pid)s, metadata property "
                        "key or value too long") % locals()
                LOG.warn(msg)
                raise exception.QuotaError(code="MetadataLimitExceeded")

    def _check_requested_networks(self, context, requested_networks):
        """ Check if the networks requested belongs to the project
            and the fixed IP address for each network provided is within
            same the network block
        """
        if requested_networks is None:
            return

        self.network_api.validate_networks(context, requested_networks)

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
               reservation_id=None, create_instance_here=False,
               scheduler_hints=None):
        """Verify all the input parameters regardless of the provisioning
        strategy being performed and schedule the instance(s) for
        creation."""

        if not metadata:
            metadata = {}
        if not display_description:
            display_description = ''
        if not security_group:
            security_group = 'default'

        if not instance_type:
            instance_type = instance_types.get_default_instance_type()
        if not min_count:
            min_count = 1
        if not max_count:
            max_count = min_count
        if not metadata:
            metadata = {}

        block_device_mapping = block_device_mapping or []

        num_instances = quota.allowed_instances(context, max_count,
                                                instance_type)
        if num_instances < min_count:
            pid = context.project_id
            if num_instances <= 0:
                msg = _("Cannot run any more instances of this type.")
            else:
                msg = (_("Can only run %s more instances of this type.") %
                       num_instances)
            LOG.warn(_("Quota exceeded for %(pid)s,"
                  " tried to run %(min_count)s instances. %(msg)s"), locals())
            raise exception.QuotaError(code="InstanceLimitExceeded")

        self._check_metadata_properties_quota(context, metadata)
        self._check_injected_file_quota(context, injected_files)
        self._check_requested_networks(context, requested_networks)

        (image_service, image_id) = nova.image.get_image_service(context,
                                                                 image_href)
        image = image_service.show(context, image_id)

        if instance_type['memory_mb'] < int(image.get('min_ram') or 0):
            raise exception.InstanceTypeMemoryTooSmall()
        if instance_type['root_gb'] < int(image.get('min_disk') or 0):
            raise exception.InstanceTypeDiskTooSmall()

        config_drive_id = None
        if config_drive and config_drive is not True:
            # config_drive is volume id
            config_drive, config_drive_id = None, config_drive

        os_type = None
        if 'properties' in image and 'os_type' in image['properties']:
            os_type = image['properties']['os_type']
        architecture = None
        if 'properties' in image and 'arch' in image['properties']:
            architecture = image['properties']['arch']
        vm_mode = None
        if 'properties' in image and 'vm_mode' in image['properties']:
            vm_mode = image['properties']['vm_mode']

        # If instance doesn't have auto_disk_config overridden by request, use
        # whatever the image indicates
        if auto_disk_config is None:
            if ('properties' in image and
                'auto_disk_config' in image['properties']):
                auto_disk_config = utils.bool_from_str(
                    image['properties']['auto_disk_config'])

        if kernel_id is None:
            kernel_id = image['properties'].get('kernel_id', None)
        if ramdisk_id is None:
            ramdisk_id = image['properties'].get('ramdisk_id', None)
        # FIXME(sirp): is there a way we can remove null_kernel?
        # No kernel and ramdisk for raw images
        if kernel_id == str(FLAGS.null_kernel):
            kernel_id = None
            ramdisk_id = None
            LOG.debug(_("Creating a raw instance"))
        # Make sure we have access to kernel and ramdisk (if not raw)
        LOG.debug(_("Using Kernel=%(kernel_id)s, Ramdisk=%(ramdisk_id)s")
                  % locals())
        if kernel_id:
            image_service.show(context, kernel_id)
        if ramdisk_id:
            image_service.show(context, ramdisk_id)
        if config_drive_id:
            image_service.show(context, config_drive_id)

        self.ensure_default_security_group(context)

        if key_data is None and key_name:
            key_pair = self.db.key_pair_get(context, context.user_id, key_name)
            key_data = key_pair['public_key']

        if reservation_id is None:
            reservation_id = utils.generate_uid('r')

        root_device_name = block_device.properties_root_device_name(
            image['properties'])

        # NOTE(vish): We have a legacy hack to allow admins to specify hosts
        #             via az using az:host. It might be nice to expose an
        #             api to specify specific hosts to force onto, but for
        #             now it just supports this legacy hack.
        host = None
        if availability_zone:
            availability_zone, _x, host = availability_zone.partition(':')
        if not availability_zone:
            availability_zone = FLAGS.default_schedule_zone
        if context.is_admin and host:
            filter_properties = {'force_hosts': [host]}
        else:
            filter_properties = {}

        filter_properties['scheduler_hints'] = scheduler_hints

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
            'launch_time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'instance_type_id': instance_type['id'],
            'memory_mb': instance_type['memory_mb'],
            'vcpus': instance_type['vcpus'],
            'root_gb': instance_type['root_gb'],
            'ephemeral_gb': instance_type['ephemeral_gb'],
            'display_name': display_name,
            'display_description': display_description,
            'user_data': user_data or '',
            'key_name': key_name,
            'key_data': key_data,
            'locked': False,
            'metadata': metadata,
            'access_ip_v4': access_ip_v4,
            'access_ip_v6': access_ip_v6,
            'availability_zone': availability_zone,
            'os_type': os_type,
            'architecture': architecture,
            'vm_mode': vm_mode,
            'root_device_name': root_device_name,
            'progress': 0,
            'auto_disk_config': auto_disk_config}

        LOG.debug(_("Going to run %s instances...") % num_instances)

        if create_instance_here:
            instance = self.create_db_entry_for_new_instance(
                    context, instance_type, image, base_options,
                    security_group, block_device_mapping)
            # Tells scheduler we created the instance already.
            base_options['uuid'] = instance['uuid']
            rpc_method = rpc.cast
        else:
            # We need to wait for the scheduler to create the instance
            # DB entries, because the instance *could* be # created in
            # a child zone.
            rpc_method = rpc.call

        # TODO(comstud): We should use rpc.multicall when we can
        # retrieve the full instance dictionary from the scheduler.
        # Otherwise, we could exceed the AMQP max message size limit.
        # This would require the schedulers' schedule_run_instances
        # methods to return an iterator vs a list.
        instances = self._schedule_run_instance(
                rpc_method,
                context, base_options,
                instance_type,
                availability_zone, injected_files,
                admin_password, image,
                num_instances, requested_networks,
                block_device_mapping, security_group,
                filter_properties)

        if create_instance_here:
            return ([instance], reservation_id)
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
                                           instance_type, instance_id,
                                           mappings):
        """tell vm driver to create ephemeral/swap device at boot time by
        updating BlockDeviceMapping
        """
        instance_type = (instance_type or
                         instance_types.get_default_instance_type())

        for bdm in block_device.mappings_prepend_dev(mappings):
            LOG.debug(_("bdm %s"), bdm)

            virtual_name = bdm['virtual']
            if virtual_name == 'ami' or virtual_name == 'root':
                continue

            if not block_device.is_swap_or_ephemeral(virtual_name):
                continue

            size = self._volume_size(instance_type, virtual_name)
            if size == 0:
                continue

            values = {
                'instance_id': instance_id,
                'device_name': bdm['device'],
                'virtual_name': virtual_name,
                'volume_size': size}
            self.db.block_device_mapping_update_or_create(elevated_context,
                                                          values)

    def _update_block_device_mapping(self, elevated_context,
                                     instance_type, instance_id,
                                     block_device_mapping):
        """tell vm driver to attach volume at boot time by updating
        BlockDeviceMapping
        """
        LOG.debug(_("block_device_mapping %s"), block_device_mapping)
        for bdm in block_device_mapping:
            assert 'device_name' in bdm

            values = {'instance_id': instance_id}
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
                for k in ('delete_on_termination', 'volume_id',
                          'snapshot_id', 'volume_id', 'volume_size',
                          'virtual_name'):
                    values[k] = None

            self.db.block_device_mapping_update_or_create(elevated_context,
                                                          values)

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
        elevated = context.elevated()
        if security_group is None:
            security_group = ['default']
        if not isinstance(security_group, list):
            security_group = [security_group]

        security_groups = []
        for security_group_name in security_group:
            group = self.db.security_group_get_by_name(context,
                    context.project_id,
                    security_group_name)
            security_groups.append(group['id'])

        base_options.setdefault('launch_index', 0)
        instance = self.db.instance_create(context, base_options)
        instance_id = instance['id']
        instance_uuid = instance['uuid']

        for security_group_id in security_groups:
            self.db.instance_add_security_group(elevated,
                                                instance_uuid,
                                                security_group_id)

        # BlockDeviceMapping table
        self._update_image_block_device_mapping(elevated, instance_type,
            instance_id, image['properties'].get('mappings', []))
        self._update_block_device_mapping(elevated, instance_type, instance_id,
            image['properties'].get('block_device_mapping', []))
        # override via command line option
        self._update_block_device_mapping(elevated, instance_type, instance_id,
                                          block_device_mapping)

        # Set sane defaults if not specified
        updates = {}

        display_name = instance.get('display_name')
        if display_name is None:
            display_name = self._default_display_name(instance_id)

        hostname = instance.get('hostname')
        if hostname is None:
            hostname = display_name

        updates['display_name'] = display_name
        updates['hostname'] = utils.sanitize_hostname(hostname)
        updates['vm_state'] = vm_states.BUILDING
        updates['task_state'] = task_states.SCHEDULING

        if (image['properties'].get('mappings', []) or
            image['properties'].get('block_device_mapping', []) or
            block_device_mapping):
            updates['shutdown_terminate'] = False

        instance = self.update(context, instance, **updates)
        return instance

    def _default_display_name(self, instance_id):
        return "Server %s" % instance_id

    def _schedule_run_instance(self,
            rpc_method,
            context, base_options,
            instance_type,
            availability_zone, injected_files,
            admin_password, image,
            num_instances,
            requested_networks,
            block_device_mapping,
            security_group,
            filter_properties):
        """Send a run_instance request to the schedulers for processing."""

        pid = context.project_id
        uid = context.user_id

        LOG.debug(_("Sending create to scheduler for %(pid)s/%(uid)s's") %
                locals())

        request_spec = {
            'image': utils.to_primitive(image),
            'instance_properties': base_options,
            'instance_type': instance_type,
            'num_instances': num_instances,
            'block_device_mapping': block_device_mapping,
            'security_group': security_group,
        }

        return rpc_method(context,
                FLAGS.scheduler_topic,
                {"method": "run_instance",
                 "args": {"topic": FLAGS.compute_topic,
                          "request_spec": request_spec,
                          "admin_password": admin_password,
                          "injected_files": injected_files,
                          "requested_networks": requested_networks,
                          "is_first_time": True,
                          "filter_properties": filter_properties}})

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

        Returns a tuple of (instances, reservation_id) where instances
        could be 'None' or a list of instance dicts depending on if
        we waited for information from the scheduler or not.
        """

        self._check_create_policies(context, availability_zone,
                requested_networks, block_device_mapping)

        # We can create the DB entry for the instance here if we're
        # only going to create 1 instance.
        # This speeds up API responses for builds
        # as we don't need to wait for the scheduler.
        create_instance_here = max_count == 1

        (instances, reservation_id) = self._create_instance(
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
                               create_instance_here=create_instance_here,
                               scheduler_hints=scheduler_hints)

        if create_instance_here or instances is None:
            return (instances, reservation_id)

        inst_ret_list = []
        for instance in instances:
            if instance.get('_is_precooked', False):
                inst_ret_list.append(instance)
            else:
                # Scheduler only gives us the 'id'.  We need to pull
                # in the created instances from the DB
                instance = self.db.instance_get(context, instance['id'])
                inst_ret_list.append(dict(instance.iteritems()))

        return (inst_ret_list, reservation_id)

    def ensure_default_security_group(self, context):
        """Ensure that a context has a security group.

        Creates a security group for the security context if it does not
        already exist.

        :param context: the security context
        """
        try:
            self.db.security_group_get_by_name(context,
                                               context.project_id,
                                               'default')
        except exception.NotFound:
            values = {'name': 'default',
                      'description': 'default',
                      'user_id': context.user_id,
                      'project_id': context.project_id}
            self.db.security_group_create(context, values)

    def trigger_security_group_rules_refresh(self, context, security_group_id):
        """Called when a rule is added to or removed from a security_group."""

        security_group = self.db.security_group_get(context, security_group_id)

        hosts = set()
        for instance in security_group['instances']:
            if instance['host'] is not None:
                hosts.add(instance['host'])

        for host in hosts:
            rpc.cast(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, host),
                     {"method": "refresh_security_group_rules",
                      "args": {"security_group_id": security_group.id}})

    def trigger_security_group_members_refresh(self, context, group_ids):
        """Called when a security group gains a new or loses a member.

        Sends an update request to each compute node for whom this is
        relevant.
        """
        # First, we get the security group rules that reference these groups as
        # the grantee..
        security_group_rules = set()
        for group_id in group_ids:
            security_group_rules.update(
                self.db.security_group_rule_get_by_security_group_grantee(
                                                                     context,
                                                                     group_id))

        # ..then we distill the security groups to which they belong..
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

        # ...then we find the hosts where they live...
        hosts = set()
        for instance in instances:
            if instance['host']:
                hosts.add(instance['host'])

        # ...and finally we tell these nodes to refresh their view of this
        # particular security group.
        for host in hosts:
            rpc.cast(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, host),
                     {"method": "refresh_security_group_members",
                      "args": {"security_group_id": group_id}})

    def trigger_provider_fw_rules_refresh(self, context):
        """Called when a rule is added/removed from a provider firewall"""

        hosts = [x['host'] for (x, idx)
                           in self.db.service_get_all_compute_sorted(context)]
        for host in hosts:
            rpc.cast(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, host),
                     {'method': 'refresh_provider_fw_rules', 'args': {}})

    def _is_security_group_associated_with_server(self, security_group,
                                                  instance_uuid):
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

    @wrap_check_policy
    def add_security_group(self, context, instance, security_group_name):
        """Add security group to the instance"""
        security_group = self.db.security_group_get_by_name(context,
                context.project_id,
                security_group_name)

        instance_uuid = instance['uuid']

        #check if the security group is associated with the server
        if self._is_security_group_associated_with_server(security_group,
                                                          instance_uuid):
            raise exception.SecurityGroupExistsForInstance(
                                        security_group_id=security_group['id'],
                                        instance_id=instance_uuid)

        #check if the instance is in running state
        if instance['power_state'] != power_state.RUNNING:
            raise exception.InstanceNotRunning(instance_id=instance_uuid)

        self.db.instance_add_security_group(context.elevated(),
                                            instance_uuid,
                                            security_group['id'])
        params = {"security_group_id": security_group['id']}
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        self._cast_compute_message('refresh_security_group_rules',
                context, host=instance['host'], params=params)

    @wrap_check_policy
    def remove_security_group(self, context, instance, security_group_name):
        """Remove the security group associated with the instance"""
        security_group = self.db.security_group_get_by_name(context,
                context.project_id,
                security_group_name)

        instance_uuid = instance['uuid']

        #check if the security group is associated with the server
        if not self._is_security_group_associated_with_server(security_group,
                                                              instance_uuid):
            raise exception.SecurityGroupNotExistsForInstance(
                                    security_group_id=security_group['id'],
                                    instance_id=instance_uuid)

        #check if the instance is in running state
        if instance['power_state'] != power_state.RUNNING:
            raise exception.InstanceNotRunning(instance_id=instance_uuid)

        self.db.instance_remove_security_group(context.elevated(),
                                               instance_uuid,
                                               security_group['id'])
        params = {"security_group_id": security_group['id']}
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        self._cast_compute_message('refresh_security_group_rules',
                context, host=instance['host'], params=params)

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
        rv = self.db.instance_update(context, instance["id"], kwargs)
        return dict(rv.iteritems())

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF,
                                    vm_states.ERROR])
    def soft_delete(self, context, instance):
        """Terminate an instance."""
        LOG.debug(_('Going to try to soft delete instance'),
                  instance=instance)

        if instance['disable_terminate']:
            return

        # NOTE(jerdfelt): The compute daemon handles reclaiming instances
        # that are in soft delete. If there is no host assigned, there is
        # no daemon to reclaim, so delete it immediately.
        host = instance['host']
        if host:
            self.update(context,
                        instance,
                        vm_state=vm_states.SOFT_DELETE,
                        task_state=task_states.POWERING_OFF,
                        deleted_at=utils.utcnow())

            self._cast_compute_message('power_off_instance',
                    context, instance)
        else:
            LOG.warning(_('No host for instance, deleting immediately'),
                        instance=instance)
            try:
                self.db.instance_destroy(context, instance['id'])
            except exception.InstanceNotFound:
                # NOTE(comstud): Race condition.  Instance already gone.
                pass

    def _delete(self, context, instance):
        host = instance['host']
        try:
            if not host:
                # Just update database, nothing else we can do
                return self.db.instance_destroy(context, instance['id'])

            self.update(context,
                        instance,
                        task_state=task_states.DELETING,
                        progress=0)

            if instance['task_state'] == task_states.RESIZE_VERIFY:
                # If in the middle of a resize, use confirm_resize to
                # ensure the original instance is cleaned up too
                migration_ref = self.db.migration_get_by_instance_and_status(
                        context, instance['uuid'], 'finished')
                if migration_ref:
                    src_host = migration_ref['source_compute']
                    params = {'migration_id': migration_ref['id']}
                    # Call since this can race with the terminate_instance
                    self._call_compute_message('confirm_resize', context,
                                               instance, host=src_host,
                                               params=params)

            self._cast_compute_message('terminate_instance',
                                       context, instance)
        except exception.InstanceNotFound:
            # NOTE(comstud): Race condition. Instance already gone.
            pass

    # NOTE(jerdfelt): The API implies that only ACTIVE and ERROR are
    # allowed but the EC2 API appears to allow from RESCUED and STOPPED
    # too
    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.BUILDING,
                                    vm_states.ERROR, vm_states.RESCUED,
                                    vm_states.SHUTOFF, vm_states.STOPPED])
    def delete(self, context, instance):
        """Terminate an instance."""
        LOG.debug(_("Going to try to terminate instance"), instance=instance)

        if instance['disable_terminate']:
            return

        self._delete(context, instance)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.SOFT_DELETE])
    def restore(self, context, instance):
        """Restore a previously deleted (but not reclaimed) instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=None,
                    deleted_at=None)

        host = instance['host']
        if host:
            self.update(context,
                        instance,
                        task_state=task_states.POWERING_ON)
            self._cast_compute_message('power_on_instance',
                    context, instance)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.SOFT_DELETE])
    def force_delete(self, context, instance):
        """Force delete a previously deleted (but not reclaimed) instance."""
        self._delete(context, instance)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF,
                                    vm_states.RESCUED],
                          task_state=[None, task_states.RESIZE_VERIFY])
    def stop(self, context, instance, do_cast=True):
        """Stop an instance."""
        instance_uuid = instance["uuid"]
        LOG.debug(_("Going to try to stop instance"), instance=instance)

        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=task_states.STOPPING,
                    terminated_at=utils.utcnow(),
                    progress=0)

        rpc_method = rpc.cast if do_cast else rpc.call
        self._cast_or_call_compute_message(rpc_method, 'stop_instance',
                context, instance)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.STOPPED, vm_states.SHUTOFF])
    def start(self, context, instance):
        """Start an instance."""
        vm_state = instance["vm_state"]
        instance_uuid = instance["uuid"]
        LOG.debug(_("Going to try to start instance"), instance=instance)

        if vm_state == vm_states.SHUTOFF:
            if instance['shutdown_terminate']:
                LOG.warning(_("Instance %(instance_uuid)s is not "
                              "stopped. (%(vm_state)s") % locals())
                return

            # NOTE(yamahata): nova compute doesn't reap instances
            # which initiated shutdown itself. So reap it here.
            self.stop(context, instance, do_cast=False)

        self.update(context,
                    instance,
                    vm_state=vm_states.STOPPED,
                    task_state=task_states.STARTING)

        # TODO(yamahata): injected_files isn't supported right now.
        #                 It is used only for osapi. not for ec2 api.
        #                 availability_zone isn't used by run_instance.
        self._cast_compute_message('start_instance', context, instance)

    #NOTE(bcwaldon): no policy check here since it should be rolled in to
    # search_opts in get_all
    def get_active_by_window(self, context, begin, end=None, project_id=None):
        """Get instances that were continuously active over a window."""
        return self.db.instance_get_active_by_window(context, begin, end,
                                                     project_id)

    #NOTE(bcwaldon): this doesn't really belong in this class
    def get_instance_type(self, context, instance_type_id):
        """Get an instance type by instance type id."""
        return instance_types.get_instance_type(instance_type_id)

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
                sort_dir='desc'):
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
                'instance_name': 'name',
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
                                                     sort_key, sort_dir)

        # Convert the models to dictionaries
        instances = []
        for inst_model in inst_models:
            instance = dict(inst_model.iteritems())
            # NOTE(comstud): Doesn't get returned by iteritems
            instance['name'] = inst_model['name']
            instances.append(instance)

        return instances

    def _get_instances_by_filters(self, context, filters, sort_key, sort_dir):
        if 'ip6' in filters or 'ip' in filters:
            res = self.network_api.get_instance_uuids_by_ip_filter(context,
                                                                   filters)
            # NOTE(jkoelker) It is possible that we will get the same
            #                instance uuid twice (one for ipv4 and ipv6)
            uuids = set([r['instance_uuid'] for r in res])
            filters['uuid'] = uuids

        return self.db.instance_get_all_by_filters(context, filters, sort_key,
                                                   sort_dir)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF])
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
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF])
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

        self.db.instance_test_and_set(
                context, instance_uuid, 'task_state', [None], task_state)

        properties = {
            'instance_uuid': instance_uuid,
            'user_id': str(context.user_id),
            'image_type': image_type,
        }

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
        params = {'image_id': recv_meta['id'], 'image_type': image_type,
                  'backup_type': backup_type, 'rotation': rotation}
        self._cast_compute_message('snapshot_instance', context, instance,
                params=params)
        return recv_meta

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
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF,
                                    vm_states.RESCUED],
                          task_state=[None, task_states.RESIZE_VERIFY])
    def reboot(self, context, instance, reboot_type):
        """Reboot the given instance."""
        state = {'SOFT': task_states.REBOOTING,
                 'HARD': task_states.REBOOTING_HARD}[reboot_type]
        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=state)
        self._cast_compute_message('reboot_instance', context, instance,
                params={'reboot_type': reboot_type})

    def _validate_image_href(self, context, image_href):
        """Throws an ImageNotFound exception if image_href does not exist."""
        (image_service, image_id) = nova.image.get_image_service(context,
                                                                 image_href)
        image_service.show(context, image_id)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF],
                          task_state=[None, task_states.RESIZE_VERIFY])
    def rebuild(self, context, instance, image_href, admin_password, **kwargs):
        """Rebuild the given instance with the provided attributes."""

        self._validate_image_href(context, image_href)

        files_to_inject = kwargs.pop('files_to_inject', [])
        self._check_injected_file_quota(context, files_to_inject)

        metadata = kwargs.get('metadata', {})
        self._check_metadata_properties_quota(context, metadata)

        self.update(context,
                    instance,
                    image_ref=image_href,
                    vm_state=vm_states.REBUILDING,
                    task_state=None,
                    progress=0,
                    **kwargs)

        rebuild_params = {
            "new_pass": admin_password,
            "injected_files": files_to_inject,
        }

        self._cast_compute_message('rebuild_instance', context, instance,
                params=rebuild_params)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF],
                          task_state=[task_states.RESIZE_VERIFY])
    def revert_resize(self, context, instance):
        """Reverts a resize, deleting the 'new' instance in the process."""
        context = context.elevated()
        migration_ref = self.db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'finished')
        if not migration_ref:
            raise exception.MigrationNotFoundByStatus(
                    instance_id=instance['uuid'], status='finished')

        self.update(context,
                    instance,
                    vm_state=vm_states.RESIZING,
                    task_state=task_states.RESIZE_REVERTING)

        params = {'migration_id': migration_ref['id']}
        self._cast_compute_message('revert_resize', context, instance,
                host=migration_ref['dest_compute'], params=params)

        self.db.migration_update(context, migration_ref['id'],
                                 {'status': 'reverted'})

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF],
                          task_state=[task_states.RESIZE_VERIFY])
    def confirm_resize(self, context, instance):
        """Confirms a migration/resize and deletes the 'old' instance."""
        context = context.elevated()
        migration_ref = self.db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'finished')
        if not migration_ref:
            raise exception.MigrationNotFoundByStatus(
                    instance_id=instance['uuid'], status='finished')

        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=None)

        params = {'migration_id': migration_ref['id']}
        self._cast_compute_message('confirm_resize', context, instance,
                host=migration_ref['source_compute'], params=params)

        self.db.migration_update(context, migration_ref['id'],
                {'status': 'confirmed'})
        self.db.instance_update(context, instance['uuid'],
                {'host': migration_ref['dest_compute'], })

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF],
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
            LOG.debug(_("flavor_id is None. Assuming migration."))
            new_instance_type = current_instance_type
        else:
            new_instance_type = instance_types.get_instance_type_by_flavor_id(
                    flavor_id)

        current_instance_type_name = current_instance_type['name']
        new_instance_type_name = new_instance_type['name']
        LOG.debug(_("Old instance type %(current_instance_type_name)s, "
                " new instance type %(new_instance_type_name)s") % locals())
        if not new_instance_type:
            raise exception.FlavorNotFound(flavor_id=flavor_id)

        # NOTE(markwash): look up the image early to avoid auth problems later
        image = self.image_service.show(context, instance['image_ref'])

        current_memory_mb = current_instance_type['memory_mb']
        new_memory_mb = new_instance_type['memory_mb']

        if (current_memory_mb == new_memory_mb) and flavor_id:
            raise exception.CannotResizeToSameSize()

        self.update(context,
                    instance,
                    vm_state=vm_states.RESIZING,
                    task_state=task_states.RESIZE_PREP,
                    progress=0,
                    **kwargs)

        request_spec = {
                'instance_type': new_instance_type,
                'num_instances': 1,
                'instance_properties': instance}

        filter_properties = {'ignore_hosts': []}

        if not FLAGS.allow_resize_to_same_host:
            filter_properties['ignore_hosts'].append(instance['host'])

        args = {
            "topic": FLAGS.compute_topic,
            "instance_uuid": instance['uuid'],
            "instance_type_id": new_instance_type['id'],
            "image": image,
            "update_db": False,
            "request_spec": utils.to_primitive(request_spec),
            "filter_properties": filter_properties,
        }
        self._cast_scheduler_message(context,
                    {"method": "prep_resize",
                     "args": args})

    @wrap_check_policy
    def add_fixed_ip(self, context, instance, network_id):
        """Add fixed_ip from specified network to given instance."""
        self._cast_compute_message('add_fixed_ip_to_instance', context,
                instance, params=dict(network_id=network_id))

    @wrap_check_policy
    def remove_fixed_ip(self, context, instance, address):
        """Remove fixed_ip from specified network to given instance."""
        self._cast_compute_message('remove_fixed_ip_from_instance',
                context, instance, params=dict(address=address))

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF,
                                    vm_states.RESCUED],
                          task_state=[None, task_states.RESIZE_VERIFY])
    def pause(self, context, instance):
        """Pause the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=task_states.PAUSING)
        self._cast_compute_message('pause_instance', context, instance)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.PAUSED])
    def unpause(self, context, instance):
        """Unpause the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.PAUSED,
                    task_state=task_states.UNPAUSING)
        self._cast_compute_message('unpause_instance', context, instance)

    @wrap_check_policy
    def get_diagnostics(self, context, instance):
        """Retrieve diagnostics for the given instance."""
        return self._call_compute_message("get_diagnostics", context,
                instance)

    @wrap_check_policy
    def get_actions(self, context, instance):
        """Retrieve actions for the given instance."""
        return self.db.instance_get_actions(context, instance['uuid'])

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF,
                                    vm_states.RESCUED],
                          task_state=[None, task_states.RESIZE_VERIFY])
    def suspend(self, context, instance):
        """Suspend the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=task_states.SUSPENDING)
        self._cast_compute_message('suspend_instance', context, instance)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.SUSPENDED])
    def resume(self, context, instance):
        """Resume the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.SUSPENDED,
                    task_state=task_states.RESUMING)
        self._cast_compute_message('resume_instance', context, instance)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.SHUTOFF,
                                    vm_states.STOPPED],
                          task_state=[None, task_states.RESIZE_VERIFY])
    def rescue(self, context, instance, rescue_password=None):
        """Rescue the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.ACTIVE,
                    task_state=task_states.RESCUING)

        rescue_params = {
            "rescue_password": rescue_password
        }
        self._cast_compute_message('rescue_instance', context, instance,
                params=rescue_params)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.RESCUED])
    def unrescue(self, context, instance):
        """Unrescue the given instance."""
        self.update(context,
                    instance,
                    vm_state=vm_states.RESCUED,
                    task_state=task_states.UNRESCUING)
        self._cast_compute_message('unrescue_instance', context, instance)

    @wrap_check_policy
    @check_instance_state(vm_state=[vm_states.ACTIVE])
    def set_admin_password(self, context, instance, password=None):
        """Set the root/admin password for the given instance."""
        self.update(context,
                    instance,
                    task_state=task_states.UPDATING_PASSWORD)

        params = {"new_pass": password}
        self._cast_compute_message('set_admin_password', context, instance,
                params=params)

    @wrap_check_policy
    def inject_file(self, context, instance, path, file_contents):
        """Write a file to the given instance."""
        params = {'path': path, 'file_contents': file_contents}
        self._cast_compute_message('inject_file', context, instance,
                params=params)

    @wrap_check_policy
    def get_vnc_console(self, context, instance, console_type):
        """Get a url to an instance Console."""
        connect_info = self._call_compute_message('get_vnc_console',
                context, instance, params={"console_type": console_type})

        rpc.call(context, '%s' % FLAGS.consoleauth_topic,
                 {'method': 'authorize_console',
                  'args': {'token': connect_info['token'],
                           'console_type': console_type,
                           'host': connect_info['host'],
                           'port': connect_info['port'],
                           'internal_access_path':
                                   connect_info['internal_access_path']}})

        return {'url': connect_info['access_url']}

    @wrap_check_policy
    def get_console_output(self, context, instance, tail_length=None):
        """Get console output for an an instance."""
        params = {'tail_length': tail_length}
        return self._call_compute_message('get_console_output', context,
                instance, params=params)

    @wrap_check_policy
    def lock(self, context, instance):
        """Lock the given instance."""
        self._cast_compute_message('lock_instance', context, instance)

    @wrap_check_policy
    def unlock(self, context, instance):
        """Unlock the given instance."""
        self._cast_compute_message('unlock_instance', context, instance)

    @wrap_check_policy
    def get_lock(self, context, instance):
        """Return the boolean state of given instance's lock."""
        return self.get(context, instance['uuid'])['locked']

    @wrap_check_policy
    def reset_network(self, context, instance):
        """Reset networking on the instance."""
        self._cast_compute_message('reset_network', context, instance)

    @wrap_check_policy
    def inject_network_info(self, context, instance):
        """Inject network info for the instance."""
        self._cast_compute_message('inject_network_info', context, instance)

    @wrap_check_policy
    def attach_volume(self, context, instance, volume_id, device):
        """Attach an existing volume to an existing instance."""
        if not re.match("^/dev/x{0,1}[a-z]d[a-z]+$", device):
            raise exception.InvalidDevicePath(path=device)
        volume = self.volume_api.get(context, volume_id)
        self.volume_api.check_attach(context, volume)
        self.volume_api.reserve_volume(context, volume)
        params = {"volume_id": volume_id,
                  "mountpoint": device}
        self._cast_compute_message('attach_volume', context, instance,
                params=params)

    # FIXME(comstud): I wonder if API should pull in the instance from
    # the volume ID via volume API and pass it and the volume object here
    def detach_volume(self, context, volume_id):
        """Detach a volume from an instance."""
        instance = self.db.volume_get_instance(context.elevated(), volume_id)
        if not instance:
            raise exception.VolumeUnattached(volume_id=volume_id)

        check_policy(context, 'detach_volume', instance)

        volume = self.volume_api.get(context, volume_id)
        self.volume_api.check_detach(context, volume)

        params = {'volume_id': volume_id}
        self._cast_compute_message('detach_volume', context, instance,
                params=params)
        return instance

    @wrap_check_policy
    def associate_floating_ip(self, context, instance, address):
        """Makes calls to network_api to associate_floating_ip.

        :param address: is a string floating ip address
        """
        instance_uuid = instance['uuid']

        # TODO(tr3buchet): currently network_info doesn't contain floating IPs
        # in its info, if this changes, the next few lines will need to
        # accommodate the info containing floating as well as fixed ip
        # addresses
        nw_info = self.network_api.get_instance_nw_info(context.elevated(),
                                                        instance)

        if not nw_info:
            raise exception.FixedIpNotFoundForInstance(
                    instance_id=instance_uuid)

        ips = [ip for ip in nw_info[0].fixed_ips()]

        if not ips:
            raise exception.FixedIpNotFoundForInstance(
                    instance_id=instance_uuid)

        # TODO(tr3buchet): this will associate the floating IP with the
        # first fixed_ip (lowest id) an instance has. This should be
        # changed to support specifying a particular fixed_ip if
        # multiple exist.
        if len(ips) > 1:
            msg = _('multiple fixedips exist, using the first: %s')
            LOG.warning(msg, ips[0]['address'])

        self.network_api.associate_floating_ip(context,
                floating_address=address, fixed_address=ips[0]['address'])

    @wrap_check_policy
    def get_instance_metadata(self, context, instance):
        """Get all metadata associated with an instance."""
        rv = self.db.instance_metadata_get(context, instance['id'])
        return dict(rv.iteritems())

    @wrap_check_policy
    def delete_instance_metadata(self, context, instance, key):
        """Delete the given metadata item from an instance."""
        self.db.instance_metadata_delete(context, instance['id'], key)

    @wrap_check_policy
    def update_instance_metadata(self, context, instance,
                                 metadata, delete=False):
        """Updates or creates instance metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if delete:
            _metadata = metadata
        else:
            _metadata = self.get_instance_metadata(context, instance)
            _metadata.update(metadata)

        self._check_metadata_properties_quota(context, _metadata)
        self.db.instance_metadata_update(context, instance['id'],
                                         _metadata, True)
        return _metadata

    def get_instance_faults(self, context, instances):
        """Get all faults for a list of instance uuids."""

        if not instances:
            return {}

        for instance in instances:
            check_policy(context, 'get_instance_faults', instance)

        uuids = [instance['uuid'] for instance in instances]
        return self.db.instance_fault_get_by_instance_uuids(context, uuids)


class HostAPI(BaseAPI):
    """Sub-set of the Compute Manager API for managing host operations."""
    def set_host_enabled(self, context, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        return self._call_compute_message("set_host_enabled", context,
                host=host, params={"enabled": enabled})

    def host_power_action(self, context, host, action):
        """Reboots, shuts down or powers up the host."""
        # NOTE(comstud): No instance_uuid argument to this compute manager
        # call
        return self._call_compute_message("host_power_action", context,
                host=host, params={"action": action})

    def set_host_maintenance(self, context, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation."""
        return self._call_compute_message("host_maintenance_mode", context,
                host=host, params={"host": host, "mode": mode})


class AggregateAPI(base.Base):
    """Sub-set of the Compute Manager API for managing host aggregates."""
    def __init__(self, **kwargs):
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
            return dict(aggregate.iteritems())
        else:
            raise exception.InvalidAggregateAction(action='create_aggregate',
                                                   aggregate_id="'N/A'",
                                                   reason='invalid zone')

    def get_aggregate(self, context, aggregate_id):
        """Get an aggregate by id."""
        aggregate = self.db.aggregate_get(context, aggregate_id)
        return self._get_aggregate_info(context, aggregate)

    def get_aggregate_list(self, context):
        """Get all the aggregates for this zone."""
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
        # As a first release of the host aggregates blueprint, this call is
        # pretty dumb, in the sense that interacts only with the model.
        # In later releasses, updating metadata may trigger virt actions like
        # the setup of shared storage, or more generally changes to the
        # underlying hypervisor pools.
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
        # add host, and reflects action in the aggregate operational state
        aggregate = self.db.aggregate_get(context, aggregate_id)
        if aggregate.operational_state in [aggregate_states.CREATED,
                                           aggregate_states.ACTIVE]:
            if service.availability_zone != aggregate.availability_zone:
                raise exception.InvalidAggregateAction(
                        action='add host',
                        aggregate_id=aggregate_id,
                        reason='availibility zone mismatch')
            self.db.aggregate_host_add(context, aggregate_id, host)
            if aggregate.operational_state == aggregate_states.CREATED:
                values = {'operational_state': aggregate_states.CHANGING}
                self.db.aggregate_update(context, aggregate_id, values)
            queue = self.db.queue_get_for(context, service.topic, host)
            rpc.cast(context, queue, {"method": "add_aggregate_host",
                                      "args": {"aggregate_id": aggregate_id,
                                               "host": host}, })
            return self.get_aggregate(context, aggregate_id)
        else:
            invalid = {aggregate_states.CHANGING: 'setup in progress',
                       aggregate_states.DISMISSED: 'aggregate deleted',
                       aggregate_states.ERROR: 'aggregate in error', }
            if aggregate.operational_state in invalid.keys():
                raise exception.InvalidAggregateAction(
                        action='add host',
                        aggregate_id=aggregate_id,
                        reason=invalid[aggregate.operational_state])

    def remove_host_from_aggregate(self, context, aggregate_id, host):
        """Removes host from the aggregate."""
        # validates the host; ComputeHostNotFound is raised if invalid
        service = self.db.service_get_all_compute_by_host(context, host)[0]
        aggregate = self.db.aggregate_get(context, aggregate_id)
        if aggregate.operational_state in [aggregate_states.ACTIVE,
                                           aggregate_states.ERROR]:
            self.db.aggregate_host_delete(context, aggregate_id, host)
            queue = self.db.queue_get_for(context, service.topic, host)
            rpc.cast(context, queue, {"method": "remove_aggregate_host",
                                      "args": {"aggregate_id": aggregate_id,
                                               "host": host}, })
            return self.get_aggregate(context, aggregate_id)
        else:
            invalid = {aggregate_states.CREATED: 'no hosts to remove',
                       aggregate_states.CHANGING: 'setup in progress',
                       aggregate_states.DISMISSED: 'aggregate deleted', }
            if aggregate.operational_state in invalid.keys():
                raise exception.InvalidAggregateAction(
                        action='remove host',
                        aggregate_id=aggregate_id,
                        reason=invalid[aggregate.operational_state])

    def _get_aggregate_info(self, context, aggregate):
        """Builds a dictionary with aggregate props, metadata and hosts."""
        metadata = self.db.aggregate_metadata_get(context, aggregate.id)
        hosts = self.db.aggregate_host_get_all(context, aggregate.id)
        result = dict(aggregate.iteritems())
        result["metadata"] = metadata
        result["hosts"] = hosts
        return result
