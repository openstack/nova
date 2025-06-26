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
from unittest import mock

from oslo_utils.fixture import uuidsentinel as uuids
from oslo_versionedobjects import base as ovo_base
import testtools

from nova import exception
from nova import objects
from nova.objects import fields
from nova.tests.unit.objects import test_objects


fake_instance_uuid = uuids.fake

fake_obj_numa_topology = objects.InstanceNUMATopology(
    instance_uuid=fake_instance_uuid,
    cells=[
        objects.InstanceNUMACell(
            id=0, cpuset=set(), pcpuset=set([1, 2]),
            cpuset_reserved=set([5, 6]), memory=512,
            pagesize=2048),
        objects.InstanceNUMACell(
            id=1, cpuset=set(), pcpuset=set([3, 4]),
            cpuset_reserved=set([7, 8]), memory=512,
            pagesize=2048),
    ])

fake_db_topology = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'instance_uuid': fake_instance_uuid,
    'numa_topology': fake_obj_numa_topology._to_json()
    }


def get_fake_obj_numa_topology(context):
    fake_obj_numa_topology_cpy = fake_obj_numa_topology.obj_clone()
    fake_obj_numa_topology_cpy._context = context
    return fake_obj_numa_topology_cpy


class _TestInstanceNUMACell(object):

    def test_siblings(self):
        # default thread number of VirtualCPUTopology is one, one thread means
        # no thread and no sibling
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([0, 1, 2]), pcpuset=set())
        self.assertEqual([], inst_cell.siblings)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([0, 1, 2]), pcpuset=set([4, 5, 6]))
        self.assertEqual([], inst_cell.siblings)

        # 'threads=0' means no sibling
        topo = objects.VirtCPUTopology(sockets=1, cores=3, threads=0)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([0, 1, 2]), pcpuset=set(), cpu_topology=topo)
        self.assertEqual([], inst_cell.siblings)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set(), pcpuset=set([0, 1, 2]), cpu_topology=topo)
        self.assertEqual([], inst_cell.siblings)

        # One thread actually means no threads
        topo = objects.VirtCPUTopology(sockets=1, cores=3, threads=1)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([0, 1, 2]), pcpuset=set(), cpu_topology=topo)
        self.assertEqual([], inst_cell.siblings)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set(), pcpuset=set([0, 1, 2]), cpu_topology=topo)
        self.assertEqual([], inst_cell.siblings)

        # 2 threads per virtual core, and numa node has only one type CPU
        # pinned and un-pinned.
        topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=2)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([0, 1, 2, 3]), pcpuset=set(), cpu_topology=topo)
        self.assertEqual([set([0, 1]), set([2, 3])], inst_cell.siblings)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set(), pcpuset=set([0, 1, 2, 3]), cpu_topology=topo)
        self.assertEqual([set([0, 1]), set([2, 3])], inst_cell.siblings)

        # 4 threads per virtual core, numa node has only one type CPU
        topo = objects.VirtCPUTopology(sockets=1, cores=1, threads=4)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([0, 1, 2, 3]), pcpuset=set(), cpu_topology=topo)
        self.assertEqual([set([0, 1, 2, 3])], inst_cell.siblings)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set(), pcpuset=set([0, 1, 2, 3]), cpu_topology=topo)
        self.assertEqual([set([0, 1, 2, 3])], inst_cell.siblings)

        # 2 threads per virtual core, numa node with two type CPUs, the pinned
        # and un-pinned
        topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=2)
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([0, 1]), pcpuset=set([2, 3]), cpu_topology=topo)
        self.assertEqual([set([0, 1]), set([2, 3])], inst_cell.siblings)

    def test_pin(self):
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([4, 5]), pcpuset=set([0, 1, 2, 3]), cpu_pinning=None)

        # Only vCPU in the 'pcpuset' list is eligible for pinning
        inst_cell.pin(0, 14)
        self.assertEqual({0: 14}, inst_cell.cpu_pinning)

        # vCPU 12 is not a CPU of this cell, drop silently
        inst_cell.pin(12, 14)
        self.assertEqual({0: 14}, inst_cell.cpu_pinning)

        # vCPU in the 'cpuset' which is for floating CPUs, drop silently
        inst_cell.pin(4, 15)
        self.assertEqual({0: 14}, inst_cell.cpu_pinning)

        # Another vCPU appeared in 'pcpuset', ready for pinning
        inst_cell.pin(1, 16)
        self.assertEqual({0: 14, 1: 16}, inst_cell.cpu_pinning)

    def test_pin_vcpus(self):
        inst_cell = objects.InstanceNUMACell(
            cpuset=set([4, 5]), pcpuset=set([0, 1, 2, 3]), cpu_pinning=None)

        # 'pcpuset' is the vCPU list for pinning
        inst_cell.pin_vcpus((0, 14), (1, 15), (2, 16), (3, 17))
        self.assertEqual({0: 14, 1: 15, 2: 16, 3: 17}, inst_cell.cpu_pinning)

        # vCPU out of 'pcpuset' list will not be added to the CPU pinning list
        inst_cell.pin_vcpus((0, 14), (1, 15), (2, 16), (3, 17), (4, 18))
        self.assertEqual({0: 14, 1: 15, 2: 16, 3: 17}, inst_cell.cpu_pinning)

        # vCPU not belonging to this cell will be dropped silently
        inst_cell.pin_vcpus((0, 14), (1, 15), (2, 16), (3, 17), (10, 18))
        self.assertEqual({0: 14, 1: 15, 2: 16, 3: 17}, inst_cell.cpu_pinning)

    def test_cpu_pinning(self):
        topo_obj = get_fake_obj_numa_topology(self.context)
        self.assertEqual(set(), topo_obj.cpu_pinning)

        topo_obj.cells[0].pin_vcpus((1, 10), (2, 11))
        self.assertEqual(set([10, 11]), topo_obj.cpu_pinning)

        topo_obj.cells[1].pin_vcpus((3, 0), (4, 1))
        self.assertEqual(set([0, 1, 10, 11]), topo_obj.cpu_pinning)

    def test_cpuset_reserved(self):
        topo_obj = get_fake_obj_numa_topology(self.context)
        self.assertEqual(set([5, 6, 7, 8]), topo_obj.cpuset_reserved)

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

    def test_emulator_threads_policy(self):
        topo_obj = get_fake_obj_numa_topology(self.context)
        self.assertFalse(topo_obj.emulator_threads_isolated)
        topo_obj.emulator_threads_policy = (
            fields.CPUEmulatorThreadsPolicy.ISOLATE)
        self.assertTrue(topo_obj.emulator_threads_isolated)

    def test_obj_make_compatible(self):
        topo_obj = objects.InstanceNUMACell(
            cpuset=set(), pcpuset=set([0, 1]),
            cpuset_reserved=set([1, 2]),
            cpu_policy=fields.CPUAllocationPolicy.MIXED,
        )
        versions = ovo_base.obj_tree_get_versions('InstanceNUMACell')
        data = lambda x: x['nova_object.data']

        primitive = data(topo_obj.obj_to_primitive(
            target_version='1.6', version_manifest=versions))
        self.assertEqual(
            fields.CPUAllocationPolicy.MIXED, primitive['cpu_policy'])

        self.assertRaises(
            exception.ObjectActionError,
            topo_obj.obj_to_primitive,
            target_version='1.5', version_manifest=versions)

        # set this to something compatible with <  1.6 so we can keep testing
        topo_obj.cpu_policy = fields.CPUAllocationPolicy.DEDICATED
        primitive = data(topo_obj.obj_to_primitive(
            target_version='1.5', version_manifest=versions))
        self.assertIn('pcpuset', primitive)

        primitive = data(topo_obj.obj_to_primitive(
            target_version='1.4', version_manifest=versions))
        self.assertNotIn('pcpuset', primitive)
        self.assertEqual(set([0, 1]), set(primitive['cpuset']))
        self.assertIn('cpuset_reserved', primitive)

        primitive = data(topo_obj.obj_to_primitive(
            target_version='1.3', version_manifest=versions))
        self.assertNotIn('cpuset_reserved', primitive)


