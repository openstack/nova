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
from oslo_utils.fixture import uuidsentinel

import nova.conf
from nova import context
from nova.db import api as db
from nova import objects
from nova.objects import compute_node
from nova.objects import fields as obj_fields
from nova import test

CONF = nova.conf.CONF

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

    def _create_zero_and_none_cn(self):
        cn1 = fake_compute_obj.obj_clone()
        cn1._context = self.context
        cn1.create()

        db.compute_node_update(self.context, cn1.id,
                               {'cpu_allocation_ratio': 0.0,
                                'disk_allocation_ratio': 0.0,
                                'ram_allocation_ratio': 0.0})
        cn1_db = db.compute_node_get(self.context, cn1.id)
        for x in ['cpu', 'disk', 'ram']:
            self.assertEqual(0.0, cn1_db['%s_allocation_ratio' % x])

        cn2 = fake_compute_obj.obj_clone()
        cn2._context = self.context
        cn2.host += '-alt'
        cn2.create()
        # We can't set a cn_obj.xxx_allocation_ratio to None,
        # so we set ratio to None in db directly
        db.compute_node_update(self.context, cn2.id,
                               {'cpu_allocation_ratio': None,
                                'disk_allocation_ratio': None,
                                'ram_allocation_ratio': None})
        cn2_db = db.compute_node_get(self.context, cn2.id)
        for x in ['cpu', 'disk', 'ram']:
            self.assertIsNone(cn2_db['%s_allocation_ratio' % x])

    def test_get_all_by_uuids(self):
        cn1 = fake_compute_obj.obj_clone()
        cn1._context = self.context
        cn1.create()
        cn2 = fake_compute_obj.obj_clone()
        cn2._context = self.context
        # Two compute nodes can't have the same tuple (host, node, deleted)
        cn2.host = _HOSTNAME + '2'
        cn2.create()
        # A deleted compute node
        cn3 = fake_compute_obj.obj_clone()
        cn3._context = self.context
        cn3.host = _HOSTNAME + '3'
        cn3.create()
        cn3.destroy()

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

        # Ensure we don't get the deleted one, even if we ask for it
        cns = objects.ComputeNodeList.get_all_by_uuids(self.context,
                                                       [cn1.uuid, cn2.uuid,
                                                        cn3.uuid])
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

    def test_ratio_online_migration_when_load(self):
        # set cpu and disk, and leave ram unset(None)
        self.flags(cpu_allocation_ratio=1.0)
        self.flags(disk_allocation_ratio=2.0)

        self._create_zero_and_none_cn()

        # trigger online migration
        objects.ComputeNodeList.get_all(self.context)

        cns = db.compute_node_get_all(self.context)

        for cn in cns:
            # the cpu/disk ratio is refreshed to CONF.xxx_allocation_ratio
            self.assertEqual(CONF.cpu_allocation_ratio,
                             cn['cpu_allocation_ratio'])
            self.assertEqual(CONF.disk_allocation_ratio,
                             cn['disk_allocation_ratio'])
            # the ram ratio is refreshed to CONF.initial_xxx_allocation_ratio
            self.assertEqual(CONF.initial_ram_allocation_ratio,
                             cn['ram_allocation_ratio'])

    def test_migrate_empty_ratio(self):
        # we have 5 records to process, the last of which is deleted
        for i in range(5):
            cn = fake_compute_obj.obj_clone()
            cn._context = self.context
            cn.host += '-alt-%s' % i
            cn.create()
            db.compute_node_update(self.context, cn.id,
                                   {'cpu_allocation_ratio': 0.0})
            if i == 4:
                cn.destroy()

        # first only process 2
        res = compute_node.migrate_empty_ratio(self.context, 2)
        self.assertEqual(res, (2, 2))

        # then process others - there should only be 2 found since one
        # of the remaining compute nodes is deleted and gets filtered out
        res = compute_node.migrate_empty_ratio(self.context, 999)
        self.assertEqual(res, (2, 2))

    def test_migrate_none_or_zero_ratio_with_none_ratio_conf(self):
        cn1 = fake_compute_obj.obj_clone()
        cn1._context = self.context
        cn1.create()

        db.compute_node_update(self.context, cn1.id,
                               {'cpu_allocation_ratio': 0.0,
                                'disk_allocation_ratio': 0.0,
                                'ram_allocation_ratio': 0.0})

        self.flags(initial_cpu_allocation_ratio=32.0)
        self.flags(initial_ram_allocation_ratio=8.0)
        self.flags(initial_disk_allocation_ratio=2.0)

        res = compute_node.migrate_empty_ratio(self.context, 1)
        self.assertEqual(res, (1, 1))

        # the ratio is refreshed to CONF.initial_xxx_allocation_ratio
        # beacause CONF.xxx_allocation_ratio is None
        cns = db.compute_node_get_all(self.context)
        # the ratio is refreshed to CONF.xxx_allocation_ratio
        for cn in cns:
            for x in ['cpu', 'disk', 'ram']:
                conf_key = 'initial_%s_allocation_ratio' % x
                key = '%s_allocation_ratio' % x
                self.assertEqual(getattr(CONF, conf_key), cn[key])

    def test_migrate_none_or_zero_ratio_with_not_empty_ratio(self):
        cn1 = fake_compute_obj.obj_clone()
        cn1._context = self.context
        cn1.create()

        db.compute_node_update(self.context, cn1.id,
                               {'cpu_allocation_ratio': 32.0,
                                'ram_allocation_ratio': 4.0,
                                'disk_allocation_ratio': 3.0})

        res = compute_node.migrate_empty_ratio(self.context, 1)
        # the non-empty ratio will not be refreshed
        self.assertEqual(res, (0, 0))

        cns = db.compute_node_get_all(self.context)
        for cn in cns:
            self.assertEqual(32.0, cn['cpu_allocation_ratio'])
            self.assertEqual(4.0, cn['ram_allocation_ratio'])
            self.assertEqual(3.0, cn['disk_allocation_ratio'])
