# Copyright (c) 2012 Rackspace Hosting
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

"""Compute API that proxies via Cells Service."""

from nova import availability_zones
from nova import block_device
from nova.cells import rpcapi as cells_rpcapi
from nova.cells import utils as cells_utils
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import vm_states
from nova import exception
from nova.openstack.common import excutils


check_instance_state = compute_api.check_instance_state
wrap_check_policy = compute_api.wrap_check_policy
check_policy = compute_api.check_policy
check_instance_lock = compute_api.check_instance_lock


def validate_cell(fn):
    def _wrapped(self, context, instance, *args, **kwargs):
        self._validate_cell(instance, fn.__name__)
        return fn(self, context, instance, *args, **kwargs)
    _wrapped.__name__ = fn.__name__
    return _wrapped


class ComputeRPCAPINoOp(object):
    def __getattr__(self, key):
        def _noop_rpc_wrapper(*args, **kwargs):
            return None
        return _noop_rpc_wrapper


class SchedulerRPCAPIRedirect(object):
    def __init__(self, cells_rpcapi_obj):
        self.cells_rpcapi = cells_rpcapi_obj

    def __getattr__(self, key):
        def _noop_rpc_wrapper(*args, **kwargs):
            return None
        return _noop_rpc_wrapper


class ConductorTaskRPCAPIRedirect(object):
    def __init__(self, cells_rpcapi_obj):
        self.cells_rpcapi = cells_rpcapi_obj

    def __getattr__(self, key):
        def _noop_rpc_wrapper(*args, **kwargs):
            return None
        return _noop_rpc_wrapper

    def build_instances(self, context, **kwargs):
        self.cells_rpcapi.build_instances(context, **kwargs)


class ComputeRPCProxyAPI(compute_rpcapi.ComputeAPI):
    """Class used to substitute Compute RPC API that will proxy
    via the cells manager to a compute manager in a child cell.
    """
    def __init__(self, *args, **kwargs):
        super(ComputeRPCProxyAPI, self).__init__(*args, **kwargs)
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def cast(self, ctxt, msg, topic=None, version=None):
        self._set_version(msg, version)
        topic = self._get_topic(topic)
        self.cells_rpcapi.proxy_rpc_to_manager(ctxt, msg, topic)

    def call(self, ctxt, msg, topic=None, version=None, timeout=None):
        self._set_version(msg, version)
        topic = self._get_topic(topic)
        return self.cells_rpcapi.proxy_rpc_to_manager(ctxt, msg, topic,
                                                      call=True,
                                                      timeout=timeout)


