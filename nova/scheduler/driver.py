# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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

"""
Scheduler base class that all Schedulers should inherit from
"""

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc
from nova import utils
from nova.compute import api as compute_api
from nova.compute import power_state
from nova.compute import vm_states
from nova.api.ec2 import ec2utils


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.scheduler.driver')
flags.DEFINE_integer('service_down_time', 60,
                     'maximum time since last check-in for up service')
flags.DECLARE('instances_path', 'nova.compute.manager')


def cast_to_volume_host(context, host, method, update_db=True, **kwargs):
    """Cast request to a volume host queue"""

    if update_db:
        volume_id = kwargs.get('volume_id', None)
        if volume_id is not None:
            now = utils.utcnow()
            db.volume_update(context, volume_id,
                    {'host': host, 'scheduled_at': now})
    rpc.cast(context,
            db.queue_get_for(context, 'volume', host),
            {"method": method, "args": kwargs})
    LOG.debug(_("Casted '%(method)s' to volume '%(host)s'") % locals())


def cast_to_compute_host(context, host, method, update_db=True, **kwargs):
    """Cast request to a compute host queue"""

    if update_db:
        # fall back on the id if the uuid is not present
        instance_id = kwargs.get('instance_id', None)
        instance_uuid = kwargs.get('instance_uuid', instance_id)
        if instance_uuid is not None:
            now = utils.utcnow()
            db.instance_update(context, instance_uuid,
                    {'host': host, 'scheduled_at': now})
    rpc.cast(context,
            db.queue_get_for(context, 'compute', host),
            {"method": method, "args": kwargs})
    LOG.debug(_("Casted '%(method)s' to compute '%(host)s'") % locals())


def cast_to_network_host(context, host, method, update_db=False, **kwargs):
    """Cast request to a network host queue"""

    rpc.cast(context,
            db.queue_get_for(context, 'network', host),
            {"method": method, "args": kwargs})
    LOG.debug(_("Casted '%(method)s' to network '%(host)s'") % locals())


def cast_to_host(context, topic, host, method, update_db=True, **kwargs):
    """Generic cast to host"""

    topic_mapping = {
            "compute": cast_to_compute_host,
            "volume": cast_to_volume_host,
            'network': cast_to_network_host}

    func = topic_mapping.get(topic)
    if func:
        func(context, host, method, update_db=update_db, **kwargs)
    else:
        rpc.cast(context,
            db.queue_get_for(context, topic, host),
                {"method": method, "args": kwargs})
        LOG.debug(_("Casted '%(method)s' to %(topic)s '%(host)s'")
                % locals())


def encode_instance(instance, local=True):
    """Encode locally created instance for return via RPC"""
    # TODO(comstud): I would love to be able to return the full
    # instance information here, but we'll need some modifications
    # to the RPC code to handle datetime conversions with the
    # json encoding/decoding.  We should be able to set a default
    # json handler somehow to do it.
    #
    # For now, I'll just return the instance ID and let the caller
    # do a DB lookup :-/
    if local:
        return dict(id=instance['id'], _is_precooked=False)
    else:
        instance['_is_precooked'] = True
        return instance


