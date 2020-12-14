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
from nova.scheduler.filters import resize_reservation_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestResizeReservedRAMFilter(test.NoDBTestCase):
    def setUp(self):
        super(TestResizeReservedRAMFilter, self).setUp()
        self.filt_cls = resize_reservation_filter.ResizeReservedRAMFilter()

        self.host = fakes.FakeHostState(
            'host1', 'node1', {
                'free_ram_mb': 2047,
                'total_usable_ram_mb': 2048,
                'ram_allocation_ratio': 1.0
            }
        )
        self.flavor = objects.Flavor(
            id=1, name='small', memory_mb=1024, extra_specs={})

    def test_resize_reserved_ram_filter_fails_on_memory(self):
        self.flags(
            resize_reserved_ram_percent=10.0,
            group='filter_scheduler',
        )
        # 2048 * 0.10 = 204.8 MiB of reserved RAM ->
        # 2048 - 204.8 = 1843.2 ->
        # 1900 oversubscribes into reserved memory.
        self.flavor.memory_mb = 1900
        request_specs = objects.RequestSpec(flavor=self.flavor)

        self.assertFalse(self.filt_cls.host_passes(self.host, request_specs))

    def test_resize_reserved_ram_filter_passes(self):
        self.flags(
            resize_reserved_ram_percent=10.0,
            group='filter_scheduler',
        )
        # The edge value of requested ram in this case
        self.flavor.memory_mb = 2662
        request_specs = objects.RequestSpec(
            flavor=self.flavor,
            scheduler_hints={'_nova_check_type': ['resize']},
        )
        self.host.free_ram_mb = 3072,
        self.host.total_usable_ram_mb = 4096,
        self.host.ram_allocation_ratio = 1.0

        self.assertTrue(self.filt_cls.host_passes(self.host, request_specs))

    def test_resize_reserved_ram_filter_oversubscribe(self):
        self.flags(
            resize_reserved_ram_percent=10.0,
            group='filter_scheduler',
        )
        self.host.free_ram_mb = -512
        self.host.total_usable_ram_mb = 4096
        self.host.ram_allocation_ratio = 2.0
        self.flavor.memory_mb = 1024
        request_specs = objects.RequestSpec(flavor=self.flavor)

        self.assertTrue(self.filt_cls.host_passes(self.host, request_specs))
