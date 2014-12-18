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


from nova import exception
from nova import objects
from nova.tests.unit.objects import test_objects

fake_obj_numa = objects.NUMATopology(
    cells=[
        objects.NUMACell(
            id=0, cpuset=set([1, 2]), memory=512,
            cpu_usage=2, memory_usage=256),
        objects.NUMACell(
            id=1, cpuset=set([3, 4]), memory=512,
            cpu_usage=1, memory_usage=128)])


class _TestNUMA(object):

    def test_convert_wipe(self):
        d1 = fake_obj_numa._to_dict()
        d2 = objects.NUMATopology.obj_from_primitive(d1)._to_dict()

        self.assertEqual(d1, d2)

    def test_pinning_logic(self):
        obj = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0, cpuset=set([1, 2]), memory=512,
                cpu_usage=2, memory_usage=256,
                pinned_cpus=set([1])),
            objects.NUMACell(
                id=1, cpuset=set([3, 4]), memory=512,
                cpu_usage=1, memory_usage=128,
                pinned_cpus=set([]))
            ]
        )
        self.assertEqual(set([2]), obj.cells[0].free_cpus)
        self.assertEqual(set([3, 4]), obj.cells[1].free_cpus)

    def test_pages_topology_wipe(self):
        pages_topology = objects.NUMAPagesTopology(
            size_kb=2048, total=1024, used=512)

        self.assertEqual(2048, pages_topology.size_kb)
        self.assertEqual(1024, pages_topology.total)
        self.assertEqual(512, pages_topology.used)
        self.assertEqual(512, pages_topology.free)
        self.assertEqual(1048576, pages_topology.free_kb)

    def test_can_fit_hugepages(self):
        cell = objects.NUMACell(
            id=0, cpuset=set([1, 2]), memory=1024,
            mempages=[
                objects.NUMAPagesTopology(
                    size_kb=4, total=1548736, used=0),
                objects.NUMAPagesTopology(
                    size_kb=2048, total=513, used=0)])  # 1,002G

        pagesize = 2048

        self.assertTrue(cell.can_fit_hugepages(pagesize, 2 ** 20))
        self.assertFalse(cell.can_fit_hugepages(pagesize, 2 ** 21))
        self.assertFalse(cell.can_fit_hugepages(pagesize, 2 ** 19 + 1))
        self.assertRaises(
            exception.MemoryPageSizeNotSupported,
            cell.can_fit_hugepages, 12345, 2 ** 20)


class TestNUMA(test_objects._LocalTest,
               _TestNUMA):
    pass


class TestNUMARemote(test_objects._RemoteTest,
                     _TestNUMA):
    pass
