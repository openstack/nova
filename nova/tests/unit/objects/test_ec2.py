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
from nova.tests.unit.objects import test_objects


fake_map = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'uuid': 'fake-uuid-2',
}


class _TestEC2InstanceMapping(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    def test_create(self):
        imap = ec2_obj.EC2InstanceMapping(context=self.context)
        imap.uuid = 'fake-uuid-2'

        with mock.patch.object(db, 'ec2_instance_create') as create:
            create.return_value = fake_map
            imap.create()

        self.assertEqual(self.context, imap._context)
        imap._context = None
        self._compare(self, fake_map, imap)

    def test_get_by_uuid(self):
        with mock.patch.object(db, 'ec2_instance_get_by_uuid') as get:
            get.return_value = fake_map
            imap = ec2_obj.EC2InstanceMapping.get_by_uuid(self.context,
                                                     'fake-uuid-2')
            self._compare(self, fake_map, imap)

    def test_get_by_ec2_id(self):
        with mock.patch.object(db, 'ec2_instance_get_by_id') as get:
            get.return_value = fake_map
            imap = ec2_obj.EC2InstanceMapping.get_by_id(self.context, 1)
            self._compare(self, fake_map, imap)


class TestEC2InstanceMapping(test_objects._LocalTest, _TestEC2InstanceMapping):
    pass


class TestRemoteEC2InstanceMapping(test_objects._RemoteTest,
                                   _TestEC2InstanceMapping):
    pass


class _TestEC2VolumeMapping(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    def test_create(self):
        vmap = ec2_obj.EC2VolumeMapping(context=self.context)
        vmap.uuid = 'fake-uuid-2'

        with mock.patch.object(db, 'ec2_volume_create') as create:
            create.return_value = fake_map
            vmap.create()

        self.assertEqual(self.context, vmap._context)
        vmap._context = None
        self._compare(self, fake_map, vmap)

    def test_get_by_uuid(self):
        with mock.patch.object(db, 'ec2_volume_get_by_uuid') as get:
            get.return_value = fake_map
            vmap = ec2_obj.EC2VolumeMapping.get_by_uuid(self.context,
                                                     'fake-uuid-2')
            self._compare(self, fake_map, vmap)

    def test_get_by_ec2_id(self):
        with mock.patch.object(db, 'ec2_volume_get_by_id') as get:
            get.return_value = fake_map
            vmap = ec2_obj.EC2VolumeMapping.get_by_id(self.context, 1)
            self._compare(self, fake_map, vmap)


class TestEC2VolumeMapping(test_objects._LocalTest, _TestEC2VolumeMapping):
    pass


class TestRemoteEC2VolumeMapping(test_objects._RemoteTest,
                                 _TestEC2VolumeMapping):
    pass


class _TestEC2SnapshotMapping(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    def test_create(self):
        smap = ec2_obj.EC2SnapshotMapping(context=self.context)
        smap.uuid = 'fake-uuid-2'

        with mock.patch.object(db, 'ec2_snapshot_create') as create:
            create.return_value = fake_map
            smap.create()

        self.assertEqual(self.context, smap._context)
        smap._context = None
        self._compare(self, fake_map, smap)

    def test_get_by_uuid(self):
        with mock.patch.object(db, 'ec2_snapshot_get_by_uuid') as get:
            get.return_value = fake_map
            smap = ec2_obj.EC2SnapshotMapping.get_by_uuid(self.context,
                                                          'fake-uuid-2')
            self._compare(self, fake_map, smap)

    def test_get_by_ec2_id(self):
        with mock.patch.object(db, 'ec2_snapshot_get_by_ec2_id') as get:
            get.return_value = fake_map
            smap = ec2_obj.EC2SnapshotMapping.get_by_id(self.context, 1)
            self._compare(self, fake_map, smap)


class TestEC2SnapshotMapping(test_objects._LocalTest, _TestEC2SnapshotMapping):
    pass


class TestRemoteEC2SnapshotMapping(test_objects._RemoteTest,
                                   _TestEC2SnapshotMapping):
    pass


class _TestS3ImageMapping(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    def test_create(self):
        s3imap = ec2_obj.S3ImageMapping(context=self.context)
        s3imap.uuid = 'fake-uuid-2'

        with mock.patch.object(db, 's3_image_create') as create:
            create.return_value = fake_map
            s3imap.create()

        self.assertEqual(self.context, s3imap._context)
        s3imap._context = None
        self._compare(self, fake_map, s3imap)

    def test_get_by_uuid(self):
        with mock.patch.object(db, 's3_image_get_by_uuid') as get:
            get.return_value = fake_map
            s3imap = ec2_obj.S3ImageMapping.get_by_uuid(self.context,
                                                        'fake-uuid-2')
            self._compare(self, fake_map, s3imap)

    def test_get_by_s3_id(self):
        with mock.patch.object(db, 's3_image_get') as get:
            get.return_value = fake_map
            s3imap = ec2_obj.S3ImageMapping.get_by_id(self.context, 1)
            self._compare(self, fake_map, s3imap)


class TestS3ImageMapping(test_objects._LocalTest, _TestS3ImageMapping):
    pass


class TestRemoteS3ImageMapping(test_objects._RemoteTest, _TestS3ImageMapping):
    pass
