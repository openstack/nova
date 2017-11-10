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
Tests For CellsScheduler
"""
import copy

import mock
from oslo_utils import uuidutils

from nova import block_device
from nova.cells import filters
from nova.cells import weights
from nova.compute import vm_states
import nova.conf
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.cells import fakes
from nova.tests.unit import fake_block_device
from nova.tests import uuidsentinel
from nova import utils

CONF = nova.conf.CONF


class FakeFilterClass1(filters.BaseCellFilter):
    pass


class FakeFilterClass2(filters.BaseCellFilter):
    pass


class FakeWeightClass1(weights.BaseCellWeigher):
    def _weigh_object(self, obj, weight_properties):
        pass


class FakeWeightClass2(weights.BaseCellWeigher):
    def _weigh_object(self, obj, weight_properties):
        pass


class CellsSchedulerTestCase(test.TestCase):
    """Test case for CellsScheduler class."""

    def setUp(self):
        super(CellsSchedulerTestCase, self).setUp()
        self.flags(scheduler_filter_classes=[], scheduler_weight_classes=[],
                   group='cells')
        self._init_cells_scheduler()

    def _init_cells_scheduler(self):
        fakes.init(self)
        self.msg_runner = fakes.get_message_runner('api-cell')
        self.scheduler = self.msg_runner.scheduler
        self.state_manager = self.msg_runner.state_manager
        self.my_cell_state = self.state_manager.get_my_state()
        self.ctxt = context.RequestContext('fake', 'fake')
        instance_uuids = []
        for x in range(3):
            instance_uuids.append(uuidutils.generate_uuid())
        self.instance_uuids = instance_uuids
        self.instances = [objects.Instance(uuid=uuid, id=id)
                          for id, uuid in enumerate(instance_uuids)]
        self.request_spec = {
                'num_instances': len(instance_uuids),
                'instance_properties': self.instances[0],
                'instance_type': 'fake_type',
                'image': 'fake_image'}
        self.build_inst_kwargs = {
                'instances': self.instances,
                'image': 'fake_image',
                'filter_properties': {'instance_type': 'fake_type'},
                'security_groups': 'fake_sec_groups',
                'block_device_mapping': 'fake_bdm'}

    def test_create_instances_here(self):
        # Just grab the first instance type
        inst_type = objects.Flavor.get_by_id(self.ctxt, 1)
        image = {'properties': {}}
        instance_uuids = self.instance_uuids
        instance_props = {'id': 'removed',
                          'security_groups': 'removed',
                          'info_cache': 'removed',
                          'name': 'instance-00000001',
                          'hostname': 'meow',
                          'display_name': 'moo',
                          'image_ref': uuidsentinel.fake_image_ref,
                          'user_id': self.ctxt.user_id,
                          # Test these as lists
                          'metadata': {'moo': 'cow'},
                          'system_metadata': {'meow': 'cat'},
                          'flavor': inst_type,
                          'project_id': self.ctxt.project_id}

        call_info = {'uuids': []}
        block_device_mapping = objects.BlockDeviceMappingList(
            objects=[
                objects.BlockDeviceMapping(context=self.ctxt,
                    **fake_block_device.FakeDbBlockDeviceDict(
                            block_device.create_image_bdm(
                                uuidsentinel.fake_image_ref),
                        anon=True))
               ])

        def _fake_instance_update_at_top(self, _ctxt, instance):
            call_info['uuids'].append(instance['uuid'])

        self.stub_out('nova.cells.messaging.MessageRunner.'
                      'instance_update_at_top',
                      _fake_instance_update_at_top)

        self.scheduler._create_instances_here(self.ctxt, instance_uuids,
                instance_props, inst_type, image,
                ['default'], block_device_mapping)
        self.assertEqual(instance_uuids, call_info['uuids'])

        for count, instance_uuid in enumerate(instance_uuids):
            bdms = db.block_device_mapping_get_all_by_instance(self.ctxt,
                                                               instance_uuid)
            self.assertIsNotNone(bdms)
            instance = db.instance_get_by_uuid(self.ctxt, instance_uuid)
            meta = utils.instance_meta(instance)
            self.assertEqual('cow', meta['moo'])
            sys_meta = utils.instance_sys_meta(instance)
            self.assertEqual('cat', sys_meta['meow'])
            self.assertEqual('meow', instance['hostname'])
            self.assertEqual('moo-%d' % (count + 1),
                             instance['display_name'])
            self.assertEqual(uuidsentinel.fake_image_ref,
                             instance['image_ref'])

    @mock.patch('nova.objects.Instance.update')
    def test_create_instances_here_pops_problematic_properties(self,
                                                               mock_update):
        values = {
            'uuid': uuidsentinel.instance,
            'metadata': [],
            'id': 1,
            'name': 'foo',
            'info_cache': 'bar',
            'security_groups': 'not secure',
            'flavor': 'chocolate',
            'pci_requests': 'no thanks',
            'ec2_ids': 'prime',
        }
        block_device_mapping = [
                objects.BlockDeviceMapping(context=self.ctxt,
                    **fake_block_device.FakeDbBlockDeviceDict(
                            block_device.create_image_bdm(
                                uuidsentinel.fake_image_ref),
                            anon=True))
               ]

        @mock.patch.object(self.scheduler.compute_api,
                           'create_db_entry_for_new_instance')
        @mock.patch.object(self.scheduler.compute_api,
                           '_bdm_validate_set_size_and_instance')
        def test(mock_bdm_validate, mock_create_db):
            self.scheduler._create_instances_here(
                self.ctxt, [uuidsentinel.instance], values,
                objects.Flavor(), 'foo', [], block_device_mapping)

        test()

        # NOTE(danms): Make sure that only the expected properties
        # are applied to the instance object. The complex ones that
        # would have been mangled over RPC should be removed.
        mock_update.assert_called_once_with(
            {'uuid': uuidsentinel.instance,
             'metadata': {}})

    def test_build_instances_selects_child_cell(self):
        # Make sure there's no capacity info so we're sure to
        # select a child cell
        our_cell_info = self.state_manager.get_my_state()
        our_cell_info.capacities = {}

        call_info = {'times': 0}

        orig_fn = self.msg_runner.build_instances

        def msg_runner_build_instances(self_mr, ctxt, target_cell,
                                       build_inst_kwargs):
            # This gets called twice.  Once for our running it
            # in this cell.. and then it'll get called when the
            # child cell is picked.  So, first time.. just run it
            # like normal.
            if not call_info['times']:
                call_info['times'] += 1
                return orig_fn(ctxt, target_cell, build_inst_kwargs)
            call_info['ctxt'] = ctxt
            call_info['target_cell'] = target_cell
            call_info['build_inst_kwargs'] = build_inst_kwargs

        def fake_build_request_spec(image, instances):
            request_spec = {
                    'num_instances': len(instances),
                    'image': image}
            return request_spec

        self.stub_out('nova.cells.messaging.MessageRunner.build_instances',
                      msg_runner_build_instances)
        self.stub_out('nova.scheduler.utils.build_request_spec',
                      fake_build_request_spec)

        self.msg_runner.build_instances(self.ctxt, self.my_cell_state,
                self.build_inst_kwargs)

        self.assertEqual(self.ctxt, call_info['ctxt'])
        self.assertEqual(self.build_inst_kwargs,
                call_info['build_inst_kwargs'])
        child_cells = self.state_manager.get_child_cells()
        self.assertIn(call_info['target_cell'], child_cells)

    def test_build_instances_selects_current_cell(self):
        self.flags(scheduler='nova.cells.scheduler.CellsScheduler',
                   group='cells')
        # Make sure there's no child cells so that we will be
        # selected
        self.state_manager.child_cells = {}

        call_info = {}
        build_inst_kwargs = copy.deepcopy(self.build_inst_kwargs)

        def fake_create_instances_here(self_cs, ctxt, instance_uuids,
                instance_properties, instance_type, image, security_groups,
                block_device_mapping):
            call_info['ctxt'] = ctxt
            call_info['instance_uuids'] = instance_uuids
            call_info['instance_properties'] = instance_properties
            call_info['instance_type'] = instance_type
            call_info['image'] = image
            call_info['security_groups'] = security_groups
            call_info['block_device_mapping'] = block_device_mapping
            return self.instances

        def fake_rpc_build_instances(self, ctxt, **build_inst_kwargs):
            call_info['build_inst_kwargs'] = build_inst_kwargs

        def fake_build_request_spec(image, instances):
            request_spec = {
                    'num_instances': len(instances),
                    'image': image}
            return request_spec

        self.stub_out('nova.cells.scheduler.CellsScheduler.'
                      '_create_instances_here',
                      fake_create_instances_here)
        self.stub_out('nova.conductor.api.ComputeTaskAPI.'
                      'build_instances', fake_rpc_build_instances)
        self.stub_out('nova.scheduler.utils.build_request_spec',
                      fake_build_request_spec)

        self.msg_runner.build_instances(self.ctxt, self.my_cell_state,
                build_inst_kwargs)

        self.assertEqual(self.ctxt, call_info['ctxt'])
        self.assertEqual(self.instance_uuids, call_info['instance_uuids'])
        self.assertEqual(self.build_inst_kwargs['instances'][0]['id'],
                         call_info['instance_properties']['id'])
        self.assertEqual(
            self.build_inst_kwargs['filter_properties']['instance_type'],
            call_info['instance_type'])
        self.assertEqual(self.build_inst_kwargs['image'], call_info['image'])
        self.assertEqual(self.build_inst_kwargs['security_groups'],
                call_info['security_groups'])
        self.assertEqual(self.build_inst_kwargs['block_device_mapping'],
                call_info['block_device_mapping'])
        self.assertEqual(build_inst_kwargs,
                call_info['build_inst_kwargs'])
        self.assertEqual(self.instance_uuids, call_info['instance_uuids'])

    def test_build_instances_retries_when_no_cells_avail(self):
        self.flags(scheduler='nova.cells.scheduler.CellsScheduler',
                   scheduler_retries=7, group='cells')

        call_info = {'num_tries': 0, 'errored_uuids': []}

        def fake_grab_target_cells(self, filter_properties):
            call_info['num_tries'] += 1
            raise exception.NoCellsAvailable()

        def fake_sleep(_secs):
            return

        def fake_instance_save(inst):
            self.assertEqual(vm_states.ERROR, inst.vm_state)
            call_info['errored_uuids'].append(inst.uuid)

        def fake_build_request_spec(image, instances):
            request_spec = {
                    'num_instances': len(instances),
                    'image': image}
            return request_spec

        self.stub_out('nova.cells.scheduler.CellsScheduler._grab_target_cells',
                      fake_grab_target_cells)
        self.stub_out('time.sleep', fake_sleep)
        self.stub_out('nova.objects.Instance.save', fake_instance_save)
        self.stub_out('nova.scheduler.utils.build_request_spec',
                       fake_build_request_spec)

        self.msg_runner.build_instances(self.ctxt, self.my_cell_state,
                self.build_inst_kwargs)

        self.assertEqual(8, call_info['num_tries'])
        self.assertEqual(self.instance_uuids, call_info['errored_uuids'])

    def test_schedule_method_on_random_exception(self):
        self.flags(scheduler='nova.cells.scheduler.CellsScheduler',
                   scheduler_retries=7, group='cells')

        instances = [objects.Instance(uuid=uuid) for uuid in
                     self.instance_uuids]
        method_kwargs = {
                'image': 'fake_image',
                'instances': instances,
                'filter_properties': {}}

        call_info = {'num_tries': 0,
                     'errored_uuids1': [],
                     'errored_uuids2': []}

        def fake_grab_target_cells(self, filter_properties):
            call_info['num_tries'] += 1
            raise test.TestingException()

        def fake_instance_save(inst):
            self.assertEqual(vm_states.ERROR, inst.vm_state)
            call_info['errored_uuids1'].append(inst.uuid)

        def fake_instance_update_at_top(self_mr, ctxt, instance):
            self.assertEqual(vm_states.ERROR, instance['vm_state'])
            call_info['errored_uuids2'].append(instance['uuid'])

        def fake_build_request_spec(image, instances):
            request_spec = {
                    'num_instances': len(instances),
                    'image': image}
            return request_spec

        self.stub_out('nova.cells.scheduler.CellsScheduler._grab_target_cells',
                      fake_grab_target_cells)
        self.stub_out('nova.objects.Instance.save', fake_instance_save)
        self.stub_out('nova.cells.messaging.MessageRunner.'
                      'instance_update_at_top',
                      fake_instance_update_at_top)
        self.stub_out('nova.scheduler.utils.build_request_spec',
                      fake_build_request_spec)

        self.msg_runner.build_instances(self.ctxt, self.my_cell_state,
                method_kwargs)
        # Shouldn't retry
        self.assertEqual(1, call_info['num_tries'])
        self.assertEqual(self.instance_uuids, call_info['errored_uuids1'])
        self.assertEqual(self.instance_uuids, call_info['errored_uuids2'])

    def test_filter_schedule_skipping(self):
        # if a filter handles scheduling, short circuit
        mock_func = mock.Mock()
        self.scheduler._grab_target_cells = mock.Mock(return_value=None)
        self.scheduler._schedule_build_to_cells(None, None, None,
                                                mock_func, None)
        mock_func.assert_not_called()

    def test_cells_filter_args_correct(self):
        # Re-init our fakes with some filters.
        our_path = 'nova.tests.unit.cells.test_cells_scheduler'
        cls_names = [our_path + '.' + 'FakeFilterClass1',
                     our_path + '.' + 'FakeFilterClass2']
        self.flags(scheduler='nova.cells.scheduler.CellsScheduler',
                   scheduler_filter_classes=cls_names, group='cells')
        self._init_cells_scheduler()

        # Make sure there's no child cells so that we will be
        # selected.  Makes stubbing easier.
        self.state_manager.child_cells = {}

        call_info = {}

        def fake_create_instances_here(self_cs, ctxt, instance_uuids,
                instance_properties, instance_type, image, security_groups,
                block_device_mapping):
            call_info['ctxt'] = ctxt
            call_info['instance_uuids'] = instance_uuids
            call_info['instance_properties'] = instance_properties
            call_info['instance_type'] = instance_type
            call_info['image'] = image
            call_info['security_groups'] = security_groups
            call_info['block_device_mapping'] = block_device_mapping

        def fake_rpc_build_instances(self, ctxt, **host_sched_kwargs):
            call_info['host_sched_kwargs'] = host_sched_kwargs

        def fake_get_filtered_objs(self, filters, cells, filt_properties):
            call_info['filt_objects'] = filters
            call_info['filt_cells'] = cells
            call_info['filt_props'] = filt_properties
            return cells

        def fake_build_request_spec(image, instances):
            request_spec = {
                    'num_instances': len(instances),
                    'instance_properties': instances[0],
                    'image': image,
                    'instance_type': 'fake_type'}
            return request_spec

        self.stub_out('nova.cells.scheduler.CellsScheduler.'
                      '_create_instances_here',
                      fake_create_instances_here)
        self.stub_out('nova.conductor.api.ComputeTaskAPI.'
                      'build_instances', fake_rpc_build_instances)
        self.stub_out('nova.scheduler.utils.build_request_spec',
                      fake_build_request_spec)
        self.stub_out('nova.cells.filters.CellFilterHandler.'
                      'get_filtered_objects',
                      fake_get_filtered_objs)

        host_sched_kwargs = {'image': 'fake_image',
                             'instances': self.instances,
                             'filter_properties':
                                {'instance_type': 'fake_type'},
                             'security_groups': 'fake_sec_groups',
                             'block_device_mapping': 'fake_bdm'}

        self.msg_runner.build_instances(self.ctxt,
                self.my_cell_state, host_sched_kwargs)
        # Our cell was selected.
        self.assertEqual(self.ctxt, call_info['ctxt'])
        self.assertEqual(self.instance_uuids, call_info['instance_uuids'])
        self.assertEqual(self.request_spec['instance_properties']['id'],
                         call_info['instance_properties']['id'])
        self.assertEqual(self.request_spec['instance_type'],
                call_info['instance_type'])
        self.assertEqual(self.request_spec['image'], call_info['image'])
        self.assertEqual(host_sched_kwargs, call_info['host_sched_kwargs'])
        # Filter args are correct
        expected_filt_props = {'context': self.ctxt,
                               'scheduler': self.scheduler,
                               'routing_path': self.my_cell_state.name,
                               'host_sched_kwargs': host_sched_kwargs,
                               'request_spec': self.request_spec,
                               'instance_type': 'fake_type'}
        self.assertEqual(expected_filt_props, call_info['filt_props'])
        self.assertEqual([FakeFilterClass1, FakeFilterClass2],
                         [obj.__class__ for obj in call_info['filt_objects']])
        self.assertEqual([self.my_cell_state], call_info['filt_cells'])

    def test_cells_filter_returning_none(self):
        # Re-init our fakes with some filters.
        our_path = 'nova.tests.unit.cells.test_cells_scheduler'
        cls_names = [our_path + '.' + 'FakeFilterClass1',
                     our_path + '.' + 'FakeFilterClass2']
        self.flags(scheduler='nova.cells.scheduler.CellsScheduler',
                   scheduler_filter_classes=cls_names, group='cells')
        self._init_cells_scheduler()

        # Make sure there's no child cells so that we will be
        # selected.  Makes stubbing easier.
        self.state_manager.child_cells = {}

        call_info = {'scheduled': False}

        def fake_create_instances_here(self, ctxt, request_spec):
            # Should not be called
            call_info['scheduled'] = True

        def fake_get_filtered_objs(filter_classes, cells, filt_properties):
            # Should cause scheduling to be skipped.  Means that the
            # filter did it.
            return None

        self.stub_out('nova.cells.scheduler.CellsScheduler.'
                      '_create_instances_here',
                      fake_create_instances_here)
        self.stub_out('nova.cells.filters.CellFilterHandler.'
                      'get_filtered_objects',
                      fake_get_filtered_objs)

        self.msg_runner.build_instances(self.ctxt,
                self.my_cell_state, {})
        self.assertFalse(call_info['scheduled'])

    def test_cells_weight_args_correct(self):
        # Re-init our fakes with some filters.
        our_path = 'nova.tests.unit.cells.test_cells_scheduler'
        cls_names = [our_path + '.' + 'FakeWeightClass1',
                     our_path + '.' + 'FakeWeightClass2']
        self.flags(scheduler='nova.cells.scheduler.CellsScheduler',
                   scheduler_weight_classes=cls_names, group='cells')
        self._init_cells_scheduler()

        # Make sure there's no child cells so that we will be
        # selected.  Makes stubbing easier.
        self.state_manager.child_cells = {}

        call_info = {}

        def fake_create_instances_here(self_cs, ctxt, instance_uuids,
                instance_properties, instance_type, image, security_groups,
                block_device_mapping):
            call_info['ctxt'] = ctxt
            call_info['instance_uuids'] = instance_uuids
            call_info['instance_properties'] = instance_properties
            call_info['instance_type'] = instance_type
            call_info['image'] = image
            call_info['security_groups'] = security_groups
            call_info['block_device_mapping'] = block_device_mapping

        def fake_rpc_build_instances(self, ctxt, **host_sched_kwargs):
            call_info['host_sched_kwargs'] = host_sched_kwargs

        def fake_get_weighed_objs(self, weighers, cells, filt_properties):
            call_info['weighers'] = weighers
            call_info['weight_cells'] = cells
            call_info['weight_props'] = filt_properties
            return [weights.WeightedCell(cells[0], 0.0)]

        def fake_build_request_spec(image, instances):
            request_spec = {
                    'num_instances': len(instances),
                    'instance_properties': instances[0],
                    'image': image,
                    'instance_type': 'fake_type'}
            return request_spec

        self.stub_out('nova.cells.scheduler.CellsScheduler.'
                      '_create_instances_here',
                      fake_create_instances_here)
        self.stub_out('nova.scheduler.utils.build_request_spec',
                      fake_build_request_spec)
        self.stub_out('nova.conductor.api.ComputeTaskAPI.'
                      'build_instances', fake_rpc_build_instances)
        self.stub_out('nova.cells.weights.CellWeightHandler.'
                      'get_weighed_objects',
                      fake_get_weighed_objs)

        host_sched_kwargs = {'image': 'fake_image',
                             'instances': self.instances,
                             'filter_properties':
                                {'instance_type': 'fake_type'},
                             'security_groups': 'fake_sec_groups',
                             'block_device_mapping': 'fake_bdm'}

        self.msg_runner.build_instances(self.ctxt,
                self.my_cell_state, host_sched_kwargs)
        # Our cell was selected.
        self.assertEqual(self.ctxt, call_info['ctxt'])
        self.assertEqual(self.instance_uuids, call_info['instance_uuids'])
        self.assertEqual(self.request_spec['instance_properties']['id'],
                         call_info['instance_properties']['id'])
        self.assertEqual(self.request_spec['instance_type'],
                call_info['instance_type'])
        self.assertEqual(self.request_spec['image'], call_info['image'])
        self.assertEqual(host_sched_kwargs, call_info['host_sched_kwargs'])
        # Weight args are correct
        expected_filt_props = {'context': self.ctxt,
                               'scheduler': self.scheduler,
                               'routing_path': self.my_cell_state.name,
                               'host_sched_kwargs': host_sched_kwargs,
                               'request_spec': self.request_spec,
                               'instance_type': 'fake_type'}
        self.assertEqual(expected_filt_props, call_info['weight_props'])
        self.assertEqual([FakeWeightClass1, FakeWeightClass2],
                         [obj.__class__ for obj in call_info['weighers']])
        self.assertEqual([self.my_cell_state], call_info['weight_cells'])
