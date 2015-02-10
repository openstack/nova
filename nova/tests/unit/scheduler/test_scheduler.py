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
from nova import db
from nova.scheduler import driver
from nova.scheduler import manager
from nova import servicegroup
from nova import test
from nova.tests.unit import fake_server_actions


class SchedulerManagerTestCase(test.NoDBTestCase):
    """Test case for scheduler manager."""

    manager_cls = manager.SchedulerManager
    driver_cls = driver.Scheduler
    driver_cls_name = 'nova.scheduler.driver.Scheduler'

    def setUp(self):
        super(SchedulerManagerTestCase, self).setUp()
        self.flags(scheduler_driver=self.driver_cls_name)
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
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(None, None, {})
            select_destinations.assert_called_once_with(None, None, {})


class SchedulerV3PassthroughTestCase(test.TestCase):
    def setUp(self):
        super(SchedulerV3PassthroughTestCase, self).setUp()
        self.manager = manager.SchedulerManager()
        self.proxy = manager._SchedulerManagerV3Proxy(self.manager)

    def test_select_destination(self):
        with mock.patch.object(self.manager, 'select_destinations'
                ) as select_destinations:
            self.proxy.select_destinations(None, None, {})
            select_destinations.assert_called_once_with(None, None, {})


class SchedulerTestCase(test.NoDBTestCase):
    """Test case for base scheduler driver class."""

    # So we can subclass this test and re-use tests if we need.
    driver_cls = driver.Scheduler

    def setUp(self):
        super(SchedulerTestCase, self).setUp()
        self.driver = self.driver_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.servicegroup_api = servicegroup.API()

    def test_hosts_up(self):
        service1 = {'host': 'host1'}
        service2 = {'host': 'host2'}
        services = [service1, service2]

        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        self.mox.StubOutWithMock(servicegroup.API, 'service_is_up')

        db.service_get_all_by_topic(self.context,
                self.topic).AndReturn(services)
        self.servicegroup_api.service_is_up(service1).AndReturn(False)
        self.servicegroup_api.service_is_up(service2).AndReturn(True)

        self.mox.ReplayAll()
        result = self.driver.hosts_up(self.context, self.topic)
        self.assertEqual(result, ['host2'])


class SchedulerDriverBaseTestCase(SchedulerTestCase):
    """Test cases for base scheduler driver class methods
       that will fail if the driver is changed.
    """

    def test_unimplemented_select_destinations(self):
        self.assertRaises(NotImplementedError,
                self.driver.select_destinations, self.context, {}, {})


class SchedulerInstanceGroupData(test.TestCase):

    driver_cls = driver.Scheduler

    def setUp(self):
        super(SchedulerInstanceGroupData, self).setUp()
        self.user_id = 'fake_user'
        self.project_id = 'fake_project'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.driver = self.driver_cls()

    def _get_default_values(self):
        return {'name': 'fake_name',
                'user_id': self.user_id,
                'project_id': self.project_id}

    def _create_instance_group(self, context, values, policies=None,
                               metadata=None, members=None):
        return db.instance_group_create(context, values, policies=policies,
                                        metadata=metadata, members=members)
