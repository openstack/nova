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

from nova.compute import provider_tree
from nova import objects
from nova import test
from nova.tests import uuidsentinel as uuids


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

    def test_tree_ops(self):
        cn1 = self.compute_node1
        cn2 = self.compute_node2
        cns = self.compute_nodes
        pt = provider_tree.ProviderTree(cns)

        self.assertRaises(
            ValueError,
            pt.new_root,
            cn1.hypervisor_hostname,
            cn1.uuid,
            1,
        )

        self.assertTrue(pt.exists(cn1.uuid))
        self.assertTrue(pt.exists(cn1.hypervisor_hostname))
        self.assertFalse(pt.exists(uuids.non_existing_rp))
        self.assertFalse(pt.exists('noexist'))

        self.assertEqual(set([cn1.uuid]),
                         pt.get_provider_uuids(name_or_uuid=cn1.uuid))
        self.assertEqual(set([cn1.uuid, cn2.uuid]), pt.get_provider_uuids())

        numa_cell0_uuid = pt.new_child('numa_cell0', cn1.uuid)
        numa_cell1_uuid = pt.new_child('numa_cell1', cn1.uuid)

        self.assertTrue(pt.exists(numa_cell0_uuid))
        self.assertTrue(pt.exists('numa_cell0'))

        self.assertTrue(pt.exists(numa_cell1_uuid))
        self.assertTrue(pt.exists('numa_cell1'))

        pf1_cell0_uuid = pt.new_child('pf1_cell0', numa_cell0_uuid)
        self.assertTrue(pt.exists(pf1_cell0_uuid))
        self.assertTrue(pt.exists('pf1_cell0'))

        # Now we've got a 3-level tree under cn1 - check provider UUIDs again
        self.assertEqual(
            set([cn1.uuid, numa_cell0_uuid, pf1_cell0_uuid, numa_cell1_uuid]),
            pt.get_provider_uuids(name_or_uuid=cn1.uuid))
        self.assertEqual(
            set([cn1.uuid, cn2.uuid, numa_cell0_uuid, pf1_cell0_uuid,
                 numa_cell1_uuid]),
            pt.get_provider_uuids())

        self.assertRaises(
            ValueError,
            pt.new_child,
            'pf1_cell0',
            uuids.non_existing_rp,
        )

        cn3 = objects.ComputeNode(
            uuid=uuids.cn3,
            hypervisor_hostname='compute-node-3',
        )
        self.assertFalse(pt.exists(cn3.uuid))
        self.assertFalse(pt.exists(cn3.hypervisor_hostname))
        pt.new_root(cn3.hypervisor_hostname, cn3.uuid, 1)

        self.assertTrue(pt.exists(cn3.uuid))
        self.assertTrue(pt.exists(cn3.hypervisor_hostname))

        self.assertRaises(
            ValueError,
            pt.new_root,
            cn3.hypervisor_hostname,
            cn3.uuid,
            1,
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

    def test_has_inventory_changed_no_existing_rp(self):
        cns = self.compute_nodes
        pt = provider_tree.ProviderTree(cns)
        self.assertRaises(
            ValueError,
            pt.has_inventory_changed,
            uuids.non_existing_rp,
            {}
        )

    def test_update_inventory_no_existing_rp(self):
        cns = self.compute_nodes
        pt = provider_tree.ProviderTree(cns)
        self.assertRaises(
            ValueError,
            pt.update_inventory,
            uuids.non_existing_rp,
            {},
            1,
        )

    def test_has_inventory_changed(self):
        cn = self.compute_node1
        cns = self.compute_nodes
        pt = provider_tree.ProviderTree(cns)
        rp_gen = 1

        cn_inv = {
            'VCPU': {
                'total': 8,
                'reserved': 0,
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
        self.assertTrue(pt.update_inventory(cn.uuid, cn_inv, rp_gen))

        # Updating with the same inventory info should return False
        self.assertFalse(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertFalse(pt.update_inventory(cn.uuid, cn_inv, rp_gen))

        cn_inv['VCPU']['total'] = 6
        self.assertTrue(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertTrue(pt.update_inventory(cn.uuid, cn_inv, rp_gen))

        self.assertFalse(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertFalse(pt.update_inventory(cn.uuid, cn_inv, rp_gen))

        # Deleting a key in the new record should NOT result in changes being
        # recorded...
        del cn_inv['VCPU']['allocation_ratio']
        self.assertFalse(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertFalse(pt.update_inventory(cn.uuid, cn_inv, rp_gen))

        del cn_inv['MEMORY_MB']
        self.assertTrue(pt.has_inventory_changed(cn.uuid, cn_inv))
        self.assertTrue(pt.update_inventory(cn.uuid, cn_inv, rp_gen))
