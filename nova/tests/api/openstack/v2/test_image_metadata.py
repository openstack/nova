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

from nova.api.openstack.v2 import image_metadata
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS


class ImageMetaDataTest(test.TestCase):

    def setUp(self):
        super(ImageMetaDataTest, self).setUp()
        fakes.stub_out_glance(self.stubs)
        self.controller = image_metadata.Controller()

    def test_index(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata')
        res_dict = self.controller.index(req, '123')
        expected = {'metadata': {'key1': 'value1'}}
        self.assertEqual(res_dict, expected)

    def test_show(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        res_dict = self.controller.show(req, '123', 'key1')
        self.assertTrue('meta' in res_dict)
        self.assertEqual(len(res_dict['meta']), 1)
        self.assertEqual('value1', res_dict['meta']['key1'])

    def test_show_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key9')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, '123', 'key9')

    def test_show_image_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata/key1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, '100', 'key9')

    def test_create(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata')
        req.method = 'POST'
        body = {"metadata": {"key7": "value7"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, '123', body)

        expected_output = {'metadata': {'key1': 'value1', 'key7': 'value7'}}
        self.assertEqual(expected_output, res)

    def test_create_image_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata')
        req.method = 'POST'
        body = {"metadata": {"key7": "value7"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.create, req, '100', body)

    def test_update_all(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata')
        req.method = 'PUT'
        body = {"metadata": {"key9": "value9"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.update_all(req, '123', body)

        expected_output = {'metadata': {'key9': 'value9'}}
        self.assertEqual(expected_output, res)

    def test_update_all_image_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata')
        req.method = 'PUT'
        body = {"metadata": {"key9": "value9"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update_all, req, '100', body)

    def test_update_item(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "zz"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.update(req, '123', 'key1', body)

        expected_output = {'meta': {'key1': 'zz'}}
        self.assertEqual(res, expected_output)

    def test_update_item_image_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "zz"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update, req, '100', 'key1', body)

    def test_update_item_bad_body(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'PUT'
        body = {"key1": "zz"}
        req.body = ''
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, '123', 'key1', body)

    def test_update_item_too_many_keys(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'PUT'
        overload = {}
        for num in range(FLAGS.quota_metadata_items + 1):
            overload['key%s' % num] = 'value%s' % num
        body = {'meta': overload}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, '123', 'key1', body)

    def test_update_item_body_uri_mismatch(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/bad')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, '123', 'bad', body)

    def test_delete(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/key1')
        req.method = 'DELETE'
        res = self.controller.delete(req, '123', 'key1')

        self.assertEqual(None, res)

    def test_delete_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/blah')
        req.method = 'DELETE'

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, '123', 'blah')

    def test_delete_image_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/fake/images/100/metadata/key1')
        req.method = 'DELETE'

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, '100', 'key1')

    def test_too_many_metadata_items_on_create(self):
        data = {"metadata": {}}
        for num in range(FLAGS.quota_metadata_items + 1):
            data['metadata']['key%i' % num] = "blah"
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata')
        req.method = 'POST'
        req.body = json.dumps(data)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, '123', data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, '123', data)

    def test_too_many_metadata_items_on_put(self):
        FLAGS.quota_metadata_items = 1
        req = fakes.HTTPRequest.blank('/v2/fake/images/123/metadata/blah')
        req.method = 'PUT'
        body = {"meta": {"blah": "blah"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update, req, '123', 'blah', body)
