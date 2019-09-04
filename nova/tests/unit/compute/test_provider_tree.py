# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import provider_tree
from nova import objects
from nova import test


class TestProviderTree(test.NoDBTestCase):

    def setUp(self):
        super(TestProviderTree, self).setUp()
        self.compute_node1 = objects.ComputeNode(
            uuid=uuids.cn1,
            hypervisor_hostname='compute-node-1',
        )
        self.compute_node2 = objects.ComputeNode(
            uuid=uuids.cn2,
            hypervisor_hostname='compute-node-2',
        )
        self.compute_nodes = objects.ComputeNodeList(
            objects=[self.compute_node1, self.compute_node2],
        )

    def _pt_with_cns(self):
        pt = provider_tree.ProviderTree()
        for cn in self.compute_nodes:
            pt.new_root(cn.hypervisor_hostname, cn.uuid, generation=0)
        return pt

    def test_tree_ops(self):
        cn1 = self.compute_node1
        cn2 = self.compute_node2
        pt = self._pt_with_cns()

        self.assertRaises(
            ValueError,
            pt.new_root,
            cn1.hypervisor_hostname,
            cn1.uuid,
        )

        self.assertTrue(pt.exists(cn1.uuid))
        self.assertTrue(pt.exists(cn1.hypervisor_hostname))
        self.assertFalse(pt.exists(uuids.non_existing_rp))
        self.assertFalse(pt.exists('noexist'))

        self.assertEqual([cn1.uuid],
                         pt.get_provider_uuids(name_or_uuid=cn1.uuid))
        # Same with ..._in_tree
        self.assertEqual([cn1.uuid], pt.get_provider_uuids_in_tree(cn1.uuid))
        self.assertEqual(set([cn1.uuid, cn2.uuid]),
                         set(pt.get_provider_uuids()))

        numa_cell0_uuid = pt.new_child('numa_cell0', cn1.uuid)
        numa_cell1_uuid = pt.new_child('numa_cell1', cn1.hypervisor_hostname)

        self.assertEqual(cn1.uuid, pt.data(numa_cell1_uuid).parent_uuid)

        self.assertTrue(pt.exists(numa_cell0_uuid))
        self.assertTrue(pt.exists('numa_cell0'))

        self.assertTrue(pt.exists(numa_cell1_uuid))
        self.assertTrue(pt.exists('numa_cell1'))

        pf1_cell0_uuid = pt.new_child('pf1_cell0', numa_cell0_uuid)
        self.assertTrue(pt.exists(pf1_cell0_uuid))
        self.assertTrue(pt.exists('pf1_cell0'))

        # Now we've got a 3-level tree under cn1 - check provider UUIDs again
        all_cn1 = [cn1.uuid, numa_cell0_uuid, pf1_cell0_uuid, numa_cell1_uuid]
        self.assertEqual(
            set(all_cn1),
            set(pt.get_provider_uuids(name_or_uuid=cn1.uuid)))
        # Same with ..._in_tree if we're asking for the root
        self.assertEqual(
            set(all_cn1),
            set(pt.get_provider_uuids_in_tree(cn1.uuid)))
        # Asking for a subtree.
        self.assertEqual(
            [numa_cell0_uuid, pf1_cell0_uuid],
            pt.get_provider_uuids(name_or_uuid=numa_cell0_uuid))
        # With ..._in_tree, get the whole tree no matter which we specify.
        for node in all_cn1:
            self.assertEqual(set(all_cn1), set(pt.get_provider_uuids_in_tree(
                node)))
        # With no provider specified, get everything
        self.assertEqual(
            set([cn1.uuid, cn2.uuid, numa_cell0_uuid, pf1_cell0_uuid,
                 numa_cell1_uuid]),
            set(pt.get_provider_uuids()))

        self.assertRaises(
            ValueError,
            pt.new_child,
            'pf1_cell0',
            uuids.non_existing_rp,
        )

        # Fail attempting to add a child that already exists in the tree
        # Existing provider is a child; search by name
        self.assertRaises(ValueError, pt.new_child, 'numa_cell0', cn1.uuid)
        # Existing provider is a root; search by UUID
        self.assertRaises(ValueError, pt.new_child, cn1.uuid, cn2.uuid)

        # Test data().
        # Root, by UUID
        cn1_snap = pt.data(cn1.uuid)
        # Fields were faithfully copied
        self.assertEqual(cn1.uuid, cn1_snap.uuid)
        self.assertEqual(cn1.hypervisor_hostname, cn1_snap.name)
        self.assertIsNone(cn1_snap.parent_uuid)
        self.assertEqual({}, cn1_snap.inventory)
        self.assertEqual(set(), cn1_snap.traits)
        self.assertEqual(set(), cn1_snap.aggregates)
        # Validate read-only-ness
        self.assertRaises(AttributeError, setattr, cn1_snap, 'name', 'foo')

        cn3 = objects.ComputeNode(
            uuid=uuids.cn3,
            hypervisor_hostname='compute-node-3',
        )
        self.assertFalse(pt.exists(cn3.uuid))
        self.assertFalse(pt.exists(cn3.hypervisor_hostname))
        pt.new_root(cn3.hypervisor_hostname, cn3.uuid)

        self.assertTrue(pt.exists(cn3.uuid))
        self.assertTrue(pt.exists(cn3.hypervisor_hostname))

        self.assertRaises(
            ValueError,
            pt.new_root,
            cn3.hypervisor_hostname,
            cn3.uuid,
        )

        self.assertRaises(
            ValueError,
            pt.remove,
            uuids.non_existing_rp,
        )

        pt.remove(numa_cell1_uuid)
        self.assertFalse(pt.exists(numa_cell1_uuid))
        self.assertTrue(pt.exists(pf1_cell0_uuid))
        self.assertTrue(pt.exists(numa_cell0_uuid))
        self.assertTrue(pt.exists(uuids.cn1))

        # Now remove the root and check that children no longer exist
        pt.remove(uuids.cn1)
        self.assertFalse(pt.exists(pf1_cell0_uuid))
        self.assertFalse(pt.exists(numa_cell0_uuid))
        self.assertFalse(pt.exists(uuids.cn1))

    def test_populate_from_iterable_empty(self):
        pt = provider_tree.ProviderTree()
        # Empty list is a no-op
        pt.populate_from_iterable([])
        self.assertEqual([], pt.get_provider_uuids())

    def test_populate_from_iterable_error_orphan_cycle(self):
        pt = provider_tree.ProviderTree()

        # Error trying to populate with an orphan
        grandchild1_1 = {
            'uuid': uuids.grandchild1_1,
            'name': 'grandchild1_1',
            'generation': 11,
            'parent_provider_uuid': uuids.child1,
        }

        self.assertRaises(ValueError,
                          pt.populate_from_iterable, [grandchild1_1])

        # Create a cycle so there are no orphans, but no path to a root
        cycle = {
            'uuid': uuids.child1,
            'name': 'child1',
            'generation': 1,
            # There's a country song about this
            'parent_provider_uuid': uuids.grandchild1_1,
        }

        self.assertRaises(ValueError,
                          pt.populate_from_iterable, [grandchild1_1, cycle])

    def test_populate_from_iterable_complex(self):
        # root
        #   +-> child1
        #   |      +-> grandchild1_2
        #   |             +-> ggc1_2_1
        #   |             +-> ggc1_2_2
        #   |             +-> ggc1_2_3
        #   +-> child2
        # another_root
        pt = provider_tree.ProviderTree()
        plist = [
            {
                'uuid': uuids.root,
                'name': 'root',
                'generation': 0,
            },
            {
                'uuid': uuids.child1,
                'name': 'child1',
                'generation': 1,
                'parent_provider_uuid': uuids.root,
            },
            {
                'uuid': uuids.child2,
                'name': 'child2',
                'generation': 2,
                'parent_provider_uuid': uuids.root,
            },
            {
                'uuid': uuids.grandchild1_2,
                'name': 'grandchild1_2',
                'generation': 12,
                'parent_provider_uuid': uuids.child1,
            },
            {
                'uuid': uuids.ggc1_2_1,
                'name': 'ggc1_2_1',
                'generation': 121,
                'parent_provider_uuid': uuids.grandchild1_2,
            },
            {
                'uuid': uuids.ggc1_2_2,
                'name': 'ggc1_2_2',
                'generation': 122,
                'parent_provider_uuid': uuids.grandchild1_2,
            },
            {
                'uuid': uuids.ggc1_2_3,
                'name': 'ggc1_2_3',
                'generation': 123,
                'parent_provider_uuid': uuids.grandchild1_2,
            },
            {
                'uuid': uuids.another_root,
                'name': 'another_root',
                'generation': 911,
            },
        ]
        pt.populate_from_iterable(plist)

        def validate_root(expected_uuids):
            # Make sure we have all and only the expected providers
            self.assertEqual(expected_uuids, set(pt.get_provider_uuids()))
            # Now make sure they're in the right hierarchy.  Cheat: get the
            # actual _Provider to make it easier to walk the tree (ProviderData
            # doesn't include children).
            root = pt._find_with_lock(uuids.root)
            self.assertEqual(uuids.root, root.uuid)
            self.assertEqual('root', root.name)
            self.assertEqual(0, root.generation)
            self.assertIsNone(root.parent_uuid)
            self.assertEqual(2, len(list(root.children)))
            for child in root.children.values():
                self.assertTrue(child.name.startswith('child'))
                if child.name == 'child1':
                    if uuids.grandchild1_1 in expected_uuids:
                        self.assertEqual(2, len(list(child.children)))
                    else:
                        self.assertEqual(1, len(list(child.children)))
                    for grandchild in child.children.values():
                        self.assertTrue(grandchild.name.startswith(
                            'grandchild1_'))
                        if grandchild.name == 'grandchild1_1':
                            self.assertEqual(0, len(list(grandchild.children)))
                        if grandchild.name == 'grandchild1_2':
                            self.assertEqual(3, len(list(grandchild.children)))
                            for ggc in grandchild.children.values():
                                self.assertTrue(ggc.name.startswith('ggc1_2_'))
            another_root = pt._find_with_lock(uuids.another_root)
            self.assertEqual(uuids.another_root, another_root.uuid)
            self.assertEqual('another_root', another_root.name)
            self.assertEqual(911, another_root.generation)
            self.assertIsNone(another_root.parent_uuid)
            self.assertEqual(0, len(list(another_root.children)))
            if uuids.new_root in expected_uuids:
                new_root = pt._find_with_lock(uuids.new_root)
                self.assertEqual(uuids.new_root, new_root.uuid)
                self.assertEqual('new_root', new_root.name)
                self.assertEqual(42, new_root.generation)
                self.assertIsNone(new_root.parent_uuid)
                self.assertEqual(0, len(list(new_root.children)))

        expected_uuids = set([
            uuids.root, uuids.child1, uuids.child2, uuids.grandchild1_2,
            uuids.ggc1_2_1, uuids.ggc1_2_2, uuids.ggc1_2_3,
            uuids.another_root])

        validate_root(expected_uuids)

        # Merge an orphan - still an error
        orphan = {
            'uuid': uuids.orphan,
            'name': 'orphan',
            'generation': 86,
            'parent_provider_uuid': uuids.mystery,
        }
        self.assertRaises(ValueError, pt.populate_from_iterable, [orphan])

        # And the tree didn't change
        validate_root(expected_uuids)

        # Merge a list with a new grandchild and a new root
        plist = [
            {
                'uuid': uuids.grandchild1_1,
                'name': 'grandchild1_1',
                'generation': 11,
                'parent_provider_uuid': uuids.child1,
            },
            {
                'uuid': uuids.new_root,
                'name': 'new_root',
                'generation': 42,
            },
        ]
        pt.populate_from_iterable(plist)

        expected_uuids |= set([uuids.grandchild1_1, uuids.new_root])

        validate_root(expected_uuids)

        # Merge an empty list - still a no-op
        pt.populate_from_iterable([])
        validate_root(expected_uuids)

        # Since we have a complex tree, test the ordering of get_provider_uuids
        # We can't predict the order of siblings, or where nephews will appear
        # relative to their uncles, but we can guarantee that any given child
        # always comes after its parent (and by extension, its ancestors too).
        puuids = pt.get_provider_uuids()
        for desc in (uuids.child1, uuids.child2):
            self.assertGreater(puuids.index(desc), puuids.index(uuids.root))
        for desc in (uuids.grandchild1_1, uuids.grandchild1_2):
            self.assertGreater(puuids.index(desc), puuids.index(uuids.child1))
        for desc in (uuids.ggc1_2_1, uuids.ggc1_2_2, uuids.ggc1_2_3):
            self.assertGreater(
                puuids.index(desc), puuids.index(uuids.grandchild1_2))

    def test_populate_from_iterable_with_root_update(self):
        # Ensure we can update hierarchies, including adding children, in a
        # tree that's already populated.  This tests the case where a given
        # provider exists both in the tree and in the input.  We must replace
        # that provider *before* we inject its descendants; otherwise the
        # descendants will be lost.  Note that this test case is not 100%
        # reliable, as we can't predict the order over which hashed values are
        # iterated.

        pt = provider_tree.ProviderTree()

        # Let's create a root
        plist = [
            {
                'uuid': uuids.root,
                'name': 'root',
                'generation': 0,
            },
        ]
        pt.populate_from_iterable(plist)
        expected_uuids = [uuids.root]
        self.assertEqual(expected_uuids, pt.get_provider_uuids())

        # Let's add a child updating the name and generation for the root.
        # root
        #   +-> child1
        plist = [
            {
                'uuid': uuids.root,
                'name': 'root_with_new_name',
                'generation': 1,
            },
            {
                'uuid': uuids.child1,
                'name': 'child1',
                'generation': 1,
                'parent_provider_uuid': uuids.root,
            },
        ]
        pt.populate_from_iterable(plist)
        expected_uuids = [uuids.root, uuids.child1]
        self.assertEqual(expected_uuids, pt.get_provider_uuids())

    def test_populate_from_iterable_disown_grandchild(self):
        # Start with:
        # root
        #   +-> child
        #   |      +-> grandchild
        # Then send in [child] and grandchild should disappear.
        child = {
            'uuid': uuids.child,
            'name': 'child',
            'generation': 1,
            'parent_provider_uuid': uuids.root,
        }
        pt = provider_tree.ProviderTree()
        plist = [
            {
                'uuid': uuids.root,
                'name': 'root',
                'generation': 0,
            },
            child,
            {
                'uuid': uuids.grandchild,
                'name': 'grandchild',
                'generation': 2,
                'parent_provider_uuid': uuids.child,
            },
        ]
        pt.populate_from_iterable(plist)
        self.assertEqual([uuids.root, uuids.child, uuids.grandchild],
                         pt.get_provider_uuids())
        self.assertTrue(pt.exists(uuids.grandchild))
        pt.populate_from_iterable([child])
        self.assertEqual([uuids.root, uuids.child], pt.get_provider_uuids())
        self.assertFalse(pt.exists(uuids.grandchild))

    def test_has_inventory_changed_no_existing_rp(self):
        pt = self._pt_with_cns()
        self.assertRaises(
            ValueError,
            pt.has_inventory_changed,
            uuids.non_existing_rp,
            {}
        )

    def test_update_inventory_no_existing_rp(self):
        pt = self._pt_with_cns()
        self.assertRaises(
            ValueError,
            pt.update_inventory,
            uuids.non_existing_rp,
            {},
        )

    def test_has_inventory_changed(self):
        cn = self.compute_node1
        pt = self._pt_with_cns()
        rp_gen = 1

        cn_inv = {
            'VCPU': {
                'total': 8,
                'min_unit': 1,
                'max_unit': 8,
                'step_size': 1,
                'allocation_ratio': 16.0,
            },
            'MEMORY_MB': {
                'total': 1024,
                'reserved': 512,
                'min_unit': 64,
                'max_unit': 1024,
                'step_size': 64,
                'allocation_ratio': 1.5,
            },
            'DISK_GB': {
                'total': 1000,
                'reserved': 100,
                'min_unit': 10,
                'max_unit': 1000,
                'step_size': 10,
                'allocation_ratio': 1.0,
            },
        }
        self.assertTrue(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertTrue(pt.update_inventory(cn.uuid, cn_inv,
                                            generation=rp_gen))

        # Updating with the same inventory info should return False
        self.assertFalse(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertFalse(pt.update_inventory(cn.uuid, cn_inv,
                                             generation=rp_gen))

        # A data-grab's inventory should be "equal" to the original
        cndata = pt.data(cn.uuid)
        self.assertFalse(pt.has_inventory_changed(cn.uuid, cndata.inventory))

        cn_inv['VCPU']['total'] = 6
        self.assertTrue(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertTrue(pt.update_inventory(cn.uuid, cn_inv,
                                            generation=rp_gen))

        # The data() result was not affected; now the tree's copy is different
        self.assertTrue(pt.has_inventory_changed(cn.uuid, cndata.inventory))

        self.assertFalse(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertFalse(pt.update_inventory(cn.uuid, cn_inv,
                                             generation=rp_gen))

        # Deleting a key in the new record should NOT result in changes being
        # recorded...
        del cn_inv['VCPU']['allocation_ratio']
        self.assertFalse(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertFalse(pt.update_inventory(cn.uuid, cn_inv,
                                             generation=rp_gen))

        del cn_inv['MEMORY_MB']
        self.assertTrue(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertTrue(pt.update_inventory(cn.uuid, cn_inv,
                                            generation=rp_gen))

        # ...but *adding* a key in the new record *should* result in changes
        # being recorded
        cn_inv['VCPU']['reserved'] = 0
        self.assertTrue(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertTrue(pt.update_inventory(cn.uuid, cn_inv,
                                            generation=rp_gen))

    def test_have_traits_changed_no_existing_rp(self):
        pt = self._pt_with_cns()
        self.assertRaises(
            ValueError, pt.have_traits_changed, uuids.non_existing_rp, [])

    def test_update_traits_no_existing_rp(self):
        pt = self._pt_with_cns()
        self.assertRaises(
            ValueError, pt.update_traits, uuids.non_existing_rp, [])

    def test_have_traits_changed(self):
        cn = self.compute_node1
        pt = self._pt_with_cns()
        rp_gen = 1

        traits = [
            "HW_GPU_API_DIRECT3D_V7_0",
            "HW_NIC_OFFLOAD_SG",
            "HW_CPU_X86_AVX",
        ]
        self.assertTrue(pt.have_traits_changed(cn.uuid, traits))
        # A data-grab's traits are the same
        cnsnap = pt.data(cn.uuid)
        self.assertFalse(pt.have_traits_changed(cn.uuid, cnsnap.traits))
        self.assertTrue(pt.has_traits(cn.uuid, []))
        self.assertFalse(pt.has_traits(cn.uuid, traits))
        self.assertFalse(pt.has_traits(cn.uuid, traits[:1]))
        self.assertTrue(pt.update_traits(cn.uuid, traits, generation=rp_gen))
        self.assertTrue(pt.has_traits(cn.uuid, traits))
        self.assertTrue(pt.has_traits(cn.uuid, traits[:1]))

        # Updating with the same traits info should return False
        self.assertFalse(pt.have_traits_changed(cn.uuid, traits))
        # But the generation should get updated
        rp_gen = 2
        self.assertFalse(pt.update_traits(cn.uuid, traits, generation=rp_gen))
        self.assertFalse(pt.have_traits_changed(cn.uuid, traits))
        self.assertEqual(rp_gen, pt.data(cn.uuid).generation)
        self.assertTrue(pt.has_traits(cn.uuid, traits))
        self.assertTrue(pt.has_traits(cn.uuid, traits[:1]))

        # Make a change to the traits list
        traits.append("HW_GPU_RESOLUTION_W800H600")
        self.assertTrue(pt.have_traits_changed(cn.uuid, traits))
        # The previously-taken data now differs
        self.assertTrue(pt.have_traits_changed(cn.uuid, cnsnap.traits))
        self.assertFalse(pt.has_traits(cn.uuid, traits[-1:]))
        # Don't update the generation
        self.assertTrue(pt.update_traits(cn.uuid, traits))
        self.assertEqual(rp_gen, pt.data(cn.uuid).generation)
        self.assertTrue(pt.has_traits(cn.uuid, traits[-1:]))

    def test_add_remove_traits(self):
        cn = self.compute_node1
        pt = self._pt_with_cns()
        self.assertEqual(set([]), pt.data(cn.uuid).traits)
        # Test adding with no trait provided for a bogus provider
        pt.add_traits('bogus-uuid')
        self.assertEqual(
            set([]),
            pt.data(cn.uuid).traits
        )
        # Add a couple of traits
        pt.add_traits(cn.uuid, "HW_GPU_API_DIRECT3D_V7_0", "HW_NIC_OFFLOAD_SG")
        self.assertEqual(
            set(["HW_GPU_API_DIRECT3D_V7_0", "HW_NIC_OFFLOAD_SG"]),
            pt.data(cn.uuid).traits)
        # set() behavior: add a trait that's already there, and one that's not.
        # The unrelated one is unaffected.
        pt.add_traits(cn.uuid, "HW_GPU_API_DIRECT3D_V7_0", "HW_CPU_X86_AVX")
        self.assertEqual(
            set(["HW_GPU_API_DIRECT3D_V7_0", "HW_NIC_OFFLOAD_SG",
                 "HW_CPU_X86_AVX"]),
            pt.data(cn.uuid).traits)
        # Test removing with no trait provided for a bogus provider
        pt.remove_traits('bogus-uuid')
        self.assertEqual(
            set(["HW_GPU_API_DIRECT3D_V7_0", "HW_NIC_OFFLOAD_SG",
                 "HW_CPU_X86_AVX"]),
            pt.data(cn.uuid).traits)
        # Now remove a trait
        pt.remove_traits(cn.uuid, "HW_NIC_OFFLOAD_SG")
        self.assertEqual(
            set(["HW_GPU_API_DIRECT3D_V7_0", "HW_CPU_X86_AVX"]),
            pt.data(cn.uuid).traits)
        # set() behavior: remove a trait that's there, and one that's not.
        # The unrelated one is unaffected.
        pt.remove_traits(cn.uuid,
                         "HW_NIC_OFFLOAD_SG", "HW_GPU_API_DIRECT3D_V7_0")
        self.assertEqual(set(["HW_CPU_X86_AVX"]), pt.data(cn.uuid).traits)
        # Remove the last trait, and an unrelated one
        pt.remove_traits(cn.uuid, "CUSTOM_FOO", "HW_CPU_X86_AVX")
        self.assertEqual(set([]), pt.data(cn.uuid).traits)

    def test_have_aggregates_changed_no_existing_rp(self):
        pt = self._pt_with_cns()
        self.assertRaises(
            ValueError, pt.have_aggregates_changed, uuids.non_existing_rp, [])

    def test_update_aggregates_no_existing_rp(self):
        pt = self._pt_with_cns()
        self.assertRaises(
            ValueError, pt.update_aggregates, uuids.non_existing_rp, [])

    def test_have_aggregates_changed(self):
        cn = self.compute_node1
        pt = self._pt_with_cns()
        rp_gen = 1

        aggregates = [
            uuids.agg1,
            uuids.agg2,
        ]
        self.assertTrue(pt.have_aggregates_changed(cn.uuid, aggregates))
        self.assertTrue(pt.in_aggregates(cn.uuid, []))
        self.assertFalse(pt.in_aggregates(cn.uuid, aggregates))
        self.assertFalse(pt.in_aggregates(cn.uuid, aggregates[:1]))
        self.assertTrue(pt.update_aggregates(cn.uuid, aggregates,
                                             generation=rp_gen))
        self.assertTrue(pt.in_aggregates(cn.uuid, aggregates))
        self.assertTrue(pt.in_aggregates(cn.uuid, aggregates[:1]))

        # data() gets the same aggregates
        cnsnap = pt.data(cn.uuid)
        self.assertFalse(
            pt.have_aggregates_changed(cn.uuid, cnsnap.aggregates))

        # Updating with the same aggregates info should return False
        self.assertFalse(pt.have_aggregates_changed(cn.uuid, aggregates))
        # But the generation should get updated
        rp_gen = 2
        self.assertFalse(pt.update_aggregates(cn.uuid, aggregates,
                                              generation=rp_gen))
        self.assertFalse(pt.have_aggregates_changed(cn.uuid, aggregates))
        self.assertEqual(rp_gen, pt.data(cn.uuid).generation)
        self.assertTrue(pt.in_aggregates(cn.uuid, aggregates))
        self.assertTrue(pt.in_aggregates(cn.uuid, aggregates[:1]))

        # Make a change to the aggregates list
        aggregates.append(uuids.agg3)
        self.assertTrue(pt.have_aggregates_changed(cn.uuid, aggregates))
        self.assertFalse(pt.in_aggregates(cn.uuid, aggregates[-1:]))
        # Don't update the generation
        self.assertTrue(pt.update_aggregates(cn.uuid, aggregates))
        self.assertEqual(rp_gen, pt.data(cn.uuid).generation)
        self.assertTrue(pt.in_aggregates(cn.uuid, aggregates[-1:]))
        # Previously-taken data now differs
        self.assertTrue(pt.have_aggregates_changed(cn.uuid, cnsnap.aggregates))

    def test_add_remove_aggregates(self):
        cn = self.compute_node1
        pt = self._pt_with_cns()
        self.assertEqual(set([]), pt.data(cn.uuid).aggregates)
        # Add a couple of aggregates
        pt.add_aggregates(cn.uuid, uuids.agg1, uuids.agg2)
        self.assertEqual(
            set([uuids.agg1, uuids.agg2]),
            pt.data(cn.uuid).aggregates)
        # set() behavior: add an aggregate that's already there, and one that's
        # not. The unrelated one is unaffected.
        pt.add_aggregates(cn.uuid, uuids.agg1, uuids.agg3)
        self.assertEqual(set([uuids.agg1, uuids.agg2, uuids.agg3]),
                         pt.data(cn.uuid).aggregates)
        # Now remove an aggregate
        pt.remove_aggregates(cn.uuid, uuids.agg2)
        self.assertEqual(set([uuids.agg1, uuids.agg3]),
                         pt.data(cn.uuid).aggregates)
        # set() behavior: remove an aggregate that's there, and one that's not.
        # The unrelated one is unaffected.
        pt.remove_aggregates(cn.uuid, uuids.agg2, uuids.agg3)
        self.assertEqual(set([uuids.agg1]), pt.data(cn.uuid).aggregates)
        # Remove the last aggregate, and an unrelated one
        pt.remove_aggregates(cn.uuid, uuids.agg4, uuids.agg1)
        self.assertEqual(set([]), pt.data(cn.uuid).aggregates)

    def test_update_resources_no_existing_rp(self):
        pt = self._pt_with_cns()
        self.assertRaises(
            ValueError,
            pt.update_resources,
            uuids.non_existing_rp,
            {},
        )

    def test_update_resources(self):
        cn = self.compute_node1
        pt = self._pt_with_cns()

        cn_resources = {
            "CUSTOM_RESOURCE_0": {
                objects.Resource(provider_uuid=cn.uuid,
                                 resource_class="CUSTOM_RESOURCE_0",
                                 identifier="bar")},
            "CUSTOM_RESOURCE_1": {
                objects.Resource(provider_uuid=cn.uuid,
                                 resource_class="CUSTOM_RESOURCE_1",
                                 identifier="foo_1"),
                objects.Resource(provider_uuid=cn.uuid,
                                 resource_class="CUSTOM_RESOURCE_1",
                                 identifier="foo_2")}}
        # resources changed
        self.assertTrue(pt.update_resources(cn.uuid, cn_resources))
        # resources not changed
        self.assertFalse(pt.update_resources(cn.uuid, cn_resources))
