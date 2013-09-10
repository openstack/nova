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
import copy
import time

from oslo.config import cfg

from nova.cells import filters
from nova.cells import weights
from nova import compute
from nova.compute import flavors
from nova.compute import instance_actions
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conductor
from nova.db import base
from nova import exception
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova.scheduler import utils as scheduler_utils
from nova import utils

cell_scheduler_opts = [
        cfg.ListOpt('scheduler_filter_classes',
                default=['nova.cells.filters.all_filters'],
                help='Filter classes the cells scheduler should use.  '
                        'An entry of "nova.cells.filters.all_filters"'
                        'maps to all cells filters included with nova.'),
        cfg.ListOpt('scheduler_weight_classes',
                default=['nova.cells.weights.all_weighers'],
                help='Weigher classes the cells scheduler should use.  '
                        'An entry of "nova.cells.weights.all_weighers"'
                        'maps to all cell weighers included with nova.'),
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
        self.compute_task_api = conductor.ComputeTaskAPI()
        self.filter_handler = filters.CellFilterHandler()
        self.filter_classes = self.filter_handler.get_matching_classes(
                CONF.cells.scheduler_filter_classes)
        self.weight_handler = weights.CellWeightHandler()
        self.weigher_classes = self.weight_handler.get_matching_classes(
                CONF.cells.scheduler_weight_classes)

    def _create_instances_here(self, ctxt, instance_uuids, instance_properties,
            instance_type, image, security_groups, block_device_mapping):
        instance_values = copy.copy(instance_properties)
        # The parent may pass these metadata values as lists, and the
        # create call expects it to be a dict.
        instance_values['metadata'] = utils.instance_meta(instance_values)
        sys_metadata = utils.instance_sys_meta(instance_values)
        # Make sure the flavor info is set.  It may not have been passed
        # down.
        sys_metadata = flavors.save_flavor_info(sys_metadata, instance_type)
        instance_values['system_metadata'] = sys_metadata
        # Pop out things that will get set properly when re-creating the
        # instance record.
        instance_values.pop('id')
        instance_values.pop('name')
        instance_values.pop('info_cache')
        instance_values.pop('security_groups')

        num_instances = len(instance_uuids)
        for i, instance_uuid in enumerate(instance_uuids):
            instance = instance_obj.Instance()
            instance.update(instance_values)
            instance.uuid = instance_uuid
            instance = self.compute_api.create_db_entry_for_new_instance(
                    ctxt,
                    instance_type,
                    image,
                    instance,
                    security_groups,
                    block_device_mapping,
                    num_instances, i)

            instance = obj_base.obj_to_primitive(instance)
            self.msg_runner.instance_update_at_top(ctxt, instance)

    def _create_action_here(self, ctxt, instance_uuids):
        for instance_uuid in instance_uuids:
            action = compute_utils.pack_action_start(ctxt, instance_uuid,
                    instance_actions.CREATE)
            self.db.action_start(ctxt, action)

    def _get_possible_cells(self):
        cells = self.state_manager.get_child_cells()
        our_cell = self.state_manager.get_my_state()
        # Include our cell in the list, if we have any capacity info
        if not cells or our_cell.capacities:
            cells.append(our_cell)
        return cells

    def _grab_target_cells(self, filter_properties):
        cells = self._get_possible_cells()
        cells = self.filter_handler.get_filtered_objects(self.filter_classes,
                                                         cells,
                                                         filter_properties)
        # NOTE(comstud): I know this reads weird, but the 'if's are nested
        # this way to optimize for the common case where 'cells' is a list
        # containing at least 1 entry.
        if not cells:
            if cells is None:
                # None means to bypass further scheduling as a filter
                # took care of everything.
                return
            raise exception.NoCellsAvailable()

        weighted_cells = self.weight_handler.get_weighed_objects(
                self.weigher_classes, cells, filter_properties)
        LOG.debug(_("Weighted cells: %(weighted_cells)s"),
                  {'weighted_cells': weighted_cells})
        target_cells = [cell.obj for cell in weighted_cells]
        return target_cells

    def _run_instance(self, message, target_cells, instance_uuids,
            host_sched_kwargs):
        """Attempt to schedule instance(s)."""
        ctxt = message.ctxt
        request_spec = host_sched_kwargs['request_spec']
        instance_properties = request_spec['instance_properties']
        instance_type = request_spec['instance_type']
        image = request_spec['image']
        security_groups = request_spec['security_group']
        block_device_mapping = request_spec['block_device_mapping']

        LOG.debug(_("Scheduling with routing_path=%(routing_path)s"),
                  {'routing_path': message.routing_path})

        for target_cell in target_cells:
            try:
                if target_cell.is_me:
                    # Need to create instance DB entries as the host scheduler
                    # expects that the instance(s) already exists.
                    self._create_instances_here(ctxt, instance_uuids,
                            instance_properties, instance_type, image,
                            security_groups, block_device_mapping)
                    # Need to record the create action in the db as the
                    # scheduler expects it to already exist.
                    self._create_action_here(ctxt, instance_uuids)
                    self.scheduler_rpcapi.run_instance(ctxt,
                            **host_sched_kwargs)
                    return
                self.msg_runner.schedule_run_instance(ctxt, target_cell,
                                                      host_sched_kwargs)
                return
            except Exception:
                LOG.exception(_("Couldn't communicate with cell '%s'") %
                        target_cell.name)
        # FIXME(comstud): Would be nice to kick this back up so that
        # the parent cell could retry, if we had a parent.
        msg = _("Couldn't communicate with any cells")
        LOG.error(msg)
        raise exception.NoCellsAvailable()

    def _build_instances(self, message, target_cells, instance_uuids,
            build_inst_kwargs):
        """Attempt to build instance(s) or send msg to child cell."""
        ctxt = message.ctxt
        instance_properties = build_inst_kwargs['instances'][0]
        filter_properties = build_inst_kwargs['filter_properties']
        instance_type = filter_properties['instance_type']
        image = build_inst_kwargs['image']
        security_groups = build_inst_kwargs['security_groups']
        block_device_mapping = build_inst_kwargs['block_device_mapping']

        LOG.debug(_("Building instances with routing_path=%(routing_path)s"),
                  {'routing_path': message.routing_path})

        for target_cell in target_cells:
            try:
                if target_cell.is_me:
                    # Need to create instance DB entries as the conductor
                    # expects that the instance(s) already exists.
                    self._create_instances_here(ctxt, instance_uuids,
                            instance_properties, instance_type, image,
                            security_groups, block_device_mapping)
                    # Need to record the create action in the db as the
                    # conductor expects it to already exist.
                    self._create_action_here(ctxt, instance_uuids)
                    self.compute_task_api.build_instances(ctxt,
                            **build_inst_kwargs)
                    return
                self.msg_runner.build_instances(ctxt, target_cell,
                        build_inst_kwargs)
                return
            except Exception:
                LOG.exception(_("Couldn't communicate with cell '%s'") %
                        target_cell.name)
        # FIXME(comstud): Would be nice to kick this back up so that
        # the parent cell could retry, if we had a parent.
        msg = _("Couldn't communicate with any cells")
        LOG.error(msg)
        raise exception.NoCellsAvailable()

    def build_instances(self, message, build_inst_kwargs):
        image = build_inst_kwargs['image']
        instance_uuids = [inst['uuid'] for inst in
                build_inst_kwargs['instances']]
        instances = build_inst_kwargs['instances']
        request_spec = scheduler_utils.build_request_spec(message.ctxt,
                                                          image, instances)
        filter_properties = copy.copy(build_inst_kwargs['filter_properties'])
        filter_properties.update({'context': message.ctxt,
                                  'scheduler': self,
                                  'routing_path': message.routing_path,
                                  'host_sched_kwargs': build_inst_kwargs,
                                  'request_spec': request_spec})
        # NOTE(belliott) remove when deprecated schedule_run_instance
        # code gets removed.
        filter_properties['cell_scheduler_method'] = 'build_instances'

        self._schedule_build_to_cells(message, instance_uuids,
                filter_properties, self._build_instances, build_inst_kwargs)

    def run_instance(self, message, host_sched_kwargs):
        request_spec = host_sched_kwargs['request_spec']
        instance_uuids = request_spec['instance_uuids']
        filter_properties = copy.copy(host_sched_kwargs['filter_properties'])
        filter_properties.update({'context': message.ctxt,
                                  'scheduler': self,
                                  'routing_path': message.routing_path,
                                  'host_sched_kwargs': host_sched_kwargs,
                                  'request_spec': request_spec})
        # NOTE(belliott) remove when deprecated schedule_run_instance
        # code gets removed.
        filter_properties['cell_scheduler_method'] = 'schedule_run_instance'

        self._schedule_build_to_cells(message, instance_uuids,
                filter_properties, self._run_instance, host_sched_kwargs)

    def _schedule_build_to_cells(self, message, instance_uuids,
            filter_properties, method, method_kwargs):
        """Pick a cell where we should create a new instance(s)."""
        try:
            for i in xrange(max(0, CONF.cells.scheduler_retries) + 1):
                try:
                    target_cells = self._grab_target_cells(filter_properties)
                    if target_cells is None:
                        # a filter took care of scheduling.  skip.
                        return

                    return method(message, target_cells, instance_uuids,
                            method_kwargs)
                except exception.NoCellsAvailable:
                    if i == max(0, CONF.cells.scheduler_retries):
                        raise
                    sleep_time = max(1, CONF.cells.scheduler_retry_delay)
                    LOG.info(_("No cells available when scheduling.  Will "
                               "retry in %(sleep_time)s second(s)"),
                             {'sleep_time': sleep_time})
                    time.sleep(sleep_time)
                    continue
        except Exception:
            LOG.exception(_("Error scheduling instances %(instance_uuids)s"),
                          {'instance_uuids': instance_uuids})
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
