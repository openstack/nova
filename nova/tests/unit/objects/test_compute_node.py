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

import mock
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from nova import db
from nova import exception
from nova import objects
from nova.objects import compute_node
from nova.objects import hv_spec
from nova.objects import service
from nova.tests.unit import fake_pci_device_pools
from nova.tests.unit.objects import test_objects

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
                                siblings=[]),
               objects.NUMACell(id=1, cpuset=set([3, 4]), memory=512,
                                cpu_usage=0, memory_usage=0,
                                mempages=[], pinned_cpus=set([]),
                                siblings=[])])
fake_numa_topology_db_format = fake_numa_topology._to_json()
fake_hv_spec = hv_spec.HVSpec(arch='foo', hv_type='bar', vm_mode='foobar')
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
    'service_id': 456,
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
    }
# FIXME(sbauza) : For compatibility checking, to be removed once we are sure
# that all computes are running latest DB version with host field in it.
fake_old_compute_node = fake_compute_node.copy()
del fake_old_compute_node['host']


class _TestComputeNodeObject(object):
    def supported_hv_specs_comparator(self, expected, obj_val):
        obj_val = [inst.to_list() for inst in obj_val]
        self.json_comparator(expected, obj_val)

    def pci_device_pools_comparator(self, expected, obj_val):
        obj_val = obj_val.obj_to_primitive()
        self.json_loads_comparator(expected, obj_val)

    def json_loads_comparator(self, expected, obj_val):
        # NOTE(edleafe): This is necessary because the dumps() version of the
        # PciDevicePoolList doesn't maintain ordering, so the output string
        # doesn't always match.
        self.assertEqual(jsonutils.loads(expected), obj_val)

    def comparators(self):
        return {'stats': self.json_comparator,
                'host_ip': self.str_comparator,
                'supported_hv_specs': self.supported_hv_specs_comparator,
                'pci_device_pools': self.pci_device_pools_comparator,
                }

    def subs(self):
        return {'supported_hv_specs': 'supported_instances',
                'pci_device_pools': 'pci_stats'}

    def test_get_by_id(self):
        self.mox.StubOutWithMock(db, 'compute_node_get')
        db.compute_node_get(self.context, 123).AndReturn(fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode.get_by_id(self.context, 123)
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch.object(objects.Service, 'get_by_id')
    @mock.patch.object(db, 'compute_node_get')
    def test_get_by_id_with_host_field_not_in_db(self, mock_cn_get,
                                                 mock_obj_svc_get):
        fake_compute_node_with_no_host = fake_compute_node.copy()
        host = fake_compute_node_with_no_host.pop('host')
        fake_service = service.Service(id=123)
        fake_service.host = host

        mock_cn_get.return_value = fake_compute_node_with_no_host
        mock_obj_svc_get.return_value = fake_service

        compute = compute_node.ComputeNode.get_by_id(self.context, 123)
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    def test_get_by_service_id(self):
        self.mox.StubOutWithMock(db, 'compute_nodes_get_by_service_id')
        db.compute_nodes_get_by_service_id(self.context, 456).AndReturn(
            [fake_compute_node])
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode.get_by_service_id(self.context, 456)
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch.object(db, 'compute_node_get_by_host_and_nodename')
    def test_get_by_host_and_nodename(self, cn_get_by_h_and_n):
        cn_get_by_h_and_n.return_value = fake_compute_node

        compute = compute_node.ComputeNode.get_by_host_and_nodename(
            self.context, 'fake', 'vm.danplanet.com')
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.objects.Service.get_by_id')
    @mock.patch('nova.db.compute_nodes_get_by_service_id')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    @mock.patch.object(db, 'compute_node_get_by_host_and_nodename')
    def test_get_by_host_and_nodename_with_old_compute(self, cn_get_by_h_and_n,
                                                       svc_get_by_ch,
                                                       cn_get_by_svc_id,
                                                       svc_get_by_id):
        cn_get_by_h_and_n.side_effect = exception.ComputeHostNotFound(
            host='fake')
        fake_service = service.Service(id=123)
        fake_service.host = 'fake'
        svc_get_by_ch.return_value = fake_service
        cn_get_by_svc_id.return_value = [fake_old_compute_node]
        svc_get_by_id.return_value = fake_service

        compute = compute_node.ComputeNode.get_by_host_and_nodename(
            self.context, 'fake', 'vm.danplanet.com')
        # NOTE(sbauza): Result is still converted to new style Compute
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.objects.Service.get_by_id')
    @mock.patch('nova.db.compute_nodes_get_by_service_id')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    @mock.patch.object(db, 'compute_node_get_by_host_and_nodename')
    def test_get_by_host_and_nodename_not_found(self, cn_get_by_h_and_n,
                                                svc_get_by_ch,
                                                cn_get_by_svc_id,
                                                svc_get_by_id):
        cn_get_by_h_and_n.side_effect = exception.ComputeHostNotFound(
            host='fake')
        fake_service = service.Service(id=123)
        fake_service.host = 'fake'
        another_node = fake_old_compute_node.copy()
        another_node['hypervisor_hostname'] = 'elsewhere'
        svc_get_by_ch.return_value = fake_service
        cn_get_by_svc_id.return_value = [another_node]
        svc_get_by_id.return_value = fake_service

        self.assertRaises(exception.ComputeHostNotFound,
                          compute_node.ComputeNode.get_by_host_and_nodename,
                          self.context, 'fake', 'vm.danplanet.com')

    @mock.patch('nova.objects.Service.get_by_id')
    @mock.patch('nova.db.compute_nodes_get_by_service_id')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    @mock.patch.object(db, 'compute_node_get_by_host_and_nodename')
    def test_get_by_host_and_nodename_good_and_bad(self, cn_get_by_h_and_n,
                                                   svc_get_by_ch,
                                                   cn_get_by_svc_id,
                                                   svc_get_by_id):
        cn_get_by_h_and_n.side_effect = exception.ComputeHostNotFound(
            host='fake')
        fake_service = service.Service(id=123)
        fake_service.host = 'fake'
        bad_node = fake_old_compute_node.copy()
        bad_node['hypervisor_hostname'] = 'elsewhere'
        good_node = fake_old_compute_node.copy()
        svc_get_by_ch.return_value = fake_service
        cn_get_by_svc_id.return_value = [bad_node, good_node]
        svc_get_by_id.return_value = fake_service

        compute = compute_node.ComputeNode.get_by_host_and_nodename(
            self.context, 'fake', 'vm.danplanet.com')
        # NOTE(sbauza): Result is still converted to new style Compute
        self.compare_obj(compute, good_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.db.compute_node_get_all_by_host')
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

    def test_create(self):
        self.mox.StubOutWithMock(db, 'compute_node_create')
        db.compute_node_create(
            self.context,
            {
                'service_id': 456,
                'stats': fake_stats_db_format,
                'host_ip': fake_host_ip,
                'supported_instances': fake_supported_hv_specs_db_format,
            }).AndReturn(fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode(context=self.context)
        compute.service_id = 456
        compute.stats = fake_stats
        # NOTE (pmurray): host_ip is coerced to an IPAddress
        compute.host_ip = fake_host_ip
        compute.supported_hv_specs = fake_supported_hv_specs
        compute.create()
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    def test_recreate_fails(self):
        self.mox.StubOutWithMock(db, 'compute_node_create')
        db.compute_node_create(self.context, {'service_id': 456}).AndReturn(
            fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode(context=self.context)
        compute.service_id = 456
        compute.create()
        self.assertRaises(exception.ObjectActionError, compute.create,
                          self.context)

    def test_save(self):
        self.mox.StubOutWithMock(db, 'compute_node_update')
        db.compute_node_update(
            self.context, 123,
            {
                'vcpus_used': 3,
                'stats': fake_stats_db_format,
                'host_ip': fake_host_ip,
                'supported_instances': fake_supported_hv_specs_db_format,
            }).AndReturn(fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode(context=self.context)
        compute.id = 123
        compute.vcpus_used = 3
        compute.stats = fake_stats
        # NOTE (pmurray): host_ip is coerced to an IPAddress
        compute.host_ip = fake_host_ip
        compute.supported_hv_specs = fake_supported_hv_specs
        compute.save()
        self.compare_obj(compute, fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch.object(db, 'compute_node_create',
                       return_value=fake_compute_node)
    def test_set_id_failure(self, db_mock):
        compute = compute_node.ComputeNode(context=self.context)
        compute.create()
        self.assertRaises(exception.ReadOnlyFieldError, setattr,
                          compute, 'id', 124)

    def test_destroy(self):
        self.mox.StubOutWithMock(db, 'compute_node_delete')
        db.compute_node_delete(self.context, 123)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode(context=self.context)
        compute.id = 123
        compute.destroy()

    def test_service(self):
        self.mox.StubOutWithMock(service.Service, 'get_by_id')
        service.Service.get_by_id(self.context, 456).AndReturn('my-service')
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute._context = self.context
        compute.id = 123
        compute.service_id = 456
        self.assertEqual('my-service', compute.service)
        # Make sure it doesn't call Service.get_by_id() again
        self.assertEqual('my-service', compute.service)

    def test_get_all(self):
        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        db.compute_node_get_all(self.context).AndReturn([fake_compute_node])
        self.mox.ReplayAll()
        computes = compute_node.ComputeNodeList.get_all(self.context)
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    def test_get_by_hypervisor(self):
        self.mox.StubOutWithMock(db, 'compute_node_search_by_hypervisor')
        db.compute_node_search_by_hypervisor(self.context, 'hyper').AndReturn(
            [fake_compute_node])
        self.mox.ReplayAll()
        computes = compute_node.ComputeNodeList.get_by_hypervisor(self.context,
                                                                  'hyper')
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.db.compute_nodes_get_by_service_id')
    def test_get_by_service(self, cn_get_by_svc_id):
        cn_get_by_svc_id.return_value = [fake_compute_node]
        fake_service = service.Service(id=123)
        computes = compute_node.ComputeNodeList.get_by_service(self.context,
                                                               fake_service)
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.db.compute_node_get_all_by_host')
    def test_get_all_by_host(self, cn_get_all_by_host):
        cn_get_all_by_host.return_value = [fake_compute_node]
        computes = compute_node.ComputeNodeList.get_all_by_host(self.context,
                                                                'fake')
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    @mock.patch('nova.objects.Service.get_by_id')
    @mock.patch('nova.db.compute_nodes_get_by_service_id')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    @mock.patch('nova.db.compute_node_get_all_by_host')
    def test_get_all_by_host_with_old_compute(self, cn_get_all_by_host,
                                              svc_get_by_ch,
                                              cn_get_by_svc_id,
                                              svc_get_by_id):
        cn_get_all_by_host.side_effect = exception.ComputeHostNotFound(
            host='fake')
        fake_service = service.Service(id=123)
        fake_service.host = 'fake'
        svc_get_by_ch.return_value = fake_service
        cn_get_by_svc_id.return_value = [fake_old_compute_node]
        svc_get_by_id.return_value = fake_service

        computes = compute_node.ComputeNodeList.get_all_by_host(self.context,
                                                                'fake')
        self.assertEqual(1, len(computes))
        # NOTE(sbauza): Result is still converted to new style Compute
        self.compare_obj(computes[0], fake_compute_node,
                         subs=self.subs(),
                         comparators=self.comparators())

    def test_compat_numa_topology(self):
        compute = compute_node.ComputeNode()
        primitive = compute.obj_to_primitive(target_version='1.4')
        self.assertNotIn('numa_topology', primitive)

    def test_compat_supported_hv_specs(self):
        compute = compute_node.ComputeNode()
        compute.supported_hv_specs = fake_supported_hv_specs
        primitive = compute.obj_to_primitive(target_version='1.5')
        self.assertNotIn('supported_hv_specs', primitive)

    def test_compat_host(self):
        compute = compute_node.ComputeNode()
        primitive = compute.obj_to_primitive(target_version='1.6')
        self.assertNotIn('host', primitive)

    def test_compat_pci_device_pools(self):
        compute = compute_node.ComputeNode()
        compute.pci_device_pools = fake_pci_device_pools.fake_pool_list
        primitive = compute.obj_to_primitive(target_version='1.8')
        self.assertNotIn('pci_device_pools', primitive)


class TestComputeNodeObject(test_objects._LocalTest,
                            _TestComputeNodeObject):
    pass


class TestRemoteComputeNodeObject(test_objects._RemoteTest,
                                  _TestComputeNodeObject):
    pass
