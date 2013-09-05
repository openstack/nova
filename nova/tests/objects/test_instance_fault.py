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
from nova.objects import instance_fault
from nova.tests.objects import test_objects


fake_faults = {
    'fake-uuid': [
        {'id': 1, 'instance_uuid': 'fake-uuid', 'code': 123, 'message': 'msg1',
         'details': 'details', 'host': 'host', 'deleted': False,
         'created_at': None, 'updated_at': None, 'deleted_at': None},
        {'id': 2, 'instance_uuid': 'fake-uuid', 'code': 456, 'message': 'msg2',
         'details': 'details', 'host': 'host', 'deleted': False,
         'created_at': None, 'updated_at': None, 'deleted_at': None},
        ]
    }


class _TestInstanceFault(object):
    def test_get_latest_for_instance(self):
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        db.instance_fault_get_by_instance_uuids(self.context, ['fake-uuid']
                                                ).AndReturn(fake_faults)
        self.mox.ReplayAll()
        fault = instance_fault.InstanceFault.get_latest_for_instance(
            self.context, 'fake-uuid')
        for key in fake_faults['fake-uuid'][0]:
            self.assertEqual(fake_faults['fake-uuid'][0][key], fault[key])

    def test_get_latest_for_instance_with_none(self):
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        db.instance_fault_get_by_instance_uuids(self.context, ['fake-uuid']
                                                ).AndReturn({})
        self.mox.ReplayAll()
        fault = instance_fault.InstanceFault.get_latest_for_instance(
            self.context, 'fake-uuid')
        self.assertIsNone(fault)

    def test_get_by_instance(self):
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        db.instance_fault_get_by_instance_uuids(self.context, ['fake-uuid']
                                                ).AndReturn(fake_faults)
        self.mox.ReplayAll()
        faults = instance_fault.InstanceFaultList.get_by_instance_uuids(
            self.context, ['fake-uuid'])
        for index, db_fault in enumerate(fake_faults['fake-uuid']):
            for key in db_fault:
                self.assertEqual(fake_faults['fake-uuid'][index][key],
                                 faults[index][key])

    def test_get_by_instance_with_none(self):
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        db.instance_fault_get_by_instance_uuids(self.context, ['fake-uuid']
                                                ).AndReturn({})
        self.mox.ReplayAll()
        faults = instance_fault.InstanceFaultList.get_by_instance_uuids(
            self.context, ['fake-uuid'])
        self.assertEqual(0, len(faults))


class TestInstanceFault(test_objects._LocalTest,
                        _TestInstanceFault):
    pass


class TestInstanceFaultRemote(test_objects._RemoteTest,
                              _TestInstanceFault):
    pass
