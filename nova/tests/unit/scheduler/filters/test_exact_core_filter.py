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

from nova import objects
from nova.scheduler.filters import exact_core_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestExactCoreFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestExactCoreFilter, self).setUp()
        self.filt_cls = exact_core_filter.ExactCoreFilter()

    def test_exact_core_filter_passes(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(vcpus=1))
        vcpus = 3
        host = self._get_host({'vcpus_total': vcpus, 'vcpus_used': vcpus - 1})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        self.assertEqual(host.limits.get('vcpu'), vcpus)

    def test_exact_core_filter_fails(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(vcpus=2))
        host = self._get_host({'vcpus_total': 3, 'vcpus_used': 2})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        self.assertNotIn('vcpu', host.limits)

    def test_exact_core_filter_fails_host_vcpus_not_set(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(vcpus=1))
        host = self._get_host({})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        self.assertNotIn('vcpu', host.limits)

    def _get_host(self, host_attributes):
        return fakes.FakeHostState('host1', 'node1', host_attributes)
