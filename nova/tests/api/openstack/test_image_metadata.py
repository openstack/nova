# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import json
import stubout
import unittest
import webob
import xml.dom.minidom as minidom


from nova import flags
from nova.api import openstack
from nova.tests.api.openstack import fakes
import nova.wsgi


FLAGS = flags.FLAGS


class ImageMetaDataTest(unittest.TestCase):

    IMAGE_FIXTURES = [
        {'status': 'active',
        'name': 'image1',
        'deleted': False,
        'container_format': None,
        'created_at': '2011-03-22T17:40:15',
        'disk_format': None,
        'updated_at': '2011-03-22T17:40:15',
        'id': '1',
        'location': 'file:///var/lib/glance/images/1',
        'is_public': True,
        'deleted_at': None,
        'properties': {
            'key1': 'value1',
            'key2': 'value2'},
        'size': 5882349},
        {'status': 'active',
        'name': 'image2',
        'deleted': False,
        'container_format': None,
        'created_at': '2011-03-22T17:40:15',
        'disk_format': None,
        'updated_at': '2011-03-22T17:40:15',
        'id': '2',
        'location': 'file:///var/lib/glance/images/2',
        'is_public': True,
        'deleted_at': None,
        'properties': {
            'key1': 'value1',
            'key2': 'value2'},
        'size': 5882349},
        {'status': 'active',
        'name': 'image3',
        'deleted': False,
        'container_format': None,
        'created_at': '2011-03-22T17:40:15',
        'disk_format': None,
        'updated_at': '2011-03-22T17:40:15',
        'id': '3',
        'location': 'file:///var/lib/glance/images/2',
        'is_public': True,
        'deleted_at': None,
        'properties': {},
        'size': 5882349},
        ]

    def setUp(self):
        super(ImageMetaDataTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.orig_image_service = FLAGS.image_service
        FLAGS.image_service = 'nova.image.glance.GlanceImageService'
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_auth(self.stubs)
        # NOTE(dprince) max out properties/metadata in image 3 for testing
        img3 = self.IMAGE_FIXTURES[2]
        for num in range(FLAGS.quota_metadata_items):
            img3['properties']['key%i' % num] = "blah"
        fakes.stub_out_glance(self.stubs, self.IMAGE_FIXTURES)

    def tearDown(self):
        self.stubs.UnsetAll()
        FLAGS.image_service = self.orig_image_service
        super(ImageMetaDataTest, self).tearDown()

    def test_index(self):
        req = webob.Request.blank('/v1.1/images/1/meta')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('value1', res_dict['metadata']['key1'])

    def test_index_xml(self):
        serializer = openstack.image_metadata.ImageMetadataXMLSerializer()
        fixture = {
            'metadata': {
                'one': 'two',
                'three': 'four',
            },
        }
        output = serializer.index(fixture)
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
            <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
                <meta key="three">
                    four
                </meta>
                <meta key="one">
                    two
                </meta>
            </metadata>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_index_xml_null_value(self):
        serializer = openstack.image_metadata.ImageMetadataXMLSerializer()
        fixture = {
            'metadata': {
                'three': None,
            },
        }
        output = serializer.index(fixture)
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
            <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
                <meta key="three">
                    None
                </meta>
            </metadata>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_show(self):
        req = webob.Request.blank('/v1.1/images/1/meta/key1')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('value1', res_dict['key1'])

    def test_show_xml(self):
        serializer = openstack.image_metadata.ImageMetadataXMLSerializer()
        fixture = {
            'meta': {
                'one': 'two',
            },
        }
        output = serializer.show(fixture)
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
            <meta xmlns="http://docs.openstack.org/compute/api/v1.1" key="one">
                two
            </meta>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_show_not_found(self):
        req = webob.Request.blank('/v1.1/images/1/meta/key9')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(404, res.status_int)

    def test_create(self):
        req = webob.Request.blank('/v1.1/images/2/meta')
        req.environ['api.version'] = '1.1'
        req.method = 'POST'
        req.body = '{"metadata": {"key9": "value9"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('value9', res_dict['metadata']['key9'])
        # other items should not be modified
        self.assertEqual('value1', res_dict['metadata']['key1'])
        self.assertEqual('value2', res_dict['metadata']['key2'])
        self.assertEqual(1, len(res_dict))

    def test_create_xml(self):
        serializer = openstack.image_metadata.ImageMetadataXMLSerializer()
        fixture = {
            'metadata': {
                'key9': 'value9',
                'key2': 'value2',
                'key1': 'value1',
            },
        }
        output = serializer.create(fixture)
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
            <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
                <meta key="key2">
                    value2
                </meta>
                <meta key="key9">
                    value9
                </meta>
                <meta key="key1">
                    value1
                </meta>
            </metadata>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_update_item(self):
        req = webob.Request.blank('/v1.1/images/1/meta/key1')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.body = '{"key1": "zz"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual('zz', res_dict['key1'])

    def test_update_item_xml(self):
        serializer = openstack.image_metadata.ImageMetadataXMLSerializer()
        fixture = {
            'meta': {
                'one': 'two',
            },
        }
        output = serializer.update(fixture)
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
            <meta xmlns="http://docs.openstack.org/compute/api/v1.1" key="one">
                two
            </meta>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_update_item_too_many_keys(self):
        req = webob.Request.blank('/v1.1/images/1/meta/key1')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.body = '{"key1": "value1", "key2": "value2"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_body_uri_mismatch(self):
        req = webob.Request.blank('/v1.1/images/1/meta/bad')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.body = '{"key1": "value1"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_delete(self):
        req = webob.Request.blank('/v1.1/images/2/meta/key1')
        req.environ['api.version'] = '1.1'
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)

    def test_delete_not_found(self):
        req = webob.Request.blank('/v1.1/images/2/meta/blah')
        req.environ['api.version'] = '1.1'
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_too_many_metadata_items_on_create(self):
        data = {"metadata": {}}
        for num in range(FLAGS.quota_metadata_items + 1):
            data['metadata']['key%i' % num] = "blah"
        json_string = str(data).replace("\'", "\"")
        req = webob.Request.blank('/v1.1/images/2/meta')
        req.environ['api.version'] = '1.1'
        req.method = 'POST'
        req.body = json_string
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_too_many_metadata_items_on_put(self):
        req = webob.Request.blank('/v1.1/images/3/meta/blah')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.body = '{"blah": "blah"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)
