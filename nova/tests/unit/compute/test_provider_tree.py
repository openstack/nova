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

        numa_cell0 = pt.new_child('numa_cell0', cn1.uuid)
        numa_cell1 = pt.new_child('numa_cell1', cn1.uuid)

        self.assertEqual(numa_cell0, pt.find('numa_cell0'))
        self.assertEqual(numa_cell0, pt.find(numa_cell0.uuid))

        self.assertTrue(pt.exists(numa_cell0.uuid))
        self.assertTrue(pt.exists('numa_cell0'))

        self.assertTrue(pt.exists(numa_cell1.uuid))
        self.assertTrue(pt.exists('numa_cell1'))

        pf1_cell0 = pt.new_child('pf1_cell0', numa_cell0.uuid)
        self.assertTrue(pt.exists(pf1_cell0.uuid))
        self.assertTrue(pt.exists('pf1_cell0'))

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

        # Save numa cell1 uuid since removing will invalidate the object
        cell0_uuid = numa_cell0.uuid
        cell1_uuid = numa_cell1.uuid
        pf1_uuid = pf1_cell0.uuid

        pt.remove(cell1_uuid)
        self.assertFalse(pt.exists(cell1_uuid))
        self.assertTrue(pt.exists(pf1_uuid))
        self.assertTrue(pt.exists(cell0_uuid))
        self.assertTrue(pt.exists(uuids.cn1))

        # Now remove the root and check that children no longer exist
        pt.remove(uuids.cn1)
        self.assertFalse(pt.exists(pf1_uuid))
        self.assertFalse(pt.exists(cell0_uuid))
        self.assertFalse(pt.exists(uuids.cn1))
