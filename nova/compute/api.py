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

import datetime
import eventlet
import re
import time

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import network
from nova import quota
from nova import rpc
from nova import utils
from nova import volume
from nova.compute import instance_types
from nova.compute import power_state
from nova.scheduler import api as scheduler_api
from nova.db import base


LOG = logging.getLogger('nova.compute.api')


FLAGS = flags.FLAGS
flags.DECLARE('vncproxy_topic', 'nova.vnc')
flags.DEFINE_integer('find_host_timeout', 30,
                     'Timeout after NN seconds when looking for a host.')


def generate_default_hostname(instance_id):
    """Default function to generate a hostname given an instance reference."""
    return str(instance_id)


class API(base.Base):
    """API for interacting with the compute manager."""

    def __init__(self, image_service=None, network_api=None,
                 volume_api=None, hostname_factory=generate_default_hostname,
                 **kwargs):
        if not image_service:
            image_service = utils.import_object(FLAGS.image_service)
        self.image_service = image_service
        if not network_api:
            network_api = network.API()
        self.network_api = network_api
        if not volume_api:
            volume_api = volume.API()
        self.volume_api = volume_api
        self.hostname_factory = hostname_factory
        super(API, self).__init__(**kwargs)

    def get_network_topic(self, context, instance_id):
        """Get the network topic for an instance."""
        try:
            instance = self.get(context, instance_id)
        except exception.NotFound:
            LOG.warning(_("Instance %d was not found in get_network_topic"),
                        instance_id)
            raise

        host = instance['host']
        if not host:
            raise exception.Error(_("Instance %d has no host") % instance_id)
        topic = self.db.queue_get_for(context, FLAGS.compute_topic, host)
        return rpc.call(context,
                        topic,
                        {"method": "get_network_topic", "args": {'fake': 1}})

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

    def create(self, context, instance_type,
               image_id, kernel_id=None, ramdisk_id=None,
               min_count=1, max_count=1,
               display_name='', display_description='',
               key_name=None, key_data=None, security_group='default',
               availability_zone=None, user_data=None, metadata={},
               injected_files=None,
               admin_password=None):
        """Create the number and type of instances requested.

        Verifies that quota and other arguments are valid.

        """
        if not instance_type:
            instance_type = instance_types.get_default_instance_type()

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

        image = self.image_service.show(context, image_id)

        os_type = None
        if 'properties' in image and 'os_type' in image['properties']:
            os_type = image['properties']['os_type']

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
            self.image_service.show(context, kernel_id)
        if ramdisk_id:
            self.image_service.show(context, ramdisk_id)

        if security_group is None:
            security_group = ['default']
        if not type(security_group) is list:
            security_group = [security_group]

        security_groups = []
        self.ensure_default_security_group(context)
        for security_group_name in security_group:
            group = db.security_group_get_by_name(context,
                                                  context.project_id,
                                                  security_group_name)
            security_groups.append(group['id'])

        if key_data is None and key_name:
            key_pair = db.key_pair_get(context, context.user_id, key_name)
            key_data = key_pair['public_key']

        base_options = {
            'reservation_id': utils.generate_uid('r'),
            'image_id': image_id,
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
            'os_type': os_type}
        elevated = context.elevated()
        instances = []
        LOG.debug(_("Going to run %s instances..."), num_instances)
        for num in range(num_instances):
            instance = dict(mac_address=utils.generate_mac(),
                            launch_index=num,
                            **base_options)
            instance = self.db.instance_create(context, instance)
            instance_id = instance['id']

            elevated = context.elevated()
            if not security_groups:
                security_groups = []
            for security_group_id in security_groups:
                self.db.instance_add_security_group(elevated,
                                                    instance_id,
                                                    security_group_id)

            # Set sane defaults if not specified
            updates = dict(hostname=self.hostname_factory(instance_id))
            if (not hasattr(instance, 'display_name') or
                    instance.display_name is None):
                updates['display_name'] = "Server %s" % instance_id

            instance = self.update(context, instance_id, **updates)
            instances.append(instance)

            pid = context.project_id
            uid = context.user_id
            LOG.debug(_("Casting to scheduler for %(pid)s/%(uid)s's"
                    " instance %(instance_id)s") % locals())

            # NOTE(sandy): For now we're just going to pass in the
            # instance_type record to the scheduler. In a later phase
            # we'll be ripping this whole for-loop out and deferring the
            # creation of the Instance record. At that point all this will
            # change.
            rpc.cast(context,
                     FLAGS.scheduler_topic,
                     {"method": "run_instance",
                      "args": {"topic": FLAGS.compute_topic,
                               "instance_id": instance_id,
                               "instance_type": instance_type,
                               "availability_zone": availability_zone,
                               "injected_files": injected_files,
                               "admin_password": admin_password}})

        for group_id in security_groups:
            self.trigger_security_group_members_refresh(elevated, group_id)

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
                     {"method": "refresh_provider_fw_rules", "args": {}})

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

    @scheduler_api.reroute_compute("delete")
    def delete(self, context, instance_id):
        """Terminate an instance."""
        LOG.debug(_("Going to try to terminate %s"), instance_id)
        try:
            instance = self.get(context, instance_id)
        except exception.NotFound:
            LOG.warning(_("Instance %s was not found during terminate"),
                        instance_id)
            raise

        if instance['state_description'] == 'terminating':
            LOG.warning(_("Instance %s is already being terminated"),
                        instance_id)
            return

        if instance['state_description'] == 'migrating':
            LOG.warning(_("Instance %s is being migrated"), instance_id)
            return

        self.update(context,
                    instance['id'],
                    state_description='terminating',
                    state=0,
                    terminated_at=datetime.datetime.utcnow())

        host = instance['host']
        if host:
            self._cast_compute_message('terminate_instance', context,
                    instance_id, host)
        else:
            self.db.instance_destroy(context, instance_id)

    def get(self, context, instance_id):
        """Get a single instance with the given instance_id."""
        rv = self.db.instance_get(context, instance_id)
        return dict(rv.iteritems())

    @scheduler_api.reroute_compute("get")
    def routing_get(self, context, instance_id):
        """A version of get with special routing characteristics.

        Use this method instead of get() if this is the only operation you
        intend to to. It will route to novaclient.get if the instance is not
        found.

        """
        return self.get(context, instance_id)

    def get_all(self, context, project_id=None, reservation_id=None,
                fixed_ip=None):
        """Get all instances filtered by one of the given parameters.

        If there is no filter and the context is an admin, it will retreive
        all instances in the system.

        """
        if reservation_id is not None:
            return self.db.instance_get_all_by_reservation(
                context, reservation_id)

        if fixed_ip is not None:
            return self.db.fixed_ip_get_instance(context, fixed_ip)

        if project_id or not context.is_admin:
            if not context.project:
                return self.db.instance_get_all_by_user(
                    context, context.user_id)

            if project_id is None:
                project_id = context.project_id

            return self.db.instance_get_all_by_project(
                context, project_id)

        return self.db.instance_get_all(context)

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
            host = instance["host"]
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

    def snapshot(self, context, instance_id, name):
        """Snapshot the given instance.

        :returns: A dict containing image metadata

        """
        properties = {'instance_id': str(instance_id),
                      'user_id': str(context.user_id)}
        sent_meta = {'name': name, 'is_public': False,
                     'properties': properties}
        recv_meta = self.image_service.create(context, sent_meta)
        params = {'image_id': recv_meta['id']}
        self._cast_compute_message('snapshot_instance', context, instance_id,
                                   params=params)
        return recv_meta

    def reboot(self, context, instance_id):
        """Reboot the given instance."""
        self._cast_compute_message('reboot_instance', context, instance_id)

    def rebuild(self, context, instance_id, image_id, metadata=None,
                files_to_inject=None):
        """Rebuild the given instance with the provided metadata."""
        instance = db.api.instance_get(context, instance_id)

        if instance["state"] == power_state.BUILDING:
            msg = _("Instance already building")
            raise exception.BuildInProgress(msg)

        metadata = metadata or {}
        self._check_metadata_properties_quota(context, metadata)

        files_to_inject = files_to_inject or []
        self._check_injected_file_quota(context, files_to_inject)

        self.db.instance_update(context, instance_id, {"metadata": metadata})

        rebuild_params = {
            "image_id": image_id,
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

    def resize(self, context, instance_id, flavor_id):
        """Resize a running instance."""
        instance = self.db.instance_get(context, instance_id)
        current_instance_type = instance['instance_type']

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
        if current_memory_mb == new_memory_mb:
            raise exception.ApiError(_("Invalid flavor: cannot use"
                    "the same flavor. "))

        self._cast_scheduler_message(context,
                    {"method": "prep_resize",
                     "args": {"topic": FLAGS.compute_topic,
                              "instance_id": instance_id,
                              "flavor_id": flavor_id}})

    @scheduler_api.reroute_compute("pause")
    def pause(self, context, instance_id):
        """Pause the given instance."""
        self._cast_compute_message('pause_instance', context, instance_id)

    @scheduler_api.reroute_compute("unpause")
    def unpause(self, context, instance_id):
        """Unpause the given instance."""
        self._cast_compute_message('unpause_instance', context, instance_id)

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
        """Associate a floating ip with an instance."""
        instance = self.get(context, instance_id)
        self.network_api.associate_floating_ip(context,
                                               floating_ip=address,
                                               fixed_ip=instance['fixed_ip'])

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
