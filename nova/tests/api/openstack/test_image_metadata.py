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
import webob


from nova import flags
from nova.api import openstack
from nova import test
from nova.tests.api.openstack import fakes
import nova.wsgi


FLAGS = flags.FLAGS


class ImageMetaDataTest(test.TestCase):

    IMAGE_FIXTURES = [
        {'status': 'active',
        'name': 'image1',
        'deleted': False,
        'container_format': None,
        'checksum': None,
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
        'checksum': None,
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
        'checksum': None,
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
        self.flags(image_service='nova.image.glance.GlanceImageService')
        # NOTE(dprince) max out properties/metadata in image 3 for testing
        img3 = self.IMAGE_FIXTURES[2]
        for num in range(FLAGS.quota_metadata_items):
            img3['properties']['key%i' % num] = "blah"
        fakes.stub_out_glance(self.stubs, self.IMAGE_FIXTURES)

    def test_index(self):
        req = webob.Request.blank('/v1.1/123/images/1/metadata')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        expected = self.IMAGE_FIXTURES[0]['properties']
        self.assertEqual(len(expected), len(res_dict['metadata']))
        for (key, value) in res_dict['metadata'].items():
            self.assertEqual(value, res_dict['metadata'][key])

    def test_show(self):
        req = webob.Request.blank('/v1.1/fake/images/1/metadata/key1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertTrue('meta' in res_dict)
        self.assertEqual(len(res_dict['meta']), 1)
        self.assertEqual('value1', res_dict['meta']['key1'])

    def test_show_not_found(self):
        req = webob.Request.blank('/v1.1/fake/images/1/metadata/key9')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_create(self):
        req = webob.Request.blank('/v1.1/fake/images/2/metadata')
        req.method = 'POST'
        req.body = '{"metadata": {"key9": "value9"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(200, res.status_int)
        actual_output = json.loads(res.body)

        expected_output = {
            'metadata': {
                'key1': 'value1',
                'key2': 'value2',
                'key9': 'value9',
            },
        }

        self.assertEqual(expected_output, actual_output)

    def test_update_all(self):
        req = webob.Request.blank('/v1.1/fake/images/1/metadata')
        req.method = 'PUT'
        req.body = '{"metadata": {"key9": "value9"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(200, res.status_int)
        actual_output = json.loads(res.body)

        expected_output = {
            'metadata': {
                'key9': 'value9',
            },
        }

        self.assertEqual(expected_output, actual_output)

    def test_update_item(self):
        req = webob.Request.blank('/v1.1/fake/images/1/metadata/key1')
        req.method = 'PUT'
        req.body = '{"meta": {"key1": "zz"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(200, res.status_int)
        actual_output = json.loads(res.body)
        expected_output = {
            'meta': {
                'key1': 'zz',
            },
        }
        self.assertEqual(actual_output, expected_output)

    def test_update_item_bad_body(self):
        req = webob.Request.blank('/v1.1/fake/images/1/metadata/key1')
        req.method = 'PUT'
        req.body = '{"key1": "zz"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_too_many_keys(self):
        req = webob.Request.blank('/v1.1/fake/images/1/metadata/key1')
        req.method = 'PUT'
        req.body = '{"meta": {"key1": "value1", "key2": "value2"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_body_uri_mismatch(self):
        req = webob.Request.blank('/v1.1/fake/images/1/metadata/bad')
        req.method = 'PUT'
        req.body = '{"meta": {"key1": "value1"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_xml(self):
        req = webob.Request.blank('/v1.1/fake/images/1/metadata/key1')
        req.method = 'PUT'
        req.body = '<meta key="key1">five</meta>'
        req.headers["content-type"] = "application/xml"
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(200, res.status_int)
        actual_output = json.loads(res.body)
        expected_output = {
            'meta': {
                'key1': 'five',
            },
        }
        self.assertEqual(actual_output, expected_output)

    def test_delete(self):
        req = webob.Request.blank('/v1.1/fake/images/2/metadata/key1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(204, res.status_int)
        self.assertEqual('', res.body)

    def test_delete_not_found(self):
        req = webob.Request.blank('/v1.1/fake/images/2/metadata/blah')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_too_many_metadata_items_on_create(self):
        data = {"metadata": {}}
        for num in range(FLAGS.quota_metadata_items + 1):
            data['metadata']['key%i' % num] = "blah"
        json_string = str(data).replace("\'", "\"")
        req = webob.Request.blank('/v1.1/fake/images/2/metadata')
        req.method = 'POST'
        req.body = json_string
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(413, res.status_int)

    def test_too_many_metadata_items_on_put(self):
        req = webob.Request.blank('/v1.1/fake/images/3/metadata/blah')
        req.method = 'PUT'
        req.body = '{"meta": {"blah": "blah"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(413, res.status_int)
