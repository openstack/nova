# Copyright (c) 2016 OpenStack Foundation
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

from nova.tests.unit.virt.xenapi.plugins import plugin_test


class BandwidthTestCase(plugin_test.PluginTestBase):
    def setUp(self):
        super(BandwidthTestCase, self).setUp()
        self.pluginlib = self.load_plugin("pluginlib_nova.py")

        # Prevent any logging to syslog
        self.mock_patch_object(self.pluginlib,
                               'configure_logging')

        self.bandwidth = self.load_plugin("bandwidth")

    def test_get_bandwitdth_from_proc(self):
        fake_data = ['Inter-|   Receive  |  Transmit',
        'if|bw_in i1 i2 i3 i4 i5 i6 i7|bw_out o1 o2 o3 o4 o5 o6 o7',
        'xenbr1: 1 0 0 0 0 0 0 0 11 0 0 0 0 0 0 0',
        'vif2.0: 2 0 0 0 0 0 0 0 12 0 0 0 0 0 0 0',
        'vif2.1: 3 0 0 0 0 0 0 0 13 0 0 0 0 0 0 0\n']
        expect_devmap = {'2': {'1': {'bw_in': 13, 'bw_out': 3},
                               '0': {'bw_in': 12, 'bw_out': 2}
                              }
                        }

        mock_read_proc_net = self.mock_patch_object(
            self.bandwidth,
            '_read_proc_net',
            return_val=fake_data)

        devmap = self.bandwidth._get_bandwitdth_from_proc()

        self.assertTrue(mock_read_proc_net.called)
        self.assertEqual(devmap, expect_devmap)
