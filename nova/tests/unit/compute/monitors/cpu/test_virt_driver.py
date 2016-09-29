# Copyright 2013 Intel Corporation
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

"""Tests for Compute Driver CPU resource monitor."""

import mock

from nova.compute.monitors.cpu import virt_driver
from nova import objects
from nova import test


class FakeDriver(object):
    def get_host_cpu_stats(self):
        return {'kernel': 5664160000000,
                'idle': 1592705190000000,
                'frequency': 800,
                'user': 26728850000000,
                'iowait': 6121490000000}


class FakeResourceTracker(object):
    driver = FakeDriver()


class VirtDriverCPUMonitorTestCase(test.NoDBTestCase):

    def test_get_metric_names(self):
        monitor = virt_driver.Monitor(FakeResourceTracker())
        names = monitor.get_metric_names()
        self.assertEqual(10, len(names))
        self.assertIn("cpu.frequency", names)
        self.assertIn("cpu.user.time", names)
        self.assertIn("cpu.kernel.time", names)
        self.assertIn("cpu.idle.time", names)
        self.assertIn("cpu.iowait.time", names)
        self.assertIn("cpu.user.percent", names)
        self.assertIn("cpu.kernel.percent", names)
        self.assertIn("cpu.idle.percent", names)
        self.assertIn("cpu.iowait.percent", names)
        self.assertIn("cpu.percent", names)

    def test_populate_metrics(self):
        metrics = objects.MonitorMetricList()
        monitor = virt_driver.Monitor(FakeResourceTracker())
        monitor.populate_metrics(metrics)
        names = monitor.get_metric_names()
        for metric in metrics.objects:
            self.assertIn(metric.name, names)

        # Some conversion to a dict to ease testing...
        metrics = {m.name: m.value for m in metrics.objects}
        self.assertEqual(metrics["cpu.frequency"], 800)
        self.assertEqual(metrics["cpu.user.time"], 26728850000000)
        self.assertEqual(metrics["cpu.kernel.time"], 5664160000000)
        self.assertEqual(metrics["cpu.idle.time"], 1592705190000000)
        self.assertEqual(metrics["cpu.iowait.time"], 6121490000000)
        self.assertEqual(metrics["cpu.user.percent"], 1)
        self.assertEqual(metrics["cpu.kernel.percent"], 0)
        self.assertEqual(metrics["cpu.idle.percent"], 97)
        self.assertEqual(metrics["cpu.iowait.percent"], 0)
        self.assertEqual(metrics["cpu.percent"], 2)

    def test_ensure_single_sampling(self):
        # We want to ensure that the virt driver's get_host_cpu_stats()
        # is only ever called once, otherwise values for monitor metrics
        # might be illogical -- e.g. pct cpu times for user/system/idle
        # may add up to more than 100.
        metrics = objects.MonitorMetricList()
        monitor = virt_driver.Monitor(FakeResourceTracker())

        with mock.patch.object(FakeDriver, 'get_host_cpu_stats') as mocked:
            monitor.populate_metrics(metrics)
            mocked.assert_called_once_with()
