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

from nova import context
from nova import objects
from nova.objects import fields as obj_fields
from nova import test
from nova.tests import uuidsentinel

_HOSTNAME = 'fake-host'
_NODENAME = 'fake-node'

_VIRT_DRIVER_AVAIL_RESOURCES = {
    'vcpus': 4,
    'memory_mb': 512,
    'local_gb': 6,
    'vcpus_used': 0,
    'memory_mb_used': 0,
    'local_gb_used': 0,
    'hypervisor_type': 'fake',
    'hypervisor_version': 0,
    'hypervisor_hostname': _NODENAME,
    'cpu_info': '',
    'numa_topology': None,
}

fake_compute_obj = objects.ComputeNode(
    host=_HOSTNAME,
    vcpus=_VIRT_DRIVER_AVAIL_RESOURCES['vcpus'],
    memory_mb=_VIRT_DRIVER_AVAIL_RESOURCES['memory_mb'],
    local_gb=_VIRT_DRIVER_AVAIL_RESOURCES['local_gb'],
    vcpus_used=_VIRT_DRIVER_AVAIL_RESOURCES['vcpus_used'],
    memory_mb_used=_VIRT_DRIVER_AVAIL_RESOURCES['memory_mb_used'],
    local_gb_used=_VIRT_DRIVER_AVAIL_RESOURCES['local_gb_used'],
    hypervisor_type='fake',
    hypervisor_version=0,
    hypervisor_hostname=_HOSTNAME,
    free_ram_mb=(_VIRT_DRIVER_AVAIL_RESOURCES['memory_mb'] -
                 _VIRT_DRIVER_AVAIL_RESOURCES['memory_mb_used']),
    free_disk_gb=(_VIRT_DRIVER_AVAIL_RESOURCES['local_gb'] -
                  _VIRT_DRIVER_AVAIL_RESOURCES['local_gb_used']),
    current_workload=0,
    running_vms=0,
    cpu_info='{}',
    disk_available_least=0,
    host_ip='1.1.1.1',
    supported_hv_specs=[
        objects.HVSpec.from_list([
            obj_fields.Architecture.I686,
            obj_fields.HVType.KVM,
            obj_fields.VMMode.HVM])
    ],
    metrics=None,
    pci_device_pools=None,
    extra_resources=None,
    stats={},
    numa_topology=None,
    cpu_allocation_ratio=16.0,
    ram_allocation_ratio=1.5,
    disk_allocation_ratio=1.0,
    )


class ComputeNodeTestCase(test.TestCase):

    def setUp(self):
        super(ComputeNodeTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def test_get_all_by_uuids(self):
        cn1 = fake_compute_obj.obj_clone()
        cn1._context = self.context
        cn1.create()
        cn2 = fake_compute_obj.obj_clone()
        cn2._context = self.context
        # Two compute nodes can't have the same tuple (host, node, deleted)
        cn2.host = _HOSTNAME + '2'
        cn2.create()

        cns = objects.ComputeNodeList.get_all_by_uuids(self.context, [])
        self.assertEqual(0, len(cns))

        # Ensure that asking for one compute node when there are multiple only
        # returns the one we want.
        cns = objects.ComputeNodeList.get_all_by_uuids(self.context,
                                                       [cn1.uuid])
        self.assertEqual(1, len(cns))

        cns = objects.ComputeNodeList.get_all_by_uuids(self.context,
                                                       [cn1.uuid, cn2.uuid])
        self.assertEqual(2, len(cns))

        # Ensure that asking for a non-existing UUID along with
        # existing UUIDs doesn't limit the return of the existing
        # compute nodes...
        cns = objects.ComputeNodeList.get_all_by_uuids(self.context,
                                                       [cn1.uuid, cn2.uuid,
                                                        uuidsentinel.noexists])
        self.assertEqual(2, len(cns))

    def test_get_by_hypervisor_type(self):
        cn1 = fake_compute_obj.obj_clone()
        cn1._context = self.context
        cn1.hypervisor_type = 'ironic'
        cn1.create()

        cn2 = fake_compute_obj.obj_clone()
        cn2._context = self.context
        cn2.hypervisor_type = 'libvirt'
        cn2.host += '-alt'
        cn2.create()

        cns = objects.ComputeNodeList.get_by_hypervisor_type(self.context,
                                                             'ironic')
        self.assertEqual(1, len(cns))
        self.assertEqual(cn1.uuid, cns[0].uuid)
