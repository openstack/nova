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
Cells Scheduler
"""
import random
import time

from nova import compute
from nova.compute import vm_states
from nova.db import base
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.scheduler import rpcapi as scheduler_rpcapi

cell_scheduler_opts = [
        cfg.IntOpt('scheduler_retries',
                default=10,
                help='How many retries when no cells are available.'),
        cfg.IntOpt('scheduler_retry_delay',
                default=2,
                help='How often to retry in seconds when no cells are '
                        'available.')
]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(cell_scheduler_opts, group='cells')


class CellsScheduler(base.Base):
    """The cells scheduler."""

    def __init__(self, msg_runner):
        super(CellsScheduler, self).__init__()
        self.msg_runner = msg_runner
        self.state_manager = msg_runner.state_manager
        self.compute_api = compute.API()
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()

    def _create_instances_here(self, ctxt, request_spec):
        instance_values = request_spec['instance_properties']
        num_instances = len(request_spec['instance_uuids'])
        for i, instance_uuid in enumerate(request_spec['instance_uuids']):
            instance_values['uuid'] = instance_uuid
            instance = self.compute_api.create_db_entry_for_new_instance(
                    ctxt,
                    request_spec['instance_type'],
                    request_spec['image'],
                    instance_values,
                    request_spec['security_group'],
                    request_spec['block_device_mapping'],
                    num_instances, i)

            self.msg_runner.instance_update_at_top(ctxt, instance)

    def _get_possible_cells(self):
        cells = set(self.state_manager.get_child_cells())
        our_cell = self.state_manager.get_my_state()
        # Include our cell in the list, if we have any capacity info
        if not cells or our_cell.capacities:
            cells.add(our_cell)
        return cells

    def _run_instance(self, message, host_sched_kwargs):
        """Attempt to schedule instance(s).  If we have no cells
        to try, raise exception.NoCellsAvailable
        """
        ctxt = message.ctxt
        request_spec = host_sched_kwargs['request_spec']

        # The message we might forward to a child cell
        cells = self._get_possible_cells()
        if not cells:
            raise exception.NoCellsAvailable()
        cells = list(cells)

        # Random selection for now
        random.shuffle(cells)
        target_cell = cells[0]

        LOG.debug(_("Scheduling with routing_path=%(routing_path)s"),
                locals())

        if target_cell.is_me:
            # Need to create instance DB entries as the host scheduler
            # expects that the instance(s) already exists.
            self._create_instances_here(ctxt, request_spec)
            self.scheduler_rpcapi.run_instance(ctxt,
                    **host_sched_kwargs)
            return
        self.msg_runner.schedule_run_instance(ctxt, target_cell,
                                              host_sched_kwargs)

    def run_instance(self, message, host_sched_kwargs):
        """Pick a cell where we should create a new instance."""
        try:
            for i in xrange(max(0, CONF.cells.scheduler_retries) + 1):
                try:
                    return self._run_instance(message, host_sched_kwargs)
                except exception.NoCellsAvailable:
                    if i == max(0, CONF.cells.scheduler_retries):
                        raise
                    sleep_time = max(1, CONF.cells.scheduler_retry_delay)
                    LOG.info(_("No cells available when scheduling.  Will "
                            "retry in %(sleep_time)s second(s)"), locals())
                    time.sleep(sleep_time)
                    continue
        except Exception:
            request_spec = host_sched_kwargs['request_spec']
            instance_uuids = request_spec['instance_uuids']
            LOG.exception(_("Error scheduling instances %(instance_uuids)s"),
                    locals())
            ctxt = message.ctxt
            for instance_uuid in instance_uuids:
                self.msg_runner.instance_update_at_top(ctxt,
                            {'uuid': instance_uuid,
                             'vm_state': vm_states.ERROR})
                try:
                    self.db.instance_update(ctxt,
                                            instance_uuid,
                                            {'vm_state': vm_states.ERROR})
                except Exception:
                    pass
