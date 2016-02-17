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

import copy
import uuid

import mock
from oslo_serialization import jsonutils

from nova import exception
from nova import objects
from nova.objects import fields
from nova.tests.unit.objects import test_objects

fake_instance_uuid = str(uuid.uuid4())

fake_obj_numa_topology = objects.InstanceNUMATopology(
    instance_uuid = fake_instance_uuid,
    cells=[
        objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2]), memory=512, pagesize=2048),
        objects.InstanceNUMACell(
            id=1, cpuset=set([3, 4]), memory=512, pagesize=2048)
    ])

fake_numa_topology = fake_obj_numa_topology._to_dict()

fake_db_topology = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'instance_uuid': fake_instance_uuid,
    'numa_topology': fake_obj_numa_topology._to_json()
    }

fake_old_db_topology = dict(fake_db_topology)  # copy
fake_old_db_topology['numa_topology'] = jsonutils.dumps(fake_numa_topology)


def get_fake_obj_numa_topology(context):
    fake_obj_numa_topology_cpy = fake_obj_numa_topology.obj_clone()
    fake_obj_numa_topology_cpy._context = context
    return fake_obj_numa_topology_cpy


class _TestInstanceNUMATopology(object):
    @mock.patch('nova.db.instance_extra_update_by_uuid')
    def test_create(self, mock_update):
        topo_obj = get_fake_obj_numa_topology(self.context)
        topo_obj.instance_uuid = fake_db_topology['instance_uuid']
        topo_obj.create()
        self.assertEqual(1, len(mock_update.call_args_list))

    @mock.patch('nova.db.instance_extra_update_by_uuid')
    def test_save(self, mock_update):
        topo_obj = get_fake_obj_numa_topology(self.context)
        topo_obj.instance_uuid = fake_db_topology['instance_uuid']
        topo_obj._save()
        self.assertEqual(1, len(mock_update.call_args_list))

    def _test_get_by_instance_uuid(self):
        numa_topology = objects.InstanceNUMATopology.get_by_instance_uuid(
            self.context, fake_db_topology['instance_uuid'])
        self.assertEqual(fake_db_topology['instance_uuid'],
                         numa_topology.instance_uuid)
        for obj_cell, topo_cell in zip(
                numa_topology.cells, fake_obj_numa_topology['cells']):
            self.assertIsInstance(obj_cell, objects.InstanceNUMACell)
            self.assertEqual(topo_cell.id, obj_cell.id)
            self.assertEqual(topo_cell.cpuset, obj_cell.cpuset)
            self.assertEqual(topo_cell.memory, obj_cell.memory)
            self.assertEqual(topo_cell.pagesize, obj_cell.pagesize)

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid(self, mock_get):
        mock_get.return_value = fake_db_topology
        self._test_get_by_instance_uuid()

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid_old(self, mock_get):
        mock_get.return_value = fake_old_db_topology
        self._test_get_by_instance_uuid()

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid_missing(self, mock_get):
        mock_get.return_value = None
        self.assertRaises(
            exception.NumaTopologyNotFound,
            objects.InstanceNUMATopology.get_by_instance_uuid,
            self.context, 'fake_uuid')

    def test_siblings(self):
        inst_cell = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2]))
        self.assertEqual([], inst_cell.siblings)

        topo = objects.VirtCPUTopology(sockets=1, cores=3, threads=0)
        inst_cell = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2]), cpu_topology=topo)
        self.assertEqual([], inst_cell.siblings)

        # One thread actually means no threads
        topo = objects.VirtCPUTopology(sockets=1, cores=3, threads=1)
        inst_cell = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2]), cpu_topology=topo)
        self.assertEqual([], inst_cell.siblings)

        topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=2)
        inst_cell = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]), cpu_topology=topo)
        self.assertEqual([set([0, 1]), set([2, 3])], inst_cell.siblings)

        topo = objects.VirtCPUTopology(sockets=1, cores=1, threads=4)
        inst_cell = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]), cpu_topology=topo)
        self.assertEqual([set([0, 1, 2, 3])], inst_cell.siblings)

    def test_pin(self):
        inst_cell = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                             cpu_pinning=None)
        inst_cell.pin(0, 14)
        self.assertEqual({0: 14}, inst_cell.cpu_pinning)
        inst_cell.pin(12, 14)
        self.assertEqual({0: 14}, inst_cell.cpu_pinning)
        inst_cell.pin(1, 16)
        self.assertEqual({0: 14, 1: 16}, inst_cell.cpu_pinning)

    def test_pin_vcpus(self):
        inst_cell = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                             cpu_pinning=None)
        inst_cell.pin_vcpus((0, 14), (1, 15), (2, 16), (3, 17))
        self.assertEqual({0: 14, 1: 15, 2: 16, 3: 17}, inst_cell.cpu_pinning)

    def test_default_behavior(self):
        inst_cell = objects.InstanceNUMACell()
        self.assertEqual(0, len(inst_cell.obj_get_changes()))

    def test_cpu_pinning_requested_cell(self):
        inst_cell = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                             cpu_pinning=None)
        self.assertFalse(inst_cell.cpu_pinning_requested)
        inst_cell.cpu_policy = fields.CPUAllocationPolicy.DEDICATED
        self.assertTrue(inst_cell.cpu_pinning_requested)

    def test_cpu_pinning_requested(self):
        fake_topo_obj = copy.deepcopy(fake_obj_numa_topology)
        self.assertFalse(fake_topo_obj.cpu_pinning_requested)
        for cell in fake_topo_obj.cells:
            cell.cpu_policy = fields.CPUAllocationPolicy.DEDICATED
        self.assertTrue(fake_topo_obj.cpu_pinning_requested)

    def test_clear_host_pinning(self):
        topo_obj = get_fake_obj_numa_topology(self.context)
        topo_obj.cells[0].pin_vcpus((1, 10), (2, 11))
        topo_obj.cells[0].id = 3
        topo_obj.cells[1].pin_vcpus((3, 0), (4, 1))
        topo_obj.cells[1].id = 0

        topo_obj.clear_host_pinning()

        self.assertEqual({}, topo_obj.cells[0].cpu_pinning)
        self.assertEqual(-1, topo_obj.cells[0].id)
        self.assertEqual({}, topo_obj.cells[1].cpu_pinning)
        self.assertEqual(-1, topo_obj.cells[1].id)


class TestInstanceNUMATopology(test_objects._LocalTest,
                               _TestInstanceNUMATopology):
    pass


class TestInstanceNUMATopologyRemote(test_objects._RemoteTest,
                                     _TestInstanceNUMATopology):
    pass
