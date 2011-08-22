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
from xml.dom import minidom

from nova import exception
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
import nova.wsgi


FLAGS = flags.FLAGS


def return_create_instance_metadata_max(context, server_id, metadata, delete):
    return stub_max_server_metadata()


def return_create_instance_metadata(context, server_id, metadata, delete):
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
    }
    return metadata


def stub_max_server_metadata():
    metadata = {"metadata": {}}
    for num in range(FLAGS.quota_metadata_items):
        metadata['metadata']['key%i' % num] = "blah"
    return metadata


def return_server(context, server_id):
    return {'id': server_id}


def return_server_nonexistant(context, server_id):
    raise exception.InstanceNotFound()


class ServerMetaDataTest(test.TestCase):

    def setUp(self):
        super(ServerMetaDataTest, self).setUp()
        fakes.stub_out_key_pair_funcs(self.stubs)
        self.stubs.Set(nova.db.api, 'instance_get', return_server)

    def test_index(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual('application/json', res.headers['Content-Type'])
        expected = {
            'metadata': {
                'key1': 'value1',
                'key2': 'value2',
                'key3': 'value3',
            },
        }
        self.assertEqual(expected, res_dict)

    def test_index_xml(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        request = webob.Request.blank("/v1.1/fake/servers/1/metadata")
        request.accept = "application/xml"
        response = request.get_response(fakes.wsgi_app())
        self.assertEqual(200, response.status_int)
        self.assertEqual("application/xml", response.content_type)

        actual_metadata = minidom.parseString(response.body.replace("  ", ""))

        expected_metadata = minidom.parseString("""
            <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
                <meta key="key3">value3</meta>
                <meta key="key2">value2</meta>
                <meta key="key1">value1</meta>
            </metadata>
        """.replace("  ", "").replace("\n", ""))

        self.assertEqual(expected_metadata.toxml(), actual_metadata.toxml())

    def test_index_nonexistant_server(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_nonexistant)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_index_no_data(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_empty_server_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        expected = {'metadata': {}}
        self.assertEqual(expected, res_dict)

    def test_show(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key2')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        expected = {'meta': {'key2': 'value2'}}
        self.assertEqual(expected, res_dict)

    def test_show_xml(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        request = webob.Request.blank("/v1.1/fake/servers/1/metadata/key2")
        request.accept = "application/xml"
        response = request.get_response(fakes.wsgi_app())
        self.assertEqual(200, response.status_int)
        self.assertEqual("application/xml", response.content_type)

        actual_metadata = minidom.parseString(response.body.replace("  ", ""))

        expected_metadata = minidom.parseString("""
            <meta xmlns="http://docs.openstack.org/compute/api/v1.1"
                 key="key2">value2</meta>
        """.replace("  ", "").replace("\n", ""))

        self.assertEqual(expected_metadata.toxml(), actual_metadata.toxml())

    def test_show_nonexistant_server(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_nonexistant)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key2')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_show_meta_not_found(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_empty_server_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key6')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_delete(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        self.stubs.Set(nova.db.api, 'instance_metadata_delete',
                       delete_server_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key2')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(204, res.status_int)
        self.assertEqual('', res.body)

    def test_delete_nonexistant_server(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_nonexistant)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_delete_meta_not_found(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_empty_server_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key6')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_create(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        req.method = 'POST'
        req.content_type = "application/json"
        input = {"metadata": {"key9": "value9"}}
        req.body = json.dumps(input)
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        input['metadata'].update({
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
        })
        self.assertEqual(input, res_dict)

    def test_create_xml(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_get',
                       return_server_metadata)
        self.stubs.Set(nova.db.api, "instance_metadata_update",
                       return_create_instance_metadata)
        req = webob.Request.blank("/v1.1/fake/servers/1/metadata")
        req.method = "POST"
        req.content_type = "application/xml"
        req.accept = "application/xml"

        request_metadata = minidom.parseString("""
            <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
                <meta key="key5">value5</meta>
            </metadata>
        """.replace("  ", "").replace("\n", ""))

        req.body = str(request_metadata.toxml())
        response = req.get_response(fakes.wsgi_app())

        expected_metadata = minidom.parseString("""
            <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
                <meta key="key3">value3</meta>
                <meta key="key2">value2</meta>
                <meta key="key1">value1</meta>
                <meta key="key5">value5</meta>
            </metadata>
        """.replace("  ", "").replace("\n", ""))

        self.assertEqual(200, response.status_int)
        actual_metadata = minidom.parseString(response.body)

        self.assertEqual(expected_metadata.toxml(), actual_metadata.toxml())

    def test_create_empty_body(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        req.method = 'POST'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_create_nonexistant_server(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_nonexistant)
        req = webob.Request.blank('/v1.1/fake/servers/100/metadata')
        req.method = 'POST'
        req.body = '{"metadata": {"key1": "value1"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_update_all(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {
            'metadata': {
                'key10': 'value10',
                'key99': 'value99',
            },
        }
        req.body = json.dumps(expected)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual(expected, res_dict)

    def test_update_all_empty_container(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': {}}
        req.body = json.dumps(expected)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual(expected, res_dict)

    def test_update_all_malformed_container(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'meta': {}}
        req.body = json.dumps(expected)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_all_malformed_data(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': ['asdf']}
        req.body = json.dumps(expected)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_all_nonexistant_server(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_nonexistant)
        req = webob.Request.blank('/v1.1/fake/servers/100/metadata')
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = json.dumps({'metadata': {'key10': 'value10'}})
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_update_item(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key1')
        req.method = 'PUT'
        req.body = '{"meta": {"key1": "value1"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        res_dict = json.loads(res.body)
        expected = {'meta': {'key1': 'value1'}}
        self.assertEqual(expected, res_dict)

    def test_update_item_xml(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key9')
        req.method = 'PUT'
        req.accept = "application/json"
        req.content_type = "application/xml"
        req.body = """
            <meta xmlns="http://docs.openstack.org/compute/api/v1.1"
                  key="key9">value9</meta>
        """
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        res_dict = json.loads(res.body)
        expected = {'meta': {'key9': 'value9'}}
        self.assertEqual(expected, res_dict)

    def test_update_item_nonexistant_server(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_nonexistant)
        req = webob.Request.blank('/v1.1/fake/servers/asdf/metadata/key1')
        req.method = 'PUT'
        req.body = '{"meta":{"key1": "value1"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_update_item_empty_body(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key1')
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_too_many_keys(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key1')
        req.method = 'PUT'
        req.body = '{"meta": {"key1": "value1", "key2": "value2"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/bad')
        req.method = 'PUT'
        req.body = '{"meta": {"key1": "value1"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_too_many_metadata_items_on_create(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata)
        data = {"metadata": {}}
        for num in range(FLAGS.quota_metadata_items + 1):
            data['metadata']['key%i' % num] = "blah"
        json_string = str(data).replace("\'", "\"")
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata')
        req.method = 'POST'
        req.body = json_string
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(413, res.status_int)

    def test_too_many_metadata_items_on_update_item(self):
        self.stubs.Set(nova.db.api, 'instance_metadata_update',
                       return_create_instance_metadata_max)
        req = webob.Request.blank('/v1.1/fake/servers/1/metadata/key1')
        req.method = 'PUT'
        req.body = '{"meta": {"a new key": "a new value"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)
