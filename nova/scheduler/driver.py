# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 OpenStack Foundation
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

import sys

from oslo.config import cfg

from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor import api as conductor_api
from nova import db
from nova import exception
from nova.image import glance
from nova import notifications
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier
from nova.openstack.common import timeutils
from nova import servicegroup

LOG = logging.getLogger(__name__)

scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='nova.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    cfg.IntOpt('scheduler_max_attempts',
               default=3,
               help='Maximum number of attempts to schedule an instance'),
    ]

CONF = cfg.CONF
CONF.register_opts(scheduler_driver_opts)


def handle_schedule_error(context, ex, instance_uuid, request_spec):
    if not isinstance(ex, exception.NoValidHost):
        LOG.exception(_("Exception during scheduler.run_instance"))
    state = vm_states.ERROR.upper()
    LOG.warning(_('Setting instance to %(state)s state.'),
                locals(), instance_uuid=instance_uuid)

    # update instance state and notify on the transition
    (old_ref, new_ref) = db.instance_update_and_get_original(context,
            instance_uuid, {'vm_state': vm_states.ERROR,
                            'task_state': None})
    notifications.send_update(context, old_ref, new_ref,
            service="scheduler")
    compute_utils.add_instance_fault_from_exc(context,
            conductor_api.LocalAPI(),
            new_ref, ex, sys.exc_info())

    properties = request_spec.get('instance_properties', {})
    payload = dict(request_spec=request_spec,
                   instance_properties=properties,
                   instance_id=instance_uuid,
                   state=vm_states.ERROR,
                   method='run_instance',
                   reason=ex)

    notifier.notify(context, notifier.publisher_id("scheduler"),
                    'scheduler.run_instance', notifier.ERROR, payload)


def instance_update_db(context, instance_uuid, extra_values=None):
    '''Clear the host and node - set the scheduled_at field of an Instance.

    :returns: An Instance with the updated fields set properly.
    '''
    now = timeutils.utcnow()
    values = {'host': None, 'node': None, 'scheduled_at': now}
    if extra_values:
        values.update(extra_values)

    return db.instance_update(context, instance_uuid, values)


