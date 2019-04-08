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

import mock

from nova.compute import monitors
from nova import test


class MonitorsTestCase(test.NoDBTestCase):
    """Test case for monitors."""

    @mock.patch('stevedore.enabled.EnabledExtensionManager')
    def test_check_enabled_monitor(self, _mock_ext_manager):
        class FakeExt(object):
            def __init__(self, ept, name):
                self.entry_point_target = ept
                self.name = name

        # We check to ensure only one CPU monitor is loaded...
        self.flags(compute_monitors=['mon1', 'mon2'])
        handler = monitors.MonitorHandler(None)
        ext_cpu_mon1 = FakeExt('nova.compute.monitors.cpu.virt_driver:Monitor',
                               'mon1')
        ext_cpu_mon2 = FakeExt('nova.compute.monitors.cpu.virt_driver:Monitor',
                               'mon2')
        self.assertTrue(handler.check_enabled_monitor(ext_cpu_mon1))
        self.assertFalse(handler.check_enabled_monitor(ext_cpu_mon2))

        # We check to ensure that the auto-prefixing of the CPU
        # namespace is handled properly...
        self.flags(compute_monitors=['cpu.mon1', 'mon2'])
        handler = monitors.MonitorHandler(None)
        ext_cpu_mon1 = FakeExt('nova.compute.monitors.cpu.virt_driver:Monitor',
                               'mon1')
        ext_cpu_mon2 = FakeExt('nova.compute.monitors.cpu.virt_driver:Monitor',
                               'mon2')
        self.assertTrue(handler.check_enabled_monitor(ext_cpu_mon1))
        self.assertFalse(handler.check_enabled_monitor(ext_cpu_mon2))

        # Run the check but with no monitors enabled to make sure we don't log.
        self.flags(compute_monitors=[])
        handler = monitors.MonitorHandler(None)
        ext_cpu_mon1 = FakeExt('nova.compute.monitors.cpu.virt_driver:Monitor',
                               'mon1')
        with mock.patch.object(monitors.LOG, 'warning') as mock_warning:
            self.assertFalse(handler.check_enabled_monitor(ext_cpu_mon1))
        mock_warning.assert_not_called()
