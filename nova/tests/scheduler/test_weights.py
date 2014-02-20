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
from nova import exception
from nova.openstack.common.fixture import mockpatch
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
        self.assertEqual(len(classes), 2)
        self.assertIn('RAMWeigher', class_names)
        self.assertIn('MetricsWeigher', class_names)


class RamWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(RamWeigherTestCase, self).setUp()
        self.useFixture(mockpatch.Patch(
            'nova.db.compute_node_get_all',
             return_value=fakes.COMPUTE_NODES))
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
        return self.host_manager.get_all_host_states(ctxt)

    def test_default_of_spreading_first(self):
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 1.0)
        self.assertEqual(weighed_host.obj.host, 'host4')

    def test_ram_filter_multiplier1(self):
        self.flags(ram_weight_multiplier=0.0)
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # We do not know the host, all have same weight.
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 0.0)

    def test_ram_filter_multiplier2(self):
        self.flags(ram_weight_multiplier=2.0)
        hostinfo_list = self._get_all_hosts()

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 1.0 * 2)
        self.assertEqual(weighed_host.obj.host, 'host4')

    def test_ram_filter_negative(self):
        self.flags(ram_weight_multiplier=1.0)
        hostinfo_list = self._get_all_hosts()
        host_attr = {'id': 100, 'memory_mb': 8192, 'free_ram_mb': -512}
        host_state = fakes.FakeHostState('negative', 'negative', host_attr)
        hostinfo_list = list(hostinfo_list) + [host_state]

        # host1: free_ram_mb=512
        # host2: free_ram_mb=1024
        # host3: free_ram_mb=3072
        # host4: free_ram_mb=8192
        # negativehost: free_ram_mb=-512

        # so, host4 should win
        weights = self.weight_handler.get_weighed_objects(self.weight_classes,
                                                          hostinfo_list, {})

        weighed_host = weights[0]
        self.assertEqual(weighed_host.weight, 1)
        self.assertEqual(weighed_host.obj.host, "host4")

        # and negativehost should lose
        weighed_host = weights[-1]
        self.assertEqual(weighed_host.weight, 0)
        self.assertEqual(weighed_host.obj.host, "negative")


class MetricsWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(MetricsWeigherTestCase, self).setUp()
        self.useFixture(mockpatch.Patch(
            'nova.db.compute_node_get_all',
             return_value=fakes.COMPUTE_NODES_METRICS))
        self.host_manager = fakes.FakeHostManager()
        self.weight_handler = weights.HostWeightHandler()
        self.weight_classes = self.weight_handler.get_matching_classes(
                ['nova.scheduler.weights.metrics.MetricsWeigher'])

    def _get_weighed_host(self, hosts, setting, weight_properties=None):
        if not weight_properties:
            weight_properties = {}
        self.flags(weight_setting=setting, group='metrics')
        return self.weight_handler.get_weighed_objects(self.weight_classes,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        ctxt = context.get_admin_context()
        return self.host_manager.get_all_host_states(ctxt)

    def _do_test(self, settings, expected_weight, expected_host):
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list, settings)
        self.assertEqual(weighed_host.weight, expected_weight)
        self.assertEqual(weighed_host.obj.host, expected_host)

    def test_single_resource(self):
        # host1: foo=512
        # host2: foo=1024
        # host3: foo=3072
        # host4: foo=8192
        # so, host4 should win:
        setting = ['foo=1']
        self._do_test(setting, 1.0, 'host4')

    def test_multiple_resource(self):
        # host1: foo=512,  bar=1
        # host2: foo=1024, bar=2
        # host3: foo=3072, bar=1
        # host4: foo=8192, bar=0
        # so, host2 should win:
        setting = ['foo=0.0001', 'bar=1']
        self._do_test(setting, 1.0, 'host2')

    def test_single_resourcenegtive_ratio(self):
        # host1: foo=512
        # host2: foo=1024
        # host3: foo=3072
        # host4: foo=8192
        # so, host1 should win:
        setting = ['foo=-1']
        self._do_test(setting, 1.0, 'host1')

    def test_multiple_resource_missing_ratio(self):
        # host1: foo=512,  bar=1
        # host2: foo=1024, bar=2
        # host3: foo=3072, bar=1
        # host4: foo=8192, bar=0
        # so, host4 should win:
        setting = ['foo=0.0001', 'bar']
        self._do_test(setting, 1.0, 'host4')

    def test_multiple_resource_wrong_ratio(self):
        # host1: foo=512,  bar=1
        # host2: foo=1024, bar=2
        # host3: foo=3072, bar=1
        # host4: foo=8192, bar=0
        # so, host4 should win:
        setting = ['foo=0.0001', 'bar = 2.0t']
        self._do_test(setting, 1.0, 'host4')

    def _check_parsing_result(self, weigher, setting, results):
        self.flags(weight_setting=setting, group='metrics')
        weigher._parse_setting()
        self.assertTrue(len(results) == len(weigher.setting))
        for item in results:
            self.assertTrue(item in weigher.setting)

    def test_parse_setting(self):
        weigher = self.weight_classes[0]()
        self._check_parsing_result(weigher,
                                   ['foo=1'],
                                   [('foo', 1.0)])
        self._check_parsing_result(weigher,
                                   ['foo=1', 'bar=-2.1'],
                                   [('foo', 1.0), ('bar', -2.1)])
        self._check_parsing_result(weigher,
                                   ['foo=a1', 'bar=-2.1'],
                                   [('bar', -2.1)])
        self._check_parsing_result(weigher,
                                   ['foo', 'bar=-2.1'],
                                   [('bar', -2.1)])
        self._check_parsing_result(weigher,
                                   ['=5', 'bar=-2.1'],
                                   [('bar', -2.1)])

    def test_metric_not_found_required(self):
        setting = ['foo=1', 'zot=2']
        self.assertRaises(exception.ComputeHostMetricNotFound,
                          self._do_test,
                          setting,
                          8192,
                          'host4')

    def test_metric_not_found_non_required(self):
        # host1: foo=512,  bar=1
        # host2: foo=1024, bar=2
        # host3: foo=3072, bar=1
        # host4: foo=8192, bar=0
        # host5: foo=768, bar=0, zot=1
        # host6: foo=2048, bar=0, zot=2
        # so, host5 should win:
        self.flags(required=False, group='metrics')
        setting = ['foo=0.0001', 'zot=-1']
        self._do_test(setting, 1.0, 'host5')
