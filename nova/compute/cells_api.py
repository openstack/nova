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

"""Compute API that proxies via Cells Service.

This relates to cells v1. This layer is basically responsible for intercepting
compute/api calls at the top layer and forwarding to the child cell to be
replayed there.
"""

import oslo_messaging as messaging
from oslo_utils import excutils

from nova import availability_zones
from nova.cells import rpcapi as cells_rpcapi
from nova.cells import utils as cells_utils
from nova.compute import api as compute_api
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import vm_states
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as obj_base
from nova import rpc


check_instance_state = compute_api.check_instance_state
reject_instance_state = compute_api.reject_instance_state
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
                        'backup_instance', 'snapshot_instance',
                        'set_admin_password']

    def __init__(self, cells_rpcapi):
        self.cells_rpcapi = cells_rpcapi

    def __getattr__(self, key):
        if key in self.cells_compatible:
            return getattr(self.cells_rpcapi, key)

        def _noop_rpc_wrapper(*args, **kwargs):
            return None
        return _noop_rpc_wrapper


class ConductorTaskRPCAPIRedirect(object):
    # NOTE(comstud): These are a list of methods where the cells_rpcapi
    # and the compute_task_rpcapi methods have the same signatures.  This
    # is for transitioning to a common interface where we can just
    # swap out the compute_task_rpcapi class with the cells_rpcapi class.
    cells_compatible = ['build_instances', 'resize_instance',
                        'live_migrate_instance', 'rebuild_instance']

    def __init__(self, cells_rpcapi_obj):
        self.cells_rpcapi = cells_rpcapi_obj

    def __getattr__(self, key):
        if key in self.cells_compatible:
            return getattr(self.cells_rpcapi, key)

        def _noop_rpc_wrapper(*args, **kwargs):
            return None
        return _noop_rpc_wrapper


class RPCClientCellsProxy(object):

    def __init__(self, target, version_cap):
        super(RPCClientCellsProxy, self).__init__()

        self.target = target
        self.version_cap = version_cap
        self._server = None
        self._version = None

        self.cells_rpcapi = cells_rpcapi.CellsAPI()

    def prepare(self, **kwargs):
        ret = type(self)(self.target, self.version_cap)
        ret.cells_rpcapi = self.cells_rpcapi

        server = kwargs.pop('server', None)
        version = kwargs.pop('version', None)

        if kwargs:
            raise ValueError(_("Unsupported kwargs: %s") % kwargs.keys())

        if server:
            ret._server = server
        if version:
            ret._version = version

        return ret

    def _check_version_cap(self, version):
        client = rpc.get_client(self.target, version_cap=self.version_cap)
        if not client.can_send_version(version):
            raise messaging.RPCVersionCapError(version=version,
                                               version_cap=self.version_cap)

    def _make_msg(self, method, **kwargs):
        version = self._version if self._version else self.target.version
        self._check_version_cap(version)
        return {
            'method': method,
            'namespace': None,
            'version': version,
            'args': kwargs
        }

    def _get_topic(self):
        if self._server is not None:
            return '%s.%s' % (self.target.topic, self._server)
        else:
            return self.target.topic

    def can_send_version(self, version):
        client = rpc.get_client(self.target, version_cap=self.version_cap)
        return client.can_send_version(version)

    def cast(self, ctxt, method, **kwargs):
        msg = self._make_msg(method, **kwargs)
        topic = self._get_topic()
        self.cells_rpcapi.proxy_rpc_to_manager(ctxt, msg, topic)

    def call(self, ctxt, method, **kwargs):
        msg = self._make_msg(method, **kwargs)
        topic = self._get_topic()
        return self.cells_rpcapi.proxy_rpc_to_manager(ctxt, msg,
                                                      topic, call=True)


class ComputeRPCProxyAPI(compute_rpcapi.ComputeAPI):
    """Class used to substitute Compute RPC API that will proxy
    via the cells manager to a compute manager in a child cell.
    """
    def get_client(self, target, version_cap, serializer):
        return RPCClientCellsProxy(target, version_cap)


