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

import datetime

from nova import context
from nova import db
from nova.objects import compute_node
from nova.objects import service
from nova.openstack.common import timeutils
from nova.tests.objects import test_objects

NOW = timeutils.utcnow().replace(microsecond=0)
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
}


class _TestComputeNodeObject(object):
    def _compare(self, obj, db_obj):
        for key in obj.fields:
            obj_val = obj[key]
            if isinstance(obj_val, datetime.datetime):
                obj_val = obj_val.replace(tzinfo=None)
            db_val = db_obj[key]
            self.assertEqual(db_val, obj_val)

    def test_get_by_id(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'compute_node_get')
        db.compute_node_get(ctxt, 123).AndReturn(fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode.get_by_id(ctxt, 123)
        self._compare(compute, fake_compute_node)

    def test_create(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'compute_node_create')
        db.compute_node_create(ctxt, {'service_id': 456}).AndReturn(
            fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute.service_id = 456
        compute.create(ctxt)
        self._compare(compute, fake_compute_node)

    def test_save(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'compute_node_update')
        db.compute_node_update(ctxt, 123, {'vcpus_used': 3},
                               prune_stats=False
                               ).AndReturn(fake_compute_node)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute.id = 123
        compute.vcpus_used = 3
        compute.save(ctxt)
        self._compare(compute, fake_compute_node)

    def test_destroy(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'compute_node_delete')
        db.compute_node_delete(ctxt, 123)
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute.id = 123
        compute.destroy(ctxt)

    def test_service(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(service.Service, 'get_by_id')
        service.Service.get_by_id(ctxt, 456).AndReturn('my-service')
        self.mox.ReplayAll()
        compute = compute_node.ComputeNode()
        compute._context = ctxt
        compute.id = 123
        compute.service_id = 456
        self.assertEqual('my-service', compute.service)
        # Make sure it doesn't call Service.get_by_id() again
        self.assertEqual('my-service', compute.service)

    def test_get_all(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        db.compute_node_get_all(ctxt).AndReturn([fake_compute_node])
        self.mox.ReplayAll()
        computes = compute_node.ComputeNodeList.get_all(ctxt)
        self.assertEqual(1, len(computes))
        self._compare(computes[0], fake_compute_node)

    def test_get_by_hypervisor(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'compute_node_search_by_hypervisor')
        db.compute_node_search_by_hypervisor(ctxt, 'hyper').AndReturn(
            [fake_compute_node])
        self.mox.ReplayAll()
        computes = compute_node.ComputeNodeList.get_by_hypervisor(ctxt,
                                                                  'hyper')
        self.assertEqual(1, len(computes))
        self._compare(computes[0], fake_compute_node)


class TestComputeNodeObject(test_objects._LocalTest,
                            _TestComputeNodeObject):
    pass


class TestRemoteComputeNodeObject(test_objects._RemoteTest,
                                  _TestComputeNodeObject):
    pass
