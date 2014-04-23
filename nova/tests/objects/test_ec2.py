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
from nova.objects import ec2 as ec2_obj
from nova.tests.objects import test_objects


fake_vmap = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'uuid': 'fake-uuid-2',
}


class _TestVolumeMapping(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    def test_create(self):
        vmap = ec2_obj.VolumeMapping()
        vmap.uuid = 'fake-uuid-2'

        with mock.patch.object(db, 'ec2_volume_create') as create:
            create.return_value = fake_vmap
            vmap.create(self.context)

        self.assertEqual(self.context, vmap._context)
        vmap._context = None
        self._compare(self, fake_vmap, vmap)

    def test_get_by_uuid(self):
        with mock.patch.object(db, 'ec2_volume_get_by_uuid') as get:
            get.return_value = fake_vmap
            vmap = ec2_obj.VolumeMapping.get_by_uuid(self.context,
                                                     'fake-uuid-2')
            self._compare(self, fake_vmap, vmap)

    def test_get_by_ec2_id(self):
        with mock.patch.object(db, 'ec2_volume_get_by_id') as get:
            get.return_value = fake_vmap
            vmap = ec2_obj.VolumeMapping.get_by_id(self.context, 1)
            self._compare(self, fake_vmap, vmap)


class TestVolumeMapping(test_objects._LocalTest, _TestVolumeMapping):
    pass


class TestRemoteVolumeMapping(test_objects._RemoteTest, _TestVolumeMapping):
    pass
