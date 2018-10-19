#    Copyright 2013 IBM Corp.
#
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

import mock
import netaddr
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_versionedobjects import base as ovo_base
from oslo_versionedobjects import exception as ovo_exc

from nova.db import api as db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import compute_node
from nova.objects import hv_spec
from nova.objects import service
from nova.tests.unit import fake_pci_device_pools
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel

NOW = timeutils.utcnow().replace(microsecond=0)
fake_stats = {'num_foo': '10'}
fake_stats_db_format = jsonutils.dumps(fake_stats)
# host_ip is coerced from a string to an IPAddress
# but needs to be converted to a string for the database format
fake_host_ip = '127.0.0.1'
fake_numa_topology = objects.NUMATopology(
        cells=[objects.NUMACell(id=0, cpuset=set([1, 2]), memory=512,
                                cpu_usage=0, memory_usage=0,
                                mempages=[], pinned_cpus=set([]),
                                siblings=[set([1]), set([2])]),
               objects.NUMACell(id=1, cpuset=set([3, 4]), memory=512,
                                cpu_usage=0, memory_usage=0,
                                mempages=[], pinned_cpus=set([]),
                                siblings=[set([3]), set([4])])])
fake_numa_topology_db_format = fake_numa_topology._to_json()
fake_supported_instances = [('x86_64', 'kvm', 'hvm')]
fake_hv_spec = hv_spec.HVSpec(arch=fake_supported_instances[0][0],
                              hv_type=fake_supported_instances[0][1],
                              vm_mode=fake_supported_instances[0][2])
fake_supported_hv_specs = [fake_hv_spec]
# for backward compatibility, each supported instance object
# is stored as a list in the database
fake_supported_hv_specs_db_format = jsonutils.dumps([fake_hv_spec.to_list()])
fake_pci = jsonutils.dumps(fake_pci_device_pools.fake_pool_list_primitive)
fake_compute_node = {
    'created_at': NOW,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'uuid': uuidsentinel.fake_compute_node,
    'service_id': None,
    'host': 'fake',
    'vcpus': 4,
    'memory_mb': 4096,
    'local_gb': 1024,
    'vcpus_used': 2,
    'memory_mb_used': 2048,
    'local_gb_used': 512,
    'hypervisor_type': 'Hyper-Dan-VM-ware',
    'hypervisor_version': 1001,
    'hypervisor_hostname': 'vm.danplanet.com',
    'free_ram_mb': 1024,
    'free_disk_gb': 256,
    'current_workload': 100,
    'running_vms': 2013,
    'cpu_info': 'Schmintel i786',
    'disk_available_least': 256,
    'metrics': '',
    'stats': fake_stats_db_format,
    'host_ip': fake_host_ip,
    'numa_topology': fake_numa_topology_db_format,
    'supported_instances': fake_supported_hv_specs_db_format,
    'pci_stats': fake_pci,
    'cpu_allocation_ratio': 16.0,
    'ram_allocation_ratio': 1.5,
    'disk_allocation_ratio': 1.0,
    'mapped': 0,
    }
# FIXME(sbauza) : For compatibility checking, to be removed once we are sure
# that all computes are running latest DB version with host field in it.
fake_old_compute_node = fake_compute_node.copy()
del fake_old_compute_node['host']
# resources are passed from the virt drivers and copied into the compute_node
fake_resources = {
    'vcpus': 2,
    'memory_mb': 1024,
    'local_gb': 10,
    'cpu_info': 'fake-info',
    'vcpus_used': 1,
    'memory_mb_used': 512,
    'local_gb_used': 4,
    'numa_topology': fake_numa_topology_db_format,
    'hypervisor_type': 'fake-type',
    'hypervisor_version': 1,
    'hypervisor_hostname': 'fake-host',
    'disk_available_least': 256,
    'host_ip': fake_host_ip,
    'supported_instances': fake_supported_instances
}
fake_compute_with_resources = objects.ComputeNode(
    vcpus=fake_resources['vcpus'],
    memory_mb=fake_resources['memory_mb'],
    local_gb=fake_resources['local_gb'],
    cpu_info=fake_resources['cpu_info'],
    vcpus_used=fake_resources['vcpus_used'],
    memory_mb_used=fake_resources['memory_mb_used'],
    local_gb_used =fake_resources['local_gb_used'],
    numa_topology=fake_resources['numa_topology'],
    hypervisor_type=fake_resources['hypervisor_type'],
    hypervisor_version=fake_resources['hypervisor_version'],
    hypervisor_hostname=fake_resources['hypervisor_hostname'],
    disk_available_least=fake_resources['disk_available_least'],
    host_ip=netaddr.IPAddress(fake_resources['host_ip']),
    supported_hv_specs=fake_supported_hv_specs,
)


