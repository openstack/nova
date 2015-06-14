# Copyright 2011 Isaku Yamahata
# All Rights Reserved.
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

import binascii
import os
import tempfile

import eventlet
import fixtures
from mox3 import mox

from nova.api.ec2 import ec2utils
from nova import context
from nova import db
from nova import exception
from nova.image import s3
from nova import test
from nova.tests.unit.image import fake


ami_manifest_xml = """<?xml version="1.0" ?>
<manifest>
        <version>2011-06-17</version>
        <bundler>
                <name>test-s3</name>
                <version>0</version>
                <release>0</release>
        </bundler>
        <machine_configuration>
                <architecture>x86_64</architecture>
                <block_device_mapping>
                        <mapping>
                                <virtual>ami</virtual>
                                <device>sda1</device>
                        </mapping>
                        <mapping>
                                <virtual>root</virtual>
                                <device>/dev/sda1</device>
                        </mapping>
                        <mapping>
                                <virtual>ephemeral0</virtual>
                                <device>sda2</device>
                        </mapping>
                        <mapping>
                                <virtual>swap</virtual>
                                <device>sda3</device>
                        </mapping>
                </block_device_mapping>
                <kernel_id>aki-00000001</kernel_id>
                <ramdisk_id>ari-00000001</ramdisk_id>
        </machine_configuration>
</manifest>
"""

file_manifest_xml = """<?xml version="1.0" ?>
<manifest>
        <image>
                <ec2_encrypted_key>foo</ec2_encrypted_key>
                <user_encrypted_key>foo</user_encrypted_key>
                <ec2_encrypted_iv>foo</ec2_encrypted_iv>
                <parts count="1">
                        <part index="0">
                               <filename>foo</filename>
                        </part>
                </parts>
        </image>
</manifest>
"""


