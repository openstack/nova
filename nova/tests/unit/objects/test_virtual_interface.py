# Copyright (C) 2014, Red Hat, Inc.
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

from nova import db
from nova.objects import virtual_interface as vif_obj
from nova.tests.unit.objects import test_objects


fake_vif = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'address': '00:00:00:00:00:00',
    'network_id': 123,
    'instance_uuid': 'fake-uuid',
    'uuid': 'fake-uuid-2',
}


class _TestVirtualInterface(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], getattr(obj, field))

    def test_get_by_id(self):
        with mock.patch.object(db, 'virtual_interface_get') as get:
            get.return_value = fake_vif
            vif = vif_obj.VirtualInterface.get_by_id(self.context, 1)
            self._compare(self, fake_vif, vif)

    def test_get_by_uuid(self):
        with mock.patch.object(db, 'virtual_interface_get_by_uuid') as get:
            get.return_value = fake_vif
            vif = vif_obj.VirtualInterface.get_by_uuid(self.context,
                                                       'fake-uuid-2')
            self._compare(self, fake_vif, vif)

    def test_get_by_address(self):
        with mock.patch.object(db, 'virtual_interface_get_by_address') as get:
            get.return_value = fake_vif
            vif = vif_obj.VirtualInterface.get_by_address(self.context,
                                                          '00:00:00:00:00:00')
            self._compare(self, fake_vif, vif)

    def test_get_by_instance_and_network(self):
        with mock.patch.object(db,
                'virtual_interface_get_by_instance_and_network') as get:
            get.return_value = fake_vif
            vif = vif_obj.VirtualInterface.get_by_instance_and_network(
                    self.context, 'fake-uuid', 123)
            self._compare(self, fake_vif, vif)

    def test_create(self):
        vif = vif_obj.VirtualInterface(context=self.context)
        vif.address = '00:00:00:00:00:00'
        vif.network_id = 123
        vif.instance_uuid = 'fake-uuid'
        vif.uuid = 'fake-uuid-2'

        with mock.patch.object(db, 'virtual_interface_create') as create:
            create.return_value = fake_vif
            vif.create()

        self.assertEqual(self.context, vif._context)
        vif._context = None
        self._compare(self, fake_vif, vif)

    def test_delete_by_instance_uuid(self):
        with mock.patch.object(db,
                'virtual_interface_delete_by_instance') as delete:
            vif_obj.VirtualInterface.delete_by_instance_uuid(self.context,
                                                             'fake-uuid')
            delete.assert_called_with(self.context, 'fake-uuid')


class TestVirtualInterfaceObject(test_objects._LocalTest,
                                 _TestVirtualInterface):
    pass


class TestRemoteVirtualInterfaceObject(test_objects._RemoteTest,
                                       _TestVirtualInterface):
    pass


class _TestVirtualInterfaceList(object):
    def test_get_all(self):
        with mock.patch.object(db, 'virtual_interface_get_all') as get:
            get.return_value = [fake_vif]
            vifs = vif_obj.VirtualInterfaceList.get_all(self.context)
            self.assertEqual(1, len(vifs))
            _TestVirtualInterface._compare(self, fake_vif, vifs[0])

    def test_get_by_instance_uuid(self):
        with mock.patch.object(db, 'virtual_interface_get_by_instance') as get:
            get.return_value = [fake_vif]
            vifs = vif_obj.VirtualInterfaceList.get_by_instance_uuid(
                    self.context, 'fake-uuid')
            self.assertEqual(1, len(vifs))
            _TestVirtualInterface._compare(self, fake_vif, vifs[0])


class TestVirtualInterfaceList(test_objects._LocalTest,
                               _TestVirtualInterfaceList):
    pass


class TestRemoteVirtualInterfaceList(test_objects._RemoteTest,
                                     _TestVirtualInterfaceList):
    pass
