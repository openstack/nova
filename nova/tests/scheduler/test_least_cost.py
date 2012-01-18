# Copyright 2011 OpenStack LLC.
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
Tests For Least Cost functions.
"""
from nova import context
from nova.scheduler import least_cost
from nova import test
from nova.tests.scheduler import fakes


def offset(hostinfo, options):
    return hostinfo.free_ram_mb + 10000


def scale(hostinfo, options):
    return hostinfo.free_ram_mb * 2


class LeastCostTestCase(test.TestCase):
    def setUp(self):
        super(LeastCostTestCase, self).setUp()
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.host_manager = fakes.FakeHostManager()

    def tearDown(self):
        super(LeastCostTestCase, self).tearDown()

    def _get_all_hosts(self):
        ctxt = context.get_admin_context()
        fakes.mox_host_manager_db_calls(self.mox, ctxt)
        self.mox.ReplayAll()
        host_states = self.host_manager.get_all_host_states(ctxt,
                'compute').values()
        self.mox.VerifyAll()
        self.mox.ResetAll()
        return host_states

    def test_weighted_sum_happy_day(self):
        fn_tuples = [(1.0, offset), (1.0, scale)]
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # [offset, scale]=
        # [10512, 11024, 13072, 18192]
        # [1024,  2048, 6144, 16384]

        # adjusted [ 1.0 * x + 1.0 * y] =
        # [11536, 13072, 19216, 34576]

        # so, host1 should win:
        options = {}
        weighted_host = least_cost.weighted_sum(fn_tuples, hostinfo_list,
                options)
        self.assertEqual(weighted_host.weight, 11536)
        self.assertEqual(weighted_host.host_state.host, 'host1')

    def test_weighted_sum_single_function(self):
        fn_tuples = [(1.0, offset), ]
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=0
        # host2: free_ram_mb=1536
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # [offset, ]=
        # [10512, 11024, 13072, 18192]

        # so, host1 should win:
        options = {}
        weighted_host = least_cost.weighted_sum(fn_tuples, hostinfo_list,
                                                                    options)
        self.assertEqual(weighted_host.weight, 10512)
        self.assertEqual(weighted_host.host_state.host, 'host1')
