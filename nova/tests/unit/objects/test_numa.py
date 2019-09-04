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

from oslo_versionedobjects import base as ovo_base
import testtools

from nova import exception
from nova import objects
from nova.tests.unit.objects import test_objects

fake_obj_numa = objects.NUMATopology(cells=[
    objects.NUMACell(
        id=0,
        cpuset=set([1, 2]),
        pcpuset=set(),
        memory=512,
        cpu_usage=2,
        memory_usage=256,
        mempages=[],
        pinned_cpus=set(),
        siblings=[set([1]), set([2])]),
    objects.NUMACell(
        id=1,
        cpuset=set([3, 4]),
        pcpuset=set(),
        memory=512,
        cpu_usage=1,
        memory_usage=128,
        mempages=[],
        pinned_cpus=set(),
        siblings=[set([3]), set([4])])])


class _TestNUMACell(object):

    def test_free_cpus(self):
        cell_a = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([1, 2]),
            memory=512,
            cpu_usage=2,
            memory_usage=256,
            pinned_cpus=set([1]),
            siblings=[set([1]), set([2])],
            mempages=[])
        cell_b = objects.NUMACell(
            id=1,
            cpuset=set(),
            pcpuset=set([3, 4]),
            memory=512,
            cpu_usage=1,
            memory_usage=128,
            pinned_cpus=set(),
            siblings=[set([3]), set([4])],
            mempages=[])

        self.assertEqual(set([2]), cell_a.free_pcpus)
        self.assertEqual(set([3, 4]), cell_b.free_pcpus)

    def test_pinning_logic(self):
        numacell = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([1, 2, 3, 4]),
            memory=512,
            cpu_usage=2,
            memory_usage=256,
            pinned_cpus=set([1]),
            siblings=[set([1]), set([2]), set([3]), set([4])],
            mempages=[])
        numacell.pin_cpus(set([2, 3]))
        self.assertEqual(set([4]), numacell.free_pcpus)

        expect_msg = exception.CPUPinningUnknown.msg_fmt % {
            'requested': r'\[1, 55\]', 'available': r'\[1, 2, 3, 4\]'}
        with testtools.ExpectedException(exception.CPUPinningUnknown,
                                         expect_msg):
            numacell.pin_cpus(set([1, 55]))

        self.assertRaises(exception.CPUPinningInvalid,
                          numacell.pin_cpus, set([1, 4]))

        expect_msg = exception.CPUUnpinningUnknown.msg_fmt % {
            'requested': r'\[1, 55\]', 'available': r'\[1, 2, 3, 4\]'}
        with testtools.ExpectedException(exception.CPUUnpinningUnknown,
                                         expect_msg):
            numacell.unpin_cpus(set([1, 55]))

        self.assertRaises(exception.CPUUnpinningInvalid,
                          numacell.unpin_cpus, set([1, 4]))
        numacell.unpin_cpus(set([1, 2, 3]))
        self.assertEqual(set([1, 2, 3, 4]), numacell.free_pcpus)

    def test_pinning_with_siblings(self):
        numacell = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([1, 2, 3, 4]),
            memory=512,
            cpu_usage=2,
            memory_usage=256,
            pinned_cpus=set(),
            siblings=[set([1, 3]), set([2, 4])],
            mempages=[])

        numacell.pin_cpus_with_siblings(set([1, 2]))
        self.assertEqual(set(), numacell.free_pcpus)
        numacell.unpin_cpus_with_siblings(set([1]))
        self.assertEqual(set([1, 3]), numacell.free_pcpus)
        self.assertRaises(exception.CPUUnpinningInvalid,
                          numacell.unpin_cpus_with_siblings,
                          set([3]))
        self.assertRaises(exception.CPUPinningInvalid,
                          numacell.pin_cpus_with_siblings,
                          set([4]))
        self.assertRaises(exception.CPUUnpinningInvalid,
                          numacell.unpin_cpus_with_siblings,
                          set([3, 4]))
        self.assertEqual(set([1, 3]), numacell.free_pcpus)
        numacell.unpin_cpus_with_siblings(set([4]))
        self.assertEqual(set([1, 2, 3, 4]), numacell.free_pcpus)

    def test_pinning_with_siblings_no_host_siblings(self):
        numacell = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([1, 2, 3, 4]),
            memory=512,
            cpu_usage=0,
            memory_usage=256,
            pinned_cpus=set(),
            siblings=[set([1]), set([2]), set([3]), set([4])],
            mempages=[])

        numacell.pin_cpus_with_siblings(set([1, 2]))
        self.assertEqual(set([1, 2]), numacell.pinned_cpus)
        numacell.unpin_cpus_with_siblings(set([1]))
        self.assertEqual(set([2]), numacell.pinned_cpus)
        self.assertRaises(exception.CPUUnpinningInvalid,
                          numacell.unpin_cpus_with_siblings,
                          set([1]))
        self.assertRaises(exception.CPUPinningInvalid,
                          numacell.pin_cpus_with_siblings,
                          set([2]))
        self.assertEqual(set([2]), numacell.pinned_cpus)

    def test_can_fit_pagesize(self):
        # NOTE(stephenfin): '**' is Python's "power of" symbol
        cell = objects.NUMACell(
            id=0,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=1024,
            siblings=[set([1]), set([2])],
            pinned_cpus=set(),
            mempages=[
                objects.NUMAPagesTopology(
                    size_kb=4, total=1548736, used=0),
                objects.NUMAPagesTopology(
                    size_kb=2048, total=513, used=0),
                objects.NUMAPagesTopology(
                    size_kb=1048576, total=4, used=1, reserved=1)])

        pagesize = 2048
        self.assertTrue(cell.can_fit_pagesize(pagesize, 2 ** 20))
        self.assertFalse(cell.can_fit_pagesize(pagesize, 2 ** 21))
        self.assertFalse(cell.can_fit_pagesize(pagesize, 2 ** 19 + 1))

        pagesize = 1048576
        self.assertTrue(cell.can_fit_pagesize(pagesize, 2 ** 20))
        self.assertTrue(cell.can_fit_pagesize(pagesize, 2 ** 20 * 2))
        self.assertFalse(cell.can_fit_pagesize(pagesize, 2 ** 20 * 3))

        self.assertRaises(
            exception.MemoryPageSizeNotSupported,
            cell.can_fit_pagesize, 12345, 2 ** 20)

    def test_can_fit_pagesize_oversubscription(self):
        """Validate behavior when using page oversubscription.

        While hugepages aren't themselves oversubscribable, we also track small
        pages which are.
        """
        # NOTE(stephenfin): '**' is Python's "power of" symbol
        cell = objects.NUMACell(
            id=0,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=1024,
            siblings=[set([1]), set([2])],
            pinned_cpus=set(),
            mempages=[
                # 1 GiB total, all used
                objects.NUMAPagesTopology(
                    size_kb=4, total=2 ** 18, used=2 ** 18),
            ])

        pagesize = 4
        # request 2^20 KiB (so 1 GiB)
        self.assertTrue(cell.can_fit_pagesize(
            pagesize, 2 ** 20, use_free=False))
        # request 2^20 + 1 KiB (so # > 1 GiB)
        self.assertFalse(cell.can_fit_pagesize(
            pagesize, 2 ** 20 + 1, use_free=False))

    def test_default_behavior(self):
        inst_cell = objects.NUMACell()
        self.assertEqual(0, len(inst_cell.obj_get_changes()))

    def test_equivalent(self):
        cell1 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])])
        cell2 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])])
        self.assertEqual(cell1, cell2)

    def test_not_equivalent(self):
        cell1 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])])
        cell2 = objects.NUMACell(
            id=2,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])])
        self.assertNotEqual(cell1, cell2)

    def test_not_equivalent_missing_a(self):
        cell1 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])])
        cell2 = objects.NUMACell(
            id=2,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])])
        self.assertNotEqual(cell1, cell2)

    def test_not_equivalent_missing_b(self):
        cell1 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])])
        cell2 = objects.NUMACell(
            id=2,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])])
        self.assertNotEqual(cell1, cell2)

    def test_equivalent_with_pages(self):
        pt1 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=0)
        pt2 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=0)
        cell1 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])],
            mempages=[pt1])
        cell2 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])],
            mempages=[pt2])
        self.assertEqual(cell1, cell2)

    def test_not_equivalent_with_pages(self):
        pt1 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=0)
        pt2 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=1)
        cell1 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])],
            mempages=[pt1])
        cell2 = objects.NUMACell(
            id=1,
            cpuset=set([1, 2]),
            pcpuset=set(),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])],
            mempages=[pt2])
        self.assertNotEqual(cell1, cell2)

    def test_obj_make_compatible(self):
        network_metadata = objects.NetworkMetadata(
            physnets=set(['foo', 'bar']), tunneled=True)
        cell = objects.NUMACell(
            id=0,
            cpuset=set([1, 2]),
            pcpuset=set([3, 4]),
            memory=32,
            cpu_usage=10,
            pinned_cpus=set([3, 4]),
            siblings=[set([5, 6])],
            network_metadata=network_metadata)

        versions = ovo_base.obj_tree_get_versions('NUMACell')

        primitive = cell.obj_to_primitive(target_version='1.4',
                                          version_manifest=versions)
        self.assertIn('pcpuset', primitive['nova_object.data'])

        primitive = cell.obj_to_primitive(target_version='1.3',
                                          version_manifest=versions)
        self.assertNotIn('pcpuset', primitive['nova_object.data'])
        self.assertIn('network_metadata', primitive['nova_object.data'])

        primitive = cell.obj_to_primitive(target_version='1.2',
                                          version_manifest=versions)
        self.assertNotIn('network_metadata', primitive['nova_object.data'])


