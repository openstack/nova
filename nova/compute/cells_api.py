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
from nova.compute import rpcapi as compute_rpcapi
from nova import exception
from nova.objects import base as obj_base
from nova.objects import service as service_obj
from nova.openstack.common import excutils
from nova import rpcclient


check_instance_state = compute_api.check_instance_state
wrap_check_policy = compute_api.wrap_check_policy
check_policy = compute_api.check_policy
check_instance_lock = compute_api.check_instance_lock
check_instance_cell = compute_api.check_instance_cell


class ComputeRPCAPIRedirect(object):
    # NOTE(comstud): These are a list of methods where the cells_rpcapi
    # and the compute_rpcapi methods have the same signatures.  This
    # is for transitioning to a common interface where we can just
    # swap out the compute_rpcapi class with the cells_rpcapi class.
    cells_compatible = ['start_instance', 'stop_instance',
                        'reboot_instance', 'suspend_instance',
                        'resume_instance', 'terminate_instance',
                        'soft_delete_instance', 'pause_instance',
                        'unpause_instance', 'revert_resize',
                        'confirm_resize', 'reset_network',
                        'inject_network_info',
                        'backup_instance', 'snapshot_instance']

    def __init__(self, cells_rpcapi):
        self.cells_rpcapi = cells_rpcapi

    def __getattr__(self, key):
        if key in self.cells_compatible:
            return getattr(self.cells_rpcapi, key)

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
    # NOTE(comstud): These are a list of methods where the cells_rpcapi
    # and the compute_task_rpcapi methods have the same signatures.  This
    # is for transitioning to a common interface where we can just
    # swap out the compute_task_rpcapi class with the cells_rpcapi class.
    cells_compatible = ['build_instances', 'resize_instance',
                        'live_migrate_instance']

    def __init__(self, cells_rpcapi_obj):
        self.cells_rpcapi = cells_rpcapi_obj

    def __getattr__(self, key):
        if key in self.cells_compatible:
            return getattr(self.cells_rpcapi, key)

        def _noop_rpc_wrapper(*args, **kwargs):
            return None
        return _noop_rpc_wrapper


class RPCClientCellsProxy(rpcclient.RPCClient):

    def __init__(self, proxy, *args, **kwargs):
        super(RPCClientCellsProxy, self).__init__(proxy, *args, **kwargs)
        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def cast(self, ctxt, method, **kwargs):
        msg = self.proxy.make_msg(method, **kwargs)
        self.proxy._set_version(msg, self.kwargs.get('version'))
        topic = self.proxy._get_topic(self.kwargs.get('topic'))
        self.cells_rpcapi.proxy_rpc_to_manager(ctxt, msg, topic)

    def call(self, ctxt, method, **kwargs):
        msg = self.proxy.make_msg(method, **kwargs)
        self.proxy._set_version(msg, self.kwargs.get('version'))
        topic = self.proxy._get_topic(self.kwargs.get('topic'))
        timeout = self.kwargs.get('timeout')
        return self.cells_rpcapi.proxy_rpc_to_manager(ctxt, msg, topic,
                                                      call=True,
                                                      timeout=timeout)


class ComputeRPCProxyAPI(compute_rpcapi.ComputeAPI):
    """Class used to substitute Compute RPC API that will proxy
    via the cells manager to a compute manager in a child cell.
    """
    def get_client(self):
        return RPCClientCellsProxy(self)