class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.zone_manager = None
        self.compute_api = compute_api.API()

    def set_zone_manager(self, zone_manager):
        """Called by the Scheduler Service to supply a ZoneManager."""
        self.zone_manager = zone_manager

    @staticmethod
    def service_is_up(service):
        """Check whether a service is up based on last heartbeat."""
        last_heartbeat = service['updated_at'] or service['created_at']
        # Timestamps in DB are UTC.
        elapsed = utils.total_seconds(utils.utcnow() - last_heartbeat)
        return abs(elapsed) <= FLAGS.service_down_time

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service.host
                for service in services
                if self.service_is_up(service)]

    def create_instance_db_entry(self, context, request_spec):
        """Create instance DB entry based on request_spec"""
        base_options = request_spec['instance_properties']
        if base_options.get('uuid'):
            # Instance was already created before calling scheduler
            return db.instance_get_by_uuid(context, base_options['uuid'])
        image = request_spec['image']
        instance_type = request_spec.get('instance_type')
        security_group = request_spec.get('security_group', 'default')
        block_device_mapping = request_spec.get('block_device_mapping', [])

        instance = self.compute_api.create_db_entry_for_new_instance(
                context, instance_type, image, base_options,
                security_group, block_device_mapping)
        # NOTE(comstud): This needs to be set for the generic exception
        # checking in scheduler manager, so that it'll set this instance
        # to ERROR properly.
        base_options['uuid'] = instance['uuid']
        return instance

    def schedule(self, context, topic, method, *_args, **_kwargs):
        """Must override at least this method for scheduler to work."""
        raise NotImplementedError(_("Must implement a fallback schedule"))

    def schedule_live_migration(self, context, instance_id, dest,
                                block_migration=False,
                                disk_over_commit=False):
        """Live migration scheduling method.
        :param context:
        :param instance_id:
        :param dest: destination host
        :param block_migration: if true, block_migration.
        :param disk_over_commit: if True, consider real(not virtual)
                                 disk size.

        :return:
            The host where instance is running currently.
            Then scheduler send request that host.
        """
        # Whether instance exists and is running.
        instance_ref = db.instance_get(context, instance_id)

        # Checking instance.
        self._live_migration_src_check(context, instance_ref)

        # Checking destination host.
        self._live_migration_dest_check(context, instance_ref,
                                        dest, block_migration,
                                        disk_over_commit)
        # Common checking.
        self._live_migration_common_check(context, instance_ref,
                                          dest, block_migration,
                                          disk_over_commit)

        # Changing instance_state.
        values = {"vm_state": vm_states.MIGRATING}
        db.instance_update(context, instance_id, values)

        # Changing volume state
        for volume_ref in instance_ref['volumes']:
            db.volume_update(context,
                             volume_ref['id'],
                             {'status': 'migrating'})

        src = instance_ref['host']
        cast_to_compute_host(context, src, 'live_migration',
                update_db=False,
                instance_id=instance_id,
                dest=dest,
                block_migration=block_migration)

    def _live_migration_src_check(self, context, instance_ref):
        """Live migration check routine (for src host).

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object

        """

        # Checking instance is running.
        if instance_ref['power_state'] != power_state.RUNNING:
            instance_id = ec2utils.id_to_ec2_id(instance_ref['id'])
            raise exception.InstanceNotRunning(instance_id=instance_id)

        # Checing volume node is running when any volumes are mounted
        # to the instance.
        if len(instance_ref['volumes']) != 0:
            services = db.service_get_all_by_topic(context, 'volume')
            if len(services) < 1 or  not self.service_is_up(services[0]):
                raise exception.VolumeServiceUnavailable()

        # Checking src host exists and compute node
        src = instance_ref['host']
        services = db.service_get_all_compute_by_host(context, src)

        # Checking src host is alive.
        if not self.service_is_up(services[0]):
            raise exception.ComputeServiceUnavailable(host=src)

    def _live_migration_dest_check(self, context, instance_ref, dest,
                                   block_migration, disk_over_commit):
        """Live migration check routine (for destination host).

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host
        :param block_migration: if true, block_migration.
        :param disk_over_commit: if True, consider real(not virtual)
                                 disk size.
        """

        # Checking dest exists and compute node.
        dservice_refs = db.service_get_all_compute_by_host(context, dest)
        dservice_ref = dservice_refs[0]

        # Checking dest host is alive.
        if not self.service_is_up(dservice_ref):
            raise exception.ComputeServiceUnavailable(host=dest)

        # Checking whether The host where instance is running
        # and dest is not same.
        src = instance_ref['host']
        if dest == src:
            instance_id = ec2utils.id_to_ec2_id(instance_ref['id'])
            raise exception.UnableToMigrateToSelf(instance_id=instance_id,
                                                  host=dest)

        # Checking dst host still has enough capacities.
        self.assert_compute_node_has_enough_resources(context,
                                                      instance_ref,
                                                      dest,
                                                      block_migration,
                                                      disk_over_commit)

    def _live_migration_common_check(self, context, instance_ref, dest,
                                     block_migration, disk_over_commit):
        """Live migration common check routine.

        Below checkings are followed by
        http://wiki.libvirt.org/page/TodoPreMigrationChecks

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host
        :param block_migration: if true, block_migration.
        :param disk_over_commit: if True, consider real(not virtual)
                                 disk size.

        """

        # Checking shared storage connectivity
        # if block migration, instances_paths should not be on shared storage.
        try:
            self.mounted_on_same_shared_storage(context, instance_ref, dest)
            if block_migration:
                reason = _("Block migration can not be used "
                           "with shared storage.")
                raise exception.InvalidSharedStorage(reason=reason, path=dest)
        except exception.FileNotFound:
            if not block_migration:
                src = instance_ref['host']
                ipath = FLAGS.instances_path
                LOG.error(_("Cannot confirm tmpfile at %(ipath)s is on "
                                "same shared storage between %(src)s "
                                "and %(dest)s.") % locals())
                raise

        # Checking destination host exists.
        dservice_refs = db.service_get_all_compute_by_host(context, dest)
        dservice_ref = dservice_refs[0]['compute_node'][0]

        # Checking original host( where instance was launched at) exists.
        try:
            oservice_refs = db.service_get_all_compute_by_host(context,
                                           instance_ref['launched_on'])
        except exception.NotFound:
            raise exception.SourceHostUnavailable()
        oservice_ref = oservice_refs[0]['compute_node'][0]

        # Checking hypervisor is same.
        orig_hypervisor = oservice_ref['hypervisor_type']
        dest_hypervisor = dservice_ref['hypervisor_type']
        if orig_hypervisor != dest_hypervisor:
            raise exception.InvalidHypervisorType()

        # Checkng hypervisor version.
        orig_hypervisor = oservice_ref['hypervisor_version']
        dest_hypervisor = dservice_ref['hypervisor_version']
        if orig_hypervisor > dest_hypervisor:
            raise exception.DestinationHypervisorTooOld()

        # Checking cpuinfo.
        try:
            rpc.call(context,
                     db.queue_get_for(context, FLAGS.compute_topic, dest),
                     {"method": 'compare_cpu',
                      "args": {'cpu_info': oservice_ref['cpu_info']}})

        except rpc.RemoteError:
            src = instance_ref['host']
            LOG.exception(_("host %(dest)s is not compatible with "
                                "original host %(src)s.") % locals())
            raise

    def assert_compute_node_has_enough_resources(self, context, instance_ref,
                                                 dest, block_migration,
                                                 disk_over_commit):

        """Checks if destination host has enough resource for live migration.

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host
        :param block_migration: if true, block_migration.
        :param disk_over_commit: if True, consider real(not virtual)
                                 disk size.

        """
        self.assert_compute_node_has_enough_memory(context,
                                                   instance_ref, dest)
        if not block_migration:
            return
        self.assert_compute_node_has_enough_disk(context,
                                                 instance_ref, dest,
                                                 disk_over_commit)

    def assert_compute_node_has_enough_memory(self, context,
                                              instance_ref, dest):
        """Checks if destination host has enough memory for live migration.


        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host

        """

        # Getting total available memory of host
        avail = self._get_compute_info(context, dest, 'memory_mb')

        # Getting total used memory and disk of host
        # It should be sum of memories that are assigned as max value,
        # because overcommiting is risky.
        used = 0
        instance_refs = db.instance_get_all_by_host(context, dest)
        used_list = [i['memory_mb'] for i in instance_refs]
        if used_list:
            used = reduce(lambda x, y: x + y, used_list)

        mem_inst = instance_ref['memory_mb']
        avail = avail - used
        if avail <= mem_inst:
            instance_id = ec2utils.id_to_ec2_id(instance_ref['id'])
            reason = _("Unable to migrate %(instance_id)s to %(dest)s: "
                       "Lack of memory(host:%(avail)s <= "
                       "instance:%(mem_inst)s)")
            raise exception.MigrationError(reason=reason % locals())

    def assert_compute_node_has_enough_disk(self, context, instance_ref, dest,
                                            disk_over_commit):
        """Checks if destination host has enough disk for block migration.

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host
        :param disk_over_commit: if True, consider real(not virtual)
                                 disk size.

        """

        # Libvirt supports qcow2 disk format,which is usually compressed
        # on compute nodes.
        # Real disk image (compressed) may enlarged to "virtual disk size",
        # that is specified as the maximum disk size.
        # (See qemu-img -f path-to-disk)
        # Scheduler recognizes destination host still has enough disk space
        # if real disk size < available disk size
        # if disk_over_commit is True,
        #  otherwise virtual disk size < available disk size.

        # Refresh compute_nodes table
        topic = db.queue_get_for(context, FLAGS.compute_topic, dest)
        rpc.call(context, topic,
                 {"method": "update_available_resource"})

        # Getting total available disk of host
        available_gb = self._get_compute_info(context,
                                              dest, 'disk_available_least')
        available = available_gb * (1024 ** 3)

        # Getting necessary disk size
        try:
            topic = db.queue_get_for(context, FLAGS.compute_topic,
                                              instance_ref['host'])
            ret = rpc.call(context, topic,
                           {"method": 'get_instance_disk_info',
                            "args": {'instance_name': instance_ref.name}})
            disk_infos = utils.loads(ret)
        except rpc.RemoteError:
            LOG.exception(_("host %(dest)s is not compatible with "
                                "original host %(src)s.") % locals())
            raise

        necessary = 0
        if disk_over_commit:
            for info in disk_infos:
                necessary += int(info['disk_size'])
        else:
            for info in disk_infos:
                necessary += int(info['virt_disk_size'])

        # Check that available disk > necessary disk
        if (available - necessary) < 0:
            instance_id = ec2utils.id_to_ec2_id(instance_ref['id'])
            reason = _("Unable to migrate %(instance_id)s to %(dest)s: "
                       "Lack of disk(host:%(available)s "
                       "<= instance:%(necessary)s)")
            raise exception.MigrationError(reason=reason % locals())

    def _get_compute_info(self, context, host, key):
        """get compute node's information specified by key

        :param context: security context
        :param host: hostname(must be compute node)
        :param key: column name of compute_nodes
        :return: value specified by key

        """
        compute_node_ref = db.service_get_all_compute_by_host(context, host)
        compute_node_ref = compute_node_ref[0]['compute_node'][0]
        return compute_node_ref[key]

    def mounted_on_same_shared_storage(self, context, instance_ref, dest):
        """Check if the src and dest host mount same shared storage.

        At first, dest host creates temp file, and src host can see
        it if they mounts same shared storage. Then src host erase it.

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host

        """

        src = instance_ref['host']
        dst_t = db.queue_get_for(context, FLAGS.compute_topic, dest)
        src_t = db.queue_get_for(context, FLAGS.compute_topic, src)

        filename = None

        try:
            # create tmpfile at dest host
            filename = rpc.call(context, dst_t,
                                {"method": 'create_shared_storage_test_file'})

            # make sure existence at src host.
            ret = rpc.call(context, src_t,
                          {"method": 'check_shared_storage_test_file',
                           "args": {'filename': filename}})
            if not ret:
                raise exception.FileNotFound(file_path=filename)

        except exception.FileNotFound:
            raise

        finally:
            # Should only be None for tests?
            if filename is not None:
                rpc.call(context, dst_t,
                         {"method": 'cleanup_shared_storage_test_file',
                          "args": {'filename': filename}})
