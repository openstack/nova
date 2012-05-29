# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 OpenStack, LLC.
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

from nova.compute import api as compute_api
from nova.compute import power_state
from nova.compute import vm_states
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import notifications
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova import rpc
from nova.rpc import common as rpc_common
from nova import utils


LOG = logging.getLogger(__name__)

scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='nova.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(scheduler_driver_opts)

flags.DECLARE('instances_path', 'nova.compute.manager')
flags.DECLARE('libvirt_type', 'nova.virt.libvirt.connection')


def cast_to_volume_host(context, host, method, update_db=True, **kwargs):
    """Cast request to a volume host queue"""

    if update_db:
        volume_id = kwargs.get('volume_id', None)
        if volume_id is not None:
            now = utils.utcnow()
            db.volume_update(context, volume_id,
                    {'host': host, 'scheduled_at': now})
    rpc.cast(context,
             rpc.queue_get_for(context, 'volume', host),
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
             rpc.queue_get_for(context, 'compute', host),
             {"method": method, "args": kwargs})
    LOG.debug(_("Casted '%(method)s' to compute '%(host)s'") % locals())


def cast_to_network_host(context, host, method, update_db=False, **kwargs):
    """Cast request to a network host queue"""

    rpc.cast(context,
             rpc.queue_get_for(context, 'network', host),
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
                 rpc.queue_get_for(context, topic, host),
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
        inst = dict(instance)
        inst['_is_precooked'] = True
        return inst


class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.host_manager = importutils.import_object(
                FLAGS.scheduler_host_manager)
        self.compute_api = compute_api.API()

    def get_host_list(self):
        """Get a list of hosts from the HostManager."""
        return self.host_manager.get_host_list()

    def get_service_capabilities(self):
        """Get the normalized set of capabilities for the services.
        """
        return self.host_manager.get_service_capabilities()

    def update_service_capabilities(self, service_name, host, capabilities):
        """Process a capability update from a service node."""
        self.host_manager.update_service_capabilities(service_name,
                host, capabilities)

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service['host']
                for service in services
                if utils.service_is_up(service)]

    def create_instance_db_entry(self, context, request_spec, reservations):
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
                security_group, block_device_mapping, reservations)
        # NOTE(comstud): This needs to be set for the generic exception
        # checking in scheduler manager, so that it'll set this instance
        # to ERROR properly.
        base_options['uuid'] = instance['uuid']
        return instance

    def schedule(self, context, topic, method, *_args, **_kwargs):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement a fallback schedule"))

    def schedule_prep_resize(self, context, request_spec, *_args, **_kwargs):
        """Must override schedule_prep_resize method for scheduler to work."""
        msg = _("Driver must implement schedule_prep_resize")
        raise NotImplementedError(msg)

    def schedule_run_instance(self, context, request_spec, *_args, **_kwargs):
        """Must override schedule_run_instance method for scheduler to work."""
        msg = _("Driver must implement schedule_run_instance")
        raise NotImplementedError(msg)

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

        # update instance state and notify
        (old_ref, new_instance_ref) = db.instance_update_and_get_original(
                context, instance_id, values)
        notifications.send_update(context, old_ref, new_instance_ref)

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
        if instance_ref['power_state'] != power_state.RUNNING and not (
            FLAGS.libvirt_type == 'xen' and
            instance_ref['power_state'] == power_state.BLOCKED):
            raise exception.InstanceNotRunning(
                    instance_id=instance_ref['uuid'])

        # Checking src host exists and compute node
        src = instance_ref['host']
        services = db.service_get_all_compute_by_host(context, src)

        # Checking src host is alive.
        if not utils.service_is_up(services[0]):
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
        if not utils.service_is_up(dservice_ref):
            raise exception.ComputeServiceUnavailable(host=dest)

        # Checking whether The host where instance is running
        # and dest is not same.
        src = instance_ref['host']
        if dest == src:
            raise exception.UnableToMigrateToSelf(
                    instance_id=instance_ref['uuid'], host=dest)

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
        shared = self.mounted_on_same_shared_storage(context, instance_ref,
                                                     dest)
        if block_migration:
            if shared:
                reason = _("Block migration can not be used "
                           "with shared storage.")
                raise exception.InvalidSharedStorage(reason=reason, path=dest)

        elif not shared:
            reason = _("Live migration can not be used "
                       "without shared storage.")
            raise exception.InvalidSharedStorage(reason=reason, path=dest)

        # Checking destination host exists.
        dservice_refs = db.service_get_all_compute_by_host(context, dest)
        dservice_ref = dservice_refs[0]['compute_node'][0]

        # Checking original host( where instance was launched at) exists.
        try:
            oservice_refs = db.service_get_all_compute_by_host(context,
                                           instance_ref['host'])
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
                     rpc.queue_get_for(context, FLAGS.compute_topic, dest),
                     {"method": 'compare_cpu',
                      "args": {'cpu_info': oservice_ref['cpu_info']}})

        except exception.InvalidCPUInfo:
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
        instance_refs = db.instance_get_all_by_host(context, dest)
        used = sum([i['memory_mb'] for i in instance_refs])

        mem_inst = instance_ref['memory_mb']
        avail = avail - used
        if avail <= mem_inst:
            instance_uuid = instance_ref['uuid']
            reason = _("Unable to migrate %(instance_uuid)s to %(dest)s: "
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

        # Getting total available disk of host
        available_gb = self._get_compute_info(context,
                                              dest, 'disk_available_least')
        available = available_gb * (1024 ** 3)

        # Getting necessary disk size
        topic = rpc.queue_get_for(context, FLAGS.compute_topic,
                                          instance_ref['host'])
        ret = rpc.call(context, topic,
                       {"method": 'get_instance_disk_info',
                        "args": {'instance_name': instance_ref['name']}})
        disk_infos = jsonutils.loads(ret)

        necessary = 0
        if disk_over_commit:
            for info in disk_infos:
                necessary += int(info['disk_size'])
        else:
            for info in disk_infos:
                necessary += int(info['virt_disk_size'])

        # Check that available disk > necessary disk
        if (available - necessary) < 0:
            instance_uuid = instance_ref['uuid']
            reason = _("Unable to migrate %(instance_uuid)s to %(dest)s: "
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
        dst_t = rpc.queue_get_for(context, FLAGS.compute_topic, dest)
        src_t = rpc.queue_get_for(context, FLAGS.compute_topic, src)

        filename = rpc.call(context, dst_t,
                            {"method": 'create_shared_storage_test_file'})

        try:
            # make sure existence at src host.
            ret = rpc.call(context, src_t,
                        {"method": 'check_shared_storage_test_file',
                        "args": {'filename': filename}})

        finally:
            rpc.cast(context, dst_t,
                    {"method": 'cleanup_shared_storage_test_file',
                    "args": {'filename': filename}})

        return ret
