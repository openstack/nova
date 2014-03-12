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

from nova import db
from nova import exception
from nova.objects import compute_node
from nova.objects import service
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova.tests.objects import test_objects

NOW = timeutils.utcnow().replace(microsecond=0)
fake_stats = {'num_foo': '10'}
fake_stats_db_format = jsonutils.dumps(fake_stats)
fake_compute_node = {
    'created_at': NOW,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'service_id': 456,
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
    }


class _TestComputeNodeObject(object):
    def test_get_by_id(self):
        self.mox.StubOutWithMock(db, 'compute_node_get')
        db.compute_node_get(self.context, 123).AndReturn(fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode.get_by_id(self.context, 123)
        self.compare_obj(compute, fake_compute_node,
                         comparators={'stats': self.json_comparator})

    def test_get_by_service_id(self):
        self.mox.StubOutWithMock(db, 'compute_node_get_by_service_id')
        db.compute_node_get_by_service_id(self.context, 456).AndReturn(
            fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode.get_by_service_id(self.context, 456)
        self.compare_obj(compute, fake_compute_node,
                         comparators={'stats': self.json_comparator})

    def test_create(self):
        self.mox.StubOutWithMock(db, 'compute_node_create')
        db.compute_node_create(
            self.context,
            {
                'service_id': 456,
                'stats': fake_stats_db_format
            }).AndReturn(fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute.service_id = 456
        compute.stats = fake_stats
        compute.create(self.context)
        self.compare_obj(compute, fake_compute_node,
                         comparators={'stats': self.json_comparator})

    def test_recreate_fails(self):
        self.mox.StubOutWithMock(db, 'compute_node_create')
        db.compute_node_create(self.context, {'service_id': 456}).AndReturn(
            fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute.service_id = 456
        compute.create(self.context)
        self.assertRaises(exception.ObjectActionError, compute.create,
                          self.context)

    def test_save(self):
        self.mox.StubOutWithMock(db, 'compute_node_update')
        db.compute_node_update(
            self.context, 123,
            {
                'vcpus_used': 3,
                'stats': fake_stats_db_format
            }).AndReturn(fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute.id = 123
        compute.vcpus_used = 3
        compute.stats = fake_stats
        compute.save(self.context)
        self.compare_obj(compute, fake_compute_node,
                         comparators={'stats': self.json_comparator})

    def test_destroy(self):
        self.mox.StubOutWithMock(db, 'compute_node_delete')
        db.compute_node_delete(self.context, 123)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute.id = 123
        compute.destroy(self.context)

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
                         comparators={'stats': self.json_comparator})

    def test_get_by_hypervisor(self):
        self.mox.StubOutWithMock(db, 'compute_node_search_by_hypervisor')
        db.compute_node_search_by_hypervisor(self.context, 'hyper').AndReturn(
            [fake_compute_node])
        self.mox.ReplayAll()
        computes = compute_node.ComputeNodeList.get_by_hypervisor(self.context,
                                                                  'hyper')
        self.assertEqual(1, len(computes))
        self.compare_obj(computes[0], fake_compute_node,
                         comparators={'stats': self.json_comparator})


class TestComputeNodeObject(test_objects._LocalTest,
                            _TestComputeNodeObject):
    pass


class TestRemoteComputeNodeObject(test_objects._RemoteTest,
                                  _TestComputeNodeObject):
    pass
