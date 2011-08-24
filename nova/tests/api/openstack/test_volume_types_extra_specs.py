# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
# Copyright 2011 University of Southern California
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
import webob
import os.path


from nova import test
from nova.api import openstack
from nova.api.openstack import extensions
from nova.tests.api.openstack import fakes
import nova.wsgi


def return_create_volume_type_extra_specs(context, volume_type_id,
                                          extra_specs):
    return stub_volume_type_extra_specs()


def return_volume_type_extra_specs(context, volume_type_id):
    return stub_volume_type_extra_specs()


def return_empty_volume_type_extra_specs(context, volume_type_id):
    return {}


def delete_volume_type_extra_specs(context, volume_type_id, key):
    pass


def stub_volume_type_extra_specs():
    specs = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5"}
    return specs


class VolumeTypesExtraSpecsTest(test.TestCase):

    def setUp(self):
        super(VolumeTypesExtraSpecsTest, self).setUp()
        fakes.stub_out_key_pair_funcs(self.stubs)
        self.api_path = '/v1.1/123/os-volume-types/1/extra_specs'

    def test_index(self):
        self.stubs.Set(nova.db.api, 'volume_type_extra_specs_get',
                       return_volume_type_extra_specs)
        request = webob.Request.blank(self.api_path)
        res = request.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    def test_index_no_data(self):
        self.stubs.Set(nova.db.api, 'volume_type_extra_specs_get',
                       return_empty_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual(0, len(res_dict['extra_specs']))

    def test_show(self):
        self.stubs.Set(nova.db.api, 'volume_type_extra_specs_get',
                       return_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path + '/key5')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual('value5', res_dict['key5'])

    def test_show_spec_not_found(self):
        self.stubs.Set(nova.db.api, 'volume_type_extra_specs_get',
                       return_empty_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path + '/key6')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(404, res.status_int)

    def test_delete(self):
        self.stubs.Set(nova.db.api, 'volume_type_extra_specs_delete',
                       delete_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path + '/key5')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)

    def test_create(self):
        self.stubs.Set(nova.db.api,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path)
        req.method = 'POST'
        req.body = '{"extra_specs": {"key1": "value1"}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    def test_create_empty_body(self):
        self.stubs.Set(nova.db.api,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item(self):
        self.stubs.Set(nova.db.api,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path + '/key1')
        req.method = 'PUT'
        req.body = '{"key1": "value1"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        res_dict = json.loads(res.body)
        self.assertEqual('value1', res_dict['key1'])

    def test_update_item_empty_body(self):
        self.stubs.Set(nova.db.api,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path + '/key1')
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_too_many_keys(self):
        self.stubs.Set(nova.db.api,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path + '/key1')
        req.method = 'PUT'
        req.body = '{"key1": "value1", "key2": "value2"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(nova.db.api,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        req = webob.Request.blank(self.api_path + '/bad')
        req.method = 'PUT'
        req.body = '{"key1": "value1"}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)
