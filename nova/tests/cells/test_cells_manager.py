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
Tests For CellsManager
"""
import datetime

from nova.cells import messaging
from nova.cells import utils as cells_utils
from nova import context
from nova.openstack.common import timeutils
from nova import test
from nova.tests.cells import fakes


class CellsManagerClassTestCase(test.TestCase):
    """Test case for CellsManager class."""

    def setUp(self):
        super(CellsManagerClassTestCase, self).setUp()
        fakes.init(self)
        # pick a child cell to use for tests.
        self.our_cell = 'grandchild-cell1'
        self.cells_manager = fakes.get_cells_manager(self.our_cell)
        self.msg_runner = self.cells_manager.msg_runner
        self.driver = self.cells_manager.driver
        self.ctxt = 'fake_context'

    def _get_fake_responses(self):
        responses = []
        expected_responses = []
        for x in xrange(1, 4):
            responses.append(messaging.Response('cell%s' % x, x, False))
            expected_responses.append(('cell%s' % x, x))
        return expected_responses, responses

    def test_get_cell_info_for_neighbors(self):
        self.mox.StubOutWithMock(self.cells_manager.state_manager,
                'get_cell_info_for_neighbors')
        self.cells_manager.state_manager.get_cell_info_for_neighbors()
        self.mox.ReplayAll()
        self.cells_manager.get_cell_info_for_neighbors(self.ctxt)

    def test_post_start_hook_child_cell(self):
        self.mox.StubOutWithMock(self.driver, 'start_consumers')
        self.mox.StubOutWithMock(context, 'get_admin_context')
        self.mox.StubOutWithMock(self.cells_manager, '_update_our_parents')

        self.driver.start_consumers(self.msg_runner)
        context.get_admin_context().AndReturn(self.ctxt)
        self.cells_manager._update_our_parents(self.ctxt)
        self.mox.ReplayAll()
        self.cells_manager.post_start_hook()

    def test_post_start_hook_middle_cell(self):
        cells_manager = fakes.get_cells_manager('child-cell2')
        msg_runner = cells_manager.msg_runner
        driver = cells_manager.driver

        self.mox.StubOutWithMock(driver, 'start_consumers')
        self.mox.StubOutWithMock(context, 'get_admin_context')
        self.mox.StubOutWithMock(msg_runner,
                                 'ask_children_for_capabilities')
        self.mox.StubOutWithMock(msg_runner,
                                 'ask_children_for_capacities')

        driver.start_consumers(msg_runner)
        context.get_admin_context().AndReturn(self.ctxt)
        msg_runner.ask_children_for_capabilities(self.ctxt)
        msg_runner.ask_children_for_capacities(self.ctxt)
        self.mox.ReplayAll()
        cells_manager.post_start_hook()

    def test_update_our_parents(self):
        self.mox.StubOutWithMock(self.msg_runner,
                                 'tell_parents_our_capabilities')
        self.mox.StubOutWithMock(self.msg_runner,
                                 'tell_parents_our_capacities')

        self.msg_runner.tell_parents_our_capabilities(self.ctxt)
        self.msg_runner.tell_parents_our_capacities(self.ctxt)
        self.mox.ReplayAll()
        self.cells_manager._update_our_parents(self.ctxt)

    def test_schedule_run_instance(self):
        host_sched_kwargs = 'fake_host_sched_kwargs_silently_passed'
        self.mox.StubOutWithMock(self.msg_runner, 'schedule_run_instance')
        our_cell = self.msg_runner.state_manager.get_my_state()
        self.msg_runner.schedule_run_instance(self.ctxt, our_cell,
                                              host_sched_kwargs)
        self.mox.ReplayAll()
        self.cells_manager.schedule_run_instance(self.ctxt,
                host_sched_kwargs=host_sched_kwargs)

    def test_run_compute_api_method(self):
        # Args should just be silently passed through
        cell_name = 'fake-cell-name'
        method_info = 'fake-method-info'

        fake_response = messaging.Response('fake', 'fake', False)

        self.mox.StubOutWithMock(self.msg_runner,
                                 'run_compute_api_method')
        self.mox.StubOutWithMock(fake_response,
                                 'value_or_raise')
        self.msg_runner.run_compute_api_method(self.ctxt,
                                               cell_name,
                                               method_info,
                                               True).AndReturn(fake_response)
        fake_response.value_or_raise().AndReturn('fake-response')
        self.mox.ReplayAll()
        response = self.cells_manager.run_compute_api_method(
                self.ctxt, cell_name=cell_name, method_info=method_info,
                call=True)
        self.assertEqual('fake-response', response)

    def test_instance_update_at_top(self):
        self.mox.StubOutWithMock(self.msg_runner, 'instance_update_at_top')
        self.msg_runner.instance_update_at_top(self.ctxt, 'fake-instance')
        self.mox.ReplayAll()
        self.cells_manager.instance_update_at_top(self.ctxt,
                                                  instance='fake-instance')

    def test_instance_destroy_at_top(self):
        self.mox.StubOutWithMock(self.msg_runner, 'instance_destroy_at_top')
        self.msg_runner.instance_destroy_at_top(self.ctxt, 'fake-instance')
        self.mox.ReplayAll()
        self.cells_manager.instance_destroy_at_top(self.ctxt,
                                                  instance='fake-instance')

    def test_instance_delete_everywhere(self):
        self.mox.StubOutWithMock(self.msg_runner,
                                 'instance_delete_everywhere')
        self.msg_runner.instance_delete_everywhere(self.ctxt,
                                                   'fake-instance',
                                                   'fake-type')
        self.mox.ReplayAll()
        self.cells_manager.instance_delete_everywhere(
                self.ctxt, instance='fake-instance',
                delete_type='fake-type')

    def test_instance_fault_create_at_top(self):
        self.mox.StubOutWithMock(self.msg_runner,
                                 'instance_fault_create_at_top')
        self.msg_runner.instance_fault_create_at_top(self.ctxt,
                                                     'fake-fault')
        self.mox.ReplayAll()
        self.cells_manager.instance_fault_create_at_top(
                self.ctxt, instance_fault='fake-fault')

    def test_bw_usage_update_at_top(self):
        self.mox.StubOutWithMock(self.msg_runner,
                                 'bw_usage_update_at_top')
        self.msg_runner.bw_usage_update_at_top(self.ctxt,
                                               'fake-bw-info')
        self.mox.ReplayAll()
        self.cells_manager.bw_usage_update_at_top(
                self.ctxt, bw_update_info='fake-bw-info')

    def test_heal_instances(self):
        self.flags(instance_updated_at_threshold=1000,
                   instance_update_num_instances=2,
                   group='cells')

        fake_context = context.RequestContext('fake', 'fake')
        stalled_time = timeutils.utcnow()
        updated_since = stalled_time - datetime.timedelta(seconds=1000)

        def utcnow():
            return stalled_time

        call_info = {'get_instances': 0, 'sync_instances': []}

        instances = ['instance1', 'instance2', 'instance3']

        def get_instances_to_sync(context, **kwargs):
            self.assertEqual(context, fake_context)
            call_info['shuffle'] = kwargs.get('shuffle')
            call_info['project_id'] = kwargs.get('project_id')
            call_info['updated_since'] = kwargs.get('updated_since')
            call_info['get_instances'] += 1
            return iter(instances)

        def instance_get_by_uuid(context, uuid):
            return instances[int(uuid[-1]) - 1]

        def sync_instance(context, instance):
            self.assertEqual(context, fake_context)
            call_info['sync_instances'].append(instance)

        self.stubs.Set(cells_utils, 'get_instances_to_sync',
                get_instances_to_sync)
        self.stubs.Set(self.cells_manager.db, 'instance_get_by_uuid',
                instance_get_by_uuid)
        self.stubs.Set(self.cells_manager, '_sync_instance',
                sync_instance)
        self.stubs.Set(timeutils, 'utcnow', utcnow)

        self.cells_manager._heal_instances(fake_context)
        self.assertEqual(call_info['shuffle'], True)
        self.assertEqual(call_info['project_id'], None)
        self.assertEqual(call_info['updated_since'], updated_since)
        self.assertEqual(call_info['get_instances'], 1)
        # Only first 2
        self.assertEqual(call_info['sync_instances'],
                instances[:2])

        call_info['sync_instances'] = []
        self.cells_manager._heal_instances(fake_context)
        self.assertEqual(call_info['shuffle'], True)
        self.assertEqual(call_info['project_id'], None)
        self.assertEqual(call_info['updated_since'], updated_since)
        self.assertEqual(call_info['get_instances'], 2)
        # Now the last 1 and the first 1
        self.assertEqual(call_info['sync_instances'],
                [instances[-1], instances[0]])

    def test_sync_instances(self):
        self.mox.StubOutWithMock(self.msg_runner,
                                 'sync_instances')
        self.msg_runner.sync_instances(self.ctxt, 'fake-project',
                                       'fake-time', 'fake-deleted')
        self.mox.ReplayAll()
        self.cells_manager.sync_instances(self.ctxt,
                                          project_id='fake-project',
                                          updated_since='fake-time',
                                          deleted='fake-deleted')
