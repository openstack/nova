# Copyright (c) 2021 SAP SE
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

from nova import objects
from nova.scheduler.filters import vm_size_threshold_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestVmSizeThresholdFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestVmSizeThresholdFilter, self).setUp()
        self.filt_cls = vm_size_threshold_filter.VmSizeThresholdFilter()

    @mock.patch('nova.scheduler.filters.vm_size_threshold_filter.'
                'VmSizeThresholdFilter._get_hv_size')
    def test_baremetal_passes(self, mock_hv_size):
        """We ignore baremetal flavors"""
        host = fakes.FakeHostState('host1', 'compute', {})
        extra_specs = {'capabilities:cpu_arch': 'x86_64'}
        flavor = objects.Flavor(memory_mb=self.filt_cls._vm_size_threshold_mb,
                                extra_specs=extra_specs)
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        # we shouldn't get that far
        mock_hv_size.assert_not_called()

    @mock.patch('nova.scheduler.filters.vm_size_threshold_filter.'
                'VmSizeThresholdFilter._get_hv_size')
    def test_vm_below_threshold_passes(self, mock_hv_size):
        """Any VM below threshold gets a pass, because the point is to have
        bigger VMs (above threshold) not land on small HVs and thus we ignore
        small ones.
        """
        host = fakes.FakeHostState('host1', 'compute', {})
        memory_mb = self.filt_cls._vm_size_threshold_mb - 1
        flavor = objects.Flavor(memory_mb=memory_mb, extra_specs={})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        # we shouldn't get that far
        mock_hv_size.assert_not_called()

    @mock.patch('nova.scheduler.filters.vm_size_threshold_filter.'
                'VmSizeThresholdFilter._get_hv_size',
                return_value=None)
    def test_no_hv_size(self, mock_hv_size):
        """If we cannot find the HV size, we cannot make a valid scheduling
        decision and thus filter out the host.
        """
        host = fakes.FakeHostState('host1', 'compute', {})
        memory_mb = self.filt_cls._vm_size_threshold_mb
        flavor = objects.Flavor(memory_mb=memory_mb, extra_specs={})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.vm_size_threshold_filter.'
                'VmSizeThresholdFilter._get_hv_size')
    def test_vm_over_hv_under_threshold(self, mock_hv_size):
        """hypervisor below threshold does not pass if the VM is above the
        threshold
        """
        mock_hv_size.return_value = self.filt_cls._hv_size_threshold_mb - 1
        host = fakes.FakeHostState('host1', 'compute', {})
        flavor = objects.Flavor(memory_mb=self.filt_cls._vm_size_threshold_mb,
                                extra_specs={})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.filters.vm_size_threshold_filter.'
                'VmSizeThresholdFilter._get_hv_size')
    def test_vm_over_hv_over_threshold(self, mock_hv_size):
        """hypervisor over threshold does pass if the VM is above the
        threshold
        """
        mock_hv_size.return_value = self.filt_cls._hv_size_threshold_mb
        host = fakes.FakeHostState('host1', 'compute', {})
        flavor = objects.Flavor(memory_mb=self.filt_cls._vm_size_threshold_mb,
                                extra_specs={})
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            flavor=flavor)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    @mock.patch('nova.scheduler.utils.is_non_vmware_spec', return_value=True)
    def test_non_vmware_spec(self, mock_is_non_vmware_spec):
        host = mock.sentinel.host
        spec_obj = mock.sentinel.spec_obj

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        mock_is_non_vmware_spec.assert_called_once_with(spec_obj)
