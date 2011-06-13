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


from nova import flags
from nova.api import openstack
from nova.tests.api.openstack import fakes
import nova.wsgi


FLAGS = flags.FLAGS


def return_create_instance_metadata_max(context, server_id, metadata):
    return stub_max_server_metadata()


def return_create_instance_metadata(context, server_id, metadata):
    return stub_server_metadata()


def return_server_metadata(context, server_id):
    return stub_server_metadata()


def return_empty_server_metadata(context, server_id):
    return {}


def delete_server_metadata(context, server_id, key):
    pass


def stub_server_metadata():
    metadata = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5"}
    return metadata


def stub_max_server_metadata():
    metadata = {"metadata": {}}
    for num in range(FLAGS.quota_metadata_items):
        metadata['metadata']['key%i' % num] = "blah"
    return metadata


class ServerMetaDataTest(unittest.TestCase):

    def setUp(self):
        super(ServerMetaDataTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_auth(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(ServerMetaDataTest, self).tearDown()

    def test_index(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual('value1', res_dict['metadata']['key1'])

    def test_index_no_data(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_empty_server_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual(0, len(res_dict['metadata']))

    def test_show(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta/key5')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual('value5', res_dict['key5'])

    def test_show_meta_not_found(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_empty_server_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta/key6')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(404, res.status_int)

    def test_delete(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_delete',
                       delete_server_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta/key5')
        req.environ['api.version'] = '1.1'
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)

    def test_create(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update_or_create',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta')
        req.environ['api.version'] = '1.1'
        req.method = 'POST'
        req.body = '{"metadata": {"key1": "value1"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual('value1', res_dict['metadata']['key1'])

    def test_create_empty_body(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update_or_create',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta')
        req.environ['api.version'] = '1.1'
        req.method = 'POST'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update_or_create',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta/key1')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.body = '{"key1": "value1"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        res_dict = json.loads(res.body)
        self.assertEqual('value1', res_dict['key1'])

    def test_update_item_empty_body(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update_or_create',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta/key1')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_too_many_keys(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update_or_create',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta/key1')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.body = '{"key1": "value1", "key2": "value2"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update_or_create',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/servers/1/meta/bad')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.body = '{"key1": "value1"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_too_many_metadata_items_on_create(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update_or_create',
                       return_create_instance_metadata)
        data = {"metadata": {}}
        for num in range(FLAGS.quota_metadata_items + 1):
            data['metadata']['key%i' % num] = "blah"
        json_string = str(data).replace("\'", "\"")
        req = webob.Request.blank('/v1.1/servers/1/meta')
        req.environ['api.version'] = '1.1'
        req.method = 'POST'
        req.body = json_string
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_to_many_metadata_items_on_update_item(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update_or_create',
                       return_create_instance_metadata_max)
        req = webob.Request.blank('/v1.1/servers/1/meta/key1')
        req.environ['api.version'] = '1.1'
        req.method = 'PUT'
        req.body = '{"a new key": "a new value"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)
