# Copyright (c) 2019 OpenStack Foundation
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

import nova.conf
from nova import objects
from nova.scheduler.filters import bigvm_filter
from nova import test
from nova.tests.unit.scheduler import fakes
from oslo_utils.fixture import uuidsentinel

CONF = nova.conf.CONF


class TestBigVmClusterUtilizationFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestBigVmClusterUtilizationFilter, self).setUp()
        self.hv_size = CONF.bigvm_mb + 1024
        self.filt_cls = bigvm_filter.BigVmClusterUtilizationFilter()
        self.filt_cls._HV_SIZE_CACHE.cache = {}
        self.filt_cls._HV_SIZE_CACHE.set(uuidsentinel.host1, self.hv_size)

    def test_big_vm_with_small_vm_passes(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=1024, extra_specs={}))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_baremetal_instance_passes(self):
        extra_specs = {'capabilities:cpu_arch': 'x86_64'}
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs=extra_specs))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_big_vm_without_hv_size(self):
        """If there's no inventory for this host, it should not even have
        passed placement API checks, so we stop it here.
        """
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb, extra_specs={}))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE.set(host.uuid, None)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_big_vm_without_enough_ram(self):
        # there's enough RAM available in the cluster but not enough (~50 % of
        # the requested size on average
        # 12 hosts (bigvm + 1 GB size)
        # 11 big VM + some smaller (12 * 1 GB) already deployed
        # -> still bigvm_mb left, but ram utilization ratio of all hosts is too
        # high
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb, extra_specs={}))
        total_ram = self.hv_size * 12
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1,
                 'free_ram_mb': CONF.bigvm_mb,
                 'total_usable_ram_mb': total_ram})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_big_vm_without_enough_ram_ignores_ram_ratio(self):
        # same as test_big_vm_without_enough_ram but with more theoretical RAM
        # via `ram_allocation_ratio`. big VMs reserve all memory so the ratio
        # does not count for them.
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb, extra_specs={}))
        total_ram = self.hv_size * 12
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1,
                 'free_ram_mb': CONF.bigvm_mb,
                 'total_usable_ram_mb': total_ram,
                 'ram_allocation_ratio': 1.5})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_big_vm_without_enough_ram_percent(self):
        # there's just closely not enough RAM available
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb, extra_specs={}))
        total_ram = self.hv_size * 12
        hv_percent = self.filt_cls._get_max_ram_percent(CONF.bigvm_mb,
                                                        self.hv_size)
        free_ram_mb = total_ram - (total_ram * hv_percent / 100.0) - 128
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1,
                 'free_ram_mb': free_ram_mb,
                 'total_usable_ram_mb': total_ram})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_big_vm_with_enough_ram(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb, extra_specs={}))
        total_ram = self.hv_size * 12
        hv_percent = self.filt_cls._get_max_ram_percent(CONF.bigvm_mb,
                                                        self.hv_size)
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1,
                 'free_ram_mb': total_ram - (total_ram * hv_percent / 100.0),
                 'total_usable_ram_mb': total_ram})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.utils.is_non_vmware_spec', return_value=True)
    def test_non_vmware_spec(self, mock_is_non_vmware_spec):
        spec_obj = mock.sentinel.spec_obj
        host = mock.sentinel.host
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        mock_is_non_vmware_spec.assert_called_once_with(spec_obj)


class TestBigVmFlavorHostSizeFilter(test.NoDBTestCase):
    def setUp(self):
        super(TestBigVmFlavorHostSizeFilter, self).setUp()
        self.hv_size = CONF.bigvm_mb + 1024
        self.filt_cls = bigvm_filter.BigVmFlavorHostSizeFilter()
        self.filt_cls._HV_SIZE_CACHE.cache = {}
        self.filt_cls._HV_SIZE_CACHE.set(uuidsentinel.host1, self.hv_size)

    def test_big_vm_with_small_vm_passes(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=1024, extra_specs={}))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_baremetal_instance_passes(self):
        extra_specs = {'capabilities:cpu_arch': 'x86_64'}
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs=extra_specs))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_big_vm_without_hv_size(self):
        """If there's no inventory for this host, it should not even have
        passed placement API checks, so we stop it here.
        """
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb, extra_specs={}))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE.set(host.uuid, None)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_memory_match_with_tolerance(self):
        """We only accept tolerance below not above the given value."""

        def call(a, b):
            return self.filt_cls._memory_match_with_tolerance(a, b)

        self.filt_cls._HV_SIZE_TOLERANCE_PERCENT = 10
        self.assertTrue(call(1024, 1024 - 1024 * 0.1))
        self.assertFalse(call(1024, 1024 - 1024 * 0.1 - 1))
        self.assertTrue(call(1024, 1024))
        self.assertFalse(call(1024, 1025))

        self.filt_cls._HV_SIZE_TOLERANCE_PERCENT = 50
        self.assertTrue(call(1024, 512))
        self.assertFalse(call(1024, 511))

    def test_big_vm_with_empty_extra_specs(self):
        """If the extra spec is empty, we fail."""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb, extra_specs={},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_invalid_values(self):
        """Invalid values in extra specs make it unscheduleable."""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': '-1,1.5'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_full_positive(self):
        """test specified full size"""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': '1'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_full_negative(self):
        """test specified full size"""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': '1'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE.set(host.uuid, CONF.bigvm_mb * 2 + 1024)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_half_positive(self):
        """test specified half size"""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': '0.5,1'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE.set(host.uuid, CONF.bigvm_mb * 2 + 1024)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_half_positive_with_unknown(self):
        """test specified half size"""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': 'broken,0.5'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE.set(host.uuid, CONF.bigvm_mb * 2 + 1024)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_half_negative(self):
        """test specified half size"""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': '0.5'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_rough_float_third_negative(self):
        """test 0.33 not precise enough for 1/3 (and thus fractional notation
        support is actually useful)
        """
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': '0.33'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE.set(host.uuid, CONF.bigvm_mb * 3 + 1024)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_fractional_third(self):
        """test fractional 1/3 size"""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': '1/3'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE.set(host.uuid, CONF.bigvm_mb * 3 + 1024)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_fractional_divbyzero(self):
        """test division by zero fails"""
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs={'host_fraction': '1/0'},
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_has_numa_trait_required(self):
        """test trait:CUSTOM_NUMASIZE_*=required passes filter"""
        extra_specs = {'trait:CUSTOM_NUMASIZE_C1_M1': 'required'}
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs=extra_specs,
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_extra_specs_has_numa_trait_not_required(self):
        """test trait:CUSTOM_NUMASIZE_*=forbidden fails filter"""
        extra_specs = {'trait:CUSTOM_NUMASIZE_C1_M1': 'forbidden'}
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=CONF.bigvm_mb,
                                  extra_specs=extra_specs,
                                  name='random-name'))
        host = fakes.FakeHostState('host1', 'compute',
                {'uuid': uuidsentinel.host1})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.utils.is_non_vmware_spec', return_value=True)
    def test_non_vmware_spec(self, mock_is_non_vmware_spec):
        """test non-vmware spec passes filter"""
        spec_obj = mock.sentinel.spec_obj
        host = mock.sentinel.host
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        mock_is_non_vmware_spec.assert_called_once_with(spec_obj)
