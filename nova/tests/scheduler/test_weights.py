# Copyright 2011-2012 OpenStack Foundation
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
Tests For Scheduler weights.
"""

from nova import context
from nova.scheduler import weights
from nova import test
from nova.tests import matchers
from nova.tests.scheduler import fakes


class TestWeighedHost(test.NoDBTestCase):
    def test_dict_conversion(self):
        host_state = fakes.FakeHostState('somehost', None, {})
        host = weights.WeighedHost(host_state, 'someweight')
        expected = {'weight': 'someweight',
                    'host': 'somehost'}
        self.assertThat(host.to_dict(), matchers.DictMatches(expected))

    def test_all_weighers(self):
        classes = weights.all_weighers()
        class_names = [cls.__name__ for cls in classes]
        self.assertEqual(len(classes), 1)
        self.assertIn('RAMWeigher', class_names)


class RamWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(RamWeigherTestCase, self).setUp()
        self.host_manager = fakes.FakeHostManager()
        self.weight_handler = weights.HostWeightHandler()
        self.weight_classes = self.weight_handler.get_matching_classes(
                ['nova.scheduler.weights.ram.RAMWeigher'])

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(self.weight_classes,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        ctxt = context.get_admin_context()
        fakes.mox_host_manager_db_calls(self.mox, ctxt)
        self.mox.ReplayAll()
        host_states = self.host_manager.get_all_host_states(ctxt)
        self.mox.VerifyAll()
        self.mox.ResetAll()
        return host_states

    def test_default_of_spreading_first(self):
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 8192)
        self.assertEqual(weighed_host.obj.host, 'host4')

    def test_ram_filter_multiplier1(self):
        self.flags(ram_weight_multiplier=-1.0)
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=-512
        # host2: free_ram_mb=-1024
        # host3: free_ram_mb=-3072
        # host4: free_ram_mb=-8192

        # so, host1 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, -512)
        self.assertEqual(weighed_host.obj.host, 'host1')

    def test_ram_filter_multiplier2(self):
        self.flags(ram_weight_multiplier=2.0)
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512 * 2
        # host2: free_ram_mb=1024 * 2
        # host3: free_ram_mb=3072 * 2
        # host4: free_ram_mb=8192 * 2

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 8192 * 2)
        self.assertEqual(weighed_host.obj.host, 'host4')
