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
from unittest import mock

import ddt

from nova import objects
from nova.scheduler.filters import hana_memory_max_unit_filter
from nova import test
from nova.tests.unit.scheduler import fakes


@ddt.ddt
class TestHANAMemoryMaxUnitFilter(test.NoDBTestCase):
    def setUp(self):
        super(TestHANAMemoryMaxUnitFilter, self).setUp()
        self.filt_cls = (
            hana_memory_max_unit_filter.HANAMemoryMaxUnitFilter())

    def test_passes(self):
        host = fakes.FakeHostState('host1', 'compute', {
            'stats': {'memory_mb_max_unit': '2048'}
        })
        extra_specs = {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'required'}

        flavor = objects.Flavor(memory_mb=1024,
                                extra_specs=extra_specs)

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_not_pass_too_big_flavor(self):
        host = fakes.FakeHostState('host1', 'compute', {
            'stats': {'memory_mb_max_unit': '2048'}
        })
        extra_specs = {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'required'}

        flavor = objects.Flavor(memory_mb=2048 + 1,
                                extra_specs=extra_specs)

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)

        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @ddt.data({},
              {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'forbidden'})
    def test_passes_non_hana(self, extra_specs):
        host = fakes.FakeHostState('host1', 'compute', {
            'stats': {'memory_mb_max_unit': '2048'}
        })

        flavor = objects.Flavor(memory_mb=3072,
                                extra_specs=extra_specs)

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_passes_no_maxunit(self):
        host = fakes.FakeHostState('host1', 'compute', {
            'stats': {}
        })
        extra_specs = {'trait:CUSTOM_HANA_EXCLUSIVE_HOST': 'required'}

        flavor = objects.Flavor(memory_mb=3072,
                                extra_specs=extra_specs)

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
