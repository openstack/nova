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

"""
Client side of nova-cells RPC API (for talking to the nova-cells service
within a cell).

This is different than communication between child and parent nova-cells
services.  That communication is handled by the cells driver via the
messging module.
"""

from oslo.config import cfg

from nova import exception
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import proxy as rpc_proxy


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.import_opt('enable', 'nova.cells.opts', group='cells')
CONF.import_opt('topic', 'nova.cells.opts', group='cells')

rpcapi_cap_opt = cfg.StrOpt('cells',
        default=None,
        help='Set a version cap for messages sent to local cells services')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')


class CellsAPI(rpc_proxy.RpcProxy):
    '''Cells client-side RPC API

    API version history:

        1.0 - Initial version.
        1.1 - Adds get_cell_info_for_neighbors() and sync_instances()
        1.2 - Adds service_get_all(), service_get_by_compute_host(),
              and proxy_rpc_to_compute_manager()
        1.3 - Adds task_log_get_all()
        1.4 - Adds compute_node_get(), compute_node_get_all(), and
              compute_node_stats()
        1.5 - Adds actions_get(), action_get_by_request_id(), and
              action_events_get()
        1.6 - Adds consoleauth_delete_tokens() and validate_console_port()

        ... Grizzly supports message version 1.6.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 1.6.

        1.7 - Adds service_update()
        1.8 - Adds build_instances(), deprecates schedule_run_instance()
        1.9 - Adds get_capacities()
        1.10 - Adds bdm_update_or_create_at_top(), and bdm_destroy_at_top()
    '''
    BASE_RPC_API_VERSION = '1.0'

    VERSION_ALIASES = {
        'grizzly': '1.6'
    }

    def __init__(self):
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.cells,
                                               CONF.upgrade_levels.cells)
        super(CellsAPI, self).__init__(topic=CONF.cells.topic,
                default_version=self.BASE_RPC_API_VERSION,
                version_cap=version_cap)

    def cast_compute_api_method(self, ctxt, cell_name, method,
            *args, **kwargs):
        """Make a cast to a compute API method in a certain cell."""
        method_info = {'method': method,
                       'method_args': args,
                       'method_kwargs': kwargs}
        self.cast(ctxt, self.make_msg('run_compute_api_method',
                                      cell_name=cell_name,
                                      method_info=method_info,
                                      call=False))

    def call_compute_api_method(self, ctxt, cell_name, method,
            *args, **kwargs):
        """Make a call to a compute API method in a certain cell."""
        method_info = {'method': method,
                       'method_args': args,
                       'method_kwargs': kwargs}
        return self.call(ctxt, self.make_msg('run_compute_api_method',
                                             cell_name=cell_name,
                                             method_info=method_info,
                                             call=True))

    # NOTE(alaski): Deprecated and should be removed later.
    def schedule_run_instance(self, ctxt, **kwargs):
        """Schedule a new instance for creation."""
        self.cast(ctxt, self.make_msg('schedule_run_instance',
                                      host_sched_kwargs=kwargs))

    def build_instances(self, ctxt, **kwargs):
        """Build instances."""
        build_inst_kwargs = kwargs
        instances = build_inst_kwargs['instances']
        instances_p = [jsonutils.to_primitive(inst) for inst in instances]
        build_inst_kwargs['instances'] = instances_p
        build_inst_kwargs['image'] = jsonutils.to_primitive(
                build_inst_kwargs['image'])
        self.cast(ctxt, self.make_msg('build_instances',
            build_inst_kwargs=build_inst_kwargs),
                version='1.8')

    def instance_update_at_top(self, ctxt, instance):
        """Update instance at API level."""
        if not CONF.cells.enable:
            return
        # Make sure we have a dict, not a SQLAlchemy model
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('instance_update_at_top',
                                      instance=instance_p))

    def instance_destroy_at_top(self, ctxt, instance):
        """Destroy instance at API level."""
        if not CONF.cells.enable:
            return
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('instance_destroy_at_top',
                                      instance=instance_p))

    def instance_delete_everywhere(self, ctxt, instance, delete_type):
        """Delete instance everywhere.  delete_type may be 'soft'
        or 'hard'.  This is generally only used to resolve races
        when API cell doesn't know to what cell an instance belongs.
        """
        if not CONF.cells.enable:
            return
        instance_p = jsonutils.to_primitive(instance)
        self.cast(ctxt, self.make_msg('instance_delete_everywhere',
                                      instance=instance_p,
                                      delete_type=delete_type))

    def instance_fault_create_at_top(self, ctxt, instance_fault):
        """Create an instance fault at the top."""
        if not CONF.cells.enable:
            return
        instance_fault_p = jsonutils.to_primitive(instance_fault)
        self.cast(ctxt, self.make_msg('instance_fault_create_at_top',
                                      instance_fault=instance_fault_p))

    def bw_usage_update_at_top(self, ctxt, uuid, mac, start_period,
            bw_in, bw_out, last_ctr_in, last_ctr_out, last_refreshed=None):
        """Broadcast upwards that bw_usage was updated."""
        if not CONF.cells.enable:
            return
        bw_update_info = {'uuid': uuid,
                          'mac': mac,
                          'start_period': start_period,
                          'bw_in': bw_in,
                          'bw_out': bw_out,
                          'last_ctr_in': last_ctr_in,
                          'last_ctr_out': last_ctr_out,
                          'last_refreshed': last_refreshed}
        self.cast(ctxt, self.make_msg('bw_usage_update_at_top',
                                      bw_update_info=bw_update_info))

    def instance_info_cache_update_at_top(self, ctxt, instance_info_cache):
        """Broadcast up that an instance's info_cache has changed."""
        if not CONF.cells.enable:
            return
        iicache = jsonutils.to_primitive(instance_info_cache)
        instance = {'uuid': iicache['instance_uuid'],
                    'info_cache': iicache}
        self.cast(ctxt, self.make_msg('instance_update_at_top',
                                      instance=instance))

    def get_cell_info_for_neighbors(self, ctxt):
        """Get information about our neighbor cells from the manager."""
        if not CONF.cells.enable:
            return []
        return self.call(ctxt, self.make_msg('get_cell_info_for_neighbors'),
                         version='1.1')

    def sync_instances(self, ctxt, project_id=None, updated_since=None,
            deleted=False):
        """Ask all cells to sync instance data."""
        if not CONF.cells.enable:
            return
        return self.cast(ctxt, self.make_msg('sync_instances',
                                             project_id=project_id,
                                             updated_since=updated_since,
                                             deleted=deleted),
                         version='1.1')

    def service_get_all(self, ctxt, filters=None):
        """Ask all cells for their list of services."""
        return self.call(ctxt,
                         self.make_msg('service_get_all',
                                       filters=filters),
                         version='1.2')

    def service_get_by_compute_host(self, ctxt, host_name):
        """Get the service entry for a host in a particular cell.  The
        cell name should be encoded within the host_name.
        """
        return self.call(ctxt, self.make_msg('service_get_by_compute_host',
                                             host_name=host_name),
                         version='1.2')

    def service_update(self, ctxt, host_name, binary, params_to_update):
        """
        Used to enable/disable a service. For compute services, setting to
        disabled stops new builds arriving on that host.

        :param host_name: the name of the host machine that the service is
                          running
        :param binary: The name of the executable that the service runs as
        :param params_to_update: eg. {'disabled': True}
        """
        return self.call(ctxt, self.make_msg(
            'service_update', host_name=host_name,
             binary=binary, params_to_update=params_to_update),
             version='1.7')

    def proxy_rpc_to_manager(self, ctxt, rpc_message, topic, call=False,
                             timeout=None):
        """Proxy RPC to a compute manager.  The host in the topic
        should be encoded with the target cell name.
        """
        return self.call(ctxt, self.make_msg('proxy_rpc_to_manager',
                                             topic=topic,
                                             rpc_message=rpc_message,
                                             call=call,
                                             timeout=timeout),
                         timeout=timeout,
                         version='1.2')

    def task_log_get_all(self, ctxt, task_name, period_beginning,
                         period_ending, host=None, state=None):
        """Get the task logs from the DB in child cells."""
        return self.call(ctxt, self.make_msg('task_log_get_all',
                                   task_name=task_name,
                                   period_beginning=period_beginning,
                                   period_ending=period_ending,
                                   host=host, state=state),
                         version='1.3')

    def compute_node_get(self, ctxt, compute_id):
        """Get a compute node by ID in a specific cell."""
        return self.call(ctxt, self.make_msg('compute_node_get',
                                             compute_id=compute_id),
                         version='1.4')

    def compute_node_get_all(self, ctxt, hypervisor_match=None):
        """Return list of compute nodes in all cells, optionally
        filtering by hypervisor host.
        """
        return self.call(ctxt,
                         self.make_msg('compute_node_get_all',
                                       hypervisor_match=hypervisor_match),
                         version='1.4')

    def compute_node_stats(self, ctxt):
        """Return compute node stats from all cells."""
        return self.call(ctxt, self.make_msg('compute_node_stats'),
                         version='1.4')

    def actions_get(self, ctxt, instance):
        if not instance['cell_name']:
            raise exception.InstanceUnknownCell(instance_uuid=instance['uuid'])
        return self.call(ctxt, self.make_msg('actions_get',
                                             cell_name=instance['cell_name'],
                                             instance_uuid=instance['uuid']),
                         version='1.5')

    def action_get_by_request_id(self, ctxt, instance, request_id):
        if not instance['cell_name']:
            raise exception.InstanceUnknownCell(instance_uuid=instance['uuid'])
        return self.call(ctxt, self.make_msg('action_get_by_request_id',
                                             cell_name=instance['cell_name'],
                                             instance_uuid=instance['uuid'],
                                             request_id=request_id),
                         version='1.5')

    def action_events_get(self, ctxt, instance, action_id):
        if not instance['cell_name']:
            raise exception.InstanceUnknownCell(instance_uuid=instance['uuid'])
        return self.call(ctxt, self.make_msg('action_events_get',
                                             cell_name=instance['cell_name'],
                                             action_id=action_id),
                         version='1.5')

    def consoleauth_delete_tokens(self, ctxt, instance_uuid):
        """Delete consoleauth tokens for an instance in API cells."""
        self.cast(ctxt, self.make_msg('consoleauth_delete_tokens',
                                      instance_uuid=instance_uuid),
                  version='1.6')

    def validate_console_port(self, ctxt, instance_uuid, console_port,
                              console_type):
        """Validate console port with child cell compute node."""
        return self.call(ctxt,
                self.make_msg('validate_console_port',
                              instance_uuid=instance_uuid,
                              console_port=console_port,
                              console_type=console_type),
                version='1.6')

    def get_capacities(self, ctxt, cell_name=None):
        return self.call(ctxt,
                         self.make_msg('get_capacities', cell_name=cell_name),
                         version='1.9')

    def bdm_update_or_create_at_top(self, ctxt, bdm, create=None):
        """Create or update a block device mapping in API cells.  If
        create is True, only try to create.  If create is None, try to
        update but fall back to create.  If create is False, only attempt
        to update.  This maps to nova-conductor's behavior.
        """
        if not CONF.cells.enable:
            return
        try:
            self.cast(ctxt, self.make_msg('bdm_update_or_create_at_top',
                                          bdm=bdm, create=create),
                      version='1.10')
        except Exception:
            LOG.exception(_("Failed to notify cells of BDM update/create."))

    def bdm_destroy_at_top(self, ctxt, instance_uuid, device_name=None,
                           volume_id=None):
        """Broadcast upwards that a block device mapping was destroyed.
        One of device_name or volume_id should be specified.
        """
        if not CONF.cells.enable:
            return
        try:
            self.cast(ctxt, self.make_msg('bdm_destroy_at_top',
                                          instance_uuid=instance_uuid,
                                          device_name=device_name,
                                          volume_id=volume_id),
                      version='1.10')
        except Exception:
            LOG.exception(_("Failed to notify cells of BDM destroy."))
