# Copyright (c) 2013 Rackspace Hosting
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
Tests For CellsStateManager
"""

from nova.cells import state
from nova import db
from nova import test


FAKE_COMPUTES = [
    ('host1', 1024, 100, 0, 0),
    ('host2', 1024, 100, -1, -1),
    ('host3', 1024, 100, 1024, 100),
    ('host4', 1024, 100, 300, 30),
]

FAKE_ITYPES = [
    (0, 0, 0),
    (50, 12, 13),
]


def _fake_compute_node_get_all(context):
    def _node(host, total_mem, total_disk, free_mem, free_disk):
        service = {'host': host, 'disabled': False}
        return {'service': service,
                'memory_mb': total_mem,
                'local_gb': total_disk,
                'free_ram_mb': free_mem,
                'free_disk_gb': free_disk}

    return [_node(*fake) for fake in FAKE_COMPUTES]


def _fake_instance_type_all(context):
    def _type(mem, root, eph):
        return {'root_gb': root,
                'ephemeral_gb': eph,
                'memory_mb': mem}

    return [_type(*fake) for fake in FAKE_ITYPES]


class TestCellsStateManager(test.TestCase):

    def setUp(self):
        super(TestCellsStateManager, self).setUp()

        self.stubs.Set(db, 'compute_node_get_all', _fake_compute_node_get_all)
        self.stubs.Set(db, 'instance_type_get_all', _fake_instance_type_all)

    def test_capacity_no_reserve(self):
        # utilize entire cell
        cap = self._capacity(0.0)

        cell_free_ram = sum(compute[3] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(compute[4] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])

        units = cell_free_ram / 50
        self.assertEqual(units, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        units = 5  # 4 on host 3, 1 on host4
        self.assertEqual(units, cap['disk_free']['units_by_mb'][str(sz)])

    def test_capacity_full_reserve(self):
        # reserve the entire cell. (utilize zero percent)
        cap = self._capacity(100.0)

        cell_free_ram = sum(compute[3] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(compute[4] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        self.assertEqual(0, cap['disk_free']['units_by_mb'][str(sz)])

    def test_capacity_part_reserve(self):
        # utilize half the cell's free capacity
        cap = self._capacity(50.0)

        cell_free_ram = sum(compute[3] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(compute[4] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])

        units = 10  # 10 from host 3
        self.assertEqual(units, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        units = 2  # 2 on host 3
        self.assertEqual(units, cap['disk_free']['units_by_mb'][str(sz)])

    def _capacity(self, reserve_percent):
        self.flags(reserve_percent=reserve_percent, group='cells')

        mgr = state.CellStateManager()
        my_state = mgr.get_my_state()
        return my_state.capacities
