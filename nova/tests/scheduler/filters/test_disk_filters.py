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

from nova.scheduler.filters import disk_filter
from nova import test
from nova.tests.scheduler import fakes


class TestDiskFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestDiskFilter, self).setUp()
        self.filt_cls = disk_filter.DiskFilter()

    def test_disk_filter_passes(self):
        self.flags(disk_allocation_ratio=1.0)
        filter_properties = {'instance_type': {'root_gb': 1,
            'ephemeral_gb': 1, 'swap': 512}}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 13})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_disk_filter_fails(self):
        self.flags(disk_allocation_ratio=1.0)
        filter_properties = {'instance_type': {'root_gb': 10,
            'ephemeral_gb': 1, 'swap': 1024}}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 13})
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_disk_filter_oversubscribe(self):
        self.flags(disk_allocation_ratio=10.0)
        filter_properties = {'instance_type': {'root_gb': 100,
            'ephemeral_gb': 18, 'swap': 1024}}
        # 1GB used... so 119GB allowed...
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 12})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        self.assertEqual(12 * 10.0, host.limits['disk_gb'])

    def test_disk_filter_oversubscribe_fail(self):
        self.flags(disk_allocation_ratio=10.0)
        filter_properties = {'instance_type': {'root_gb': 100,
            'ephemeral_gb': 19, 'swap': 1024}}
        # 1GB used... so 119GB allowed...
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 12})
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))
