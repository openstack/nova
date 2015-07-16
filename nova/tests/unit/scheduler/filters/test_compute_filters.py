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
from nova.scheduler.filters import compute_filter
from nova import test
from nova.tests.unit.scheduler import fakes


@mock.patch('nova.servicegroup.API.service_is_up')
class TestComputeFilter(test.NoDBTestCase):

    def test_compute_filter_manual_disable(self, service_up_mock):
        filt_cls = compute_filter.ComputeFilter()
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=1024))
        service = {'disabled': True}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'service': service})
        self.assertFalse(filt_cls.host_passes(host, spec_obj))
        self.assertFalse(service_up_mock.called)

    def test_compute_filter_sgapi_passes(self, service_up_mock):
        filt_cls = compute_filter.ComputeFilter()
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=1024))
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'service': service})
        service_up_mock.return_value = True
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
        service_up_mock.assert_called_once_with(service)

    def test_compute_filter_sgapi_fails(self, service_up_mock):
        filt_cls = compute_filter.ComputeFilter()
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=1024))
        service = {'disabled': False, 'updated_at': 'now'}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'service': service})
        service_up_mock.return_value = False
        self.assertFalse(filt_cls.host_passes(host, spec_obj))
        service_up_mock.assert_called_once_with(service)
