# Copyright (c) 2012 Rackspace Hosting
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

"""
Client side of nova-cells RPC API (for talking to the nova-cells service
within a cell).

This is different than communication between child and parent nova-cells
services.  That communication is handled by the cells driver via the
messaging module.
"""

from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils

import nova.conf
from nova import exception
from nova.i18n import _LE
from nova import objects
from nova.objects import base as objects_base
from nova import rpc

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class CellsAPI(object):
    '''Cells client-side RPC API

    API version history:

        * 1.0 - Initial version.
        * 1.1 - Adds get_cell_info_for_neighbors() and sync_instances()
        * 1.2 - Adds service_get_all(), service_get_by_compute_host(),
                and proxy_rpc_to_compute_manager()
        * 1.3 - Adds task_log_get_all()
        * 1.4 - Adds compute_node_get(), compute_node_get_all(), and
                compute_node_stats()
        * 1.5 - Adds actions_get(), action_get_by_request_id(), and
                action_events_get()
        * 1.6 - Adds consoleauth_delete_tokens() and validate_console_port()

        ... Grizzly supports message version 1.6.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 1.6.

        * 1.7 - Adds service_update()
        * 1.8 - Adds build_instances(), deprecates schedule_run_instance()
        * 1.9 - Adds get_capacities()
        * 1.10 - Adds bdm_update_or_create_at_top(), and bdm_destroy_at_top()
        * 1.11 - Adds get_migrations()
        * 1.12 - Adds instance_start() and instance_stop()
        * 1.13 - Adds cell_create(), cell_update(), cell_delete(), and
                 cell_get()
        * 1.14 - Adds reboot_instance()
        * 1.15 - Adds suspend_instance() and resume_instance()
        * 1.16 - Adds instance_update_from_api()
        * 1.17 - Adds get_host_uptime()
        * 1.18 - Adds terminate_instance() and soft_delete_instance()
        * 1.19 - Adds pause_instance() and unpause_instance()
        * 1.20 - Adds resize_instance() and live_migrate_instance()
        * 1.21 - Adds revert_resize() and confirm_resize()
        * 1.22 - Adds reset_network()
        * 1.23 - Adds inject_network_info()
        * 1.24 - Adds backup_instance() and snapshot_instance()

        ... Havana supports message version 1.24.  So, any changes to existing
        methods in 1.x after that point should be done such that they can
        handle the version_cap being set to 1.24.

        * 1.25 - Adds rebuild_instance()
        * 1.26 - Adds service_delete()
        * 1.27 - Updates instance_delete_everywhere() for instance objects

        ... Icehouse supports message version 1.27.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.27.

        * 1.28 - Make bdm_update_or_create_at_top and use bdm objects
        * 1.29 - Adds set_admin_password()

        ... Juno supports message version 1.29.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.29.

        * 1.30 - Make build_instances() use flavor object
        * 1.31 - Add clean_shutdown to stop, resize, rescue, and shelve
        * 1.32 - Send objects for instances in build_instances()
        * 1.33 - Add clean_shutdown to resize_instance()
        * 1.34 - build_instances uses BlockDeviceMapping objects, drops
                 legacy_bdm argument

        ... Kilo supports message version 1.34.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.34.

        * 1.35 - Make instance_update_at_top, instance_destroy_at_top
                 and instance_info_cache_update_at_top use instance objects
        * 1.36 - Added 'delete_type' parameter to terminate_instance()
        * 1.37 - Add get_keypair_at_top to fetch keypair from api cell

        ... Liberty and Mitaka support message version 1.37.  So, any
        changes to existing methods in 1.x after that point should be
        done such that they can handle the version_cap being set to
        1.37.
    '''

    VERSION_ALIASES = {
        'grizzly': '1.6',
        'havana': '1.24',
        'icehouse': '1.27',
        'juno': '1.29',
        'kilo': '1.34',
        'liberty': '1.37',
        'mitaka': '1.37',
    }

    def __init__(self):
        super(CellsAPI, self).__init__()
        target = messaging.Target(topic=CONF.cells.topic, version='1.0')
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.cells,
                                               CONF.upgrade_levels.cells)
        # NOTE(sbauza): Yes, this is ugly but cells_utils is calling cells.db
        # which itself calls cells.rpcapi... You meant import cycling ? Gah.
        from nova.cells import utils as cells_utils
        serializer = cells_utils.ProxyObjectSerializer()
        self.client = rpc.get_client(target,
                                     version_cap=version_cap,
                                     serializer=serializer)

    def cast_compute_api_method(self, ctxt, cell_name, method,
            *args, **kwargs):
        """Make a cast to a compute API method in a certain cell."""
        method_info = {'method': method,
                       'method_args': args,
                       'method_kwargs': kwargs}
        self.client.cast(ctxt, 'run_compute_api_method',
                         cell_name=cell_name,
                         method_info=method_info,
                         call=False)

    def call_compute_api_method(self, ctxt, cell_name, method,
            *args, **kwargs):
        """Make a call to a compute API method in a certain cell."""
        method_info = {'method': method,
                       'method_args': args,
                       'method_kwargs': kwargs}
        return self.client.call(ctxt, 'run_compute_api_method',
                                cell_name=cell_name,
                                method_info=method_info,
                                call=True)

    def build_instances(self, ctxt, **kwargs):
        """Build instances."""
        build_inst_kwargs = kwargs
        instances = build_inst_kwargs['instances']
        build_inst_kwargs['image'] = jsonutils.to_primitive(
                build_inst_kwargs['image'])

        version = '1.34'
        if self.client.can_send_version('1.34'):
            build_inst_kwargs.pop('legacy_bdm', None)
        else:
            bdm_p = objects_base.obj_to_primitive(
                    build_inst_kwargs['block_device_mapping'])
            build_inst_kwargs['block_device_mapping'] = bdm_p
            version = '1.32'
        if not self.client.can_send_version('1.32'):
            instances_p = [jsonutils.to_primitive(inst) for inst in instances]
            build_inst_kwargs['instances'] = instances_p
            version = '1.30'
        if not self.client.can_send_version('1.30'):
            if 'filter_properties' in build_inst_kwargs:
                filter_properties = build_inst_kwargs['filter_properties']
                flavor = filter_properties['instance_type']
                flavor_p = objects_base.obj_to_primitive(flavor)
                filter_properties['instance_type'] = flavor_p
            version = '1.8'
        cctxt = self.client.prepare(version=version)
        cctxt.cast(ctxt, 'build_instances',
                   build_inst_kwargs=build_inst_kwargs)

    def instance_update_at_top(self, ctxt, instance):
        """Update instance at API level."""
        version = '1.35'
        if not self.client.can_send_version('1.35'):
            instance = objects_base.obj_to_primitive(instance)
            version = '1.34'
        cctxt = self.client.prepare(version=version)
        cctxt.cast(ctxt, 'instance_update_at_top', instance=instance)

    def instance_destroy_at_top(self, ctxt, instance):
        """Destroy instance at API level."""
        version = '1.35'
        if not self.client.can_send_version('1.35'):
            instance = objects_base.obj_to_primitive(instance)
            version = '1.34'
        cctxt = self.client.prepare(version=version)
        cctxt.cast(ctxt, 'instance_destroy_at_top', instance=instance)

    def instance_delete_everywhere(self, ctxt, instance, delete_type):
        """Delete instance everywhere.  delete_type may be 'soft'
        or 'hard'.  This is generally only used to resolve races
        when API cell doesn't know to what cell an instance belongs.
        """
        if self.client.can_send_version('1.27'):
            version = '1.27'
        else:
            version = '1.0'
            instance = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare(version=version)
        cctxt.cast(ctxt, 'instance_delete_everywhere', instance=instance,
                delete_type=delete_type)

    def instance_fault_create_at_top(self, ctxt, instance_fault):
        """Create an instance fault at the top."""
        instance_fault_p = jsonutils.to_primitive(instance_fault)
        self.client.cast(ctxt, 'instance_fault_create_at_top',
                         instance_fault=instance_fault_p)

    def bw_usage_update_at_top(self, ctxt, uuid, mac, start_period,
            bw_in, bw_out, last_ctr_in, last_ctr_out, last_refreshed=None):
        """Broadcast upwards that bw_usage was updated."""
        bw_update_info = {'uuid': uuid,
                          'mac': mac,
                          'start_period': start_period,
                          'bw_in': bw_in,
                          'bw_out': bw_out,
                          'last_ctr_in': last_ctr_in,
                          'last_ctr_out': last_ctr_out,
                          'last_refreshed': last_refreshed}
        self.client.cast(ctxt, 'bw_usage_update_at_top',
                         bw_update_info=bw_update_info)

    def instance_info_cache_update_at_top(self, ctxt, instance_info_cache):
        """Broadcast up that an instance's info_cache has changed."""
        version = '1.35'
        instance = objects.Instance(uuid=instance_info_cache.instance_uuid,
                                    info_cache=instance_info_cache)
        if not self.client.can_send_version('1.35'):
            instance = objects_base.obj_to_primitive(instance)
            version = '1.34'
        cctxt = self.client.prepare(version=version)
        cctxt.cast(ctxt, 'instance_update_at_top', instance=instance)

    def get_cell_info_for_neighbors(self, ctxt):
        """Get information about our neighbor cells from the manager."""
        if not CONF.cells.enable:
            return []
        cctxt = self.client.prepare(version='1.1')
        return cctxt.call(ctxt, 'get_cell_info_for_neighbors')

    def sync_instances(self, ctxt, project_id=None, updated_since=None,
            deleted=False):
        """Ask all cells to sync instance data."""
        cctxt = self.client.prepare(version='1.1')
        return cctxt.cast(ctxt, 'sync_instances',
                          project_id=project_id,
                          updated_since=updated_since,
                          deleted=deleted)

    def service_get_all(self, ctxt, filters=None):
        """Ask all cells for their list of services."""
        cctxt = self.client.prepare(version='1.2')
        return cctxt.call(ctxt, 'service_get_all', filters=filters)

    def service_get_by_compute_host(self, ctxt, host_name):
        """Get the service entry for a host in a particular cell.  The
        cell name should be encoded within the host_name.
        """
        cctxt = self.client.prepare(version='1.2')
        return cctxt.call(ctxt, 'service_get_by_compute_host',
                          host_name=host_name)

    def get_host_uptime(self, context, host_name):
        """Gets the host uptime in a particular cell. The cell name should
        be encoded within the host_name
        """
        cctxt = self.client.prepare(version='1.17')
        return cctxt.call(context, 'get_host_uptime', host_name=host_name)

    def service_update(self, ctxt, host_name, binary, params_to_update):
        """Used to enable/disable a service. For compute services, setting to
        disabled stops new builds arriving on that host.

        :param host_name: the name of the host machine that the service is
                          running
        :param binary: The name of the executable that the service runs as
        :param params_to_update: eg. {'disabled': True}
        """
        cctxt = self.client.prepare(version='1.7')
        return cctxt.call(ctxt, 'service_update',
                          host_name=host_name,
                          binary=binary,
                          params_to_update=params_to_update)

    def service_delete(self, ctxt, cell_service_id):
        """Deletes the specified service."""
        cctxt = self.client.prepare(version='1.26')
        cctxt.call(ctxt, 'service_delete',
                   cell_service_id=cell_service_id)

    def proxy_rpc_to_manager(self, ctxt, rpc_message, topic, call=False,
                             timeout=None):
        """Proxy RPC to a compute manager.  The host in the topic
        should be encoded with the target cell name.
        """
        cctxt = self.client.prepare(version='1.2', timeout=timeout)
        return cctxt.call(ctxt, 'proxy_rpc_to_manager',
                          topic=topic,
                          rpc_message=rpc_message,
                          call=call,
                          timeout=timeout)

    def task_log_get_all(self, ctxt, task_name, period_beginning,
                         period_ending, host=None, state=None):
        """Get the task logs from the DB in child cells."""
        cctxt = self.client.prepare(version='1.3')
        return cctxt.call(ctxt, 'task_log_get_all',
                          task_name=task_name,
                          period_beginning=period_beginning,
                          period_ending=period_ending,
                          host=host, state=state)

    def compute_node_get(self, ctxt, compute_id):
        """Get a compute node by ID in a specific cell."""
        cctxt = self.client.prepare(version='1.4')
        return cctxt.call(ctxt, 'compute_node_get', compute_id=compute_id)

    def compute_node_get_all(self, ctxt, hypervisor_match=None):
        """Return list of compute nodes in all cells, optionally
        filtering by hypervisor host.
        """
        cctxt = self.client.prepare(version='1.4')
        return cctxt.call(ctxt, 'compute_node_get_all',
                          hypervisor_match=hypervisor_match)

    def compute_node_stats(self, ctxt):
        """Return compute node stats from all cells."""
        cctxt = self.client.prepare(version='1.4')
        return cctxt.call(ctxt, 'compute_node_stats')

    def actions_get(self, ctxt, instance):
        if not instance['cell_name']:
            raise exception.InstanceUnknownCell(instance_uuid=instance['uuid'])
        cctxt = self.client.prepare(version='1.5')
        return cctxt.call(ctxt, 'actions_get',
                          cell_name=instance['cell_name'],
                          instance_uuid=instance['uuid'])

    def action_get_by_request_id(self, ctxt, instance, request_id):
        if not instance['cell_name']:
            raise exception.InstanceUnknownCell(instance_uuid=instance['uuid'])
        cctxt = self.client.prepare(version='1.5')
        return cctxt.call(ctxt, 'action_get_by_request_id',
                          cell_name=instance['cell_name'],
                          instance_uuid=instance['uuid'],
                          request_id=request_id)

    def action_events_get(self, ctxt, instance, action_id):
        if not instance['cell_name']:
            raise exception.InstanceUnknownCell(instance_uuid=instance['uuid'])
        cctxt = self.client.prepare(version='1.5')
        return cctxt.call(ctxt, 'action_events_get',
                          cell_name=instance['cell_name'],
                          action_id=action_id)

    def consoleauth_delete_tokens(self, ctxt, instance_uuid):
        """Delete consoleauth tokens for an instance in API cells."""
        cctxt = self.client.prepare(version='1.6')
        cctxt.cast(ctxt, 'consoleauth_delete_tokens',
                   instance_uuid=instance_uuid)

    def validate_console_port(self, ctxt, instance_uuid, console_port,
                              console_type):
        """Validate console port with child cell compute node."""
        cctxt = self.client.prepare(version='1.6')
        return cctxt.call(ctxt, 'validate_console_port',
                          instance_uuid=instance_uuid,
                          console_port=console_port,
                          console_type=console_type)

    def get_capacities(self, ctxt, cell_name=None):
        cctxt = self.client.prepare(version='1.9')
        return cctxt.call(ctxt, 'get_capacities', cell_name=cell_name)

    def bdm_update_or_create_at_top(self, ctxt, bdm, create=None):
        """Create or update a block device mapping in API cells.  If
        create is True, only try to create.  If create is None, try to
        update but fall back to create.  If create is False, only attempt
        to update.  This maps to nova-conductor's behavior.
        """
        if self.client.can_send_version('1.28'):
            version = '1.28'
        else:
            version = '1.10'
            bdm = objects_base.obj_to_primitive(bdm)
        cctxt = self.client.prepare(version=version)

        try:
            cctxt.cast(ctxt, 'bdm_update_or_create_at_top',
                       bdm=bdm, create=create)
        except Exception:
            LOG.exception(_LE("Failed to notify cells of BDM update/create."))

    def bdm_destroy_at_top(self, ctxt, instance_uuid, device_name=None,
                           volume_id=None):
        """Broadcast upwards that a block device mapping was destroyed.
        One of device_name or volume_id should be specified.
        """
        cctxt = self.client.prepare(version='1.10')
        try:
            cctxt.cast(ctxt, 'bdm_destroy_at_top',
                       instance_uuid=instance_uuid,
                       device_name=device_name,
                       volume_id=volume_id)
        except Exception:
            LOG.exception(_LE("Failed to notify cells of BDM destroy."))

    def get_migrations(self, ctxt, filters):
        """Get all migrations applying the filters."""
        cctxt = self.client.prepare(version='1.11')
        return cctxt.call(ctxt, 'get_migrations', filters=filters)

    def instance_update_from_api(self, ctxt, instance, expected_vm_state,
                                 expected_task_state, admin_state_reset):
        """Update an instance in its cell.

        This method takes a new-world instance object.
        """
        cctxt = self.client.prepare(version='1.16')
        cctxt.cast(ctxt, 'instance_update_from_api',
                   instance=instance,
                   expected_vm_state=expected_vm_state,
                   expected_task_state=expected_task_state,
                   admin_state_reset=admin_state_reset)

    def start_instance(self, ctxt, instance):
        """Start an instance in its cell.

        This method takes a new-world instance object.
        """
        cctxt = self.client.prepare(version='1.12')
        cctxt.cast(ctxt, 'start_instance', instance=instance)

    def stop_instance(self, ctxt, instance, do_cast=True, clean_shutdown=True):
        """Stop an instance in its cell.

        This method takes a new-world instance object.
        """
        msg_args = {'instance': instance,
                    'do_cast': do_cast}
        if self.client.can_send_version('1.31'):
            version = '1.31'
            msg_args['clean_shutdown'] = clean_shutdown
        else:
            version = '1.12'
        cctxt = self.client.prepare(version=version)
        method = do_cast and cctxt.cast or cctxt.call
        return method(ctxt, 'stop_instance', **msg_args)

    def cell_create(self, ctxt, values):
        cctxt = self.client.prepare(version='1.13')
        return cctxt.call(ctxt, 'cell_create', values=values)

    def cell_update(self, ctxt, cell_name, values):
        cctxt = self.client.prepare(version='1.13')
        return cctxt.call(ctxt, 'cell_update',
                          cell_name=cell_name, values=values)

    def cell_delete(self, ctxt, cell_name):
        cctxt = self.client.prepare(version='1.13')
        return cctxt.call(ctxt, 'cell_delete', cell_name=cell_name)

    def cell_get(self, ctxt, cell_name):
        cctxt = self.client.prepare(version='1.13')
        return cctxt.call(ctxt, 'cell_get', cell_name=cell_name)

    def reboot_instance(self, ctxt, instance, block_device_info,
                        reboot_type):
        """Reboot an instance in its cell.

        This method takes a new-world instance object.
        """
        cctxt = self.client.prepare(version='1.14')
        cctxt.cast(ctxt, 'reboot_instance', instance=instance,
                   reboot_type=reboot_type)

    def pause_instance(self, ctxt, instance):
        """Pause an instance in its cell.

        This method takes a new-world instance object.
        """
        cctxt = self.client.prepare(version='1.19')
        cctxt.cast(ctxt, 'pause_instance', instance=instance)

    def unpause_instance(self, ctxt, instance):
        """Unpause an instance in its cell.

        This method takes a new-world instance object.
        """
        cctxt = self.client.prepare(version='1.19')
        cctxt.cast(ctxt, 'unpause_instance', instance=instance)

    def suspend_instance(self, ctxt, instance):
        """Suspend an instance in its cell.

        This method takes a new-world instance object.
        """
        cctxt = self.client.prepare(version='1.15')
        cctxt.cast(ctxt, 'suspend_instance', instance=instance)

    def resume_instance(self, ctxt, instance):
        """Resume an instance in its cell.

        This method takes a new-world instance object.
        """
        cctxt = self.client.prepare(version='1.15')
        cctxt.cast(ctxt, 'resume_instance', instance=instance)

    def terminate_instance(self, ctxt, instance, bdms, reservations=None,
                           delete_type='delete'):
        """Delete an instance in its cell.

        This method takes a new-world instance object.
        """
        msg_kwargs = {'instance': instance}
        if self.client.can_send_version('1.36'):
            version = '1.36'
            msg_kwargs['delete_type'] = delete_type
        else:
            version = '1.18'
        cctxt = self.client.prepare(version=version)
        cctxt.cast(ctxt, 'terminate_instance', **msg_kwargs)

    def soft_delete_instance(self, ctxt, instance, reservations=None):
        """Soft-delete an instance in its cell.

        This method takes a new-world instance object.
        """
        cctxt = self.client.prepare(version='1.18')
        cctxt.cast(ctxt, 'soft_delete_instance', instance=instance)

    def resize_instance(self, ctxt, instance, extra_instance_updates,
                       scheduler_hint, flavor, reservations,
                       clean_shutdown=True):
        flavor_p = jsonutils.to_primitive(flavor)
        version = '1.33'
        msg_args = {'instance': instance,
                    'flavor': flavor_p,
                    'extra_instance_updates': extra_instance_updates,
                    'clean_shutdown': clean_shutdown}
        if not self.client.can_send_version(version):
            del msg_args['clean_shutdown']
            version = '1.20'

        cctxt = self.client.prepare(version=version)
        cctxt.cast(ctxt, 'resize_instance', **msg_args)

    def live_migrate_instance(self, ctxt, instance, host_name,
                              block_migration, disk_over_commit,
                              request_spec=None):
        # NOTE(sbauza): Since Cells v1 is quite feature-freeze, we don't want
        # to pass down request_spec to the manager and rather keep the
        # cell conductor providing a new RequestSpec like the original
        # behaviour
        cctxt = self.client.prepare(version='1.20')
        cctxt.cast(ctxt, 'live_migrate_instance',
                   instance=instance,
                   block_migration=block_migration,
                   disk_over_commit=disk_over_commit,
                   host_name=host_name)

    def revert_resize(self, ctxt, instance, migration, host,
                      reservations):
        cctxt = self.client.prepare(version='1.21')
        cctxt.cast(ctxt, 'revert_resize', instance=instance)

    def confirm_resize(self, ctxt, instance, migration, host,
                       reservations, cast=True):
        # NOTE(comstud): This is only used in the API cell where we should
        # always cast and ignore the 'cast' kwarg.
        # Also, the compute api method normally takes an optional
        # 'migration_ref' argument.  But this is only used from the manager
        # back to the API... which would happen in the child cell.
        cctxt = self.client.prepare(version='1.21')
        cctxt.cast(ctxt, 'confirm_resize', instance=instance)

    def reset_network(self, ctxt, instance):
        """Reset networking for an instance."""
        cctxt = self.client.prepare(version='1.22')
        cctxt.cast(ctxt, 'reset_network', instance=instance)

    def inject_network_info(self, ctxt, instance):
        """Inject networking for an instance."""
        cctxt = self.client.prepare(version='1.23')
        cctxt.cast(ctxt, 'inject_network_info', instance=instance)

    def snapshot_instance(self, ctxt, instance, image_id):
        cctxt = self.client.prepare(version='1.24')
        cctxt.cast(ctxt, 'snapshot_instance',
                   instance=instance, image_id=image_id)

    def backup_instance(self, ctxt, instance, image_id, backup_type, rotation):
        cctxt = self.client.prepare(version='1.24')
        cctxt.cast(ctxt, 'backup_instance',
                   instance=instance,
                   image_id=image_id,
                   backup_type=backup_type,
                   rotation=rotation)

    def rebuild_instance(self, ctxt, instance, new_pass, injected_files,
                         image_ref, orig_image_ref, orig_sys_metadata, bdms,
                         recreate=False, on_shared_storage=False, host=None,
                         preserve_ephemeral=False, request_spec=None,
                         kwargs=None):
        # NOTE(sbauza): Since Cells v1 is quite feature-freeze, we don't want
        # to pass down request_spec to the manager and rather keep the
        # cell conductor providing a new RequestSpec like the original
        # behaviour
        cctxt = self.client.prepare(version='1.25')
        cctxt.cast(ctxt, 'rebuild_instance',
                   instance=instance, image_href=image_ref,
                   admin_password=new_pass, files_to_inject=injected_files,
                   preserve_ephemeral=preserve_ephemeral, kwargs=kwargs)

    def set_admin_password(self, ctxt, instance, new_pass):
        cctxt = self.client.prepare(version='1.29')
        cctxt.cast(ctxt, 'set_admin_password', instance=instance,
                new_pass=new_pass)

    def get_keypair_at_top(self, ctxt, user_id, name):
        if not CONF.cells.enable:
            return

        cctxt = self.client.prepare(version='1.37')
        keypair = cctxt.call(ctxt, 'get_keypair_at_top', user_id=user_id,
                             name=name)
        if keypair is None:
            raise exception.KeypairNotFound(user_id=user_id,
                                            name=name)
        return keypair