class TestNUMACell(test_objects._LocalTest, _TestNUMACell):
    pass


class TestNUMACellRemote(test_objects._RemoteTest, _TestNUMACell):
    pass


class _TestNUMAPagesTopology(object):

    def test_wipe(self):
        pages_topology = objects.NUMAPagesTopology(
            size_kb=2048, total=1024, used=512)

        self.assertEqual(2048, pages_topology.size_kb)
        self.assertEqual(1024, pages_topology.total)
        self.assertEqual(512, pages_topology.used)
        self.assertEqual(512, pages_topology.free)
        self.assertEqual(1048576, pages_topology.free_kb)

    def test_equivalent(self):
        pt1 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=0)
        pt2 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=0)
        self.assertEqual(pt1, pt2)

    def test_not_equivalent(self):
        pt1 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=0)
        pt2 = objects.NUMAPagesTopology(size_kb=1024, total=33, used=0)
        self.assertNotEqual(pt1, pt2)

    def test_not_equivalent_missing_a(self):
        pt1 = objects.NUMAPagesTopology(size_kb=1024, used=0)
        pt2 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=0)
        self.assertNotEqual(pt1, pt2)

    def test_not_equivalent_missing_b(self):
        pt1 = objects.NUMAPagesTopology(size_kb=1024, total=32, used=0)
        pt2 = objects.NUMAPagesTopology(size_kb=1024, used=0)
        self.assertNotEqual(pt1, pt2)

    def test_reserved_property_not_set(self):
        p = objects.NUMAPagesTopology(
            # To have reserved not set is similar than to have receive
            # a NUMAPageTopology version 1.0
            size_kb=1024, total=64, used=32)
        self.assertEqual(32, p.free)


class TestNUMAPagesTopology(test_objects._LocalTest, _TestNUMACell):
    pass


class TestNUMAPagesTopologyRemote(test_objects._RemoteTest, _TestNUMACell):
    pass


class _TestNUMATopologyLimits(object):

    def test_obj_make_compatible(self):
        network_meta = objects.NetworkMetadata(
            physnets=set(['foo', 'bar']), tunneled=True)
        limits = objects.NUMATopologyLimits(
            cpu_allocation_ratio=1.0,
            ram_allocation_ratio=1.0,
            network_metadata=network_meta)

        versions = ovo_base.obj_tree_get_versions('NUMATopologyLimits')
        primitive = limits.obj_to_primitive(target_version='1.1',
                                            version_manifest=versions)
        self.assertIn('network_metadata', primitive['nova_object.data'])

        primitive = limits.obj_to_primitive(target_version='1.0',
                                            version_manifest=versions)
        self.assertNotIn('network_metadata', primitive['nova_object.data'])


class TestNUMA(test_objects._LocalTest, _TestNUMATopologyLimits):
    pass


class TestNUMARemote(test_objects._RemoteTest, _TestNUMATopologyLimits):
    pass
