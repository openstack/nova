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
import testtools

from nova import context
from nova import objects
from nova.scheduler import caching_scheduler
from nova.scheduler import chance
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import ironic_host_manager
from nova.scheduler import manager
from nova import servicegroup
from nova import test
from nova.tests.unit import fake_server_actions
from nova.tests.unit.scheduler import fakes


class SchedulerManagerInitTestCase(test.NoDBTestCase):
    """Test case for scheduler manager initiation."""
    manager_cls = manager.SchedulerManager

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_default_schedulerdriver(self,
                                                mock_init_agg,
                                                mock_init_inst):
        driver = self.manager_cls().driver
        self.assertIsInstance(driver, filter_scheduler.FilterScheduler)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_chance_schedulerdriver(self,
                                               mock_init_agg,
                                               mock_init_inst):
        self.flags(driver='chance_scheduler', group='scheduler')
        driver = self.manager_cls().driver
        self.assertIsInstance(driver, chance.ChanceScheduler)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_caching_schedulerdriver(self,
                                                mock_init_agg,
                                                mock_init_inst):
        self.flags(driver='caching_scheduler', group='scheduler')
        driver = self.manager_cls().driver
        self.assertIsInstance(driver, caching_scheduler.CachingScheduler)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_nonexist_schedulerdriver(self,
                                           mock_init_agg,
                                           mock_init_inst):
        with testtools.ExpectedException(ValueError):
            self.flags(driver='nonexist_scheduler', group='scheduler')


class SchedulerManagerTestCase(test.NoDBTestCase):
    """Test case for scheduler manager."""

    manager_cls = manager.SchedulerManager
    driver_cls = fakes.FakeScheduler
    driver_plugin_name = 'fake_scheduler'

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(SchedulerManagerTestCase, self).setUp()
        self.flags(driver=self.driver_plugin_name, group='scheduler')
        with mock.patch.object(host_manager.HostManager, '_init_aggregates'):
            self.manager = self.manager_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.fake_args = (1, 2, 3)
        self.fake_kwargs = {'cat': 'meow', 'dog': 'woof'}
        fake_server_actions.stub_out_action_events(self)

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

    @mock.patch('nova.objects.host_mapping.discover_hosts')
    def test_discover_hosts(self, mock_discover):
        cm1 = objects.CellMapping(name='cell1')
        cm2 = objects.CellMapping(name='cell2')
        mock_discover.return_value = [objects.HostMapping(host='a',
                                                          cell_mapping=cm1),
                                      objects.HostMapping(host='b',
                                                          cell_mapping=cm2)]
        self.manager._discover_hosts_in_cells(mock.sentinel.context)


class SchedulerInitTestCase(test.NoDBTestCase):
    """Test case for base scheduler driver initiation."""

    driver_cls = fakes.FakeScheduler

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_default_hostmanager(self,
                                            mock_init_agg,
                                            mock_init_inst):
        manager = self.driver_cls().host_manager
        self.assertIsInstance(manager, host_manager.HostManager)

    @mock.patch.object(ironic_host_manager.IronicHostManager,
                       '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_ironic_hostmanager(self,
                                           mock_init_agg,
                                           mock_init_inst):
        self.flags(host_manager='ironic_host_manager', group='scheduler')
        manager = self.driver_cls().host_manager
        self.assertIsInstance(manager, ironic_host_manager.IronicHostManager)


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

    @mock.patch('nova.objects.ServiceList.get_by_topic')
    @mock.patch('nova.servicegroup.API.service_is_up')
    def test_hosts_up(self, mock_service_is_up, mock_get_by_topic):
        service1 = objects.Service(host='host1')
        service2 = objects.Service(host='host2')
        services = objects.ServiceList(objects=[service1, service2])

        mock_get_by_topic.return_value = services
        mock_service_is_up.side_effect = [False, True]

        result = self.driver.hosts_up(self.context, self.topic)
        self.assertEqual(result, ['host2'])

        mock_get_by_topic.assert_called_once_with(self.context, self.topic)
        calls = [mock.call(service1), mock.call(service2)]
        self.assertEqual(calls, mock_service_is_up.call_args_list)
