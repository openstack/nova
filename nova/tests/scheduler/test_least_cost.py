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
from nova.scheduler import least_cost
from nova.scheduler import zone_manager
from nova import test
from nova.tests.scheduler import fake_zone_manager


def offset(hostinfo):
    return hostinfo.free_ram_mb + 10000


def scale(hostinfo):
    return hostinfo.free_ram_mb * 2


class LeastCostTestCase(test.TestCase):
    def setUp(self):
        super(LeastCostTestCase, self).setUp()

        self.zone_manager = fake_zone_manager.FakeZoneManager()

    def tearDown(self):
        super(LeastCostTestCase, self).tearDown()

    def test_normalize_grid(self):
        raw = [
            [1, 2, 3, 4, 5],
            [10, 20, 30, 40, 50],
            [100, 200, 300, 400, 500],
        ]
        expected = [
            [.2, .4, .6, .8, 1.0],
            [.2, .4, .6, .8, 1.0],
            [.2, .4, .6, .8, 1.0],
        ]

        self.assertEquals(expected, least_cost.normalize_grid(raw))

        self.assertEquals([[]], least_cost.normalize_grid([]))
        self.assertEquals([[]], least_cost.normalize_grid([[]]))

    def test_weighted_sum_happy_day(self):
        fn_tuples = [(1.0, offset), (1.0, scale)]
        hostinfo_list = self.zone_manager.get_all_host_data(None).items()

        # host1: free_ram_mb=0
        # host2: free_ram_mb=1536
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # [offset, scale]=
        # [10000, 11536, 13072, 18192]
        # [0,  768, 1536, 4096]

        # normalized =
        # [ 0.55, 0.63, 0.72, 1.0]
        # [ 0.0, 0.19, 0.38, 1.0]

        # adjusted [ 1.0 * x + 1.0 * y] =
        # [0.55, 0.82, 1.1, 2.0]

        # so, host1 should win:
        weighted_host = least_cost.weighted_sum(hostinfo_list, fn_tuples)
        self.assertTrue(abs(weighted_host.weight - 0.55) < 0.01)
        self.assertEqual(weighted_host.host, 'host1')

    def test_weighted_sum_single_function(self):
        fn_tuples = [(1.0, offset), ]
        hostinfo_list = self.zone_manager.get_all_host_data(None).items()

        # host1: free_ram_mb=0
        # host2: free_ram_mb=1536
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # [offset, ]=
        # [10000, 11536, 13072, 18192]

        # normalized =
        # [ 0.55, 0.63, 0.72, 1.0]

        # so, host1 should win:
        weighted_host = least_cost.weighted_sum(hostinfo_list, fn_tuples)
        self.assertTrue(abs(weighted_host.weight - 0.55) < 0.01)
        self.assertEqual(weighted_host.host, 'host1')

    def test_get_cost_functions(self):
        fns = least_cost.get_cost_fns()
        self.assertEquals(len(fns), 1)
        weight, fn = fns[0]
        self.assertEquals(weight, 1.0)
        hostinfo = zone_manager.HostInfo('host', free_ram_mb=1000)
        self.assertEquals(1000, fn(hostinfo))
