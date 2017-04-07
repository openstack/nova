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

from oslo_log import log as logging
from six.moves import range

from nova.cells import filters
from nova.cells import weights
from nova import compute
from nova.compute import instance_actions
from nova.compute import vm_states
from nova import conductor
import nova.conf
from nova.db import base
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.scheduler import utils as scheduler_utils
from nova import utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class CellsScheduler(base.Base):
    """The cells scheduler."""

    def __init__(self, msg_runner):
        super(CellsScheduler, self).__init__()
        self.msg_runner = msg_runner
        self.state_manager = msg_runner.state_manager
        self.compute_api = compute.API()
        self.compute_task_api = conductor.ComputeTaskAPI()
        self.filter_handler = filters.CellFilterHandler()
        filter_classes = self.filter_handler.get_matching_classes(
                CONF.cells.scheduler_filter_classes)
        self.filters = [cls() for cls in filter_classes]
        self.weight_handler = weights.CellWeightHandler()
        weigher_classes = self.weight_handler.get_matching_classes(
                CONF.cells.scheduler_weight_classes)
        self.weighers = [cls() for cls in weigher_classes]

    def _create_instances_here(self, ctxt, instance_uuids, instance_properties,
            instance_type, image, security_groups, block_device_mapping):
        instance_values = copy.copy(instance_properties)
        # The parent may pass these metadata values as lists, and the
        # create call expects it to be a dict.
        instance_values['metadata'] = utils.instance_meta(instance_values)
        # Pop out things that will get set properly when re-creating the
        # instance record.
        instance_values.pop('id')
        instance_values.pop('name')
        instance_values.pop('info_cache')
        instance_values.pop('security_groups')
        instance_values.pop('flavor')

        # FIXME(danms): The instance was brutally serialized before being
        # sent over RPC to us. Thus, the pci_requests value wasn't really
        # sent in a useful form. Since it was getting ignored for cells
        # before it was part of the Instance, skip it now until cells RPC
        # is sending proper instance objects.
        instance_values.pop('pci_requests', None)

        # FIXME(danms): Same for ec2_ids
        instance_values.pop('ec2_ids', None)

        # FIXME(danms): Same for keypairs
        instance_values.pop('keypairs', None)

        instances = []
        num_instances = len(instance_uuids)
        security_groups = (
            self.compute_api.security_group_api.populate_security_groups(
                security_groups))
        for i, instance_uuid in enumerate(instance_uuids):
            instance = objects.Instance(context=ctxt)
            instance.update(instance_values)
            instance.uuid = instance_uuid
            instance.flavor = instance_type
            instance.old_flavor = None
            instance.new_flavor = None
            instance = self.compute_api.create_db_entry_for_new_instance(
                    ctxt,
                    instance_type,
                    image,
                    instance,
                    security_groups,
                    block_device_mapping,
                    num_instances, i)
            block_device_mapping = (
                self.compute_api._bdm_validate_set_size_and_instance(
                    ctxt, instance, instance_type, block_device_mapping))
            self.compute_api._create_block_device_mapping(block_device_mapping)

            instances.append(instance)
            self.msg_runner.instance_update_at_top(ctxt, instance)
        return instances

    def _create_action_here(self, ctxt, instance_uuids):
        for instance_uuid in instance_uuids:
            objects.InstanceAction.action_start(
                    ctxt,
                    instance_uuid,
                    instance_actions.CREATE,
                    want_result=False)

    def _get_possible_cells(self):
        cells = self.state_manager.get_child_cells()
        our_cell = self.state_manager.get_my_state()
        # Include our cell in the list, if we have any capacity info
        if not cells or our_cell.capacities:
            cells.append(our_cell)
        return cells

    def _grab_target_cells(self, filter_properties):
        cells = self._get_possible_cells()
        cells = self.filter_handler.get_filtered_objects(self.filters, cells,
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
                self.weighers, cells, filter_properties)
        LOG.debug("Weighted cells: %(weighted_cells)s",
                  {'weighted_cells': weighted_cells})
        target_cells = [cell.obj for cell in weighted_cells]
        return target_cells

    def _build_instances(self, message, target_cells, instance_uuids,
            build_inst_kwargs):
        """Attempt to build instance(s) or send msg to child cell."""
        ctxt = message.ctxt
        instance_properties = obj_base.obj_to_primitive(
            build_inst_kwargs['instances'][0])
        filter_properties = build_inst_kwargs['filter_properties']
        instance_type = filter_properties['instance_type']
        image = build_inst_kwargs['image']
        security_groups = build_inst_kwargs['security_groups']
        block_device_mapping = build_inst_kwargs['block_device_mapping']

        LOG.debug("Building instances with routing_path=%(routing_path)s",
                  {'routing_path': message.routing_path})

        for target_cell in target_cells:
            try:
                if target_cell.is_me:
                    # Need to create instance DB entries as the conductor
                    # expects that the instance(s) already exists.
                    instances = self._create_instances_here(ctxt,
                            instance_uuids, instance_properties, instance_type,
                            image, security_groups, block_device_mapping)
                    build_inst_kwargs['instances'] = instances
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
                LOG.exception("Couldn't communicate with cell '%s'",
                              target_cell.name)
        # FIXME(comstud): Would be nice to kick this back up so that
        # the parent cell could retry, if we had a parent.
        LOG.error("Couldn't communicate with any cells")
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

        self._schedule_build_to_cells(message, instance_uuids,
                filter_properties, self._build_instances, build_inst_kwargs)

    def _schedule_build_to_cells(self, message, instance_uuids,
            filter_properties, method, method_kwargs):
        """Pick a cell where we should create a new instance(s)."""
        try:
            for i in range(max(0, CONF.cells.scheduler_retries) + 1):
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
                    LOG.info("No cells available when scheduling.  Will "
                             "retry in %(sleep_time)s second(s)",
                             {'sleep_time': sleep_time})
                    time.sleep(sleep_time)
                    continue
        except Exception:
            LOG.exception("Error scheduling instances %(instance_uuids)s",
                          {'instance_uuids': instance_uuids})
            ctxt = message.ctxt
            for instance_uuid in instance_uuids:
                instance = objects.Instance(context=ctxt, uuid=instance_uuid,
                                            vm_state=vm_states.ERROR)
                self.msg_runner.instance_update_at_top(ctxt, instance)
                try:
                    instance.vm_state = vm_states.ERROR
                    instance.save()
                except Exception:
                    pass
