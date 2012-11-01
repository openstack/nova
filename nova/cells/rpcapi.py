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

from nova.openstack.common import cfg
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import proxy as rpc_proxy

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('enable', 'nova.cells.opts', group='cells')
CONF.import_opt('topic', 'nova.cells.opts', group='cells')


class CellsAPI(rpc_proxy.RpcProxy):
    '''Cells client-side RPC API

    API version history:

        1.0 - Initial version.
        1.1 - Adds get_cell_info_for_neighbors() and sync_instances()
    '''
    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(CellsAPI, self).__init__(topic=CONF.cells.topic,
                default_version=self.BASE_RPC_API_VERSION)

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

    def schedule_run_instance(self, ctxt, **kwargs):
        """Schedule a new instance for creation."""
        self.cast(ctxt, self.make_msg('schedule_run_instance',
                                      host_sched_kwargs=kwargs))

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
