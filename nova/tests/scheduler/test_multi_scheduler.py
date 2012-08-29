# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 OpenStack LLC
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
Tests For Multi Scheduler
"""

from nova.scheduler import driver
from nova.scheduler import multi
from nova.tests.scheduler import test_scheduler


class FakeComputeScheduler(driver.Scheduler):
    is_fake_compute = True

    def __init__(self):
        super(FakeComputeScheduler, self).__init__()
        self.is_update_caps_called = False

    def schedule_theoretical(self, *args, **kwargs):
        pass


class FakeVolumeScheduler(driver.Scheduler):
    is_fake_volume = True

    def __init__(self):
        super(FakeVolumeScheduler, self).__init__()
        self.is_update_caps_called = False


class FakeDefaultScheduler(driver.Scheduler):
    is_fake_default = True

    def __init__(self):
        super(FakeDefaultScheduler, self).__init__()
        self.is_update_caps_called = False


class MultiDriverTestCase(test_scheduler.SchedulerTestCase):
    """Test case for multi driver"""

    driver_cls = multi.MultiScheduler

    def setUp(self):
        super(MultiDriverTestCase, self).setUp()
        base_name = 'nova.tests.scheduler.test_multi_scheduler.%s'
        compute_cls_name = base_name % 'FakeComputeScheduler'
        volume_cls_name = base_name % 'FakeVolumeScheduler'
        default_cls_name = base_name % 'FakeDefaultScheduler'
        self.flags(compute_scheduler_driver=compute_cls_name,
                volume_scheduler_driver=volume_cls_name,
                default_scheduler_driver=default_cls_name)
        self._manager = multi.MultiScheduler()

    def test_drivers_inited(self):
        mgr = self._manager
        self.assertEqual(len(mgr.drivers), 3)
        self.assertTrue(mgr.drivers['compute'].is_fake_compute)
        self.assertTrue(mgr.drivers['volume'].is_fake_volume)
        self.assertTrue(mgr.drivers['default'].is_fake_default)

    def test_update_service_capabilities(self):
        def fake_update_service_capabilities(self, service, host, caps):
            self.is_update_caps_called = True

        mgr = self._manager
        self.stubs.Set(driver.Scheduler,
                       'update_service_capabilities',
                       fake_update_service_capabilities)
        self.assertFalse(mgr.drivers['compute'].is_update_caps_called)
        self.assertFalse(mgr.drivers['volume'].is_update_caps_called)
        mgr.update_service_capabilities('foo_svc', 'foo_host', 'foo_caps')
        self.assertTrue(mgr.drivers['compute'].is_update_caps_called)
        self.assertTrue(mgr.drivers['volume'].is_update_caps_called)


class SimpleSchedulerTestCase(MultiDriverTestCase):
    """Test case for simple driver."""

    driver_cls = multi.MultiScheduler

    def setUp(self):
        super(SimpleSchedulerTestCase, self).setUp()
        base_name = 'nova.tests.scheduler.test_multi_scheduler.%s'
        compute_cls_name = base_name % 'FakeComputeScheduler'
        volume_cls_name = 'nova.scheduler.simple.SimpleScheduler'
        default_cls_name = base_name % 'FakeDefaultScheduler'
        self.flags(compute_scheduler_driver=compute_cls_name,
                volume_scheduler_driver=volume_cls_name,
                default_scheduler_driver=default_cls_name)
        self._manager = multi.MultiScheduler()

    def test_update_service_capabilities(self):
        def fake_update_service_capabilities(self, service, host, caps):
            self.is_update_caps_called = True

        mgr = self._manager
        self.stubs.Set(driver.Scheduler,
                       'update_service_capabilities',
                       fake_update_service_capabilities)
        self.assertFalse(mgr.drivers['compute'].is_update_caps_called)
        mgr.update_service_capabilities('foo_svc', 'foo_host', 'foo_caps')
        self.assertTrue(mgr.drivers['compute'].is_update_caps_called)
        self.assertTrue(mgr.drivers['volume'].is_update_caps_called)

    def test_drivers_inited(self):
        mgr = self._manager
        self.assertEqual(len(mgr.drivers), 3)
        self.assertTrue(mgr.drivers['compute'].is_fake_compute)
        self.assertTrue(mgr.drivers['volume'] is not None)
        self.assertTrue(mgr.drivers['default'].is_fake_default)