class _TestComputeNodeObject(object):
    def supported_hv_specs_comparator(self, expected, obj_val):
        obj_val = [inst.to_list() for inst in obj_val]
        self.assertJsonEqual(expected, obj_val)

    def pci_device_pools_comparator(self, expected, obj_val):
        if obj_val is not None:
            obj_val = obj_val.obj_to_primitive()
            self.assertJsonEqual(expected, obj_val)
        else:
            self.assertEqual(expected, obj_val)

    def comparators(self):
        return {'stats': self.assertJsonEqual,
                'host_ip': self.str_comparator,
                'supported_hv_specs': self.supported_hv_specs_comparator,
                'pci_device_pools': self.pci_device_pools_comparator,
                }

    def subs(self):
        return {'supported_hv_specs': 'supported_instances',
                'pci_device_pools': 'pci_stats'}

    @mock.patch.object(db, 'compute_node_get')
    def test_get_by_id(self, get_mock):
        get_mock.return_value = fake_compute_node
        compute = compute_node.ComputeNode.get_by_id(self.context, 123)
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())
        self.assertNotIn('uuid', compute.obj_what_changed())
        get_mock.assert_called_once_with(self.context, 123)

    @mock.patch.object(compute_node.ComputeNodeList, 'get_all_by_uuids')
    def test_get_by_uuid(self, get_all_by_uuids):
        fake_node = copy.copy(fake_compute_node)
        fake_node['stats'] = None
        get_all_by_uuids.return_value = objects.ComputeNodeList(
            objects=[objects.ComputeNode(**fake_node)])
        compute = compute_node.ComputeNode.get_by_uuid(
            self.context, uuidsentinel.fake_compute_node)
        self.assertEqual(uuidsentinel.fake_compute_node, compute.uuid)
        get_all_by_uuids.assert_called_once_with(
            self.context, [uuidsentinel.fake_compute_node])

    @mock.patch.object(compute_node.ComputeNodeList, 'get_all_by_uuids')
    def test_get_by_uuid_not_found(self, get_all_by_uuids):
        get_all_by_uuids.return_value = objects.ComputeNodeList()
        self.assertRaises(exception.ComputeHostNotFound,
                          compute_node.ComputeNode.get_by_uuid,
                          self.context, uuidsentinel.fake_compute_node)
        get_all_by_uuids.assert_called_once_with(
            self.context, [uuidsentinel.fake_compute_node])

    @mock.patch.object(db, 'compute_node_get')
    def test_get_without_mapped(self, get_mock):
        fake_node = copy.copy(fake_compute_node)
        fake_node['mapped'] = None
        get_mock.return_value = fake_node
        compute = compute_node.ComputeNode.get_by_id(self.context, 123)
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())
        self.assertIn('mapped', compute)
        self.assertEqual(0, compute.mapped)

    @mock.patch.object(objects.Service, 'get_by_id')
    @mock.patch.object(db, 'compute_node_get')
    def test_get_by_id_with_host_field_not_in_db(self, mock_cn_get,
                                                 mock_obj_svc_get):
        fake_compute_node_with_svc_id = fake_compute_node.copy()
        fake_compute_node_with_svc_id['service_id'] = 123
        fake_compute_node_with_no_host = fake_compute_node_with_svc_id.copy()
        host = fake_compute_node_with_no_host.pop('host')
        fake_service = service.Service(id=123)
        fake_service.host = host

        mock_cn_get.return_value = fake_compute_node_with_no_host
        mock_obj_svc_get.return_value = fake_service

        compute = compute_node.ComputeNode.get_by_id(self.context, 123)
        self.compare_obj(compute, fake_compute_node_with_svc_id,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch.object(db, 'compute_nodes_get_by_service_id')
    def test_get_by_service_id(self, get_mock):
        get_mock.return_value = [fake_compute_node]
        compute = compute_node.ComputeNode.get_by_service_id(self.context, 456)
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())
        get_mock.assert_called_once_with(self.context, 456)

    @mock.patch.object(db, 'compute_node_get_by_host_and_nodename')
    def test_get_by_host_and_nodename(self, cn_get_by_h_and_n):
        cn_get_by_h_and_n.return_value = fake_compute_node

        compute = compute_node.ComputeNode.get_by_host_and_nodename(
            self.context, 'fake', 'vm.danplanet.com')
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.db.api.compute_node_get_all_by_host')
    def test_get_first_node_by_host_for_old_compat(
            self, cn_get_all_by_host):
        another_node = fake_compute_node.copy()
        another_node['hypervisor_hostname'] = 'neverland'
        cn_get_all_by_host.return_value = [fake_compute_node, another_node]

        compute = (
            compute_node.ComputeNode.get_first_node_by_host_for_old_compat(
                self.context, 'fake')
        )
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_get_first_node_by_host_for_old_compat_not_found(
            self, cn_get_all_by_host):
        cn_get_all_by_host.side_effect = exception.ComputeHostNotFound(
            host='fake')

        self.assertRaises(
            exception.ComputeHostNotFound,
            compute_node.ComputeNode.get_first_node_by_host_for_old_compat,
            self.context, 'fake')

    @mock.patch.object(db, 'compute_node_create')
    @mock.patch('nova.db.api.compute_node_get', return_value=fake_compute_node)
    def test_create(self, mock_get, mock_create):
        mock_create.return_value = fake_compute_node
        compute = compute_node.ComputeNode(context=self.context)
        compute.service_id = 456
        compute.uuid = uuidsentinel.fake_compute_node
        compute.stats = fake_stats
        # NOTE (pmurray): host_ip is coerced to an IPAddress
        compute.host_ip = fake_host_ip
        compute.supported_hv_specs = fake_supported_hv_specs
        with mock.patch('oslo_utils.uuidutils.generate_uuid') as mock_gu:
            compute.create()
            self.assertFalse(mock_gu.called)
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())
        param_dict = {
            'service_id': 456,
            'stats': fake_stats_db_format,
            'host_ip': fake_host_ip,
            'supported_instances': fake_supported_hv_specs_db_format,
            'uuid': uuidsentinel.fake_compute_node
        }
        mock_create.assert_called_once_with(self.context, param_dict)

    @mock.patch('nova.db.api.compute_node_create')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch('nova.db.api.compute_node_get', return_value=fake_compute_node)
    def test_create_allocates_uuid(self, mock_get, mock_gu, mock_create):
        mock_create.return_value = fake_compute_node
        mock_gu.return_value = fake_compute_node['uuid']
        obj = objects.ComputeNode(context=self.context)
        obj.create()
        mock_gu.assert_called_once_with()
        mock_create.assert_called_once_with(
            self.context, {'uuid': fake_compute_node['uuid']})

    @mock.patch('nova.db.api.compute_node_create')
    @mock.patch('nova.db.api.compute_node_get', return_value=fake_compute_node)
    def test_recreate_fails(self, mock_get, mock_create):
        mock_create.return_value = fake_compute_node
        compute = compute_node.ComputeNode(context=self.context)
        compute.service_id = 456
        compute.uuid = uuidsentinel.fake_compute_node
        compute.create()
        self.assertRaises(exception.ObjectActionError, compute.create)
        param_dict = {'service_id': 456,
                      'uuid': uuidsentinel.fake_compute_node}
        mock_create.assert_called_once_with(self.context, param_dict)

    @mock.patch.object(db, 'compute_node_update')
    @mock.patch('nova.db.api.compute_node_get', return_value=fake_compute_node)
    def test_save(self, mock_get, mock_update):
        mock_update.return_value = fake_compute_node
        compute = compute_node.ComputeNode(context=self.context)
        compute.id = 123
        compute.vcpus_used = 3
        compute.stats = fake_stats
        compute.uuid = uuidsentinel.fake_compute_node
        # NOTE (pmurray): host_ip is coerced to an IPAddress
        compute.host_ip = fake_host_ip
        compute.supported_hv_specs = fake_supported_hv_specs
        compute.save()
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())
        param_dict = {
            'vcpus_used': 3,
            'stats': fake_stats_db_format,
            'host_ip': fake_host_ip,
            'supported_instances': fake_supported_hv_specs_db_format,
            'uuid': uuidsentinel.fake_compute_node,
        }
        mock_update.assert_called_once_with(self.context, 123, param_dict)

    @mock.patch('nova.db.api.compute_node_update')
    def test_save_pci_device_pools_empty(self, mock_update):
        fake_pci = jsonutils.dumps(
            objects.PciDevicePoolList(objects=[]).obj_to_primitive())
        compute_dict = fake_compute_node.copy()
        compute_dict['pci_stats'] = fake_pci
        mock_update.return_value = compute_dict

        compute = compute_node.ComputeNode(context=self.context)
        compute.id = 123
        compute.pci_device_pools = objects.PciDevicePoolList(objects=[])
        compute.save()
        self.compare_obj(compute, compute_dict,
                         subs=self.subs(),
                         comparators=self.comparators())

        mock_update.assert_called_once_with(
            self.context, 123, {'pci_stats': fake_pci})

    @mock.patch('nova.db.api.compute_node_update')
    def test_save_pci_device_pools_null(self, mock_update):
        compute_dict = fake_compute_node.copy()
        compute_dict['pci_stats'] = None
        mock_update.return_value = compute_dict

        compute = compute_node.ComputeNode(context=self.context)
        compute.id = 123
        compute.pci_device_pools = None
        compute.save()
        self.compare_obj(compute, compute_dict,
                         subs=self.subs(),
                         comparators=self.comparators())

        mock_update.assert_called_once_with(
            self.context, 123, {'pci_stats': None})

    @mock.patch.object(db, 'compute_node_create',
                       return_value=fake_compute_node)
    @mock.patch.object(db, 'compute_node_get',
                       return_value=fake_compute_node)
    def test_set_id_failure(self, mock_get, db_mock):
        compute = compute_node.ComputeNode(context=self.context,
                                           uuid=fake_compute_node['uuid'])
        compute.create()
        self.assertRaises(ovo_exc.ReadOnlyFieldError, setattr,
                          compute, 'id', 124)

    @mock.patch.object(db, 'compute_node_delete')
    def test_destroy(self, mock_delete):
        compute = compute_node.ComputeNode(context=self.context)
        compute.id = 123
        compute.destroy()
        mock_delete.assert_called_once_with(self.context, 123)

    @mock.patch.object(db, 'compute_node_get_all')
    def test_get_all(self, mock_get_all):
        mock_get_all.return_value = [fake_compute_node]
        computes = compute_node.ComputeNodeList.get_all(self.context)
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())
        mock_get_all.assert_called_once_with(self.context)

    @mock.patch.object(db, 'compute_node_search_by_hypervisor')
    def test_get_by_hypervisor(self, mock_search):
        mock_search.return_value = [fake_compute_node]
        computes = compute_node.ComputeNodeList.get_by_hypervisor(self.context,
                                                                  'hyper')
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())
        mock_search.assert_called_once_with(self.context, 'hyper')

    @mock.patch('nova.db.api.compute_node_get_all_by_pagination',
                return_value=[fake_compute_node])
    def test_get_by_pagination(self, fake_get_by_pagination):
        computes = compute_node.ComputeNodeList.get_by_pagination(
            self.context, limit=1, marker=1)
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.db.api.compute_nodes_get_by_service_id')
    def test__get_by_service(self, cn_get_by_svc_id):
        cn_get_by_svc_id.return_value = [fake_compute_node]
        computes = compute_node.ComputeNodeList._get_by_service(self.context,
                                                                123)
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.db.api.compute_node_get_all_by_host')
    def test_get_all_by_host(self, cn_get_all_by_host):
        cn_get_all_by_host.return_value = [fake_compute_node]
        computes = compute_node.ComputeNodeList.get_all_by_host(self.context,
                                                                'fake')
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    def test_compat_numa_topology(self):
        compute = compute_node.ComputeNode()
        versions = ovo_base.obj_tree_get_versions('ComputeNode')
        primitive = compute.obj_to_primitive(target_version='1.4',
                                             version_manifest=versions)
        self.assertNotIn('numa_topology', primitive)

    def test_compat_supported_hv_specs(self):
        compute = compute_node.ComputeNode()
        compute.supported_hv_specs = fake_supported_hv_specs
        versions = ovo_base.obj_tree_get_versions('ComputeNode')
        primitive = compute.obj_to_primitive(target_version='1.5',
                                             version_manifest=versions)
        self.assertNotIn('supported_hv_specs', primitive)

    def test_compat_host(self):
        compute = compute_node.ComputeNode()
        primitive = compute.obj_to_primitive(target_version='1.6')
        self.assertNotIn('host', primitive)

    def test_compat_pci_device_pools(self):
        compute = compute_node.ComputeNode()
        compute.pci_device_pools = fake_pci_device_pools.fake_pool_list
        versions = ovo_base.obj_tree_get_versions('ComputeNode')
        primitive = compute.obj_to_primitive(target_version='1.8',
                                             version_manifest=versions)
        self.assertNotIn('pci_device_pools', primitive)

    @mock.patch('nova.objects.Service.get_by_compute_host')
    def test_compat_service_id(self, mock_get):
        mock_get.return_value = objects.Service(id=1)
        compute = objects.ComputeNode(host='fake-host', service_id=None)
        primitive = compute.obj_to_primitive(target_version='1.12')
        self.assertEqual(1, primitive['nova_object.data']['service_id'])

    @mock.patch('nova.objects.Service.get_by_compute_host')
    def test_compat_service_id_compute_host_not_found(self, mock_get):
        mock_get.side_effect = exception.ComputeHostNotFound(host='fake-host')
        compute = objects.ComputeNode(host='fake-host', service_id=None)
        primitive = compute.obj_to_primitive(target_version='1.12')
        self.assertEqual(-1, primitive['nova_object.data']['service_id'])

    def test_update_from_virt_driver(self):
        # copy in case the update has a side effect
        resources = copy.deepcopy(fake_resources)
        # Emulate the ironic driver which adds a uuid field.
        resources['uuid'] = uuidsentinel.node_uuid
        compute = compute_node.ComputeNode()
        compute.update_from_virt_driver(resources)
        expected = fake_compute_with_resources.obj_clone()
        expected.uuid = uuidsentinel.node_uuid
        self.assertTrue(base.obj_equal_prims(expected, compute))

    def test_update_from_virt_driver_uuid_already_set(self):
        """Tests update_from_virt_driver where the compute node object already
        has a uuid value so the uuid from the virt driver is ignored.
        """
        # copy in case the update has a side effect
        resources = copy.deepcopy(fake_resources)
        # Emulate the ironic driver which adds a uuid field.
        resources['uuid'] = uuidsentinel.node_uuid
        compute = compute_node.ComputeNode(uuid=uuidsentinel.something_else)
        compute.update_from_virt_driver(resources)
        expected = fake_compute_with_resources.obj_clone()
        expected.uuid = uuidsentinel.something_else
        self.assertTrue(base.obj_equal_prims(expected, compute))

    def test_update_from_virt_driver_missing_field(self):
        # NOTE(pmurray): update_from_virt_driver does not require
        # all fields to be present in resources. Validation of the
        # resources data structure would be done in a different method.
        resources = copy.deepcopy(fake_resources)
        del resources['vcpus']
        compute = compute_node.ComputeNode()
        compute.update_from_virt_driver(resources)
        expected = fake_compute_with_resources.obj_clone()
        del expected.vcpus
        self.assertTrue(base.obj_equal_prims(expected, compute))

    def test_update_from_virt_driver_extra_field(self):
        # copy in case the update has a side effect
        resources = copy.deepcopy(fake_resources)
        resources['extra_field'] = 'nonsense'
        compute = compute_node.ComputeNode()
        compute.update_from_virt_driver(resources)
        expected = fake_compute_with_resources
        self.assertTrue(base.obj_equal_prims(expected, compute))

    def test_update_from_virt_driver_bad_value(self):
        # copy in case the update has a side effect
        resources = copy.deepcopy(fake_resources)
        resources['vcpus'] = 'nonsense'
        compute = compute_node.ComputeNode()
        self.assertRaises(ValueError,
                          compute.update_from_virt_driver, resources)

    def test_compat_allocation_ratios(self):
        compute = compute_node.ComputeNode()
        primitive = compute.obj_to_primitive(target_version='1.13')
        self.assertNotIn('cpu_allocation_ratio', primitive)
        self.assertNotIn('ram_allocation_ratio', primitive)

    def test_compat_disk_allocation_ratio(self):
        compute = compute_node.ComputeNode()
        primitive = compute.obj_to_primitive(target_version='1.15')
        self.assertNotIn('disk_allocation_ratio', primitive)

    def test_compat_allocation_ratios_old_compute(self):
        self.flags(cpu_allocation_ratio=2.0, ram_allocation_ratio=3.0,
                   disk_allocation_ratio=0.9)
        compute_dict = fake_compute_node.copy()
        # old computes don't provide allocation ratios to the table
        compute_dict['cpu_allocation_ratio'] = None
        compute_dict['ram_allocation_ratio'] = None
        compute_dict['disk_allocation_ratio'] = None
        cls = objects.ComputeNode
        compute = cls._from_db_object(self.context, cls(), compute_dict)

        self.assertEqual(2.0, compute.cpu_allocation_ratio)
        self.assertEqual(3.0, compute.ram_allocation_ratio)
        self.assertEqual(0.9, compute.disk_allocation_ratio)

    def test_compat_allocation_ratios_default_values(self):
        compute_dict = fake_compute_node.copy()
        # new computes provide allocation ratios defaulted to 0.0
        compute_dict['cpu_allocation_ratio'] = 0.0
        compute_dict['ram_allocation_ratio'] = 0.0
        compute_dict['disk_allocation_ratio'] = 0.0
        cls = objects.ComputeNode
        compute = cls._from_db_object(self.context, cls(), compute_dict)

        self.assertEqual(16.0, compute.cpu_allocation_ratio)
        self.assertEqual(1.5, compute.ram_allocation_ratio)
        self.assertEqual(1.0, compute.disk_allocation_ratio)

    def test_compat_allocation_ratios_old_compute_default_values(self):
        compute_dict = fake_compute_node.copy()
        # old computes don't provide allocation ratios to the table
        compute_dict['cpu_allocation_ratio'] = None
        compute_dict['ram_allocation_ratio'] = None
        compute_dict['disk_allocation_ratio'] = None
        cls = objects.ComputeNode
        compute = cls._from_db_object(self.context, cls(), compute_dict)

        self.assertEqual(16.0, compute.cpu_allocation_ratio)
        self.assertEqual(1.5, compute.ram_allocation_ratio)
        self.assertEqual(1.0, compute.disk_allocation_ratio)

    def test_get_all_by_not_mapped(self):
        for mapped in (1, 0, 1, 3):
            compute = fake_compute_with_resources.obj_clone()
            compute._context = self.context
            compute.mapped = mapped
            compute.create()
        nodes = compute_node.ComputeNodeList.get_all_by_not_mapped(
            self.context, 2)
        self.assertEqual(3, len(nodes))
        self.assertEqual([0, 1, 1], sorted([x.mapped for x in nodes]))


class TestComputeNodeObject(test_objects._LocalTest,
                            _TestComputeNodeObject):
    pass


class TestRemoteComputeNodeObject(test_objects._RemoteTest,
                                  _TestComputeNodeObject):
    pass
