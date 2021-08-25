# Copyright 2020 OpenStack Foundation
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

import nova.conf
from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import hv_ram_class
from nova import test
from nova.tests.unit.scheduler import fakes

CONF = nova.conf.CONF


@ddt.ddt
class HvRamClassWeigherTestCase(test.NoDBTestCase):

    def setUp(self):
        super(HvRamClassWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [hv_ram_class.HvRamClassWeigher()]

    @mock.patch('nova.scheduler.weights.hv_ram_class.'
                'HvRamClassWeigher._get_hv_size')
    def test_baremetal_passes(self, mock_hv_size):
        """We ignore baremetal flavors"""
        host = fakes.FakeHostState('host1', 'compute', {})
        extra_specs = {'capabilities:cpu_arch': 'x86_64'}
        flavor = objects.Flavor(extra_specs=extra_specs)
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)
        weight = self.weighers[0]._weigh_object(host, spec_obj)
        self.assertEqual(0.0, weight)
        # we shouldn't get that far
        mock_hv_size.assert_not_called()

    @mock.patch('nova.scheduler.weights.hv_ram_class.'
                'HvRamClassWeigher._get_hv_size')
    @ddt.data(((1024 * 1024) - 1, {1024: 1, 3027: 0.5}, 1),
              ((1024 * 1024), {1024: 1, 3027: 0.5}, 1),
              ((1024 * 1024) + 1, {1024: 1, 3027: 0.5}, 0.5),
              (3027 * 1024, {1024: 1, 3027: 0.5}, 0.5),
              ((3027 * 1024) + 1, {1024: 1, 3027: 0.5}, 0.0))
    @ddt.unpack
    def test_class_weights(self, host_memory_mb, classes, expected_weight,
                           mock_hv_size):
        """make sure the given host_memory_mb ends up with the expected
        weight given the classes
        """
        CONF.set_override('hv_ram_class_weights_gib', classes,
                          group='filter_scheduler')
        self.weighers[0]._load_classes()

        mock_hv_size.return_value = host_memory_mb

        host = fakes.FakeHostState('host1', 'compute', {})
        flavor = objects.Flavor(extra_specs={})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)
        weight = self.weighers[0]._weigh_object(host, spec_obj)

        self.assertEqual(expected_weight, weight)

    @mock.patch('nova.scheduler.weights.hv_ram_class.'
                'HvRamClassWeigher._get_hv_size')
    def test_multiple_hosts(self, mock_hv_size):
        """See the order of the hosts is what we would expect."""
        CONF.set_override('hv_ram_class_weights_gib', {1024: 1, 3027: 0.5},
                          group='filter_scheduler')
        self.weighers[0]._load_classes()

        mock_hv_size.side_effect = (
            3002 * 1024,
            6000 * 1024,
            800 * 1024,
            4000 * 1024,
            768 * 1024,
            800 * 1024,
            2000 * 1024)

        hosts = [fakes.FakeHostState('host{}'.format(i), 'compute', {})
                 for i in range(7)]

        flavor = objects.Flavor(extra_specs={})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)

        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, hosts, spec_obj)

        expected = ['host2', 'host4', 'host5',
                    'host0', 'host6',
                    'host1', 'host3']
        self.assertEqual(expected, [h.obj.host for h in weighed_hosts])

    def test_load_classes_handles_strings(self):
        """We get strings from the config file"""
        CONF.set_override('hv_ram_class_weights_gib',
                          {'1024': '1', '3027': '0.5'},
                          group='filter_scheduler')
        self.weighers[0]._load_classes()

        self.assertEqual({1024 * 1024: 1.0, 3027 * 1024: 0.5},
                         dict(self.weighers[0]._classes))
