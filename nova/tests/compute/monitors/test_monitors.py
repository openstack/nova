# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Tests for resource monitors."""

from nova.compute import monitors
from nova import test


class FakeResourceMonitor(monitors.ResourceMonitorBase):
    def get_metric_names(self):
        return ["foo.metric1", "foo.metric2"]

    def get_metrics(self):
        data = []
        data.append(self._populate('foo.metric1', '1000'))
        data.append(self._populate('foo.metric2', '99.999'))

        return data


class ResourceMonitorBaseTestCase(test.TestCase):
    def setUp(self):
        super(ResourceMonitorBaseTestCase, self).setUp()
        self.monitor = FakeResourceMonitor(None)

    def test_get_metric_names(self):
        names = self.monitor.get_metric_names()
        self.assertEqual(2, len(names))
        self.assertIn("foo.metric1", names)
        self.assertIn("foo.metric2", names)

    def test_get_metrics(self):
        metrics_raw = self.monitor.get_metrics()
        names = self.monitor.get_metric_names()
        metrics = {}
        for metric in metrics_raw:
            self.assertIn(metric['name'], names)
            metrics[metric['name']] = metric['value']

        self.assertEqual(metrics["foo.metric1"], '1000')
        self.assertEqual(metrics["foo.metric2"], '99.999')


class ResourceMonitorsTestCase(test.TestCase):
    """Test case for monitors."""

    def setUp(self):
        super(ResourceMonitorsTestCase, self).setUp()
        monitor_handler = monitors.ResourceMonitorHandler()
        classes = monitor_handler.get_matching_classes(
            ['nova.compute.monitors.all_monitors'])
        self.class_map = {}
        for cls in classes:
            self.class_map[cls.__name__] = cls

    def test_all_monitors(self):
        # Double check at least a couple of known monitors exist
        self.assertIn('ComputeDriverCPUMonitor', self.class_map)
