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
Tests For Least Cost Scheduler
"""

from nova import flags
from nova import test
from nova.scheduler import least_cost

MB = 1024 * 1024
FLAGS = flags.FLAGS


class FakeHost(object):
    def __init__(self, host_id, free_ram, io):
        self.id = host_id
        self.free_ram = free_ram
        self.io = io


class WeightedSumTestCase(test.TestCase):
    def test_empty_domain(self):
        domain = []
        weighted_fns = []
        result = least_cost.weighted_sum(domain, weighted_fns)
        expected = []
        self.assertEqual(expected, result)

    def test_basic_costing(self):
        hosts = [
            FakeHost(1, 512 * MB, 100),
            FakeHost(2, 256 * MB, 400),
            FakeHost(3, 512 * MB, 100)
        ]

        weighted_fns = [
            (1, lambda h: h.free_ram),  # Fill-first, free_ram is a *cost*
            (2, lambda h: h.io),  # Avoid high I/O
        ]

        costs = least_cost.weighted_sum(
            domain=hosts, weighted_fns=weighted_fns)

        # Each 256 MB unit of free-ram contributes 0.5 points by way of:
        #   cost = weight * (score/max_score) = 1 * (256/512) = 0.5
        # Each 100 iops of IO adds 0.5 points by way of:
        #   cost = 2 * (100/400) = 2 * 0.25 = 0.5
        expected = [1.5, 2.5, 1.5]
        self.assertEqual(expected, costs)


# TODO(sirp): unify this with test_host_filter tests? possibility of sharing
# test setup code
class FakeZoneManager:
    pass


class LeastCostSchedulerTestCase(test.TestCase):
    def _host_caps(self, multiplier):
        # Returns host capabilities in the following way:
        # host1 = memory:free 10 (100max)
        #         disk:available 100 (1000max)
        # hostN = memory:free 10 + 10N
        #         disk:available 100 + 100N
        # in other words: hostN has more resources than host0
        # which means ... don't go above 10 hosts.
        return {'host_name-description': 'XenServer %s' % multiplier,
                'host_hostname': 'xs-%s' % multiplier,
                'host_memory_total': 100,
                'host_memory_overhead': 10,
                'host_memory_free': 10 + multiplier * 10,
                'host_memory_free-computed': 10 + multiplier * 10,
                'host_other-config': {},
                'host_ip_address': '192.168.1.%d' % (100 + multiplier),
                'host_cpu_info': {},
                'disk_available': 100 + multiplier * 100,
                'disk_total': 1000,
                'disk_used': 0,
                'host_uuid': 'xxx-%d' % multiplier,
                'host_name-label': 'xs-%s' % multiplier}

    def setUp(self):
        super(LeastCostSchedulerTestCase, self).setUp()
        #self.old_flag = FLAGS.default_host_filter_driver
        #FLAGS.default_host_filter_driver = \
        #                    'nova.scheduler.host_filter.AllHostsFilter'
        self.instance_type = dict(name='tiny',
                memory_mb=50,
                vcpus=10,
                local_gb=500,
                flavorid=1,
                swap=500,
                rxtx_quota=30000,
                rxtx_cap=200)

        zone_manager = FakeZoneManager()
        states = {}
        for x in xrange(10):
            states['host%02d' % (x + 1)] = {'compute': self._host_caps(x)}
        zone_manager.service_states = states

        self.sched = least_cost.LeastCostScheduler()
        self.sched.zone_manager = zone_manager

    def tearDown(self):
        #FLAGS.default_host_filter_driver = self.old_flag
        super(LeastCostSchedulerTestCase, self).tearDown()

    def assertWeights(self, expected, num, request_spec, hosts):
        weighted = self.sched.weigh_hosts(num, request_spec, hosts)
        self.assertDictListMatch(weighted, expected, approx_equal=True)

    def test_no_hosts(self):
        num = 1
        request_spec = {}
        hosts = []

        expected = []
        self.assertWeights(expected, num, request_spec, hosts)

    def test_noop_cost_fn(self):
        FLAGS.least_cost_scheduler_cost_functions = [
            'nova.scheduler.least_cost.noop_cost_fn'
        ]
        FLAGS.noop_cost_fn_weight = 1

        num = 1
        request_spec = {}
        hosts = self.sched.filter_hosts(num, request_spec)

        expected = [dict(weight=1, hostname=hostname)
                    for hostname, caps in hosts]
        self.assertWeights(expected, num, request_spec, hosts)

    def test_cost_fn_weights(self):
        FLAGS.least_cost_scheduler_cost_functions = [
            'nova.scheduler.least_cost.noop_cost_fn'
        ]
        FLAGS.noop_cost_fn_weight = 2

        num = 1
        request_spec = {}
        hosts = self.sched.filter_hosts(num, request_spec)

        expected = [dict(weight=2, hostname=hostname)
                    for hostname, caps in hosts]
        self.assertWeights(expected, num, request_spec, hosts)

    def test_fill_first_cost_fn(self):
        FLAGS.least_cost_scheduler_cost_functions = [
            'nova.scheduler.least_cost.fill_first_cost_fn'
        ]
        FLAGS.fill_first_cost_fn_weight = 1

        num = 1
        request_spec = {}
        hosts = self.sched.filter_hosts(num, request_spec)

        expected = []
        for idx, (hostname, caps) in enumerate(hosts):
            # Costs are normalized so over 10 hosts, each host with increasing
            # free ram will cost 1/N more. Since the lowest cost host has some
            # free ram, we add in the 1/N for the base_cost
            weight = 0.1 + (0.1 * idx)
            weight_dict = dict(weight=weight, hostname=hostname)
            expected.append(weight_dict)

        self.assertWeights(expected, num, request_spec, hosts)
