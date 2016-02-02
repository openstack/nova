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
from nova.scheduler.filters import exact_ram_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestRamFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestRamFilter, self).setUp()
        self.filt_cls = exact_ram_filter.ExactRamFilter()

    def test_exact_ram_filter_passes(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=1024))
        ram_mb = 1024
        host = self._get_host({'free_ram_mb': ram_mb,
                               'total_usable_ram_mb': ram_mb})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        self.assertEqual(host.limits.get('memory_mb'), ram_mb)

    def test_exact_ram_filter_fails(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=512))
        host = self._get_host({'free_ram_mb': 1024})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        self.assertNotIn('memory_mb', host.limits)

    def _get_host(self, host_attributes):
        return fakes.FakeHostState('host1', 'node1', host_attributes)
