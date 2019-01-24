# Copyright (c) 2015 Ericsson AB
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

import mock

from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import affinity
from nova import test
from nova.tests.unit.scheduler import fakes


class SoftWeigherTestBase(test.NoDBTestCase):

    def setUp(self):
        super(SoftWeigherTestBase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = []

    def _get_weighed_host(self, hosts, policy):
        request_spec = objects.RequestSpec(
            instance_group=objects.InstanceGroup(
                policy=policy,
                members=['member1',
                         'member2',
                         'member3',
                         'member4',
                         'member5',
                         'member6',
                         'member7']))
        return self.weight_handler.get_weighed_objects(self.weighers,
                                                       hosts,
                                                       request_spec)[0]

    def _get_all_hosts(self):
        host_values = [
            ('host1', 'node1', {'instances': {
                'member1': mock.sentinel,
                'instance13': mock.sentinel
            }}),
            ('host2', 'node2', {'instances': {
                'member2': mock.sentinel,
                'member3': mock.sentinel,
                'member4': mock.sentinel,
                'member5': mock.sentinel,
                'instance14': mock.sentinel
            }}),
            ('host3', 'node3', {'instances': {
                'instance15': mock.sentinel
            }}),
            ('host4', 'node4', {'instances': {
                'member6': mock.sentinel,
                'member7': mock.sentinel,
                'instance16': mock.sentinel
            }})]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def _do_test(self, policy, expected_weight,
                 expected_host):
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list,
                                              policy)
        self.assertEqual(expected_weight, weighed_host.weight)
        if expected_host:
            self.assertEqual(expected_host, weighed_host.obj.host)


class SoftAffinityWeigherTestCase(SoftWeigherTestBase):

    def setUp(self):
        super(SoftAffinityWeigherTestCase, self).setUp()
        self.weighers = [affinity.ServerGroupSoftAffinityWeigher()]
        self.softaffin_weigher = affinity.ServerGroupSoftAffinityWeigher()

    def test_soft_affinity_weight_multiplier_by_default(self):
        self._do_test(policy='soft-affinity',
                      expected_weight=1.0,
                      expected_host='host2')

    def test_soft_affinity_weight_multiplier_zero_value(self):
        # We do not know the host, all have same weight.
        self.flags(soft_affinity_weight_multiplier=0.0,
                   group='filter_scheduler')
        self._do_test(policy='soft-affinity',
                      expected_weight=0.0,
                      expected_host=None)

    def test_soft_affinity_weight_multiplier_positive_value(self):
        self.flags(soft_affinity_weight_multiplier=2.0,
                   group='filter_scheduler')
        self._do_test(policy='soft-affinity',
                      expected_weight=2.0,
                      expected_host='host2')

    def test_soft_affinity_weight_multiplier(self):
        self.flags(soft_affinity_weight_multiplier=0.0,
                   group='filter_scheduler')
        host_attr = {'instances': {'instance1': mock.sentinel}}
        host1 = fakes.FakeHostState('fake-host', 'node', host_attr)
        # By default, return the weight_multiplier configuration directly
        self.assertEqual(0.0, self.softaffin_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'soft_affinity_weight_multiplier': '2'},
            )]
        # read the weight multiplier from metadata to override the config
        self.assertEqual(2.0, self.softaffin_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'soft_affinity_weight_multiplier': '2'},
            ),
            objects.Aggregate(
                id=2,
                name='foo',
                hosts=['fake-host'],
                metadata={'soft_affinity_weight_multiplier': '1.5'},
            )]
        # If the host is in multiple aggs and there are conflict weight values
        # in the metadata, we will use the min value among them
        self.assertEqual(1.5, self.softaffin_weigher.weight_multiplier(host1))

    def test_host_with_agg(self):
        self.flags(soft_affinity_weight_multiplier=0.0,
                   group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        aggs = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'soft_affinity_weight_multiplier': '1.5'},
            )]
        for h in hostinfo_list:
            h.aggregates = aggs

        weighed_host = self._get_weighed_host(hostinfo_list,
                                              'soft-affinity')
        self.assertEqual(1.5, weighed_host.weight)
        self.assertEqual('host2', weighed_host.obj.host)


class SoftAntiAffinityWeigherTestCase(SoftWeigherTestBase):

    def setUp(self):
        super(SoftAntiAffinityWeigherTestCase, self).setUp()
        self.weighers = [affinity.ServerGroupSoftAntiAffinityWeigher()]
        self.antiaffin_weigher = affinity.ServerGroupSoftAntiAffinityWeigher()

    def test_soft_anti_affinity_weight_multiplier_by_default(self):
        self._do_test(policy='soft-anti-affinity',
                      expected_weight=1.0,
                      expected_host='host3')

    def test_soft_anti_affinity_weight_multiplier_zero_value(self):
        # We do not know the host, all have same weight.
        self.flags(soft_anti_affinity_weight_multiplier=0.0,
                   group='filter_scheduler')
        self._do_test(policy='soft-anti-affinity',
                      expected_weight=0.0,
                      expected_host=None)

    def test_soft_anti_affinity_weight_multiplier_positive_value(self):
        self.flags(soft_anti_affinity_weight_multiplier=2.0,
                   group='filter_scheduler')
        self._do_test(policy='soft-anti-affinity',
                      expected_weight=2.0,
                      expected_host='host3')

    def test_soft_anti_affinity_weight_multiplier(self):
        self.flags(soft_anti_affinity_weight_multiplier=0.0,
                   group='filter_scheduler')
        host_attr = {'instances': {'instance1': mock.sentinel}}
        host1 = fakes.FakeHostState('fake-host', 'node', host_attr)
        # By default, return the weight_multiplier configuration directly
        self.assertEqual(0.0, self.antiaffin_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'soft_anti_affinity_weight_multiplier': '2'},
            )]
        # read the weight multiplier from metadata to override the config
        self.assertEqual(2.0, self.antiaffin_weigher.weight_multiplier(host1))

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'soft_anti_affinity_weight_multiplier': '2'},
            ),
            objects.Aggregate(
                id=2,
                name='foo',
                hosts=['fake-host'],
                metadata={'soft_anti_affinity_weight_multiplier': '1.5'},
            )]
        # If the host is in multiple aggs and there are conflict weight values
        # in the metadata, we will use the min value among them
        self.assertEqual(1.5, self.antiaffin_weigher.weight_multiplier(host1))

    def test_host_with_agg(self):
        self.flags(soft_anti_affinity_weight_multiplier=0.0,
                   group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        aggs = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['host1', 'host2', 'host3', 'host4'],
                metadata={'soft_anti_affinity_weight_multiplier': '1.5'},
            )]
        for h in hostinfo_list:
            h.aggregates = aggs

        weighed_host = self._get_weighed_host(hostinfo_list,
                                              'soft-anti-affinity')
        self.assertEqual(1.5, weighed_host.weight)
        self.assertEqual('host3', weighed_host.obj.host)
