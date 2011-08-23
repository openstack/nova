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
import copy

from nova import test
from nova.scheduler import least_cost
from nova.tests.scheduler import test_abstract_scheduler

MB = 1024 * 1024


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
            FakeHost(3, 512 * MB, 100),
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


class LeastCostSchedulerTestCase(test.TestCase):
    def setUp(self):
        super(LeastCostSchedulerTestCase, self).setUp()

        class FakeZoneManager:
            pass

        zone_manager = FakeZoneManager()

        states = test_abstract_scheduler.fake_zone_manager_service_states(
            num_hosts=10)
        zone_manager.service_states = states

        self.sched = least_cost.LeastCostScheduler()
        self.sched.zone_manager = zone_manager

    def tearDown(self):
        super(LeastCostSchedulerTestCase, self).tearDown()

    def assertWeights(self, expected, num, request_spec, hosts):
        weighted = self.sched.weigh_hosts("compute", request_spec, hosts)
        self.assertDictListMatch(weighted, expected, approx_equal=True)

    def test_no_hosts(self):
        num = 1
        request_spec = {}
        hosts = []

        expected = []
        self.assertWeights(expected, num, request_spec, hosts)

    def test_noop_cost_fn(self):
        self.flags(least_cost_scheduler_cost_functions=[
                'nova.scheduler.least_cost.noop_cost_fn'],
                noop_cost_fn_weight=1)

        num = 1
        request_spec = {}
        hosts = self.sched.filter_hosts(num, request_spec)

        expected = [dict(weight=1, hostname=hostname)
                    for hostname, caps in hosts]
        self.assertWeights(expected, num, request_spec, hosts)

    def test_cost_fn_weights(self):
        self.flags(least_cost_scheduler_cost_functions=[
                'nova.scheduler.least_cost.noop_cost_fn'],
                noop_cost_fn_weight=2)

        num = 1
        request_spec = {}
        hosts = self.sched.filter_hosts(num, request_spec)

        expected = [dict(weight=2, hostname=hostname)
                    for hostname, caps in hosts]
        self.assertWeights(expected, num, request_spec, hosts)

    def test_compute_fill_first_cost_fn(self):
        self.flags(least_cost_scheduler_cost_functions=[
                'nova.scheduler.least_cost.compute_fill_first_cost_fn'],
                compute_fill_first_cost_fn_weight=1)
        num = 1
        instance_type = {'memory_mb': 1024}
        request_spec = {'instance_type': instance_type}
        svc_states = self.sched.zone_manager.service_states.iteritems()
        all_hosts = [(host, services["compute"])
                for host, services in svc_states
                if "compute" in services]
        hosts = self.sched.filter_hosts('compute', request_spec, all_hosts)

        expected = []
        for idx, (hostname, services) in enumerate(hosts):
            caps = copy.deepcopy(services["compute"])
            # Costs are normalized so over 10 hosts, each host with increasing
            # free ram will cost 1/N more. Since the lowest cost host has some
            # free ram, we add in the 1/N for the base_cost
            weight = 0.1 + (0.1 * idx)
            wtd_dict = dict(hostname=hostname, weight=weight,
                    capabilities=caps)
            expected.append(wtd_dict)

        self.assertWeights(expected, num, request_spec, hosts)
