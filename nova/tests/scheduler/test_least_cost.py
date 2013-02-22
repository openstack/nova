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
Tests For Least Cost functions.
"""

from oslo.config import cfg

from nova import context
from nova.scheduler import weights
from nova.scheduler.weights import least_cost
from nova import test
from nova.tests.scheduler import fakes

test_least_cost_opts = [
    cfg.FloatOpt('compute_fake_weigher1_weight',
             default=2.0,
             help='How much weight to give the fake_weigher1 function'),
    cfg.FloatOpt('compute_fake_weigher2_weight',
             default=1.0,
             help='How much weight to give the fake_weigher2 function'),
    ]

CONF = cfg.CONF
CONF.import_opt('least_cost_functions', 'nova.scheduler.weights.least_cost')
CONF.import_opt('compute_fill_first_cost_fn_weight',
        'nova.scheduler.weights.least_cost')
CONF.register_opts(test_least_cost_opts)


def compute_fake_weigher1(hostinfo, options):
    return hostinfo.free_ram_mb + 10000


def compute_fake_weigher2(hostinfo, options):
    return hostinfo.free_ram_mb * 2


class LeastCostTestCase(test.TestCase):
    def setUp(self):
        super(LeastCostTestCase, self).setUp()
        self.host_manager = fakes.FakeHostManager()
        self.weight_handler = weights.HostWeightHandler()

    def _get_weighed_host(self, hosts, weight_properties=None):
        weigher_classes = least_cost.get_least_cost_weighers()
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(weigher_classes,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        ctxt = context.get_admin_context()
        fakes.mox_host_manager_db_calls(self.mox, ctxt)
        self.mox.ReplayAll()
        host_states = self.host_manager.get_all_host_states(ctxt)
        self.mox.VerifyAll()
        self.mox.ResetAll()
        return host_states

    def test_default_of_spread_first(self):
        # Default modifier is -1.0, so it turns out that hosts with
        # the most free memory win
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # so, host1 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 8192)
        self.assertEqual(weighed_host.obj.host, 'host4')

    def test_filling_first(self):
        self.flags(compute_fill_first_cost_fn_weight=1.0)
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=-512
        # host2: free_ram_mb=-1024
        # host3: free_ram_mb=-3072
        # host4: free_ram_mb=-8192

        # so, host1 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, -512)
        self.assertEqual(weighed_host.obj.host, 'host1')

    def test_weighted_sum_provided_method(self):
        fns = ['nova.tests.scheduler.test_least_cost.compute_fake_weigher1',
               'nova.tests.scheduler.test_least_cost.compute_fake_weigher2']
        self.flags(least_cost_functions=fns)
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # [offset, scale]=
        # [10512, 11024, 13072, 18192]
        # [1024,  2048, 6144, 16384]

        # adjusted [ 2.0 * x + 1.0 * y] =
        # [22048, 24096, 32288, 52768]

        # so, host1 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 52768)
        self.assertEqual(weighed_host.obj.host, 'host4')

    def test_weighted_sum_single_function(self):
        fns = ['nova.tests.scheduler.test_least_cost.compute_fake_weigher1']
        self.flags(least_cost_functions=fns)
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=0
        # host2: free_ram_mb=1536
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # [offset, ]=
        # [10512, 11024, 13072, 18192]
        # adjusted [ 2.0 * x ]=
        # [21024, 22048, 26144, 36384]

        # so, host1 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 36384)
        self.assertEqual(weighed_host.obj.host, 'host4')
