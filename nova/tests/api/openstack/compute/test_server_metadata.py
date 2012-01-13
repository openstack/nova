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

from nova.api.openstack.compute import server_metadata
import nova.db
from nova import exception
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


FLAGS = flags.FLAGS


def return_create_instance_metadata_max(context, server_id, metadata, delete):
    return stub_max_server_metadata()


def return_create_instance_metadata(context, server_id, metadata, delete):
    return stub_server_metadata()


def return_server_metadata(context, server_id):
    if not isinstance(server_id, int):
        msg = 'id %s must be int in return server metadata' % server_id
        raise Exception(msg)
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
    }
    return metadata


def stub_max_server_metadata():
    metadata = {"metadata": {}}
    for num in range(FLAGS.quota_metadata_items):
        metadata['metadata']['key%i' % num] = "blah"
    return metadata


def return_server(context, server_id):
    return {'id': server_id, 'name': 'fake'}


def return_server_by_uuid(context, server_uuid):
    return {'id': 1, 'name': 'fake'}


def return_server_nonexistant(context, server_id):
    raise exception.InstanceNotFound()


class ServerMetaDataTest(test.TestCase):

    def setUp(self):
        super(ServerMetaDataTest, self).setUp()
        fakes.stub_out_key_pair_funcs(self.stubs)
        self.stubs.Set(nova.db, 'instance_get', return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_by_uuid)

        self.stubs.Set(nova.db, 'instance_metadata_get',
                       return_server_metadata)

        self.controller = server_metadata.Controller()
        self.uuid = str(utils.gen_uuid())
        self.url = '/v1.1/fake/servers/%s/metadata' % self.uuid

    def test_index(self):
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, self.uuid)

        expected = {
            'metadata': {
                'key1': 'value1',
                'key2': 'value2',
                'key3': 'value3',
            },
        }
        self.assertEqual(expected, res_dict)

    def test_index_nonexistant_server(self):
        self.stubs.Set(nova.db, 'instance_metadata_get',
                       return_server_nonexistant)
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.index, req, self.url)

    def test_index_no_data(self):
        self.stubs.Set(nova.db, 'instance_metadata_get',
                       return_empty_server_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, self.uuid)
        expected = {'metadata': {}}
        self.assertEqual(expected, res_dict)

    def test_show(self):
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        res_dict = self.controller.show(req, self.uuid, 'key2')
        expected = {'meta': {'key2': 'value2'}}
        self.assertEqual(expected, res_dict)

    def test_show_nonexistant_server(self):
        self.stubs.Set(nova.db, 'instance_metadata_get',
                       return_server_nonexistant)
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, self.uuid, 'key2')

    def test_show_meta_not_found(self):
        self.stubs.Set(nova.db, 'instance_metadata_get',
                       return_empty_server_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key6')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, self.uuid, 'key6')

    def test_delete(self):
        self.stubs.Set(nova.db, 'instance_metadata_get',
                       return_server_metadata)
        self.stubs.Set(nova.db, 'instance_metadata_delete',
                       delete_server_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.method = 'DELETE'
        res = self.controller.delete(req, self.uuid, 'key2')

        self.assertEqual(None, res)

    def test_delete_nonexistant_server(self):
        self.stubs.Set(nova.db, 'instance_get', return_server_nonexistant)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, self.uuid, 'key1')

    def test_delete_meta_not_found(self):
        self.stubs.Set(nova.db, 'instance_metadata_get',
                       return_empty_server_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key6')
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, self.uuid, 'key6')

    def test_create(self):
        self.stubs.Set(nova.db, 'instance_metadata_get',
                       return_server_metadata)
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key9": "value9"}}
        req.body = json.dumps(body)
        res_dict = self.controller.create(req, self.uuid, body)

        body['metadata'].update({
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
        })
        self.assertEqual(body, res_dict)

    def test_create_empty_body(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, self.uuid, None)

    def test_create_nonexistant_server(self):
        self.stubs.Set(nova.db, 'instance_get', return_server_nonexistant)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        body = {"metadata": {"key1": "value1"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.create, req, self.uuid, body)

    def test_update_all(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {
            'metadata': {
                'key10': 'value10',
                'key99': 'value99',
            },
        }
        req.body = json.dumps(expected)
        res_dict = self.controller.update_all(req, self.uuid, expected)

        self.assertEqual(expected, res_dict)

    def test_update_all_empty_container(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': {}}
        req.body = json.dumps(expected)
        res_dict = self.controller.update_all(req, self.uuid, expected)

        self.assertEqual(expected, res_dict)

    def test_update_all_malformed_container(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'meta': {}}
        req.body = json.dumps(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, self.uuid, expected)

    def test_update_all_malformed_data(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': ['asdf']}
        req.body = json.dumps(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, self.uuid, expected)

    def test_update_all_nonexistant_server(self):
        self.stubs.Set(nova.db, 'instance_get', return_server_nonexistant)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        body = {'metadata': {'key10': 'value10'}}
        req.body = json.dumps(body)

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update_all, req, '100', body)

    def test_update_item(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res_dict = self.controller.update(req, self.uuid, 'key1', body)
        expected = {'meta': {'key1': 'value1'}}
        self.assertEqual(expected, res_dict)

    def test_update_item_nonexistant_server(self):
        self.stubs.Set(nova.db, 'instance_get', return_server_nonexistant)
        req = fakes.HTTPRequest.blank('/v1.1/fake/servers/asdf/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update, req, self.uuid, 'key1', body)

    def test_update_item_empty_body(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.uuid, 'key1', None)

    def test_update_item_too_many_keys(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1", "key2": "value2"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.uuid, 'key1', body)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/bad')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.uuid, 'bad', body)

    def test_too_many_metadata_items_on_create(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        data = {"metadata": {}}
        for num in range(FLAGS.quota_metadata_items + 1):
            data['metadata']['key%i' % num] = "blah"
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.body = json.dumps(data)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, self.uuid, data)

    def test_too_many_metadata_items_on_update_item(self):
        self.stubs.Set(nova.db, 'instance_metadata_update',
                       return_create_instance_metadata)
        data = {"metadata": {}}
        for num in range(FLAGS.quota_metadata_items + 1):
            data['metadata']['key%i' % num] = "blah"
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.body = json.dumps(data)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update_all, req, self.uuid, data)
