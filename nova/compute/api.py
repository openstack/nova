# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Handles all requests relating to instances (guest vms)."""

import eventlet
import re
import time

from nova import db
from nova import exception
from nova import flags
import nova.image
from nova import log as logging
from nova import network
from nova import quota
from nova import rpc
from nova import utils
from nova import volume
from nova.compute import instance_types
from nova.compute import power_state
from nova.compute.utils import terminate_volumes
from nova.scheduler import api as scheduler_api
from nova.db import base


LOG = logging.getLogger('nova.compute.api')


FLAGS = flags.FLAGS
flags.DECLARE('vncproxy_topic', 'nova.vnc')
flags.DEFINE_integer('find_host_timeout', 30,
                     'Timeout after NN seconds when looking for a host.')


def generate_default_hostname(instance):
    """Default function to generate a hostname given an instance reference."""
    display_name = instance['display_name']
    if display_name is None:
        return 'server_%d' % (instance['id'],)
    table = ''
    deletions = ''
    for i in xrange(256):
        c = chr(i)
        if ('a' <= c <= 'z') or ('0' <= c <= '9') or (c == '-'):
            table += c
        elif c == ' ':
            table += '_'
        elif ('A' <= c <= 'Z'):
            table += c.lower()
        else:
            table += '\0'
            deletions += c
    if isinstance(display_name, unicode):
        display_name = display_name.encode('latin-1', 'ignore')
    return display_name.translate(table, deletions)


def _is_able_to_shutdown(instance, instance_id):
    states = {'terminating': "Instance %s is already being terminated",
              'migrating': "Instance %s is being migrated",
              'stopping': "Instance %s is being stopped"}
    msg = states.get(instance['state_description'])
    if msg:
        LOG.warning(_(msg), instance_id)
        return False

    return True