def encode_instance(instance, local=True):
    """Encode locally created instance for return via RPC."""
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
                CONF.scheduler_host_manager)
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.servicegroup_api = servicegroup.API()
        self.image_service = glance.get_default_image_service()

    def update_service_capabilities(self, service_name, host, capabilities):
        """Process a capability update from a service node."""
        self.host_manager.update_service_capabilities(service_name,
                host, capabilities)

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service['host']
                for service in services
                if self.servicegroup_api.service_is_up(service)]

    def group_hosts(self, context, group):
        """Return the list of hosts that have VM's from the group."""

        # The system_metadata 'group' will be filtered
        members = db.instance_get_all_by_filters(context,
                {'deleted': False, 'group': group})
        return [member['host']
                for member in members
                if member.get('host') is not None]

    def schedule_prep_resize(self, context, image, request_spec,
                             filter_properties, instance, instance_type,
                             reservations):
        """Must override schedule_prep_resize method for scheduler to work."""
        msg = _("Driver must implement schedule_prep_resize")
        raise NotImplementedError(msg)

    def schedule_run_instance(self, context, request_spec,
                              admin_password, injected_files,
                              requested_networks, is_first_time,
                              filter_properties):
        """Must override schedule_run_instance method for scheduler to work."""
        msg = _("Driver must implement schedule_run_instance")
        raise NotImplementedError(msg)

    def select_hosts(self, context, request_spec, filter_properties):
        """Must override select_hosts method for scheduler to work."""
        msg = _("Driver must implement select_hosts")
        raise NotImplementedError(msg)

    def schedule_live_migration(self, context, instance, dest,
                                block_migration, disk_over_commit):
        """Live migration scheduling method.

        :param context:
        :param instance: instance dict
        :param dest: destination host
        :param block_migration: if true, block_migration.
        :param disk_over_commit: if True, consider real(not virtual)
                                 disk size.

        :return:
            The host where instance is running currently.
            Then scheduler send request that host.
        """
        # Check we can do live migration
        self._live_migration_src_check(context, instance)

        if dest is None:
            # Let scheduler select a dest host, retry next best until success
            # or no more valid hosts.
            ignore_hosts = [instance['host']]
            while dest is None:
                dest = self._live_migration_dest_check(context, instance, dest,
                                                       ignore_hosts)
                try:
                    self._live_migration_common_check(context, instance, dest)
                    migrate_data = self.compute_rpcapi.\
                        check_can_live_migrate_destination(context, instance,
                                                           dest,
                                                           block_migration,
                                                           disk_over_commit)
                except exception.Invalid:
                    ignore_hosts.append(dest)
                    dest = None
                    continue
        else:
            # Test the given dest host
            self._live_migration_dest_check(context, instance, dest)
            self._live_migration_common_check(context, instance, dest)
            migrate_data = self.compute_rpcapi.\
                check_can_live_migrate_destination(context, instance, dest,
                                                   block_migration,
                                                   disk_over_commit)

        # Perform migration
        src = instance['host']
        self.compute_rpcapi.live_migration(context, host=src,
                instance=instance, dest=dest,
                block_migration=block_migration,
                migrate_data=migrate_data)

    def _live_migration_src_check(self, context, instance_ref):
        """Live migration check routine (for src host).

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object

        """
        # TODO(johngar) why is this not in the API layer?
        # Checking instance is running.
        if instance_ref['power_state'] != power_state.RUNNING:
            raise exception.InstanceNotRunning(
                    instance_id=instance_ref['uuid'])

        # Checking src host exists and compute node
        src = instance_ref['host']
        try:
            service = db.service_get_by_compute_host(context, src)
        except exception.NotFound:
            raise exception.ComputeServiceUnavailable(host=src)

        # Checking src host is alive.
        if not self.servicegroup_api.service_is_up(service):
            raise exception.ComputeServiceUnavailable(host=src)

    def _live_migration_dest_check(self, context, instance_ref, dest,
                                   ignore_hosts=None):
        """Live migration check routine (for destination host).

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host
        :param ignore_hosts: hosts that should be avoided as dest host
        """

        # If dest is not specified, have scheduler pick one.
        if dest is None:
            instance_type = db.instance_type_get(
                context, instance_ref['instance_type_id'])
            image = self.image_service.show(context, instance_ref['image_ref'])
            request_spec = {'instance_properties': instance_ref,
                            'instance_type': instance_type,
                            'instance_uuids': [instance_ref['uuid']],
                            'image': image}
            filter_properties = {'ignore_hosts': ignore_hosts}
            return self.select_hosts(context, request_spec,
                                     filter_properties)[0]

        # Checking whether The host where instance is running
        # and dest is not same.
        src = instance_ref['host']
        if dest == src:
            raise exception.UnableToMigrateToSelf(
                    instance_id=instance_ref['uuid'], host=dest)

        # Checking dest exists and compute node.
        try:
            dservice_ref = db.service_get_by_compute_host(context, dest)
        except exception.NotFound:
            raise exception.ComputeServiceUnavailable(host=dest)

        # Checking dest host is alive.
        if not self.servicegroup_api.service_is_up(dservice_ref):
            raise exception.ComputeServiceUnavailable(host=dest)

        # Check memory requirements
        self._assert_compute_node_has_enough_memory(context,
                                                   instance_ref, dest)

        return dest

    def _live_migration_common_check(self, context, instance_ref, dest):
        """Live migration common check routine.

        The following checks are based on
        http://wiki.libvirt.org/page/TodoPreMigrationChecks

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host
        """
        dservice_ref = self._get_compute_info(context, dest)
        src = instance_ref['host']
        oservice_ref = self._get_compute_info(context, src)

        # Checking hypervisor is same.
        orig_hypervisor = oservice_ref['hypervisor_type']
        dest_hypervisor = dservice_ref['hypervisor_type']
        if orig_hypervisor != dest_hypervisor:
            raise exception.InvalidHypervisorType()

        # Checking hypervisor version.
        orig_hypervisor = oservice_ref['hypervisor_version']
        dest_hypervisor = dservice_ref['hypervisor_version']
        if orig_hypervisor > dest_hypervisor:
            raise exception.DestinationHypervisorTooOld()

    def _assert_compute_node_has_enough_memory(self, context,
                                              instance_ref, dest):
        """Checks if destination host has enough memory for live migration.


        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance object
        :param dest: destination host

        """
        # Getting total available memory of host
        avail = self._get_compute_info(context, dest)['free_ram_mb']

        mem_inst = instance_ref['memory_mb']
        if not mem_inst or avail <= mem_inst:
            instance_uuid = instance_ref['uuid']
            reason = _("Unable to migrate %(instance_uuid)s to %(dest)s: "
                       "Lack of memory(host:%(avail)s <= "
                       "instance:%(mem_inst)s)")
            raise exception.MigrationError(reason=reason % locals())

    def _get_compute_info(self, context, host):
        """get compute node's information specified by key

        :param context: security context
        :param host: hostname(must be compute node)
        :param key: column name of compute_nodes
        :return: value specified by key

        """
        service_ref = db.service_get_by_compute_host(context, host)
        return service_ref['compute_node'][0]