class ComputeCellsAPI(compute_api.API):
    def __init__(self, *args, **kwargs):
        super(ComputeCellsAPI, self).__init__(*args, **kwargs)
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        # Avoid casts/calls directly to compute
        self.compute_rpcapi = ComputeRPCAPINoOp()
        # Redirect scheduler run_instance to cells.
        self.scheduler_rpcapi = SchedulerRPCAPIRedirect(self.cells_rpcapi)
        # Redirect conductor build_instances to cells
        self._compute_task_api = ConductorTaskRPCAPIRedirect(self.cells_rpcapi)

    def _cell_read_only(self, cell_name):
        """Is the target cell in a read-only mode?"""
        # FIXME(comstud): Add support for this.
        return False

    def _validate_cell(self, instance, method):
        cell_name = instance['cell_name']
        if not cell_name:
            raise exception.InstanceUnknownCell(
                    instance_uuid=instance['uuid'])
        if self._cell_read_only(cell_name):
            raise exception.InstanceInvalidState(
                    attr="vm_state",
                    instance_uuid=instance['uuid'],
                    state="temporary_readonly",
                    method=method)

    def _cast_to_cells(self, context, instance, method, *args, **kwargs):
        instance_uuid = instance['uuid']
        cell_name = instance['cell_name']
        if not cell_name:
            raise exception.InstanceUnknownCell(instance_uuid=instance_uuid)
        self.cells_rpcapi.cast_compute_api_method(context, cell_name,
                method, instance_uuid, *args, **kwargs)

    def _call_to_cells(self, context, instance, method, *args, **kwargs):
        instance_uuid = instance['uuid']
        cell_name = instance['cell_name']
        if not cell_name:
            raise exception.InstanceUnknownCell(instance_uuid=instance_uuid)
        return self.cells_rpcapi.call_compute_api_method(context, cell_name,
                method, instance_uuid, *args, **kwargs)

    def _check_requested_networks(self, context, requested_networks):
        """Override compute API's checking of this.  It'll happen in
        child cell
        """
        return

    def _validate_image_href(self, context, image_href):
        """Override compute API's checking of this.  It'll happen in
        child cell
        """
        return

    def backup(self, context, instance, name, backup_type, rotation,
               extra_properties=None, image_id=None):
        """Backup the given instance."""
        image_meta = super(ComputeCellsAPI, self).backup(context,
                instance, name, backup_type, rotation,
                extra_properties=extra_properties, image_id=image_id)
        image_id = image_meta['id']
        self._cast_to_cells(context, instance, 'backup', name,
                backup_type=backup_type, rotation=rotation,
                extra_properties=extra_properties, image_id=image_id)
        return image_meta

    def snapshot(self, context, instance, name, extra_properties=None,
                 image_id=None):
        """Snapshot the given instance."""
        image_meta = super(ComputeCellsAPI, self).snapshot(context,
                instance, name, extra_properties=extra_properties,
                image_id=image_id)
        image_id = image_meta['id']
        self._cast_to_cells(context, instance, 'snapshot',
                name, extra_properties=extra_properties, image_id=image_id)
        return image_meta

    def create(self, *args, **kwargs):
        """We can use the base functionality, but I left this here just
        for completeness.
        """
        return super(ComputeCellsAPI, self).create(*args, **kwargs)

    def update_state(self, context, instance, new_state):
        """Updates the state of a compute instance.
        For example to 'active' or 'error'.
        Also sets 'task_state' to None.
        Used by admin_actions api

        :param context: The security context
        :param instance: The instance to update
        :param new_state: A member of vm_state to change
                          the instance's state to,
                          eg. 'active'
        """
        self.update(context, instance,
                    pass_on_state_change=True,
                    vm_state=new_state,
                    task_state=None)

    def update(self, context, instance, pass_on_state_change=False, **kwargs):
        """
        Update an instance.
        :param pass_on_state_change: if true, the state change will be passed
                                     on to child cells
        """
        cell_name = instance['cell_name']
        if cell_name and self._cell_read_only(cell_name):
            raise exception.InstanceInvalidState(
                    attr="vm_state",
                    instance_uuid=instance['uuid'],
                    state="temporary_readonly",
                    method='update')
        rv = super(ComputeCellsAPI, self).update(context,
                instance, **kwargs)
        kwargs_copy = kwargs.copy()
        if not pass_on_state_change:
            # We need to skip vm_state/task_state updates... those will
            # happen via a _cast_to_cells when running a different
            # compute api method
            kwargs_copy.pop('vm_state', None)
            kwargs_copy.pop('task_state', None)
        if kwargs_copy:
            try:
                self._cast_to_cells(context, instance, 'update',
                        **kwargs_copy)
            except exception.InstanceUnknownCell:
                pass
        return rv

    def _local_delete(self, context, instance, bdms):
        # This will get called for every delete in the API cell
        # because _delete() in compute/api.py will not find a
        # service when checking if it's up.
        # We need to only take action if there's no cell_name.  Our
        # overrides of delete() and soft_delete() will take care of
        # the rest.
        cell_name = instance['cell_name']
        if not cell_name:
            return super(ComputeCellsAPI, self)._local_delete(context,
                    instance, bdms)

    def soft_delete(self, context, instance):
        self._handle_cell_delete(context, instance,
                super(ComputeCellsAPI, self).soft_delete, 'soft_delete')

    def delete(self, context, instance):
        self._handle_cell_delete(context, instance,
                super(ComputeCellsAPI, self).delete, 'delete')

    def _handle_cell_delete(self, context, instance, method, method_name):
        """Terminate an instance."""
        # We can't use the decorator because we have special logic in the
        # case we don't know the cell_name...
        cell_name = instance['cell_name']
        if cell_name and self._cell_read_only(cell_name):
            raise exception.InstanceInvalidState(
                    attr="vm_state",
                    instance_uuid=instance['uuid'],
                    state="temporary_readonly",
                    method=method_name)
        method(context, instance)
        try:
            self._cast_to_cells(context, instance, method_name)
        except exception.InstanceUnknownCell:
            # If there's no cell, there's also no host... which means
            # the instance was destroyed from the DB here.  Let's just
            # broadcast a message down to all cells and hope this ends
            # up resolving itself...  Worse case.. the instance will
            # show back up again here.
            delete_type = method_name == 'soft_delete' and 'soft' or 'hard'
            self.cells_rpcapi.instance_delete_everywhere(context,
                    instance, delete_type)

    @validate_cell
    def restore(self, context, instance):
        """Restore a previously deleted (but not reclaimed) instance."""
        super(ComputeCellsAPI, self).restore(context, instance)
        self._cast_to_cells(context, instance, 'restore')

    @validate_cell
    def force_delete(self, context, instance):
        """Force delete a previously deleted (but not reclaimed) instance."""
        super(ComputeCellsAPI, self).force_delete(context, instance)
        self._cast_to_cells(context, instance, 'force_delete')

    @validate_cell
    def stop(self, context, instance, do_cast=True):
        """Stop an instance."""
        super(ComputeCellsAPI, self).stop(context, instance)
        if do_cast:
            self._cast_to_cells(context, instance, 'stop', do_cast=True)
        else:
            return self._call_to_cells(context, instance, 'stop',
                    do_cast=False)

    @validate_cell
    def start(self, context, instance):
        """Start an instance."""
        super(ComputeCellsAPI, self).start(context, instance)
        self._cast_to_cells(context, instance, 'start')

    @validate_cell
    def reboot(self, context, instance, *args, **kwargs):
        """Reboot the given instance."""
        super(ComputeCellsAPI, self).reboot(context, instance,
                *args, **kwargs)
        self._cast_to_cells(context, instance, 'reboot', *args,
                **kwargs)

    @validate_cell
    def rebuild(self, context, instance, *args, **kwargs):
        """Rebuild the given instance with the provided attributes."""
        super(ComputeCellsAPI, self).rebuild(context, instance, *args,
                **kwargs)
        self._cast_to_cells(context, instance, 'rebuild', *args, **kwargs)

    @validate_cell
    def evacuate(self, context, instance, *args, **kwargs):
        """Evacuate the given instance with the provided attributes."""
        super(ComputeCellsAPI, self).evacuate(context, instance, *args,
                **kwargs)
        self._cast_to_cells(context, instance, 'evacuate', *args, **kwargs)

    @check_instance_state(vm_state=[vm_states.RESIZED])
    @validate_cell
    def revert_resize(self, context, instance):
        """Reverts a resize, deleting the 'new' instance in the process."""
        super(ComputeCellsAPI, self).revert_resize(context, instance)
        self._cast_to_cells(context, instance, 'revert_resize')

    @check_instance_state(vm_state=[vm_states.RESIZED])
    @validate_cell
    def confirm_resize(self, context, instance):
        """Confirms a migration/resize and deletes the 'old' instance."""
        super(ComputeCellsAPI, self).confirm_resize(context, instance)
        self._cast_to_cells(context, instance, 'confirm_resize')

    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED],
                          task_state=[None])
    @validate_cell
    def resize(self, context, instance, flavor_id=None, *args, **kwargs):
        """Resize (ie, migrate) a running instance.

        If flavor_id is None, the process is considered a migration, keeping
        the original flavor_id. If flavor_id is not None, the instance should
        be migrated to a new host and resized to the new flavor_id.
        """
        super(ComputeCellsAPI, self).resize(context, instance,
                                            flavor_id=flavor_id, *args,
                                            **kwargs)

        # NOTE(johannes): If we get to this point, then we know the
        # specified flavor_id is valid and exists. We'll need to load
        # it again, but that should be safe.

        old_instance_type = flavors.extract_flavor(instance)

        if not flavor_id:
            new_instance_type = old_instance_type
        else:
            new_instance_type = flavors.get_flavor_by_flavor_id(
                    flavor_id, read_deleted="no")

        # NOTE(johannes): Later, when the resize is confirmed or reverted,
        # the superclass implementations of those methods will need access
        # to a local migration record for quota reasons. We don't need
        # source and/or destination information, just the old and new
        # flavors. Status is set to 'finished' since nothing else
        # will update the status along the way.
        self.db.migration_create(context.elevated(),
                    {'instance_uuid': instance['uuid'],
                     'old_instance_type_id': old_instance_type['id'],
                     'new_instance_type_id': new_instance_type['id'],
                     'status': 'finished'})

        # FIXME(comstud): pass new instance_type object down to a method
        # that'll unfold it
        self._cast_to_cells(context, instance, 'resize', flavor_id=flavor_id,
                            *args, **kwargs)

    @validate_cell
    def add_fixed_ip(self, context, instance, *args, **kwargs):
        """Add fixed_ip from specified network to given instance."""
        super(ComputeCellsAPI, self).add_fixed_ip(context, instance,
                *args, **kwargs)
        self._cast_to_cells(context, instance, 'add_fixed_ip',
                *args, **kwargs)

    @validate_cell
    def remove_fixed_ip(self, context, instance, *args, **kwargs):
        """Remove fixed_ip from specified network to given instance."""
        super(ComputeCellsAPI, self).remove_fixed_ip(context, instance,
                *args, **kwargs)
        self._cast_to_cells(context, instance, 'remove_fixed_ip',
                *args, **kwargs)

    @validate_cell
    def pause(self, context, instance):
        """Pause the given instance."""
        super(ComputeCellsAPI, self).pause(context, instance)
        self._cast_to_cells(context, instance, 'pause')

    @validate_cell
    def unpause(self, context, instance):
        """Unpause the given instance."""
        super(ComputeCellsAPI, self).unpause(context, instance)
        self._cast_to_cells(context, instance, 'unpause')

    def get_diagnostics(self, context, instance):
        """Retrieve diagnostics for the given instance."""
        # FIXME(comstud): Cache this?
        # Also: only calling super() to get state/policy checking
        super(ComputeCellsAPI, self).get_diagnostics(context, instance)
        return self._call_to_cells(context, instance, 'get_diagnostics')

    @validate_cell
    def suspend(self, context, instance):
        """Suspend the given instance."""
        super(ComputeCellsAPI, self).suspend(context, instance)
        self._cast_to_cells(context, instance, 'suspend')

    @validate_cell
    def resume(self, context, instance):
        """Resume the given instance."""
        super(ComputeCellsAPI, self).resume(context, instance)
        self._cast_to_cells(context, instance, 'resume')

    @validate_cell
    def rescue(self, context, instance, rescue_password=None):
        """Rescue the given instance."""
        super(ComputeCellsAPI, self).rescue(context, instance,
                rescue_password=rescue_password)
        self._cast_to_cells(context, instance, 'rescue',
                rescue_password=rescue_password)

    @validate_cell
    def unrescue(self, context, instance):
        """Unrescue the given instance."""
        super(ComputeCellsAPI, self).unrescue(context, instance)
        self._cast_to_cells(context, instance, 'unrescue')

    @validate_cell
    def set_admin_password(self, context, instance, password=None):
        """Set the root/admin password for the given instance."""
        super(ComputeCellsAPI, self).set_admin_password(context, instance,
                password=password)
        self._cast_to_cells(context, instance, 'set_admin_password',
                password=password)

    @validate_cell
    def inject_file(self, context, instance, *args, **kwargs):
        """Write a file to the given instance."""
        super(ComputeCellsAPI, self).inject_file(context, instance, *args,
                **kwargs)
        self._cast_to_cells(context, instance, 'inject_file', *args, **kwargs)

    @wrap_check_policy
    @validate_cell
    def get_vnc_console(self, context, instance, console_type):
        """Get a url to a VNC Console."""
        if not instance['host']:
            raise exception.InstanceNotReady(instance_id=instance['uuid'])

        connect_info = self._call_to_cells(context, instance,
                'get_vnc_connect_info', console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type, connect_info['host'],
                connect_info['port'], connect_info['internal_access_path'],
                instance_uuid=instance['uuid'])
        return {'url': connect_info['access_url']}

    @wrap_check_policy
    @validate_cell
    def get_spice_console(self, context, instance, console_type):
        """Get a url to a SPICE Console."""
        if not instance['host']:
            raise exception.InstanceNotReady(instance_id=instance['uuid'])

        connect_info = self._call_to_cells(context, instance,
                'get_spice_connect_info', console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type, connect_info['host'],
                connect_info['port'], connect_info['internal_access_path'],
                instance_uuid=instance['uuid'])
        return {'url': connect_info['access_url']}

    @validate_cell
    def get_console_output(self, context, instance, *args, **kwargs):
        """Get console output for an an instance."""
        # NOTE(comstud): Calling super() just to get policy check
        super(ComputeCellsAPI, self).get_console_output(context, instance,
                *args, **kwargs)
        return self._call_to_cells(context, instance, 'get_console_output',
                *args, **kwargs)

    def lock(self, context, instance):
        """Lock the given instance."""
        super(ComputeCellsAPI, self).lock(context, instance)
        self._cast_to_cells(context, instance, 'lock')

    def unlock(self, context, instance):
        """Unlock the given instance."""
        super(ComputeCellsAPI, self).lock(context, instance)
        self._cast_to_cells(context, instance, 'unlock')

    @validate_cell
    def reset_network(self, context, instance):
        """Reset networking on the instance."""
        super(ComputeCellsAPI, self).reset_network(context, instance)
        self._cast_to_cells(context, instance, 'reset_network')

    @validate_cell
    def inject_network_info(self, context, instance):
        """Inject network info for the instance."""
        super(ComputeCellsAPI, self).inject_network_info(context, instance)
        self._cast_to_cells(context, instance, 'inject_network_info')

    @wrap_check_policy
    @validate_cell
    def attach_volume(self, context, instance, volume_id, device=None):
        """Attach an existing volume to an existing instance."""
        if device and not block_device.match_device(device):
            raise exception.InvalidDevicePath(path=device)
        try:
            volume = self.volume_api.get(context, volume_id)
            self.volume_api.check_attach(context, volume, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.block_device_mapping_destroy_by_instance_and_device(
                        context, instance['uuid'], device)
        return self._call_to_cells(context, instance, 'attach_volume',
                volume_id, device)

    @validate_cell
    def _detach_volume(self, context, instance, volume):
        """Detach a volume from an instance."""
        self.volume_api.check_detach(context, volume)
        self._cast_to_cells(context, instance, 'detach_volume',
                volume)

    @wrap_check_policy
    @validate_cell
    def associate_floating_ip(self, context, instance, address):
        """Makes calls to network_api to associate_floating_ip.

        :param address: is a string floating ip address
        """
        self._cast_to_cells(context, instance, 'associate_floating_ip',
                address)

    @validate_cell
    def delete_instance_metadata(self, context, instance, key):
        """Delete the given metadata item from an instance."""
        super(ComputeCellsAPI, self).delete_instance_metadata(context,
                instance, key)
        self._cast_to_cells(context, instance, 'delete_instance_metadata',
                key)

    @wrap_check_policy
    @validate_cell
    def update_instance_metadata(self, context, instance,
                                 metadata, delete=False):
        rv = super(ComputeCellsAPI, self).update_instance_metadata(context,
                instance, metadata, delete=delete)
        try:
            self._cast_to_cells(context, instance,
                    'update_instance_metadata',
                    metadata, delete=delete)
        except exception.InstanceUnknownCell:
            pass
        return rv

    @validate_cell
    def live_migrate(self, context, instance, block_migration,
                     disk_over_commit, host_name):
        """Migrate a server lively to a new host."""
        super(ComputeCellsAPI, self).live_migrate(context,
            instance, block_migration, disk_over_commit, host_name)

        self._cast_to_cells(context, instance, 'live_migrate',
                            block_migration, disk_over_commit, host_name)


class HostAPI(compute_api.HostAPI):
    """HostAPI() class for cells.

    Implements host management related operations.  Works by setting the
    RPC API used by the base class to proxy via the cells manager to the
    compute manager in the correct cell.  Hosts specified with cells will
    need to be of the format 'path!to!cell@host'.

    DB methods in the base class are also overridden to proxy via the
    cells manager.
    """
    def __init__(self):
        super(HostAPI, self).__init__(rpcapi=ComputeRPCProxyAPI())
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def _assert_host_exists(self, context, host_name):
        """Cannot check this in API cell.  This will be checked in the
        target child cell.
        """
        pass

    def service_get_all(self, context, filters=None, set_zones=False):
        if filters is None:
            filters = {}
        if 'availability_zone' in filters:
            zone_filter = filters.pop('availability_zone')
            set_zones = True
        else:
            zone_filter = None
        services = self.cells_rpcapi.service_get_all(context,
                                                     filters=filters)
        if set_zones:
            services = availability_zones.set_availability_zones(context,
                                                                 services)
            if zone_filter is not None:
                services = [s for s in services
                            if s['availability_zone'] == zone_filter]
        return services

    def service_get_by_compute_host(self, context, host_name):
        return self.cells_rpcapi.service_get_by_compute_host(context,
                                                             host_name)

    def service_update(self, context, host_name, binary, params_to_update):
        """
        Used to enable/disable a service. For compute services, setting to
        disabled stops new builds arriving on that host.

        :param host_name: the name of the host machine that the service is
                          running
        :param binary: The name of the executable that the service runs as
        :param params_to_update: eg. {'disabled': True}
        """
        return self.cells_rpcapi.service_update(
            context, host_name, binary, params_to_update)

    def instance_get_all_by_host(self, context, host_name):
        """Get all instances by host.  Host might have a cell prepended
        to it, so we'll need to strip it out.  We don't need to proxy
        this call to cells, as we have instance information here in
        the API cell.
        """
        cell_name, host_name = cells_utils.split_cell_and_item(host_name)
        instances = super(HostAPI, self).instance_get_all_by_host(context,
                                                                  host_name)
        if cell_name:
            instances = [i for i in instances
                         if i['cell_name'] == cell_name]
        return instances

    def task_log_get_all(self, context, task_name, beginning, ending,
                         host=None, state=None):
        """Return the task logs within a given range from cells,
        optionally filtering by the host and/or state.  For cells, the
        host should be a path like 'path!to!cell@host'.  If no @host
        is given, only task logs from a particular cell will be returned.
        """
        return self.cells_rpcapi.task_log_get_all(context,
                                                  task_name,
                                                  beginning,
                                                  ending,
                                                  host=host,
                                                  state=state)

    def compute_node_get(self, context, compute_id):
        """Get a compute node from a particular cell by its integer ID.
        compute_id should be in the format of 'path!to!cell@ID'.
        """
        return self.cells_rpcapi.compute_node_get(context, compute_id)

    def compute_node_get_all(self, context):
        return self.cells_rpcapi.compute_node_get_all(context)

    def compute_node_search_by_hypervisor(self, context, hypervisor_match):
        return self.cells_rpcapi.compute_node_get_all(context,
                hypervisor_match=hypervisor_match)

    def compute_node_statistics(self, context):
        return self.cells_rpcapi.compute_node_stats(context)


class InstanceActionAPI(compute_api.InstanceActionAPI):
    """InstanceActionAPI() class for cells."""
    def __init__(self):
        super(InstanceActionAPI, self).__init__()
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def actions_get(self, context, instance):
        return self.cells_rpcapi.actions_get(context, instance)

    def action_get_by_request_id(self, context, instance, request_id):
        return self.cells_rpcapi.action_get_by_request_id(context, instance,
                                                          request_id)

    def action_events_get(self, context, instance, action_id):
        return self.cells_rpcapi.action_events_get(context, instance,
                                                   action_id)