class API(base.Base):
    """API for interacting with the compute manager."""

    def __init__(self, image_service=None, network_api=None,
                 volume_api=None, hostname_factory=generate_default_hostname,
                 **kwargs):
        self.image_service = image_service or \
                nova.image.get_default_image_service()

        if not network_api:
            network_api = network.API()
        self.network_api = network_api
        if not volume_api:
            volume_api = volume.API()
        self.volume_api = volume_api
        self.hostname_factory = hostname_factory
        super(API, self).__init__(**kwargs)

    def _check_injected_file_quota(self, context, injected_files):
        """Enforce quota limits on injected files.

        Raises a QuotaError if any limit is exceeded.
        """
        if injected_files is None:
            return
        limit = quota.allowed_injected_files(context, len(injected_files))
        if len(injected_files) > limit:
            raise quota.QuotaError(code="OnsetFileLimitExceeded")
        path_limit = quota.allowed_injected_file_path_bytes(context)
        for path, content in injected_files:
            if len(path) > path_limit:
                raise quota.QuotaError(code="OnsetFilePathLimitExceeded")
            content_limit = quota.allowed_injected_file_content_bytes(
                                                    context, len(content))
            if len(content) > content_limit:
                raise quota.QuotaError(code="OnsetFileContentLimitExceeded")

    def _check_metadata_properties_quota(self, context, metadata={}):
        """Enforce quota limits on metadata properties."""
        num_metadata = len(metadata)
        quota_metadata = quota.allowed_metadata_items(context, num_metadata)
        if quota_metadata < num_metadata:
            pid = context.project_id
            msg = _("Quota exceeeded for %(pid)s, tried to set "
                    "%(num_metadata)s metadata properties") % locals()
            LOG.warn(msg)
            raise quota.QuotaError(msg, "MetadataLimitExceeded")

        # Because metadata is stored in the DB, we hard-code the size limits
        # In future, we may support more variable length strings, so we act
        #  as if this is quota-controlled for forwards compatibility
        for k, v in metadata.iteritems():
            if len(k) > 255 or len(v) > 255:
                pid = context.project_id
                msg = _("Quota exceeeded for %(pid)s, metadata property "
                        "key or value too long") % locals()
                LOG.warn(msg)
                raise quota.QuotaError(msg, "MetadataLimitExceeded")

    def _check_create_parameters(self, context, instance_type,
               image_href, kernel_id=None, ramdisk_id=None,
               min_count=None, max_count=None,
               display_name='', display_description='',
               key_name=None, key_data=None, security_group='default',
               availability_zone=None, user_data=None, metadata={},
               injected_files=None, admin_password=None, zone_blob=None,
               reservation_id=None, vsa_id=None):
        """Verify all the input parameters regardless of the provisioning
        strategy being performed."""

        if not instance_type:
            instance_type = instance_types.get_default_instance_type()
        if not min_count:
            min_count = 1
        if not max_count:
            max_count = min_count

        num_instances = quota.allowed_instances(context, max_count,
                                                instance_type)
        if num_instances < min_count:
            pid = context.project_id
            LOG.warn(_("Quota exceeeded for %(pid)s,"
                    " tried to run %(min_count)s instances") % locals())
            if num_instances <= 0:
                message = _("Instance quota exceeded. You cannot run any "
                            "more instances of this type.")
            else:
                message = _("Instance quota exceeded. You can only run %s "
                            "more instances of this type.") % num_instances
            raise quota.QuotaError(message, "InstanceLimitExceeded")

        self._check_metadata_properties_quota(context, metadata)
        self._check_injected_file_quota(context, injected_files)

        (image_service, image_id) = nova.image.get_image_service(image_href)
        image = image_service.show(context, image_id)

        os_type = None
        if 'properties' in image and 'os_type' in image['properties']:
            os_type = image['properties']['os_type']
        architecture = None
        if 'properties' in image and 'arch' in image['properties']:
            architecture = image['properties']['arch']
        vm_mode = None
        if 'properties' in image and 'vm_mode' in image['properties']:
            vm_mode = image['properties']['vm_mode']

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
        logging.debug("Using Kernel=%s, Ramdisk=%s" %
                       (kernel_id, ramdisk_id))
        if kernel_id:
            image_service.show(context, kernel_id)
        if ramdisk_id:
            image_service.show(context, ramdisk_id)

        self.ensure_default_security_group(context)

        if key_data is None and key_name:
            key_pair = db.key_pair_get(context, context.user_id, key_name)
            key_data = key_pair['public_key']

        if reservation_id is None:
            reservation_id = utils.generate_uid('r')

        base_options = {
            'reservation_id': reservation_id,
            'image_ref': image_href,
            'kernel_id': kernel_id or '',
            'ramdisk_id': ramdisk_id or '',
            'state': 0,
            'state_description': 'scheduling',
            'user_id': context.user_id,
            'project_id': context.project_id,
            'launch_time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'instance_type_id': instance_type['id'],
            'memory_mb': instance_type['memory_mb'],
            'vcpus': instance_type['vcpus'],
            'local_gb': instance_type['local_gb'],
            'display_name': display_name,
            'display_description': display_description,
            'user_data': user_data or '',
            'key_name': key_name,
            'key_data': key_data,
            'locked': False,
            'metadata': metadata,
            'availability_zone': availability_zone,
            'os_type': os_type,
            'architecture': architecture,
            'vm_mode': vm_mode,
            'vsa_id': vsa_id}

        return (num_instances, base_options)

    def create_db_entry_for_new_instance(self, context, base_options,
             security_group, block_device_mapping, num=1):
        """Create an entry in the DB for this new instance,
        including any related table updates (such as security group,
        etc).

        This will called by create() in the majority of situations,
        but create_all_at_once() style Schedulers may initiate the call.
        If you are changing this method, be sure to update both
        call paths.
        """
        instance = dict(launch_index=num, **base_options)
        instance = self.db.instance_create(context, instance)
        instance_id = instance['id']

        elevated = context.elevated()
        if security_group is None:
            security_group = ['default']
        if not isinstance(security_group, list):
            security_group = [security_group]

        security_groups = []
        for security_group_name in security_group:
            group = db.security_group_get_by_name(context,
                                                  context.project_id,
                                                  security_group_name)
            security_groups.append(group['id'])

        for security_group_id in security_groups:
            self.db.instance_add_security_group(elevated,
                                                instance_id,
                                                security_group_id)

        block_device_mapping = block_device_mapping or []
        # NOTE(yamahata)
        # tell vm driver to attach volume at boot time by updating
        # BlockDeviceMapping
        for bdm in block_device_mapping:
            LOG.debug(_('bdm %s'), bdm)
            assert 'device_name' in bdm
            values = {
                'instance_id': instance_id,
                'device_name': bdm['device_name'],
                'delete_on_termination': bdm.get('delete_on_termination'),
                'virtual_name': bdm.get('virtual_name'),
                'snapshot_id': bdm.get('snapshot_id'),
                'volume_id': bdm.get('volume_id'),
                'volume_size': bdm.get('volume_size'),
                'no_device': bdm.get('no_device')}
            self.db.block_device_mapping_create(elevated, values)

        # Set sane defaults if not specified
        updates = {}
        if (not hasattr(instance, 'display_name') or
                instance.display_name is None):
            updates['display_name'] = "Server %s" % instance_id
            instance['display_name'] = updates['display_name']
        updates['hostname'] = self.hostname_factory(instance)

        instance = self.update(context, instance_id, **updates)

        for group_id in security_groups:
            self.trigger_security_group_members_refresh(elevated, group_id)

        return instance

    def _ask_scheduler_to_create_instance(self, context, base_options,
                                          instance_type, zone_blob,
                                          availability_zone, injected_files,
                                          admin_password,
                                          instance_id=None, num_instances=1):
        """Send the run_instance request to the schedulers for processing."""
        pid = context.project_id
        uid = context.user_id
        if instance_id:
            LOG.debug(_("Casting to scheduler for %(pid)s/%(uid)s's"
                    " instance %(instance_id)s (single-shot)") % locals())
        else:
            LOG.debug(_("Casting to scheduler for %(pid)s/%(uid)s's"
                    " (all-at-once)") % locals())

        filter_class = 'nova.scheduler.host_filter.InstanceTypeFilter'
        request_spec = {
            'instance_properties': base_options,
            'instance_type': instance_type,
            'filter': filter_class,
            'blob': zone_blob,
            'num_instances': num_instances,
        }

        rpc.cast(context,
                 FLAGS.scheduler_topic,
                 {"method": "run_instance",
                  "args": {"topic": FLAGS.compute_topic,
                           "instance_id": instance_id,
                           "request_spec": request_spec,
                           "availability_zone": availability_zone,
                           "admin_password": admin_password,
                           "injected_files": injected_files}})

    def create_all_at_once(self, context, instance_type,
               image_href, kernel_id=None, ramdisk_id=None,
               min_count=None, max_count=None,
               display_name='', display_description='',
               key_name=None, key_data=None, security_group='default',
               availability_zone=None, user_data=None, metadata={},
               injected_files=None, admin_password=None, zone_blob=None,
               reservation_id=None, block_device_mapping=None):
        """Provision the instances by passing the whole request to
        the Scheduler for execution. Returns a Reservation ID
        related to the creation of all of these instances."""
        num_instances, base_options = self._check_create_parameters(
                               context, instance_type,
                               image_href, kernel_id, ramdisk_id,
                               min_count, max_count,
                               display_name, display_description,
                               key_name, key_data, security_group,
                               availability_zone, user_data, metadata,
                               injected_files, admin_password, zone_blob,
                               reservation_id)

        self._ask_scheduler_to_create_instance(context, base_options,
                                      instance_type, zone_blob,
                                      availability_zone, injected_files,
                                      admin_password,
                                      num_instances=num_instances)

        return base_options['reservation_id']

    def create(self, context, instance_type,
               image_href, kernel_id=None, ramdisk_id=None,
               min_count=None, max_count=None,
               display_name='', display_description='',
               key_name=None, key_data=None, security_group='default',
               availability_zone=None, user_data=None, metadata={},
               injected_files=None, admin_password=None, zone_blob=None,
               reservation_id=None, block_device_mapping=None,
               vsa_id=None):
        """
        Provision the instances by sending off a series of single
        instance requests to the Schedulers. This is fine for trival
        Scheduler drivers, but may remove the effectiveness of the
        more complicated drivers.

        NOTE: If you change this method, be sure to change
        create_all_at_once() at the same time!

        Returns a list of instance dicts.
        """

        num_instances, base_options = self._check_create_parameters(
                               context, instance_type,
                               image_href, kernel_id, ramdisk_id,
                               min_count, max_count,
                               display_name, display_description,
                               key_name, key_data, security_group,
                               availability_zone, user_data, metadata,
                               injected_files, admin_password, zone_blob,
                               reservation_id, vsa_id)

        instances = []
        LOG.debug(_("Going to run %s instances..."), num_instances)
        for num in range(num_instances):
            instance = self.create_db_entry_for_new_instance(context,
                                    base_options, security_group,
                                    block_device_mapping, num=num)
            instances.append(instance)
            instance_id = instance['id']

            self._ask_scheduler_to_create_instance(context, base_options,
                                          instance_type, zone_blob,
                                          availability_zone, injected_files,
                                          admin_password,
                                          instance_id=instance_id)

        return [dict(x.iteritems()) for x in instances]

    def has_finished_migration(self, context, instance_id):
        """Returns true if an instance has a finished migration."""
        try:
            db.migration_get_by_instance_and_status(context, instance_id,
                    'finished')
            return True
        except exception.NotFound:
            return False

    def ensure_default_security_group(self, context):
        """Ensure that a context has a security group.

        Creates a security group for the security context if it does not
        already exist.

        :param context: the security context
        """
        try:
            db.security_group_get_by_name(context, context.project_id,
                                          'default')
        except exception.NotFound:
            values = {'name': 'default',
                      'description': 'default',
                      'user_id': context.user_id,
                      'project_id': context.project_id}
            db.security_group_create(context, values)

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

    def trigger_security_group_members_refresh(self, context, group_id):
        """Called when a security group gains a new or loses a member.

        Sends an update request to each compute node for whom this is
        relevant.
        """
        # First, we get the security group rules that reference this group as
        # the grantee..
        security_group_rules = \
                self.db.security_group_rule_get_by_security_group_grantee(
                                                                     context,
                                                                     group_id)

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
        """Called when a rule is added to or removed from a security_group"""

        hosts = [x['host'] for (x, idx)
                           in db.service_get_all_compute_sorted(context)]
        for host in hosts:
            rpc.cast(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, host),
                     {'method': 'refresh_provider_fw_rules', 'args': {}})

    def update(self, context, instance_id, **kwargs):
        """Updates the instance in the datastore.

        :param context: The security context
        :param instance_id: ID of the instance to update
        :param kwargs: All additional keyword args are treated
                       as data fields of the instance to be
                       updated

        :returns: None
        """
        rv = self.db.instance_update(context, instance_id, kwargs)
        return dict(rv.iteritems())

    def _get_instance(self, context, instance_id, action_str):
        try:
            return self.get(context, instance_id)
        except exception.NotFound:
            LOG.warning(_("Instance %(instance_id)s was not found during "
                          "%(action_str)s") %
                        {'instance_id': instance_id, 'action_str': action_str})
            raise

    @scheduler_api.reroute_compute("delete")
    def delete(self, context, instance_id):
        """Terminate an instance."""
        LOG.debug(_("Going to try to terminate %s"), instance_id)
        instance = self._get_instance(context, instance_id, 'terminating')

        if not _is_able_to_shutdown(instance, instance_id):
            return

        self.update(context,
                    instance['id'],
                    state_description='terminating',
                    state=0,
                    terminated_at=utils.utcnow())

        host = instance['host']
        if host:
            self._cast_compute_message('terminate_instance', context,
                    instance_id, host)
        else:
            terminate_volumes(self.db, context, instance_id)
            self.db.instance_destroy(context, instance_id)

    @scheduler_api.reroute_compute("stop")
    def stop(self, context, instance_id):
        """Stop an instance."""
        LOG.debug(_("Going to try to stop %s"), instance_id)

        instance = self._get_instance(context, instance_id, 'stopping')
        if not _is_able_to_shutdown(instance, instance_id):
            return

        self.update(context,
                    instance['id'],
                    state_description='stopping',
                    state=power_state.NOSTATE,
                    terminated_at=utils.utcnow())

        host = instance['host']
        if host:
            self._cast_compute_message('stop_instance', context,
                    instance_id, host)

    def start(self, context, instance_id):
        """Start an instance."""
        LOG.debug(_("Going to try to start %s"), instance_id)
        instance = self._get_instance(context, instance_id, 'starting')
        if instance['state_description'] != 'stopped':
            _state_description = instance['state_description']
            LOG.warning(_("Instance %(instance_id)s is not "
                          "stopped(%(_state_description)s)") % locals())
            return

        # TODO(yamahata): injected_files isn't supported right now.
        #                 It is used only for osapi. not for ec2 api.
        #                 availability_zone isn't used by run_instance.
        rpc.cast(context,
                 FLAGS.scheduler_topic,
                 {"method": "start_instance",
                  "args": {"topic": FLAGS.compute_topic,
                           "instance_id": instance_id}})

    def get(self, context, instance_id):
        """Get a single instance with the given instance_id."""
        # NOTE(sirp): id used to be exclusively integer IDs; now we're
        # accepting both UUIDs and integer IDs. The handling of this
        # is done in db/sqlalchemy/api/instance_get
        if utils.is_uuid_like(instance_id):
            uuid = instance_id
            instance = self.db.instance_get_by_uuid(context, uuid)
        else:
            instance = self.db.instance_get(context, instance_id)
        return dict(instance.iteritems())

    @scheduler_api.reroute_compute("get")
    def routing_get(self, context, instance_id):
        """A version of get with special routing characteristics.

        Use this method instead of get() if this is the only operation you
        intend to to. It will route to novaclient.get if the instance is not
        found.
        """
        return self.get(context, instance_id)

    def get_all(self, context, project_id=None, reservation_id=None,
                fixed_ip=None, recurse_zones=False):
        """Get all instances filtered by one of the given parameters.

        If there is no filter and the context is an admin, it will retreive
        all instances in the system.
        """

        if reservation_id is not None:
            recurse_zones = True
            instances = self.db.instance_get_all_by_reservation(
                                    context, reservation_id)
        elif fixed_ip is not None:
            try:
                instances = self.db.fixed_ip_get_instance(context, fixed_ip)
            except exception.FloatingIpNotFound, e:
                if not recurse_zones:
                    raise
                instances = None
        elif project_id or not context.is_admin:
            if not context.project:
                instances = self.db.instance_get_all_by_user(
                    context, context.user_id)
            else:
                if project_id is None:
                    project_id = context.project_id
                instances = self.db.instance_get_all_by_project(
                    context, project_id)
        else:
            instances = self.db.instance_get_all(context)

        if instances is None:
            instances = []
        elif not isinstance(instances, list):
            instances = [instances]

        if not recurse_zones:
            return instances

        admin_context = context.elevated()
        children = scheduler_api.call_zone_method(admin_context,
                "list",
                novaclient_collection_name="servers",
                reservation_id=reservation_id,
                project_id=project_id,
                fixed_ip=fixed_ip,
                recurse_zones=True)

        for zone, servers in children:
            for server in servers:
                # Results are ready to send to user. No need to scrub.
                server._info['_is_precooked'] = True
                instances.append(server._info)
        return instances

    def _cast_compute_message(self, method, context, instance_id, host=None,
                              params=None):
        """Generic handler for RPC casts to compute.

        :param params: Optional dictionary of arguments to be passed to the
                       compute worker

        :returns: None
        """
        if not params:
            params = {}
        if not host:
            instance = self.get(context, instance_id)
            host = instance['host']
        queue = self.db.queue_get_for(context, FLAGS.compute_topic, host)
        params['instance_id'] = instance_id
        kwargs = {'method': method, 'args': params}
        rpc.cast(context, queue, kwargs)

    def _call_compute_message(self, method, context, instance_id, host=None,
                              params=None):
        """Generic handler for RPC calls to compute.

        :param params: Optional dictionary of arguments to be passed to the
                       compute worker

        :returns: Result returned by compute worker
        """
        if not params:
            params = {}
        if not host:
            instance = self.get(context, instance_id)
            host = instance['host']
        queue = self.db.queue_get_for(context, FLAGS.compute_topic, host)
        params['instance_id'] = instance_id
        kwargs = {'method': method, 'args': params}
        return rpc.call(context, queue, kwargs)

    def _cast_scheduler_message(self, context, args):
        """Generic handler for RPC calls to the scheduler."""
        rpc.cast(context, FLAGS.scheduler_topic, args)

    def _find_host(self, context, instance_id):
        """Find the host associated with an instance."""
        for attempts in xrange(FLAGS.find_host_timeout):
            instance = self.get(context, instance_id)
            host = instance["host"]
            if host:
                return host
            time.sleep(1)
        raise exception.Error(_("Unable to find host for Instance %s")
                                % instance_id)

    def backup(self, context, instance_id, name, backup_type, rotation,
               extra_properties=None):
        """Backup the given instance

        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param name: name of the backup or snapshot
            name = backup_type  # daily backups are called 'daily'
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        :param extra_properties: dict of extra image properties to include
        """
        recv_meta = self._create_image(context, instance_id, name, 'backup',
                            backup_type=backup_type, rotation=rotation,
                            extra_properties=extra_properties)
        return recv_meta

    def snapshot(self, context, instance_id, name, extra_properties=None):
        """Snapshot the given instance.

        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param name: name of the backup or snapshot
        :param extra_properties: dict of extra image properties to include

        :returns: A dict containing image metadata
        """
        return self._create_image(context, instance_id, name, 'snapshot',
                                  extra_properties=extra_properties)

    def _create_image(self, context, instance_id, name, image_type,
                      backup_type=None, rotation=None, extra_properties=None):
        """Create snapshot or backup for an instance on this host.

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param name: string for name of the snapshot
        :param image_type: snapshot | backup
        :param backup_type: daily | weekly
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        :param extra_properties: dict of extra image properties to include

        """
        instance = db.api.instance_get(context, instance_id)
        properties = {'instance_uuid': instance['uuid'],
                      'user_id': str(context.user_id),
                      'image_state': 'creating',
                      'image_type': image_type,
                      'backup_type': backup_type}
        properties.update(extra_properties or {})
        sent_meta = {'name': name, 'is_public': False,
                     'status': 'creating', 'properties': properties}
        recv_meta = self.image_service.create(context, sent_meta)
        params = {'image_id': recv_meta['id'], 'image_type': image_type,
                  'backup_type': backup_type, 'rotation': rotation}
        self._cast_compute_message('snapshot_instance', context, instance_id,
                                   params=params)
        return recv_meta

    def reboot(self, context, instance_id):
        """Reboot the given instance."""
        self._cast_compute_message('reboot_instance', context, instance_id)

    def rebuild(self, context, instance_id, image_href, name=None,
            metadata=None, files_to_inject=None):
        """Rebuild the given instance with the provided metadata."""
        instance = db.api.instance_get(context, instance_id)

        if instance["state"] == power_state.BUILDING:
            msg = _("Instance already building")
            raise exception.BuildInProgress(msg)

        files_to_inject = files_to_inject or []
        self._check_injected_file_quota(context, files_to_inject)

        values = {}
        if metadata is not None:
            self._check_metadata_properties_quota(context, metadata)
            values['metadata'] = metadata
        if name is not None:
            values['display_name'] = name
        self.db.instance_update(context, instance_id, values)

        rebuild_params = {
            "image_ref": image_href,
            "injected_files": files_to_inject,
        }

        self._cast_compute_message('rebuild_instance',
                                   context,
                                   instance_id,
                                   params=rebuild_params)

    def revert_resize(self, context, instance_id):
        """Reverts a resize, deleting the 'new' instance in the process."""
        context = context.elevated()
        migration_ref = self.db.migration_get_by_instance_and_status(context,
                instance_id, 'finished')
        if not migration_ref:
            raise exception.MigrationNotFoundByStatus(instance_id=instance_id,
                                                      status='finished')

        params = {'migration_id': migration_ref['id']}
        self._cast_compute_message('revert_resize', context, instance_id,
                migration_ref['dest_compute'], params=params)
        self.db.migration_update(context, migration_ref['id'],
                {'status': 'reverted'})

    def confirm_resize(self, context, instance_id):
        """Confirms a migration/resize and deletes the 'old' instance."""
        context = context.elevated()
        migration_ref = self.db.migration_get_by_instance_and_status(context,
                instance_id, 'finished')
        if not migration_ref:
            raise exception.MigrationNotFoundByStatus(instance_id=instance_id,
                                                      status='finished')
        instance_ref = self.db.instance_get(context, instance_id)
        params = {'migration_id': migration_ref['id']}
        self._cast_compute_message('confirm_resize', context, instance_id,
                migration_ref['source_compute'], params=params)

        self.db.migration_update(context, migration_ref['id'],
                {'status': 'confirmed'})
        self.db.instance_update(context, instance_id,
                {'host': migration_ref['dest_compute'], })

    def resize(self, context, instance_id, flavor_id=None):
        """Resize (ie, migrate) a running instance.

        If flavor_id is None, the process is considered a migration, keeping
        the original flavor_id. If flavor_id is not None, the instance should
        be migrated to a new host and resized to the new flavor_id.
        """
        instance = self.db.instance_get(context, instance_id)
        current_instance_type = instance['instance_type']

        # If flavor_id is not provided, only migrate the instance.
        if not flavor_id:
            LOG.debug(_("flavor_id is None. Assuming migration."))
            new_instance_type = current_instance_type
        else:
            new_instance_type = self.db.instance_type_get_by_flavor_id(
                    context, flavor_id)

        current_instance_type_name = current_instance_type['name']
        new_instance_type_name = new_instance_type['name']
        LOG.debug(_("Old instance type %(current_instance_type_name)s, "
                " new instance type %(new_instance_type_name)s") % locals())
        if not new_instance_type:
            raise exception.ApiError(_("Requested flavor %(flavor_id)d "
                    "does not exist") % locals())

        current_memory_mb = current_instance_type['memory_mb']
        new_memory_mb = new_instance_type['memory_mb']
        if current_memory_mb > new_memory_mb:
            raise exception.ApiError(_("Invalid flavor: cannot downsize"
                    "instances"))

        if (current_memory_mb == new_memory_mb) and flavor_id:
            raise exception.ApiError(_("Invalid flavor: cannot use"
                    "the same flavor. "))

        self._cast_scheduler_message(context,
                    {"method": "prep_resize",
                     "args": {"topic": FLAGS.compute_topic,
                              "instance_id": instance_id,
                              "flavor_id": new_instance_type['id']}})

    @scheduler_api.reroute_compute("add_fixed_ip")
    def add_fixed_ip(self, context, instance_id, network_id):
        """Add fixed_ip from specified network to given instance."""
        self._cast_compute_message('add_fixed_ip_to_instance', context,
                                   instance_id,
                                   params=dict(network_id=network_id))

    @scheduler_api.reroute_compute("remove_fixed_ip")
    def remove_fixed_ip(self, context, instance_id, address):
        """Remove fixed_ip from specified network to given instance."""
        self._cast_compute_message('remove_fixed_ip_from_instance', context,
                                   instance_id, params=dict(address=address))

    #TODO(tr3buchet): how to run this in the correct zone?
    def add_network_to_project(self, context, project_id):
        """Force adds a network to the project."""
        # this will raise if zone doesn't know about project so the decorator
        # can catch it and pass it down
        self.db.project_get(context, project_id)

        # didn't raise so this is the correct zone
        self.network_api.add_network_to_project(context, project_id)

    @scheduler_api.reroute_compute("pause")
    def pause(self, context, instance_id):
        """Pause the given instance."""
        self._cast_compute_message('pause_instance', context, instance_id)

    @scheduler_api.reroute_compute("unpause")
    def unpause(self, context, instance_id):
        """Unpause the given instance."""
        self._cast_compute_message('unpause_instance', context, instance_id)

    def set_host_enabled(self, context, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        return self._call_compute_message("set_host_enabled", context,
                instance_id=None, host=host, params={"enabled": enabled})

    @scheduler_api.reroute_compute("diagnostics")
    def get_diagnostics(self, context, instance_id):
        """Retrieve diagnostics for the given instance."""
        return self._call_compute_message("get_diagnostics",
                                          context,
                                          instance_id)

    def get_actions(self, context, instance_id):
        """Retrieve actions for the given instance."""
        return self.db.instance_get_actions(context, instance_id)

    @scheduler_api.reroute_compute("suspend")
    def suspend(self, context, instance_id):
        """Suspend the given instance."""
        self._cast_compute_message('suspend_instance', context, instance_id)

    @scheduler_api.reroute_compute("resume")
    def resume(self, context, instance_id):
        """Resume the given instance."""
        self._cast_compute_message('resume_instance', context, instance_id)

    @scheduler_api.reroute_compute("rescue")
    def rescue(self, context, instance_id):
        """Rescue the given instance."""
        self._cast_compute_message('rescue_instance', context, instance_id)

    @scheduler_api.reroute_compute("unrescue")
    def unrescue(self, context, instance_id):
        """Unrescue the given instance."""
        self._cast_compute_message('unrescue_instance', context, instance_id)

    def set_admin_password(self, context, instance_id, password=None):
        """Set the root/admin password for the given instance."""
        host = self._find_host(context, instance_id)

        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "set_admin_password",
                  "args": {"instance_id": instance_id, "new_pass": password}})

    def inject_file(self, context, instance_id):
        """Write a file to the given instance."""
        self._cast_compute_message('inject_file', context, instance_id)

    def get_ajax_console(self, context, instance_id):
        """Get a url to an AJAX Console."""
        output = self._call_compute_message('get_ajax_console',
                                            context,
                                            instance_id)
        rpc.cast(context, '%s' % FLAGS.ajax_console_proxy_topic,
                 {'method': 'authorize_ajax_console',
                  'args': {'token': output['token'], 'host': output['host'],
                  'port': output['port']}})
        return {'url': '%s/?token=%s' % (FLAGS.ajax_console_proxy_url,
                                         output['token'])}

    def get_vnc_console(self, context, instance_id):
        """Get a url to a VNC Console."""
        instance = self.get(context, instance_id)
        output = self._call_compute_message('get_vnc_console',
                                            context,
                                            instance_id)
        rpc.call(context, '%s' % FLAGS.vncproxy_topic,
                 {'method': 'authorize_vnc_console',
                  'args': {'token': output['token'],
                           'host': output['host'],
                           'port': output['port']}})

        # hostignore and portignore are compatability params for noVNC
        return {'url': '%s/vnc_auto.html?token=%s&host=%s&port=%s' % (
                       FLAGS.vncproxy_url,
                       output['token'],
                       'hostignore',
                       'portignore')}

    def get_console_output(self, context, instance_id):
        """Get console output for an an instance."""
        return self._call_compute_message('get_console_output',
                                          context,
                                          instance_id)

    def lock(self, context, instance_id):
        """Lock the given instance."""
        self._cast_compute_message('lock_instance', context, instance_id)

    def unlock(self, context, instance_id):
        """Unlock the given instance."""
        self._cast_compute_message('unlock_instance', context, instance_id)

    def get_lock(self, context, instance_id):
        """Return the boolean state of given instance's lock."""
        instance = self.get(context, instance_id)
        return instance['locked']

    def reset_network(self, context, instance_id):
        """Reset networking on the instance."""
        self._cast_compute_message('reset_network', context, instance_id)

    def inject_network_info(self, context, instance_id):
        """Inject network info for the instance."""
        self._cast_compute_message('inject_network_info', context, instance_id)

    def attach_volume(self, context, instance_id, volume_id, device):
        """Attach an existing volume to an existing instance."""
        if not re.match("^/dev/[a-z]d[a-z]+$", device):
            raise exception.ApiError(_("Invalid device specified: %s. "
                                     "Example device: /dev/vdb") % device)
        self.volume_api.check_attach(context, volume_id=volume_id)
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "attach_volume",
                  "args": {"volume_id": volume_id,
                           "instance_id": instance_id,
                           "mountpoint": device}})

    def detach_volume(self, context, volume_id):
        """Detach a volume from an instance."""
        instance = self.db.volume_get_instance(context.elevated(), volume_id)
        if not instance:
            raise exception.ApiError(_("Volume isn't attached to anything!"))
        self.volume_api.check_detach(context, volume_id=volume_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "detach_volume",
                  "args": {"instance_id": instance['id'],
                           "volume_id": volume_id}})
        return instance

    def associate_floating_ip(self, context, instance_id, address):
        """Makes calls to network_api to associate_floating_ip.

        :param address: is a string floating ip address
        """
        instance = self.get(context, instance_id)

        # TODO(tr3buchet): currently network_info doesn't contain floating IPs
        # in its info, if this changes, the next few lines will need to
        # accomodate the info containing floating as well as fixed ip addresses
        fixed_ip_addrs = []
        for info in self.network_api.get_instance_nw_info(context,
                                                          instance):
            ips = info[1]['ips']
            fixed_ip_addrs.extend([ip_dict['ip'] for ip_dict in ips])

        # TODO(tr3buchet): this will associate the floating IP with the first
        # fixed_ip (lowest id) an instance has. This should be changed to
        # support specifying a particular fixed_ip if multiple exist.
        if not fixed_ip_addrs:
            msg = _("instance |%s| has no fixed_ips. "
                    "unable to associate floating ip") % instance_id
            raise exception.ApiError(msg)
        if len(fixed_ip_addrs) > 1:
            LOG.warning(_("multiple fixed_ips exist, using the first: %s"),
                                                         fixed_ip_addrs[0])
        self.network_api.associate_floating_ip(context,
                                               floating_ip=address,
                                               fixed_ip=fixed_ip_addrs[0])

    def get_instance_metadata(self, context, instance_id):
        """Get all metadata associated with an instance."""
        rv = self.db.instance_metadata_get(context, instance_id)
        return dict(rv.iteritems())

    def delete_instance_metadata(self, context, instance_id, key):
        """Delete the given metadata item from an instance."""
        self.db.instance_metadata_delete(context, instance_id, key)

    def update_or_create_instance_metadata(self, context, instance_id,
                                            metadata):
        """Updates or creates instance metadata."""
        combined_metadata = self.get_instance_metadata(context, instance_id)
        combined_metadata.update(metadata)
        self._check_metadata_properties_quota(context, combined_metadata)
        self.db.instance_metadata_update_or_create(context, instance_id,
                                                    metadata)
