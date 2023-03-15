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
"""
Tests for scheduler prefer-resize-to-same-host weigher.
"""
from unittest import mock

from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import resize_same_host
from nova import test
from nova.tests.unit.scheduler import fakes
from nova import utils
from oslo_utils.fixture import uuidsentinel


class PreferSameHostOnResizeWeigherTestCase(test.NoDBTestCase):
    def setUp(self):
        super(PreferSameHostOnResizeWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [resize_same_host.PreferSameHostOnResizeWeigher()]

        flavor_big = objects.Flavor(id=1, name='big',
                                    memory_mb=1024 * 512, extra_specs={})
        flavor_small = objects.Flavor(id=2, name='small',
                                      memory_mb=1024 * 256, extra_specs={})
        baremetal_extra_specs = {'capabilities:cpu_arch': 'x86_64',
                                 utils.QUOTA_SEPARATE_KEY: 'true'}
        flavor_bm_big = objects.Flavor(id=3, name='bm_big',
                                       memory_mb=1024 * 512,
                                       extra_specs=baremetal_extra_specs)
        flavor_bm_small = objects.Flavor(id=4, name='bm_small',
                                         memory_mb=1024 * 256,
                                         extra_specs=baremetal_extra_specs)
        old_instance = objects.Instance(host='same_host',
                                        uuid=uuidsentinel.fake_instance,
                                        flavor=flavor_small)
        new_instance = objects.Instance(uuid=uuidsentinel.fake_new_instance,
                                        flavor=flavor_small)
        bm_instance = objects.Instance(host='same_host',
                                       uuid=uuidsentinel.fake_bm_instance,
                                       flavor=flavor_bm_small)
        self.hosts = [
            fakes.FakeHostState('same_host', 'n1', {}, [old_instance,
                                                        bm_instance]),
            fakes.FakeHostState('other_host', 'n2', {}, []),
        ]
        self.request_specs = {
            'to-big': objects.RequestSpec(instance_uuid=old_instance.uuid,
                                          flavor=flavor_big,
                                          scheduler_hints={
                                            '_nova_check_type': ['resize'],
                                            'source_host': ['same_host'],
                                          }),
            'unchanged': objects.RequestSpec(instance_uuid=old_instance.uuid,
                                            flavor=flavor_small,
                                           ),
            'rebuild': objects.RequestSpec(instance_uuid=old_instance.uuid,
                                           flavor=flavor_big,
                                           scheduler_hints={
                                            '_nova_check_type': ['rebuild'],
                                            'source_host': ['same_host'],
                                           }),
            'new': objects.RequestSpec(instance_uuid=new_instance.uuid),
            'resize-bm': objects.RequestSpec(instance_uuid=bm_instance.uuid,
                                             flavor=flavor_bm_big,
                                             scheduler_hints={
                                                '_nova_check_type': ['resize'],
                                                'source_host': ['same_host'],
                                             }),
        }

    def test_prefer_resize_to_same_host(self):
        self.flags(prefer_same_host_resize_weight_multiplier=1.0,
                   group='filter_scheduler')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, self.request_specs['to-big'])
        self.assertEqual(1.0, weighed_hosts[0].weight)
        self.assertEqual(0.0, weighed_hosts[1].weight)
        self.assertEqual('same_host', weighed_hosts[0].obj.host)

    def test_prefer_resize_to_different_host(self):
        self.flags(prefer_same_host_resize_weight_multiplier=-1.0,
                   group='filter_scheduler')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, self.request_specs['to-big'])
        self.assertEqual(0.0, weighed_hosts[0].weight)
        self.assertEqual(-1.0, weighed_hosts[1].weight)
        self.assertEqual('other_host', weighed_hosts[0].obj.host)

    def test_ignore_non_resizing_instance(self):
        self.flags(prefer_same_host_resize_weight_multiplier=1.0,
                   group='filter_scheduler')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, self.request_specs['unchanged'])
        self.assertEqual(0.0, weighed_hosts[0].weight)
        self.assertEqual(0.0, weighed_hosts[1].weight)

    def test_ignore_rebuilding_instance(self):
        self.flags(prefer_same_host_resize_weight_multiplier=1.0,
                   group='filter_scheduler')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, self.request_specs['rebuild'])
        self.assertEqual(0.0, weighed_hosts[0].weight)
        self.assertEqual(0.0, weighed_hosts[1].weight)

    def test_ignore_scheduling_new_instance(self):
        self.flags(prefer_same_host_resize_weight_multiplier=1.0,
                   group='filter_scheduler')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, self.request_specs['new'])
        self.assertEqual(0.0, weighed_hosts[0].weight)
        self.assertEqual(0.0, weighed_hosts[1].weight)

    def test_ignore_baremetal_instance(self):
        self.flags(prefer_same_host_resize_weight_multiplier=1.0,
                   group='filter_scheduler')
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, self.request_specs['resize-bm'])
        self.assertEqual(0.0, weighed_hosts[0].weight)
        self.assertEqual(0.0, weighed_hosts[1].weight)

    @mock.patch('nova.scheduler.utils.is_non_vmware_spec', return_value=True)
    def test_ignore_non_vmware_instance(self, mock_is_non_vmware_spec):
        self.flags(prefer_same_host_resize_weight_multiplier=1.0,
                   group='filter_scheduler')
        request_spec = self.request_specs['to-big']
        weighed_hosts = self.weight_handler.get_weighed_objects(
            self.weighers, self.hosts, request_spec)
        self.assertEqual(0.0, weighed_hosts[0].weight)
        self.assertEqual(0.0, weighed_hosts[1].weight)
        mock_is_non_vmware_spec.assert_has_calls(
            len(self.hosts) * [mock.call(request_spec)])
