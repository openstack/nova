# Copyright 2013 Josh Durgin
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

import datetime

from lxml import etree
import webob

from nova.api.openstack.volume import extensions
from nova.api.openstack.volume import volumes
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests.image import fake as fake_image
from nova.volume import api as volume_api


FLAGS = flags.FLAGS

TEST_SNAPSHOT_UUID = '00000000-0000-0000-0000-000000000001'


def stub_snapshot_get(self, context, snapshot_id):
    if snapshot_id != TEST_SNAPSHOT_UUID:
        raise exception.NotFound

    return {
            'id': snapshot_id,
            'volume_id': 12,
            'status': 'available',
            'volume_size': 100,
            'created_at': None,
            'display_name': 'Default name',
            'display_description': 'Default description',
            }


class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = volumes.VolumeController(self.ext_mgr)

        self.stubs.Set(db, 'volume_get_all', fakes.stub_volume_get_all)
        self.stubs.Set(db, 'volume_get_all_by_project',
                       fakes.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(volume_api.API, 'delete', fakes.stub_volume_delete)

    def test_volume_create(self):
        self.stubs.Set(volume_api.API, "create", fakes.stub_volume_create)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        res = self.controller.create(req, body)
        expected = {'volume': {'status': 'fakestatus',
                               'display_description': 'Volume Test Desc',
                               'availability_zone': 'zone1:host1',
                               'display_name': 'Volume Test Name',
                               'attachments': [{'device': '/',
                                                'server_id': 'fakeuuid',
                                                'id': '1',
                                                'volume_id': '1'}],
                               'volume_type': 'vol_type_name',
                               'snapshot_id': None,
                               'metadata': {},
                               'id': '1',
                               'created_at': datetime.datetime(1999, 1, 1,
                                                               1, 1, 1),
                               'size': 100}}
        self.assertEqual(res.obj, expected)
        self.assertEqual(res.code, 200)
        self.assertTrue('location' in res.headers)

    def test_volume_creation_fails_with_bad_size(self):
        vol = {"size": '',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(exception.InvalidInput,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_no_body(self):
        body = {}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_id(self):
        self.stubs.Set(volume_api.API, "create", fakes.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {"size": '1',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "nova",
               "imageRef": 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'}
        expected = {'volume': {'status': 'fakestatus',
                           'display_description': 'Volume Test Desc',
                           'availability_zone': 'nova',
                           'display_name': 'Volume Test Name',
                           'attachments': [{'device': '/',
                                            'server_id': 'fakeuuid',
                                            'id': '1',
                                            'volume_id': '1'}],
                            'volume_type': 'vol_type_name',
                            'image_id': 'c905cedb-7281-47e4-8a62-f26bc5fc4c77',
                            'snapshot_id': None,
                            'metadata': {},
                            'id': '1',
                            'created_at': datetime.datetime(1999, 1, 1,
                                                            1, 1, 1),
                            'size': '1'}
                    }
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        res = self.controller.create(req, body)
        self.maxDiff = 4096
        self.assertEqual(res.obj, expected)

    def test_volume_create_with_image_id_and_snapshot_id(self):
        self.stubs.Set(volume_api.API, "create", fakes.stub_volume_create)
        self.stubs.Set(volume_api.API, "get_snapshot", stub_snapshot_get)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {"size": '1',
                "display_name": "Volume Test Name",
                "display_description": "Volume Test Desc",
                "availability_zone": "nova",
                "imageRef": 'c905cedb-7281-47e4-8a62-f26bc5fc4c77',
                "snapshot_id": TEST_SNAPSHOT_UUID}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_id_is_integer(self):
        self.stubs.Set(volume_api.API, "create", fakes.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {"size": '1',
                "display_name": "Volume Test Name",
                "display_description": "Volume Test Desc",
                "availability_zone": "nova",
                "imageRef": 1234}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_id_not_uuid_format(self):
        self.stubs.Set(volume_api.API, "create", fakes.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {"size": '1',
                "display_name": "Volume Test Name",
                "display_description": "Volume Test Desc",
                "availability_zone": "nova",
                "imageRef": '12345'}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_list(self):
        self.stubs.Set(volume_api.API, 'get_all',
                     fakes.stub_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v1/volumes')
        res_dict = self.controller.index(req)
        expected = {'volumes': [{'status': 'fakestatus',
                                 'display_description': 'displaydesc',
                                 'availability_zone': 'fakeaz',
                                 'display_name': 'displayname',
                                 'attachments': [{'device': '/',
                                                  'server_id': 'fakeuuid',
                                                  'id': '1',
                                                  'volume_id': '1'}],
                                 'volume_type': 'vol_type_name',
                                 'snapshot_id': None,
                                 'metadata': {},
                                 'id': '1',
                                 'created_at': datetime.datetime(1999, 1, 1,
                                                                 1, 1, 1),
                                 'size': 1}]}
        self.maxDiff = None
        self.assertEqual(res_dict, expected)

    def test_volume_list_detail(self):
        self.stubs.Set(volume_api.API, 'get_all',
                   fakes.stub_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v1/volumes/detail')
        res_dict = self.controller.index(req)
        expected = {'volumes': [{'status': 'fakestatus',
                                 'display_description': 'displaydesc',
                                 'availability_zone': 'fakeaz',
                                 'display_name': 'displayname',
                                 'attachments': [{'device': '/',
                                                  'server_id': 'fakeuuid',
                                                  'id': '1',
                                                  'volume_id': '1'}],
                                 'volume_type': 'vol_type_name',
                                 'snapshot_id': None,
                                 'metadata': {},
                                 'id': '1',
                                 'created_at': datetime.datetime(1999, 1, 1,
                                                                 1, 1, 1),
                                 'size': 1}]}
        self.assertEqual(res_dict, expected)

    def test_volume_show(self):
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = {'volume': {'status': 'fakestatus',
                               'display_description': 'displaydesc',
                               'availability_zone': 'fakeaz',
                               'display_name': 'displayname',
                               'attachments': [{'device': '/',
                                                'server_id': 'fakeuuid',
                                                'id': '1',
                                                'volume_id': '1'}],
                               'volume_type': 'vol_type_name',
                               'snapshot_id': None,
                               'metadata': {},
                               'id': '1',
                               'created_at': datetime.datetime(1999, 1, 1,
                                                               1, 1, 1),
                               'size': 1}}
        self.assertEqual(res_dict, expected)

    def test_volume_show_no_attachments(self):
        def stub_volume_get(self, context, volume_id):
            return fakes.stub_volume(volume_id, attach_status='detached')

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = {'volume': {'status': 'fakestatus',
                               'display_description': 'displaydesc',
                               'availability_zone': 'fakeaz',
                               'display_name': 'displayname',
                               'attachments': [],
                               'volume_type': 'vol_type_name',
                               'snapshot_id': None,
                               'metadata': {},
                               'id': '1',
                               'created_at': datetime.datetime(1999, 1, 1,
                                                               1, 1, 1),
                               'size': 1}}
        self.assertEqual(res_dict, expected)

    def test_volume_show_no_volume(self):
        self.stubs.Set(volume_api.API, "get", fakes.stub_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req,
                          1)

    def test_volume_delete(self):
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        resp = self.controller.delete(req, 1)
        self.assertEqual(resp.status_int, 202)

    def test_volume_delete_no_volume(self):
        self.stubs.Set(volume_api.API, "get", fakes.stub_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete,
                          req,
                          1)

    def test_admin_list_volumes_limited_to_project(self):
        req = fakes.HTTPRequest.blank('/v1/fake/volumes',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertTrue('volumes' in res)
        self.assertEqual(1, len(res['volumes']))

    def test_admin_list_volumes_all_tenants(self):
        req = fakes.HTTPRequest.blank('/v1/fake/volumes?all_tenants=1',
                                      use_admin_context=True)
        res = self.controller.index(req)
        self.assertTrue('volumes' in res)
        self.assertEqual(3, len(res['volumes']))

    def test_all_tenants_non_admin_gets_all_tenants(self):
        req = fakes.HTTPRequest.blank('/v1/fake/volumes?all_tenants=1')
        res = self.controller.index(req)
        self.assertTrue('volumes' in res)
        self.assertEqual(1, len(res['volumes']))

    def test_non_admin_get_by_project(self):
        req = fakes.HTTPRequest.blank('/v1/fake/volumes')
        res = self.controller.index(req)
        self.assertTrue('volumes' in res)
        self.assertEqual(1, len(res['volumes']))


class VolumeSerializerTest(test.TestCase):
    def _verify_volume_attachment(self, attach, tree):
        for attr in ('id', 'volume_id', 'server_id', 'device'):
            self.assertEqual(str(attach[attr]), tree.get(attr))

    def _verify_volume(self, vol, tree):
        self.assertEqual(tree.tag, 'volume')

        for attr in ('id', 'status', 'size', 'availability_zone', 'created_at',
                     'display_name', 'display_description', 'volume_type',
                     'snapshot_id'):
            self.assertEqual(str(vol[attr]), tree.get(attr))

        for child in tree:
            self.assertTrue(child.tag in ('attachments', 'metadata'))
            if child.tag == 'attachments':
                self.assertEqual(1, len(child))
                self.assertEqual('attachment', child[0].tag)
                self._verify_volume_attachment(vol['attachments'][0], child[0])
            elif child.tag == 'metadata':
                not_seen = set(vol['metadata'].keys())
                for gr_child in child:
                    self.assertTrue(gr_child.get("key") in not_seen)
                    self.assertEqual(str(vol['metadata'][gr_child.get("key")]),
                                     gr_child.text)
                    not_seen.remove(gr_child.get("key"))
                self.assertEqual(0, len(not_seen))

    def test_volume_show_create_serializer(self):
        serializer = volumes.VolumeTemplate()
        raw_volume = dict(
            id='vol_id',
            status='vol_status',
            size=1024,
            availability_zone='vol_availability',
            created_at=timeutils.utcnow(),
            attachments=[dict(
                    id='vol_id',
                    volume_id='vol_id',
                    server_id='instance_uuid',
                    device='/foo')],
            display_name='vol_name',
            display_description='vol_desc',
            volume_type='vol_type',
            snapshot_id='snap_id',
            metadata=dict(
                foo='bar',
                baz='quux',
                ),
            )
        text = serializer.serialize(dict(volume=raw_volume))

        print text
        tree = etree.fromstring(text)

        self._verify_volume(raw_volume, tree)

    def test_volume_index_detail_serializer(self):
        serializer = volumes.VolumesTemplate()
        raw_volumes = [dict(
                id='vol1_id',
                status='vol1_status',
                size=1024,
                availability_zone='vol1_availability',
                created_at=timeutils.utcnow(),
                attachments=[dict(
                        id='vol1_id',
                        volume_id='vol1_id',
                        server_id='instance_uuid',
                        device='/foo1')],
                display_name='vol1_name',
                display_description='vol1_desc',
                volume_type='vol1_type',
                snapshot_id='snap1_id',
                metadata=dict(
                    foo='vol1_foo',
                    bar='vol1_bar',
                    ),
                ),
                       dict(
                id='vol2_id',
                status='vol2_status',
                size=1024,
                availability_zone='vol2_availability',
                created_at=timeutils.utcnow(),
                attachments=[dict(
                        id='vol2_id',
                        volume_id='vol2_id',
                        server_id='instance_uuid',
                        device='/foo2')],
                display_name='vol2_name',
                display_description='vol2_desc',
                volume_type='vol2_type',
                snapshot_id='snap2_id',
                metadata=dict(
                    foo='vol2_foo',
                    bar='vol2_bar',
                    ),
                )]
        text = serializer.serialize(dict(volumes=raw_volumes))

        print text
        tree = etree.fromstring(text)

        self.assertEqual('volumes', tree.tag)
        self.assertEqual(len(raw_volumes), len(tree))
        for idx, child in enumerate(tree):
            self._verify_volume(raw_volumes[idx], child)


class TestVolumeCreateRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestVolumeCreateRequestXMLDeserializer, self).setUp()
        self.deserializer = volumes.CreateDeserializer()

    def test_minimal_volume(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_display_name(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_display_description(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_volume_type(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "display_name": "Volume-xml",
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_availability_zone(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"
        availability_zone="us-east1"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
                "availability_zone": "us-east1",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_metadata(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        display_name="Volume-xml"
        size="1">
        <metadata><meta key="Type">work</meta></metadata></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "display_name": "Volume-xml",
                "size": "1",
                "metadata": {
                    "Type": "work",
                },
            },
        }
        self.assertEquals(request['body'], expected)

    def test_full_volume(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"
        availability_zone="us-east1">
        <metadata><meta key="Type">work</meta></metadata></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
                "availability_zone": "us-east1",
                "metadata": {
                    "Type": "work",
                },
            },
        }
        self.maxDiff = None
        self.assertEquals(request['body'], expected)


class VolumesUnprocessableEntityTestCase(test.TestCase):

    """
    Tests of places we throw 422 Unprocessable Entity from
    """

    def setUp(self):
        super(VolumesUnprocessableEntityTestCase, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = volumes.VolumeController(self.ext_mgr)

    def _unprocessable_volume_create(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/volumes')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, body)

    def test_create_no_body(self):
        self._unprocessable_volume_create(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._unprocessable_volume_create(body=body)

    def test_create_malformed_entity(self):
        body = {'volume': 'string'}
        self._unprocessable_volume_create(body=body)