class TestInstanceNUMACell(
    test_objects._LocalTest, _TestInstanceNUMACell,
):
    pass


class TestInstanceNUMACellRemote(
    test_objects._RemoteTest, _TestInstanceNUMACell,
):
    pass


class _TestInstanceNUMATopology(object):

    @mock.patch('nova.db.main.api.instance_extra_update_by_uuid')
    def test_create(self, mock_update):
        topo_obj = get_fake_obj_numa_topology(self.context)
        topo_obj.instance_uuid = fake_db_topology['instance_uuid']
        topo_obj.create()
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

    @mock.patch('nova.db.main.api.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid(self, mock_get):
        mock_get.return_value = fake_db_topology
        self._test_get_by_instance_uuid()

    @mock.patch('nova.db.main.api.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid_missing(self, mock_get):
        mock_get.return_value = None
        self.assertRaises(
            exception.NumaTopologyNotFound,
            objects.InstanceNUMATopology.get_by_instance_uuid,
            self.context, 'fake_uuid')

    def test_cpu_policy(self):
        cpu_policy = fields.CPUAllocationPolicy.SHARED
        topology = objects.InstanceNUMATopology(
            instance_uuid=fake_instance_uuid,
            cells=[
                objects.InstanceNUMACell(
                    cpuset=set([0, 1, 2, 3]),
                    pcpuset=set(),
                    cpu_pinning=None,
                    cpu_policy=cpu_policy,
                ),
                objects.InstanceNUMACell(
                    cpuset=set([4, 5, 6, 7]),
                    pcpuset=set(),
                    cpu_pinning=None,
                    cpu_policy=cpu_policy,
                ),
            ],
        )

        self.assertEqual(cpu_policy, topology.cpu_policy)

    def test_cpu_policy__error(self):
        """Ensure we raise an error if cells have different values."""
        topology = objects.InstanceNUMATopology(
            instance_uuid=fake_instance_uuid,
            cells=[
                objects.InstanceNUMACell(
                    cpuset=set([0, 1, 2, 3]),
                    pcpuset=set(),
                    cpu_pinning=None,
                    cpu_policy=None,
                ),
                objects.InstanceNUMACell(
                    cpuset=set([4, 5, 6, 7]),
                    pcpuset=set(),
                    cpu_pinning=None,
                    cpu_policy=fields.CPUAllocationPolicy.SHARED
                ),
            ],
        )

        with testtools.ExpectedException(exception.InternalError):
            topology.cpu_policy

    def test_cpuset_reserved(self):
        topology = objects.InstanceNUMATopology(
            instance_uuid=fake_instance_uuid,
            cells=[
                objects.InstanceNUMACell(
                    id=0, cpuset=set([1, 2]), pcpuset=set(), memory=512,
                    pagesize=2048, cpuset_reserved=set([3, 7])),
                objects.InstanceNUMACell(
                    id=1, cpuset=set([3, 4]), pcpuset=set(), memory=512,
                    pagesize=2048, cpuset_reserved=set([9, 12]))
            ])
        self.assertEqual(set([3, 7]), topology.cells[0].cpuset_reserved)
        self.assertEqual(set([9, 12]), topology.cells[1].cpuset_reserved)

    def test_obj_make_compatible_numa(self):
        topo_obj = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE))
        versions = ovo_base.obj_tree_get_versions('InstanceNUMATopology')
        primitive = topo_obj.obj_to_primitive(target_version='1.2',
                                              version_manifest=versions)
        self.assertNotIn(
            'emulator_threads_policy', primitive['nova_object.data'])

        topo_obj = objects.InstanceNUMATopology.obj_from_primitive(primitive)
        self.assertFalse(topo_obj.emulator_threads_isolated)

    def test_obj_from_db_obj(self):
        """Test of creating 'InstanceNUMATopology' OVO object from the
        database primitives, which has an old version 'InstanceNUMACell'
        primitives.

        Prior to version 1.5, 'InstanceNUMACell' saves the instance CPUs in the
        'cpuset' field, for both the pinned CPUs of a dedicated and the
        un-pinned CPUs of a shared instances, after version 1.5, any pinned
        CPUs of dedicated instance are moved to 'pcpuset'. this test verifies
        the CPU movement for instance with a 'dedicated' allocation policy.
        """
        fake_topo_obj_w_cell_v1_4 = objects.InstanceNUMATopology(
            instance_uuid=fake_instance_uuid,
            cells=[
                objects.InstanceNUMACell(
                    id=0, cpuset=set([1, 2]), pcpuset=set(), memory=512,
                    pagesize=2048),
                objects.InstanceNUMACell(
                    id=1, cpuset=set([3, 4]), pcpuset=set(), memory=512,
                    pagesize=2048),
            ])

        fake_topo_obj = copy.deepcopy(fake_topo_obj_w_cell_v1_4)
        for cell in fake_topo_obj.cells:
            cell.cpu_policy = objects.fields.CPUAllocationPolicy.DEDICATED

        numa_topology = objects.InstanceNUMATopology.obj_from_db_obj(
            self.context, fake_instance_uuid, fake_topo_obj._to_json())

        for obj_cell, topo_cell in zip(
                numa_topology.cells,
                fake_topo_obj_w_cell_v1_4['cells']):
            self.assertEqual(set(), obj_cell.cpuset)
            self.assertEqual(topo_cell.cpuset, obj_cell.pcpuset)

    def test_obj_from_db_obj_no_pinning(self):
        """Test of creating 'InstanceNUMATopology' OVO object from the
        database primitives, which has an old version 'InstanceNUMACell'
        primitives.

        Prior to version 1.5, 'InstanceNUMACell' saves the instance CPUs in
        the 'cpuset' field, for both the pinned CPUs of a dedicated and the
        un-pinned CPUs of a shared instances, after version 1.5, any pinned
        CPUs of dedicated instance are moved to 'pcpuset'. this test verifies
        the CPU movement for instance with a 'dedicated' allocation policy.

        This test is for the case where the instance has no pinned CPUs but
        the instance has a numa topology such as when hugepages are used.
        See bug: https://bugs.launchpad.net/nova/+bug/2080556 for more details.
        """
        fake_topo_obj_w_cell_v1_4 = objects.InstanceNUMATopology(
            instance_uuid=fake_instance_uuid,
            cells=[
                objects.InstanceNUMACell(
                    id=0, cpuset=set([1, 2]), memory=512,
                    pagesize=2048),
                objects.InstanceNUMACell(
                    id=1, cpuset=set([3, 4]), memory=512,
                    pagesize=2048),
            ])

        fake_topo_obj = copy.deepcopy(fake_topo_obj_w_cell_v1_4)
        for cell in fake_topo_obj.cells:
            cell.cpu_policy = objects.fields.CPUAllocationPolicy.SHARED

        numa_topology = objects.InstanceNUMATopology.obj_from_db_obj(
            self.context, fake_instance_uuid, fake_topo_obj._to_json())

        for obj_cell, topo_cell in zip(
                numa_topology.cells,
                fake_topo_obj_w_cell_v1_4['cells']):
            self.assertEqual(topo_cell.cpuset, obj_cell.cpuset)
            self.assertEqual(set(), obj_cell.pcpuset)


class TestInstanceNUMATopology(
    test_objects._LocalTest, _TestInstanceNUMATopology,
):
    pass


class TestInstanceNUMATopologyRemote(
    test_objects._RemoteTest, _TestInstanceNUMATopology,
):
    pass
