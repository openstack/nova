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

from oslo_utils import timeutils

from nova.compute import monitors
from nova.compute.monitors import base
from nova.objects import fields
from nova import test


class CPUMonitor1(base.MonitorBase):

    NOW_TS = timeutils.utcnow()

    def __init__(self, *args):
        super(CPUMonitor1, self).__init__(*args)
        self.source = 'CPUMonitor1'

    def get_metric_names(self):
        return set([
            fields.MonitorMetricType.CPU_FREQUENCY
        ])

    def get_metric(self, name):
        return 100, CPUMonitor1.NOW_TS


class CPUMonitor2(base.MonitorBase):

    def get_metric_names(self):
        return set([
            fields.MonitorMetricType.CPU_FREQUENCY
        ])

    def get_metric(self, name):
        # This should never be called since the CPU metrics overlap
        # with the ones in the CPUMonitor1.
        pass


class ResourceMonitorsTestCase(test.NoDBTestCase):
    """Test case for monitors."""

    def setUp(self):
        super(ResourceMonitorsTestCase, self).setUp()
        self.monitor_handler = monitors.ResourceMonitorHandler()
        fake_monitors = [
            'nova.tests.unit.compute.monitors.test_monitors.CPUMonitor1',
            'nova.tests.unit.compute.monitors.test_monitors.CPUMonitor2']
        self.flags(compute_available_monitors=fake_monitors)

    def test_choose_monitors_not_found(self):
        self.flags(compute_monitors=['CPUMonitor1', 'CPUMonitorb'])
        monitor_classes = self.monitor_handler.choose_monitors(self)
        self.assertEqual(len(monitor_classes), 1)

    def test_choose_monitors_bad(self):
        self.flags(compute_monitors=['CPUMonitor1', 'CPUMonitor2'])
        monitor_classes = self.monitor_handler.choose_monitors(self)
        self.assertEqual(len(monitor_classes), 1)

    def test_choose_monitors_none(self):
        self.flags(compute_monitors=[])
        monitor_classes = self.monitor_handler.choose_monitors(self)
        self.assertEqual(len(monitor_classes), 0)
