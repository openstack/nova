# Copyright 2017 Huawei Technologies Co.,LTD.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests import uuidsentinel as uuids


class ComputeHostAPIMultiCellTestCase(test.NoDBTestCase):
    """Tests for the HostAPI with multiple cells."""

    USES_DB_SELF = True

    def setUp(self):
        super(ComputeHostAPIMultiCellTestCase, self).setUp()
        self.host_api = compute_api.HostAPI()
        self.useFixture(nova_fixtures.Database(database='api'))
        celldbs = nova_fixtures.CellDatabases()
        celldbs.add_cell_database(objects.CellMapping.CELL0_UUID)
        celldbs.add_cell_database(uuids.cell1, default=True)
        celldbs.add_cell_database(uuids.cell2)
        self.useFixture(celldbs)

        self.ctxt = context.get_admin_context()
        cell0 = objects.CellMapping(
            context=self.ctxt, uuid=objects.CellMapping.CELL0_UUID,
            database_connection=objects.CellMapping.CELL0_UUID,
            transport_url='none:///')
        cell0.create()
        cell1 = objects.CellMapping(
            context=self.ctxt, uuid=uuids.cell1,
            database_connection=uuids.cell1, transport_url='none:///')
        cell1.create()
        cell2 = objects.CellMapping(
            context=self.ctxt, uuid=uuids.cell2,
            database_connection=uuids.cell2, transport_url='none:///')
        cell2.create()
        self.cell_mappings = (cell0, cell1, cell2)

    def test_compute_node_get_all_uuid_marker(self):
        """Tests paging over multiple cells with a uuid marker.

        This test is going to setup three compute nodes in two cells for a
        total of six compute nodes. Then it will page over them with a limit
        of two so there should be three pages total.
        """
        # create the compute nodes in the non-cell0 cells
        count = 0
        for cell in self.cell_mappings[1:]:
            for x in range(3):
                compute_node_uuid = getattr(uuids, 'node_%s' % count)
                with context.target_cell(self.ctxt, cell) as cctxt:
                    node = objects.ComputeNode(
                        cctxt, uuid=compute_node_uuid, host=compute_node_uuid,
                        vcpus=2, memory_mb=2048, local_gb=128, vcpus_used=0,
                        memory_mb_used=0, local_gb_used=0, cpu_info='{}',
                        hypervisor_type='fake', hypervisor_version=10)
                    node.create()
                    count += 1

                # create a host mapping for the compute to link it to the cell
                host_mapping = objects.HostMapping(
                    self.ctxt, host=compute_node_uuid, cell_mapping=cell)
                host_mapping.create()

        # now start paging with a limit of two per page; the first page starts
        # with no marker
        compute_nodes = self.host_api.compute_node_get_all(self.ctxt, limit=2)
        # assert that we got two compute nodes from cell1
        self.assertEqual(2, len(compute_nodes))
        for compute_node in compute_nodes:
            host_mapping = objects.HostMapping.get_by_host(
                self.ctxt, compute_node.host)
            self.assertEqual(uuids.cell1, host_mapping.cell_mapping.uuid)

        # now our marker is the last item in the first page
        marker = compute_nodes[-1].uuid
        compute_nodes = self.host_api.compute_node_get_all(
            self.ctxt, limit=2, marker=marker)
        # assert that we got the last compute node from cell1 and the first
        # compute node from cell2
        self.assertEqual(2, len(compute_nodes))
        host_mapping = objects.HostMapping.get_by_host(
            self.ctxt, compute_nodes[0].host)
        self.assertEqual(uuids.cell1, host_mapping.cell_mapping.uuid)
        host_mapping = objects.HostMapping.get_by_host(
            self.ctxt, compute_nodes[1].host)
        self.assertEqual(uuids.cell2, host_mapping.cell_mapping.uuid)

        # now our marker is the last item in the second page; make the limit=3
        # so we make sure we've exhausted the pages
        marker = compute_nodes[-1].uuid
        compute_nodes = self.host_api.compute_node_get_all(
            self.ctxt, limit=3, marker=marker)
        # assert that we got two compute nodes from cell2
        self.assertEqual(2, len(compute_nodes))
        for compute_node in compute_nodes:
            host_mapping = objects.HostMapping.get_by_host(
                self.ctxt, compute_node.host)
            self.assertEqual(uuids.cell2, host_mapping.cell_mapping.uuid)

    def test_compute_node_get_all_uuid_marker_not_found(self):
        """Simple test to make sure we get MarkerNotFound raised up if we try
        paging with a uuid marker that is not found in any cell.
        """
        self.assertRaises(exception.MarkerNotFound,
                          self.host_api.compute_node_get_all,
                          self.ctxt, limit=10, marker=uuids.not_found)
