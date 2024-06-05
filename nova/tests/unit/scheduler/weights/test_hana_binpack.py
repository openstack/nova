# Copyright (c) 2024 SAP SE
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
import ddt

from unittest import mock

from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import hana_binpack
from nova import test
from nova.tests.unit.scheduler import fakes


@ddt.ddt
class HANABingPackWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(HANABingPackWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [hana_binpack.HANABinPackWeigher()]
        self._hana_spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=objects.Flavor(extra_specs={
                'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'required'
            }))

    def _get_weighed_host(self, hosts, weight_properties=None,
                          extra_specs=None):
        if weight_properties is None:
            weight_properties = objects.RequestSpec(
                context=mock.sentinel.ctx,
                flavor=objects.Flavor(extra_specs=extra_specs or {}))
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, weight_properties)[0]

    def _get_all_hosts(self):
        host_values = [
            ('host1', 'node1', {'stats': {'memory_mb_max_unit': '3072'}}),
            ('host2', 'node2', {'stats': {'memory_mb_max_unit': '8192'}}),
            ('host3', 'node3', {'stats': {'memory_mb_max_unit': '1024'}}),
            ('host4', 'node4', {'stats': {'memory_mb_max_unit': '512'}})
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def test_default_of_stacking_first(self):
        hostinfo_list = self._get_all_hosts()
        # host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list,
                                              self._hana_spec_obj)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_multiplier(self):
        self.flags(hana_binpack_weight_multiplier=2.0,
                   group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        # host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list,
                                              self._hana_spec_obj)
        self.assertEqual('host4', weighed_host.obj.host)

    def test_multiplier_zero(self):
        self.flags(hana_binpack_weight_multiplier=0.0,
                   group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list,
                                              self._hana_spec_obj)
        # first host will win:
        self.assertEqual('host1', weighed_host.obj.host)

    def test_negative_multiplier(self):
        self.flags(hana_binpack_weight_multiplier=-1.0,
                   group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list,
                                              self._hana_spec_obj)
        # spreading instead of stacking, host2 should win
        self.assertEqual('host2', weighed_host.obj.host)

    @ddt.data({},
              {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'forbidden'})
    def test_normal_flavor(self, extra_specs):
        hostinfo_list = self._get_all_hosts()
        # first host will win:
        weighed_host = self._get_weighed_host(hostinfo_list,
                                              extra_specs=extra_specs)
        self.assertEqual('host1', weighed_host.obj.host)
        self.assertEqual(0, weighed_host.weight)

    def test_no_memory_mb_max_unit(self):
        attrs = {'stats': {}}
        host_list = [fakes.FakeHostState('host1', 'node1', attrs),
                     fakes.FakeHostState('host2', 'node2', attrs)]
        weighed_host = self._get_weighed_host(host_list,
                                              self._hana_spec_obj)
        self.assertEqual('host1', weighed_host.obj.host)
        self.assertEqual(0, weighed_host.weight)