class ComputeCellsAPI(compute_api.API):
    def __init__(self, *args, **kwargs):
        super(ComputeCellsAPI, self).__init__(*args, **kwargs)
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        # Avoid casts/calls directly to compute
        self.compute_rpcapi = ComputeRPCAPIRedirect(self.cells_rpcapi)
        # Redirect conductor build_instances to cells
        self.compute_task_api = ConductorTaskRPCAPIRedirect(self.cells_rpcapi)
        self._cell_type = 'api'

    def _cast_to_cells(self, context, instance, method, *args, **kwargs):
        instance_uuid = instance.uuid
        cell_name = instance.cell_name
        if not cell_name:
            raise exception.InstanceUnknownCell(instance_uuid=instance_uuid)
        self.cells_rpcapi.cast_compute_api_method(context, cell_name,
                method, instance_uuid, *args, **kwargs)

    def _call_to_cells(self, context, instance, method, *args, **kwargs):
        instance_uuid = instance.uuid
        cell_name = instance.cell_name
        if not cell_name:
            raise exception.InstanceUnknownCell(instance_uuid=instance_uuid)
        return self.cells_rpcapi.call_compute_api_method(context, cell_name,
                method, instance_uuid, *args, **kwargs)

    def _check_requested_networks(self, context, requested_networks,
                                  max_count):
        """Override compute API's checking of this.  It'll happen in
        child cell
        """
        return max_count

    def create(self, *args, **kwargs):
        """We can use the base functionality, but I left this here just
        for completeness.
        """
        return super(ComputeCellsAPI, self).create(*args, **kwargs)

    def _create_block_device_mapping(self, *args, **kwargs):
        """Don't create block device mappings in the API cell.

        The child cell will create it and propagate it up to the parent cell.
        """
        pass

    def force_delete(self, context, instance):
        self._handle_cell_delete(context, instance, 'force_delete')

    def soft_delete(self, context, instance):
        self._handle_cell_delete(context, instance, 'soft_delete')

    def delete(self, context, instance):
        self._handle_cell_delete(context, instance, 'delete')

    def _handle_cell_delete(self, context, instance, method_name):
        if not instance.cell_name:
            delete_type = method_name == 'soft_delete' and 'soft' or 'hard'
            self.cells_rpcapi.instance_delete_everywhere(context,
                    instance, delete_type)
            # NOTE(danms): If we try to delete an instance with no cell,
            # there isn't anything to salvage, so we can hard-delete here.
            try:
                if self._delete_while_booting(context, instance):
                    return
            except exception.ObjectActionError:
                # NOTE(alaski): We very likely got here because the host
                # constraint in instance.destroy() failed.  This likely means
                # that an update came up from a child cell and cell_name is
                # set now.  We handle this similarly to how the
                # ObjectActionError is handled below.
                with excutils.save_and_reraise_exception() as exc:
                    _cell, instance = self._lookup_instance(context,
                                                            instance.uuid)
                    if instance is None:
                        exc.reraise = False
                    elif instance.cell_name:
                        exc.reraise = False
                        self._handle_cell_delete(context, instance,
                                                 method_name)
                return
            # If instance.cell_name was not set it's possible that the Instance
            # object here was pulled from a BuildRequest object and is not
            # fully populated. Notably it will be missing an 'id' field which
            # will prevent instance.destroy from functioning properly. A
            # lookup is attempted which will either return a full Instance or
            # None if not found. If not found then it's acceptable to skip the
            # rest of the delete processing.
            _cell, instance = self._lookup_instance(context, instance.uuid)
            if instance is None:
                # Instance has been deleted out from under us
                return

            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)
            try:
                super(ComputeCellsAPI, self)._local_delete(context, instance,
                                                           bdms, method_name,
                                                           self._do_delete)
            except exception.ObjectActionError:
                # NOTE(alaski): We very likely got here because the host
                # constraint in instance.destroy() failed.  This likely means
                # that an update came up from a child cell and cell_name is
                # set now.  If so try the delete again.
                with excutils.save_and_reraise_exception() as exc:
                    try:
                        instance.refresh()
                    except exception.InstanceNotFound:
                        # NOTE(melwitt): If the instance has already been
                        # deleted by instance_destroy_at_top from a cell,
                        # instance.refresh() will raise InstanceNotFound.
                        exc.reraise = False
                    else:
                        if instance.cell_name:
                            exc.reraise = False
                            self._handle_cell_delete(context, instance,
                                    method_name)
            except exception.InstanceNotFound:
                # NOTE(melwitt): We can get here if anything tries to
                # lookup the instance after an instance_destroy_at_top hits.
                pass
            return

        method = getattr(super(ComputeCellsAPI, self), method_name)
        method(context, instance)

    @check_instance_cell
    def restore(self, context, instance):
        """Restore a previously deleted (but not reclaimed) instance."""
        super(ComputeCellsAPI, self).restore(context, instance)
        self._cast_to_cells(context, instance, 'restore')

    @check_instance_cell
    def evacuate(self, context, instance, host, *args, **kwargs):
        """Evacuate the given instance with the provided attributes."""
        if host:
            cell_path, host = cells_utils.split_cell_and_item(host)
        self._cast_to_cells(context, instance, 'evacuate',
                host, *args, **kwargs)

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

    def get_instance_diagnostics(self, context, instance):
        """Retrieve diagnostics for the given instance."""
        # FIXME(comstud): Cache this?
        # Also: only calling super() to get state/policy checking
        super(ComputeCellsAPI, self).get_instance_diagnostics(context,
                                                              instance)
        return self._call_to_cells(context, instance,
                                   'get_instance_diagnostics')

    @check_instance_cell
    def rescue(self, context, instance, rescue_password=None,
               rescue_image_ref=None, clean_shutdown=True):
        """Rescue the given instance."""
        super(ComputeCellsAPI, self).rescue(context, instance,
                rescue_password=rescue_password,
                rescue_image_ref=rescue_image_ref,
                clean_shutdown=clean_shutdown)
        self._cast_to_cells(context, instance, 'rescue',
                rescue_password=rescue_password,
                rescue_image_ref=rescue_image_ref,
                clean_shutdown=clean_shutdown)

    @check_instance_cell
    def unrescue(self, context, instance):
        """Unrescue the given instance."""
        super(ComputeCellsAPI, self).unrescue(context, instance)
        self._cast_to_cells(context, instance, 'unrescue')

    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.ACTIVE, vm_states.STOPPED,
                                    vm_states.PAUSED, vm_states.SUSPENDED])
    def shelve(self, context, instance, clean_shutdown=True):
        """Shelve the given instance."""
        self._cast_to_cells(context, instance, 'shelve',
                clean_shutdown=clean_shutdown)

    @check_instance_cell
    def shelve_offload(self, context, instance, clean_shutdown=True):
        """Offload the shelved instance."""
        super(ComputeCellsAPI, self).shelve_offload(context, instance,
                clean_shutdown=clean_shutdown)
        self._cast_to_cells(context, instance, 'shelve_offload',
                clean_shutdown=clean_shutdown)

    @check_instance_cell
    @check_instance_state(vm_state=[vm_states.SHELVED,
                                    vm_states.SHELVED_OFFLOADED])
    def unshelve(self, context, instance):
        """Unshelve the given instance."""
        self._cast_to_cells(context, instance, 'unshelve')

    @check_instance_cell
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_vnc_console(self, context, instance, console_type):
        """Get a url to a VNC Console."""
        if not instance.host:
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        connect_info = self._call_to_cells(context, instance,
                'get_vnc_connect_info', console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type, connect_info['host'],
                connect_info['port'], connect_info['internal_access_path'],
                instance.uuid, access_url=connect_info['access_url'])
        return {'url': connect_info['access_url']}

    @check_instance_cell
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_spice_console(self, context, instance, console_type):
        """Get a url to a SPICE Console."""
        if not instance.host:
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        connect_info = self._call_to_cells(context, instance,
                'get_spice_connect_info', console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type, connect_info['host'],
                connect_info['port'], connect_info['internal_access_path'],
                instance.uuid, access_url=connect_info['access_url'])
        return {'url': connect_info['access_url']}

    @check_instance_cell
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_rdp_console(self, context, instance, console_type):
        """Get a url to a RDP Console."""
        if not instance.host:
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        connect_info = self._call_to_cells(context, instance,
                'get_rdp_connect_info', console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type, connect_info['host'],
                connect_info['port'], connect_info['internal_access_path'],
                instance.uuid, access_url=connect_info['access_url'])
        return {'url': connect_info['access_url']}

    @check_instance_cell
    @reject_instance_state(
        task_state=[task_states.DELETING, task_states.MIGRATING])
    def get_serial_console(self, context, instance, console_type):
        """Get a url to a serial console."""
        if not instance.host:
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        connect_info = self._call_to_cells(context, instance,
                'get_serial_console_connect_info', console_type)

        self.consoleauth_rpcapi.authorize_console(context,
                connect_info['token'], console_type, connect_info['host'],
                connect_info['port'], connect_info['internal_access_path'],
                instance.uuid, access_url=connect_info['access_url'])
        return {'url': connect_info['access_url']}

    @check_instance_cell
    def get_console_output(self, context, instance, *args, **kwargs):
        """Get console output for an instance."""
        # NOTE(comstud): Calling super() just to get policy check
        super(ComputeCellsAPI, self).get_console_output(context, instance,
                *args, **kwargs)
        return self._call_to_cells(context, instance, 'get_console_output',
                *args, **kwargs)

    @check_instance_cell
    def _attach_volume(self, context, instance, volume, device,
                       disk_bus, device_type, tag=None,
                       supports_multiattach=False):
        """Attach an existing volume to an existing instance."""
        if tag:
            raise exception.VolumeTaggedAttachNotSupported()
        if volume['multiattach']:
            # We don't support multiattach volumes with cells v1.
            raise exception.MultiattachSupportNotYetAvailable()
        self.volume_api.check_availability_zone(context, volume,
                                                instance=instance)

        return self._call_to_cells(context, instance, 'attach_volume',
                volume['id'], device, disk_bus, device_type)

    @check_instance_cell
    def _detach_volume(self, context, instance, volume):
        """Detach a volume from an instance."""
        self._cast_to_cells(context, instance, 'detach_volume',
                volume)

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

    def set_host_enabled(self, context, host_name, enabled):
        try:
            result = super(HostAPI, self).set_host_enabled(context, host_name,
                    enabled)
        except exception.CellRoutingInconsistency:
            raise exception.HostNotFound(host=host_name)

        return result

    def host_power_action(self, context, host_name, action):
        try:
            result = super(HostAPI, self).host_power_action(context, host_name,
                    action)
        except exception.CellRoutingInconsistency:
            raise exception.HostNotFound(host=host_name)

        return result

    def get_host_uptime(self, context, host_name):
        """Returns the result of calling "uptime" on the target host."""
        return self.cells_rpcapi.get_host_uptime(context, host_name)

    def service_get_all(self, context, filters=None, set_zones=False,
                        all_cells=False):
        """Get all services.

        Note that this is the cellsv1 variant, which means we ignore the
        "all_cells" parameter.
        """
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
            # TODO(sbauza): set_availability_zones returns flat dicts,
            # we should rather modify the RPC API to amend service_get_all by
            # adding a set_zones argument
            services = availability_zones.set_availability_zones(context,
                                                                 services)
            if zone_filter is not None:
                services = [s for s in services
                            if s['availability_zone'] == zone_filter]

            # NOTE(sbauza): As services is a list of flat dicts, we need to
            # rehydrate the corresponding ServiceProxy objects
            cell_paths = []
            for service in services:
                cell_path, id = cells_utils.split_cell_and_item(service['id'])
                cell_path, host = cells_utils.split_cell_and_item(
                    service['host'])
                service['id'] = id
                service['host'] = host
                cell_paths.append(cell_path)
            services = obj_base.obj_make_list(context,
                                              objects.ServiceList(),
                                              objects.Service,
                                              services)
            services = [cells_utils.ServiceProxy(s, c)
                        for s, c in zip(services, cell_paths)]

        return services

    def service_get_by_compute_host(self, context, host_name):
        try:
            return self.cells_rpcapi.service_get_by_compute_host(context,
                    host_name)
        except exception.CellRoutingInconsistency:
            raise exception.ComputeHostNotFound(host=host_name)

    def service_update(self, context, host_name, binary, params_to_update):
        """Used to enable/disable a service. For compute services, setting to
        disabled stops new builds arriving on that host.

        :param host_name: the name of the host machine that the service is
                          running
        :param binary: The name of the executable that the service runs as
        :param params_to_update: eg. {'disabled': True}
        """
        return self.cells_rpcapi.service_update(
            context, host_name, binary, params_to_update)

    def service_delete(self, context, service_id):
        """Deletes the specified service."""
        self.cells_rpcapi.service_delete(context, service_id)

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
        """Get a compute node from a particular cell by its integer ID or UUID.
        compute_id should be in the format of 'path!to!cell@ID'.
        """
        try:
            return self.cells_rpcapi.compute_node_get(context, compute_id)
        except exception.CellRoutingInconsistency:
            raise exception.ComputeHostNotFound(host=compute_id)

    def compute_node_get_all(self, context, limit=None, marker=None):
        # NOTE(lyj): No pagination for cells, just make sure the arguments
        #            for the method are the same with the compute.api for now.
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

    def actions_get(self, context, instance, limit=None, marker=None,
                    filters=None):
        # Paging and filtering isn't supported in cells v1.
        return self.cells_rpcapi.actions_get(context, instance)

    def action_get_by_request_id(self, context, instance, request_id):
        return self.cells_rpcapi.action_get_by_request_id(context, instance,
                                                          request_id)

    def action_events_get(self, context, instance, action_id):
        return self.cells_rpcapi.action_events_get(context, instance,
                                                   action_id)
