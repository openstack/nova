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
from nova.scheduler.filters import exact_disk_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestExactDiskFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestExactDiskFilter, self).setUp()
        self.filt_cls = exact_disk_filter.ExactDiskFilter()

    def test_exact_disk_filter_passes(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(root_gb=1, ephemeral_gb=1, swap=1024))
        disk_gb = 3
        host = self._get_host({'free_disk_mb': disk_gb * 1024,
                               'total_usable_disk_gb': disk_gb})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        self.assertEqual(host.limits.get('disk_gb'), disk_gb)

    def test_exact_disk_filter_fails(self):
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(root_gb=1, ephemeral_gb=1, swap=1024))
        host = self._get_host({'free_disk_mb': 2 * 1024})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        self.assertNotIn('disk_gb', host.limits)

    def _get_host(self, host_attributes):
        return fakes.FakeHostState('host1', 'node1', host_attributes)