class TestS3ImageService(test.TestCase):
    def setUp(self):
        super(TestS3ImageService, self).setUp()
        self.context = context.RequestContext(None, None)
        self.useFixture(fixtures.FakeLogger('boto'))

        # set up 3 fixtures to test shows, should have id '1', '2', and '3'
        db.s3_image_create(self.context,
                           '155d900f-4e14-4e4c-a73d-069cbf4541e6')
        db.s3_image_create(self.context,
                           'a2459075-d96c-40d5-893e-577ff92e721c')
        db.s3_image_create(self.context,
                           '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6')

        fake.stub_out_image_service(self.stubs)
        self.image_service = s3.S3ImageService()
        ec2utils.reset_cache()

    def tearDown(self):
        super(TestS3ImageService, self).tearDown()
        fake.FakeImageService_reset()

    def _assertEqualList(self, list0, list1, keys):
        self.assertEqual(len(list0), len(list1))
        key = keys[0]
        for x in list0:
            self.assertEqual(len(x), len(keys))
            self.assertIn(key, x)
            for y in list1:
                self.assertIn(key, y)
                if x[key] == y[key]:
                    for k in keys:
                        self.assertEqual(x[k], y[k])

    def test_show_cannot_use_uuid(self):
        self.assertRaises(exception.ImageNotFound,
                          self.image_service.show, self.context,
                          '155d900f-4e14-4e4c-a73d-069cbf4541e6')

    def test_show_translates_correctly(self):
        self.image_service.show(self.context, '1')

    def test_show_translates_image_state_correctly(self):
        def my_fake_show(self, context, image_id, **kwargs):
            fake_state_map = {
                '155d900f-4e14-4e4c-a73d-069cbf4541e6': 'downloading',
                'a2459075-d96c-40d5-893e-577ff92e721c': 'failed_decrypt',
                '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6': 'available'}
            return {'id': image_id,
                    'name': 'fakeimage123456',
                    'deleted_at': None,
                    'deleted': False,
                    'status': 'active',
                    'is_public': False,
                    'container_format': 'raw',
                    'disk_format': 'raw',
                    'size': '25165824',
                    'properties': {'image_state': fake_state_map[image_id]}}

        # Override part of the fake image service as well just for
        # this test so we can set the image_state to various values
        # and test that S3ImageService does the correct mapping for
        # us. We can't put fake bad or pending states in the real fake
        # image service as it causes other tests to fail
        self.stubs.Set(fake._FakeImageService, 'show', my_fake_show)
        ret_image = self.image_service.show(self.context, '1')
        self.assertEqual(ret_image['properties']['image_state'], 'pending')
        ret_image = self.image_service.show(self.context, '2')
        self.assertEqual(ret_image['properties']['image_state'], 'failed')
        ret_image = self.image_service.show(self.context, '3')
        self.assertEqual(ret_image['properties']['image_state'], 'available')

    def test_detail(self):
        self.image_service.detail(self.context)

    def test_s3_create(self):
        metadata = {'properties': {
            'root_device_name': '/dev/sda1',
            'block_device_mapping': [
                {'device_name': '/dev/sda1',
                 'snapshot_id': 'snap-12345678',
                 'delete_on_termination': True},
                {'device_name': '/dev/sda2',
                 'virtual_name': 'ephemeral0'},
                {'device_name': '/dev/sdb0',
                 'no_device': True}]}}
        _manifest, image, image_uuid = self.image_service._s3_parse_manifest(
            self.context, metadata, ami_manifest_xml)

        ret_image = self.image_service.show(self.context, image['id'])
        self.assertIn('properties', ret_image)
        properties = ret_image['properties']

        self.assertIn('mappings', properties)
        mappings = properties['mappings']
        expected_mappings = [
            {"device": "sda1", "virtual": "ami"},
            {"device": "/dev/sda1", "virtual": "root"},
            {"device": "sda2", "virtual": "ephemeral0"},
            {"device": "sda3", "virtual": "swap"}]
        self._assertEqualList(mappings, expected_mappings,
            ['device', 'virtual'])

        self.assertIn('block_device_mapping', properties)
        block_device_mapping = properties['block_device_mapping']
        expected_bdm = [
            {'device_name': '/dev/sda1',
             'snapshot_id': 'snap-12345678',
             'delete_on_termination': True},
            {'device_name': '/dev/sda2',
             'virtual_name': 'ephemeral0'},
            {'device_name': '/dev/sdb0',
             'no_device': True}]
        self.assertEqual(block_device_mapping, expected_bdm)

    def _initialize_mocks(self):
        handle, tempf = tempfile.mkstemp(dir='/tmp')
        ignore = mox.IgnoreArg()
        mockobj = self.mox.CreateMockAnything()
        self.stubs.Set(self.image_service, '_conn', mockobj)
        mockobj(ignore).AndReturn(mockobj)
        self.stubs.Set(mockobj, 'get_bucket', mockobj)
        mockobj(ignore).AndReturn(mockobj)
        self.stubs.Set(mockobj, 'get_key', mockobj)
        mockobj(ignore).AndReturn(mockobj)
        self.stubs.Set(mockobj, 'get_contents_as_string', mockobj)
        mockobj().AndReturn(file_manifest_xml)
        self.stubs.Set(self.image_service, '_download_file', mockobj)
        mockobj(ignore, ignore, ignore).AndReturn(tempf)
        self.stubs.Set(binascii, 'a2b_hex', mockobj)
        mockobj(ignore).AndReturn('foo')
        mockobj(ignore).AndReturn('foo')
        self.stubs.Set(self.image_service, '_decrypt_image', mockobj)
        mockobj(ignore, ignore, ignore, ignore, ignore).AndReturn(mockobj)
        self.stubs.Set(self.image_service, '_untarzip_image', mockobj)
        mockobj(ignore, ignore).AndReturn(tempf)
        self.mox.ReplayAll()

    def test_s3_create_image_locations(self):
        image_location_1 = 'testbucket_1/test.img.manifest.xml'
        # Use another location that starts with a '/'
        image_location_2 = '/testbucket_2/test.img.manifest.xml'

        metadata = [{'properties': {'image_location': image_location_1}},
                    {'properties': {'image_location': image_location_2}}]

        for mdata in metadata:
            self._initialize_mocks()
            image = self.image_service._s3_create(self.context, mdata)
            eventlet.sleep()
            translated = self.image_service._translate_id_to_uuid(self.context,
                                                              image)
            uuid = translated['id']
            image_service = fake.FakeImageService()
            updated_image = image_service.update(self.context, uuid,
                            {'properties': {'image_state': 'available'}},
                            purge_props=False)
            self.assertEqual(updated_image['properties']['image_state'],
                             'available')

    def test_s3_create_is_public(self):
        self._initialize_mocks()
        metadata = {'properties': {
                    'image_location': 'mybucket/my.img.manifest.xml'},
                    'name': 'mybucket/my.img'}
        img = self.image_service._s3_create(self.context, metadata)
        eventlet.sleep()
        translated = self.image_service._translate_id_to_uuid(self.context,
                                                              img)
        uuid = translated['id']
        image_service = fake.FakeImageService()
        updated_image = image_service.update(self.context, uuid,
                        {'is_public': True}, purge_props=False)
        self.assertTrue(updated_image['is_public'])
        self.assertEqual(updated_image['status'], 'active')
        self.assertEqual(updated_image['properties']['image_state'],
                          'available')

    def test_s3_malicious_tarballs(self):
        self.assertRaises(exception.NovaException,
            self.image_service._test_for_malicious_tarball,
            "/unused", os.path.join(os.path.dirname(__file__), 'abs.tar.gz'))
        self.assertRaises(exception.NovaException,
            self.image_service._test_for_malicious_tarball,
            "/unused", os.path.join(os.path.dirname(__file__), 'rel.tar.gz'))
