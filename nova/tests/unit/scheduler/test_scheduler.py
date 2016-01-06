# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Tests For Scheduler
"""

import mock

from nova import context
from nova import objects
from nova.scheduler import host_manager
from nova.scheduler import manager
from nova import servicegroup
from nova import test
from nova.tests.unit import fake_server_actions
from nova.tests.unit.scheduler import fakes


class SchedulerManagerTestCase(test.NoDBTestCase):
    """Test case for scheduler manager."""

    manager_cls = manager.SchedulerManager
    driver_cls = fakes.FakeScheduler
    driver_cls_name = 'nova.tests.unit.scheduler.fakes.FakeScheduler'

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(SchedulerManagerTestCase, self).setUp()
        self.flags(scheduler_driver=self.driver_cls_name)
        with mock.patch.object(host_manager.HostManager, '_init_aggregates'):
            self.manager = self.manager_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.fake_args = (1, 2, 3)
        self.fake_kwargs = {'cat': 'meow', 'dog': 'woof'}
        fake_server_actions.stub_out_action_events(self.stubs)

    def test_1_correct_init(self):
        # Correct scheduler driver
        manager = self.manager
        self.assertIsInstance(manager.driver, self.driver_cls)

    def test_select_destination(self):
        fake_spec = objects.RequestSpec()
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(None, spec_obj=fake_spec)
            select_destinations.assert_called_once_with(None, fake_spec)

    # TODO(sbauza): Remove that test once the API v4 is removed
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    def test_select_destination_with_old_client(self, from_primitives):
        fake_spec = objects.RequestSpec()
        from_primitives.return_value = fake_spec
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(None, request_spec='fake_spec',
                                             filter_properties='fake_props')
            select_destinations.assert_called_once_with(None, fake_spec)

    def test_update_aggregates(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'update_aggregates'
                ) as update_aggregates:
            self.manager.update_aggregates(None, aggregates='agg')
            update_aggregates.assert_called_once_with('agg')

    def test_delete_aggregate(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'delete_aggregate'
                ) as delete_aggregate:
            self.manager.delete_aggregate(None, aggregate='agg')
            delete_aggregate.assert_called_once_with('agg')

    def test_update_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'update_instance_info') as mock_update:
            self.manager.update_instance_info(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_info)
            mock_update.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.host_name,
                                                mock.sentinel.instance_info)

    def test_delete_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'delete_instance_info') as mock_delete:
            self.manager.delete_instance_info(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_uuid)
            mock_delete.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.host_name,
                                                mock.sentinel.instance_uuid)

    def test_sync_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'sync_instance_info') as mock_sync:
            self.manager.sync_instance_info(mock.sentinel.context,
                                            mock.sentinel.host_name,
                                            mock.sentinel.instance_uuids)
            mock_sync.assert_called_once_with(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_uuids)


class SchedulerTestCase(test.NoDBTestCase):
    """Test case for base scheduler driver class."""

    # So we can subclass this test and re-use tests if we need.
    driver_cls = fakes.FakeScheduler

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(SchedulerTestCase, self).setUp()
        self.driver = self.driver_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.servicegroup_api = servicegroup.API()

    def test_hosts_up(self):
        service1 = objects.Service(host='host1')
        service2 = objects.Service(host='host2')
        services = objects.ServiceList(objects=[service1, service2])

        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_topic')
        self.mox.StubOutWithMock(servicegroup.API, 'service_is_up')

        objects.ServiceList.get_by_topic(self.context,
                self.topic).AndReturn(services)
        self.servicegroup_api.service_is_up(service1).AndReturn(False)
        self.servicegroup_api.service_is_up(service2).AndReturn(True)

        self.mox.ReplayAll()
        result = self.driver.hosts_up(self.context, self.topic)
        self.assertEqual(result, ['host2'])