class ComputeCellsAPI(compute_api.API):
    def __init__(self, *args, **kwargs):
        super(ComputeCellsAPI, self).__init__(*args, **kwargs)
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        # Avoid casts/calls directly to compute
        self.compute_rpcapi = ComputeRPCAPIRedirect(self.cells_rpcapi)
        # Redirect scheduler run_instance to cells.
        self.scheduler_rpcapi = SchedulerRPCAPIRedirect(self.cells_rpcapi)
        # Redirect conductor build_instances to cells
        self._compute_task_api = ConductorTaskRPCAPIRedirect(self.cells_rpcapi)
        self._cell_type = 'api'

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

    def create(self, *args, **kwargs):
        """We can use the base functionality, but I left this here just
        for completeness.
        """
        return super(ComputeCellsAPI, self).create(*args, **kwargs)

    def update(self, context, instance, **kwargs):
        """Update an instance."""
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
        # We need to skip vm_state/task_state updates as the child
        # cell is authoritative for these.  The admin API does
        # support resetting state, but it has been converted to use
        # Instance.save() with an appropriate kwarg.
        kwargs_copy.pop('vm_state', None)
        kwargs_copy.pop('task_state', None)
        if kwargs_copy:
            try:
                self._cast_to_cells(context, instance, 'update',
                        **kwargs_copy)
            except exception.InstanceUnknownCell:
                pass
        return rv

    def soft_delete(self, context, instance):
        self._handle_cell_delete(context, instance, 'soft_delete')

    def delete(self, context, instance):
        self._handle_cell_delete(context, instance, 'delete')

    def _handle_cell_delete(self, context, instance, method_name):
        if not instance['cell_name']:
            delete_type = method_name == 'soft_delete' and 'soft' or 'hard'
            self.cells_rpcapi.instance_delete_everywhere(context,
                    instance, delete_type)
            bdms = block_device.legacy_mapping(
                self.db.block_device_mapping_get_all_by_instance(
                    context, instance['uuid']))
            # NOTE(danms): If we try to delete an instance with no cell,
            # there isn't anything to salvage, so we can hard-delete here.
            super(ComputeCellsAPI, self)._local_delete(context, instance, bdms,
                                                       method_name,
                                                       self._do_delete)
            return

        method = getattr(super(ComputeCellsAPI, self), method_name)
        method(context, instance)

    @check_instance_cell
    def restore(self, context, instance):
        """Restore a previously deleted (but not reclaimed) instance."""
        super(ComputeCellsAPI, self).restore(context, instance)
        self._cast_to_cells(context, instance, 'restore')

    @check_instance_cell
    def force_delete(self, context, instance):
        """Force delete a previously deleted (but not reclaimed) instance."""
        super(ComputeCellsAPI, self).force_delete(context, instance)
        self._cast_to_cells(context, instance, 'force_delete')

    @check_instance_cell
    def rebuild(self, context, instance, *args, **kwargs):
        """Rebuild the given instance with the provided attributes."""
        super(ComputeCellsAPI, self).rebuild(context, instance, *args,
                **kwargs)
        self._cast_to_cells(context, instance, 'rebuild', *args, **kwargs)

    @check_instance_cell
    def evacuate(self, context, instance, *args, **kwargs):
        """Evacuate the given instance with the provided attributes."""
        super(ComputeCellsAPI, self).evacuate(context, instance, *args,
                **kwargs)
        self._cast_to_cells(context, instance, 'evacuate', *args, **kwargs)

    @check_instance_cell
    def add_fixed_ip(self, context, instance, *args, **kwargs):
        """Add fixed_ip from specified network to given instance."""
        super(ComputeCellsAPI, self).add_fixed_ip(context, instance,
                *args, **kwargs)
        self._cast_to_cells(context, instance, 'add_fixed_ip',
                *args, **kwargs)

    @check_instance_cell
    def remove_fixed_ip(self, context, instance, *args, **kwargs):
        """Remove fixed_ip from specified network to given instance."""
        super(ComputeCellsAPI, self).remove_fixed_ip(context, instance,
                *args, **kwargs)
        self._cast_to_cells(context, instance, 'remove_fixed_ip',
                *args, **kwargs)

    def get_diagnostics(self, context, instance):
        """Retrieve diagnostics for the given instance."""
        # FIXME(comstud): Cache this?
        # Also: only calling super() to get state/policy checking
        super(ComputeCellsAPI, self).get_diagnostics(context, instance)
        return self._call_to_cells(context, instance, 'get_diagnostics')

    @check_instance_cell
    def rescue(self, context, instance, rescue_password=None):
        """Rescue the given instance."""
        super(ComputeCellsAPI, self).rescue(context, instance,
                rescue_password=rescue_password)
        self._cast_to_cells(context, instance, 'rescue',
                rescue_password=rescue_password)

    @check_instance_cell
    def unrescue(self, context, instance):
        """Unrescue the given instance."""
        super(ComputeCellsAPI, self).unrescue(context, instance)
        self._cast_to_cells(context, instance, 'unrescue')

    @wrap_check_policy
    @check_instance_cell
    def shelve(self, context, instance):
        """Shelve the given instance."""
        self._cast_to_cells(context, instance, 'shelve')

    @wrap_check_policy
    @check_instance_cell
    def shelve_offload(self, context, instance):
        """Offload the shelved instance."""
        super(ComputeCellsAPI, self).shelve_offload(context, instance)
        self._cast_to_cells(context, instance, 'shelve_offload')

    @wrap_check_policy
    @check_instance_cell
    def unshelve(self, context, instance):
        """Unshelve the given instance."""
        super(ComputeCellsAPI, self).unshelve(context, instance)
        self._cast_to_cells(context, instance, 'unshelve')

    @check_instance_cell
    def set_admin_password(self, context, instance, password=None):
        """Set the root/admin password for the given instance."""
        super(ComputeCellsAPI, self).set_admin_password(context, instance,
                password=password)
        self._cast_to_cells(context, instance, 'set_admin_password',
                password=password)

    @check_instance_cell
    def inject_file(self, context, instance, *args, **kwargs):
        """Write a file to the given instance."""
        super(ComputeCellsAPI, self).inject_file(context, instance, *args,
                **kwargs)
        self._cast_to_cells(context, instance, 'inject_file', *args, **kwargs)

    @wrap_check_policy
    @check_instance_cell
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
    @check_instance_cell
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

    @check_instance_cell
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

    @wrap_check_policy
    @check_instance_cell
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

    @check_instance_cell
    def _detach_volume(self, context, instance, volume):
        """Detach a volume from an instance."""
        self.volume_api.check_detach(context, volume)
        self._cast_to_cells(context, instance, 'detach_volume',
                volume)

    @wrap_check_policy
    @check_instance_cell
    def associate_floating_ip(self, context, instance, address):
        """Makes calls to network_api to associate_floating_ip.

        :param address: is a string floating ip address
        """
        self._cast_to_cells(context, instance, 'associate_floating_ip',
                address)

    @check_instance_cell
    def delete_instance_metadata(self, context, instance, key):
        """Delete the given metadata item from an instance."""
        super(ComputeCellsAPI, self).delete_instance_metadata(context,
                instance, key)
        self._cast_to_cells(context, instance, 'delete_instance_metadata',
                key)

    @wrap_check_policy
    @check_instance_cell
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

    def get_migrations(self, context, filters):
        return self.cells_rpcapi.get_migrations(context, filters)


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

    def _assert_host_exists(self, context, host_name, must_be_up=False):
        """Cannot check this in API cell.  This will be checked in the
        target child cell.
        """
        pass

    def get_host_uptime(self, context, host_name):
        """Returns the result of calling "uptime" on the target host."""
        return self.cells_rpcapi.get_host_uptime(context, host_name)

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
        # NOTE(danms): Currently cells does not support objects as
        # return values, so just convert the db-formatted service objects
        # to new-world objects here
        return obj_base.obj_make_list(context,
                                      service_obj.ServiceList(),
                                      service_obj.Service,
                                      services)

    def service_get_by_compute_host(self, context, host_name):
        db_service = self.cells_rpcapi.service_get_by_compute_host(context,
                                                                   host_name)
        # NOTE(danms): Currently cells does not support objects as
        # return values, so just convert the db-formatted service objects
        # to new-world objects here
        if db_service:
            return service_obj.Service._from_db_object(context,
                                                       service_obj.Service(),
                                                       db_service)

    def service_update(self, context, host_name, binary, params_to_update):
        """
        Used to enable/disable a service. For compute services, setting to
        disabled stops new builds arriving on that host.

        :param host_name: the name of the host machine that the service is
                          running
        :param binary: The name of the executable that the service runs as
        :param params_to_update: eg. {'disabled': True}
        """
        db_service = self.cells_rpcapi.service_update(
            context, host_name, binary, params_to_update)
        # NOTE(danms): Currently cells does not support objects as
        # return values, so just convert the db-formatted service objects
        # to new-world objects here
        if db_service:
            return service_obj.Service._from_db_object(context,
                                                       service_obj.Service(),
                                                       db_service)

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
