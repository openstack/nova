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
from mox3 import mox
from oslo.config import cfg

from nova.compute import api as compute_api
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova import rpc
from nova.scheduler import driver
from nova.scheduler import manager
from nova import servicegroup
from nova import test
from nova.tests.unit import fake_server_actions
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit.objects import test_instance_fault
from nova.tests.unit.scheduler import fakes

CONF = cfg.CONF


class SchedulerManagerTestCase(test.NoDBTestCase):
    """Test case for scheduler manager."""

    manager_cls = manager.SchedulerManager
    driver_cls = driver.Scheduler
    driver_cls_name = 'nova.scheduler.driver.Scheduler'

    def setUp(self):
        super(SchedulerManagerTestCase, self).setUp()
        self.flags(scheduler_driver=self.driver_cls_name)
        self.stubs.Set(compute_api, 'API', fakes.FakeComputeAPI)
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

    def _mox_schedule_method_helper(self, method_name):
        # Make sure the method exists that we're going to test call
        def stub_method(*args, **kwargs):
            pass

        setattr(self.manager.driver, method_name, stub_method)

        self.mox.StubOutWithMock(self.manager.driver,
                method_name)

    def test_select_destination(self):
        with mock.patch.object(self.manager, 'select_destinations'
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
        self.stubs.Set(compute_api, 'API', fakes.FakeComputeAPI)

        def fake_show(meh, context, id, **kwargs):
            if id:
                return {'id': id, 'min_disk': None, 'min_ram': None,
                        'name': 'fake_name',
                        'status': 'active',
                        'properties': {'kernel_id': 'fake_kernel_id',
                                       'ramdisk_id': 'fake_ramdisk_id',
                                       'something_else': 'meow'}}
            else:
                raise exception.ImageNotFound(image_id=id)

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)
        self.image_service = glance.get_default_image_service()

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

    def test_handle_schedule_error_adds_instance_fault(self):
        instance = {'uuid': 'fake-uuid'}
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'instance_fault_create')
        db.instance_update_and_get_original(self.context, instance['uuid'],
                                            mox.IgnoreArg()).AndReturn(
                                                (None, instance))
        db.instance_fault_create(self.context, mox.IgnoreArg()).AndReturn(
            test_instance_fault.fake_faults['fake-uuid'][0])
        self.mox.StubOutWithMock(rpc, 'get_notifier')
        notifier = self.mox.CreateMockAnything()
        rpc.get_notifier('scheduler').AndReturn(notifier)
        notifier.error(self.context, 'scheduler.run_instance', mox.IgnoreArg())
        self.mox.ReplayAll()

        driver.handle_schedule_error(self.context,
                                     exception.NoValidHost('test'),
                                     instance['uuid'], {})


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
