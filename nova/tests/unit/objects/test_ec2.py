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
from oslo_utils.fixture import uuidsentinel as uuids

from nova.db import api as db
from nova import objects
from nova.objects import ec2 as ec2_obj
from nova.tests.unit.objects import test_objects


fake_map = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'uuid': uuids.ec2_map_uuid,
}


class _TestEC2InstanceMapping(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], getattr(obj, field))

    def test_create(self):
        imap = ec2_obj.EC2InstanceMapping(context=self.context)
        imap.uuid = uuids.ec2_map_uuid

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
                                                     uuids.ec2_map_uuid)
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


class _TestS3ImageMapping(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], getattr(obj, field))

    def test_create(self):
        s3imap = ec2_obj.S3ImageMapping(context=self.context)
        s3imap.uuid = uuids.ec2_map_uuid

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
                                                        uuids.ec2_map_uuid)
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


class _TestEC2Ids(object):
    @mock.patch('nova.objects.ec2.glance_type_to_ec2_type')
    @mock.patch('nova.objects.ec2.glance_id_to_ec2_id')
    @mock.patch('nova.objects.ec2.id_to_ec2_inst_id')
    def test_get_by_instance(self, mock_inst, mock_glance, mock_type):
        mock_inst.return_value = 'fake-ec2-inst-id'
        mock_glance.side_effect = ['fake-ec2-ami-id',
                                   'fake-ec2-kernel-id',
                                   'fake-ec2-ramdisk-id']
        mock_type.side_effect = [mock.sentinel.ec2_kernel_type,
                                 mock.sentinel.ec2_ramdisk_type]
        inst = objects.Instance(uuid=uuids.instance,
                                image_ref='fake-image-id',
                                kernel_id='fake-kernel-id',
                                ramdisk_id='fake-ramdisk-id')

        result = ec2_obj.EC2Ids.get_by_instance(self.context, inst)

        self.assertEqual('fake-ec2-inst-id', result.instance_id)
        self.assertEqual('fake-ec2-ami-id', result.ami_id)
        self.assertEqual('fake-ec2-kernel-id', result.kernel_id)
        self.assertEqual('fake-ec2-ramdisk-id', result.ramdisk_id)

    @mock.patch('nova.objects.ec2.glance_id_to_ec2_id')
    @mock.patch('nova.objects.ec2.id_to_ec2_inst_id')
    def test_get_by_instance_no_image_ref(self, mock_inst, mock_glance):
        mock_inst.return_value = 'fake-ec2-inst-id'
        mock_glance.return_value = None
        inst = objects.Instance(uuid=uuids.instance, image_ref=None,
                                kernel_id=None, ramdisk_id=None)

        result = ec2_obj.EC2Ids.get_by_instance(self.context, inst)

        self.assertEqual('fake-ec2-inst-id', result.instance_id)
        self.assertIsNone(result.ami_id)
        self.assertIsNone(result.kernel_id)
        self.assertIsNone(result.ramdisk_id)

    @mock.patch('nova.objects.ec2.glance_type_to_ec2_type')
    @mock.patch('nova.objects.ec2.glance_id_to_ec2_id')
    @mock.patch('nova.objects.ec2.id_to_ec2_inst_id')
    def test_get_by_instance_no_kernel_id(self, mock_inst, mock_glance,
                                          mock_type):
        mock_inst.return_value = 'fake-ec2-inst-id'
        mock_glance.side_effect = ['fake-ec2-ami-id',
                                   'fake-ec2-ramdisk-id']
        mock_type.return_value = mock.sentinel.ec2_ramdisk_type
        inst = objects.Instance(uuid=uuids.instance,
                                image_ref='fake-image-id',
                                kernel_id=None, ramdisk_id='fake-ramdisk-id')

        result = ec2_obj.EC2Ids.get_by_instance(self.context, inst)

        self.assertEqual('fake-ec2-inst-id', result.instance_id)
        self.assertEqual('fake-ec2-ami-id', result.ami_id)
        self.assertIsNone(result.kernel_id)
        self.assertEqual('fake-ec2-ramdisk-id', result.ramdisk_id)

    @mock.patch('nova.objects.ec2.glance_type_to_ec2_type')
    @mock.patch('nova.objects.ec2.glance_id_to_ec2_id')
    @mock.patch('nova.objects.ec2.id_to_ec2_inst_id')
    def test_get_by_instance_no_ramdisk_id(self, mock_inst, mock_glance,
                                          mock_type):
        mock_inst.return_value = 'fake-ec2-inst-id'
        mock_glance.side_effect = ['fake-ec2-ami-id',
                                   'fake-ec2-kernel-id']
        mock_type.return_value = mock.sentinel.ec2_kernel_type
        inst = objects.Instance(uuid=uuids.instance,
                                image_ref='fake-image-id',
                                kernel_id='fake-kernel-id', ramdisk_id=None)

        result = ec2_obj.EC2Ids.get_by_instance(self.context, inst)

        self.assertEqual('fake-ec2-inst-id', result.instance_id)
        self.assertEqual('fake-ec2-ami-id', result.ami_id)
        self.assertEqual('fake-ec2-kernel-id', result.kernel_id)
        self.assertIsNone(result.ramdisk_id)


class TestEC2Ids(test_objects._LocalTest, _TestEC2Ids):
    pass


class TestRemoteEC2Ids(test_objects._RemoteTest, _TestEC2Ids):
    pass
