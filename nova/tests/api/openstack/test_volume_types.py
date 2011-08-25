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
import webob

from nova import exception
from nova import context
from nova import test
from nova import log as logging
from nova.volume import volume_types
from nova.tests.api.openstack import fakes

LOG = logging.getLogger('nova.tests.api.openstack.test_volume_types')

last_param = {}


def stub_volume_type(id):
    specs = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5"}
    return dict(id=id, name='vol_type_%s' % str(id), extra_specs=specs)


def return_volume_types_get_all_types(context):
    return dict(vol_type_1=stub_volume_type(1),
                vol_type_2=stub_volume_type(2),
                vol_type_3=stub_volume_type(3))


def return_empty_volume_types_get_all_types(context):
    return {}


def return_volume_types_get_volume_type(context, id):
    if id == "777":
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    return stub_volume_type(int(id))


def return_volume_types_destroy(context, name):
    if name == "777":
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    pass


def return_volume_types_create(context, name, specs):
    pass


def return_volume_types_get_by_name(context, name):
    if name == "777":
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    return stub_volume_type(int(name.split("_")[2]))


class VolumeTypesApiTest(test.TestCase):
    def setUp(self):
        super(VolumeTypesApiTest, self).setUp()
        fakes.stub_out_key_pair_funcs(self.stubs)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VolumeTypesApiTest, self).tearDown()

    def test_volume_types_index(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_volume_types_get_all_types)
        req = webob.Request.blank('/v1.1/123/os-volume-types')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual('application/json', res.headers['Content-Type'])

        self.assertEqual(3, len(res_dict))
        for name in ['vol_type_1', 'vol_type_2', 'vol_type_3']:
            self.assertEqual(name, res_dict[name]['name'])
            self.assertEqual('value1', res_dict[name]['extra_specs']['key1'])

    def test_volume_types_index_no_data(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_empty_volume_types_get_all_types)
        req = webob.Request.blank('/v1.1/123/os-volume-types')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual(0, len(res_dict))

    def test_volume_types_show(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        req = webob.Request.blank('/v1.1/123/os-volume-types/1')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual(1, len(res_dict))
        self.assertEqual('vol_type_1', res_dict['volume_type']['name'])

    def test_volume_types_show_not_found(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        req = webob.Request.blank('/v1.1/123/os-volume-types/777')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_volume_types_delete(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        self.stubs.Set(volume_types, 'destroy',
                       return_volume_types_destroy)
        req = webob.Request.blank('/v1.1/123/os-volume-types/1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)

    def test_volume_types_delete_not_found(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        self.stubs.Set(volume_types, 'destroy',
                       return_volume_types_destroy)
        req = webob.Request.blank('/v1.1/123/os-volume-types/777')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_create(self):
        self.stubs.Set(volume_types, 'create',
                       return_volume_types_create)
        self.stubs.Set(volume_types, 'get_volume_type_by_name',
                       return_volume_types_get_by_name)
        req = webob.Request.blank('/v1.1/123/os-volume-types')
        req.method = 'POST'
        req.body = '{"volume_type": {"name": "vol_type_1", '\
                                    '"extra_specs": {"key1": "value1"}}}'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual(1, len(res_dict))
        self.assertEqual('vol_type_1', res_dict['volume_type']['name'])

    def test_create_empty_body(self):
        self.stubs.Set(volume_types, 'create',
                       return_volume_types_create)
        self.stubs.Set(volume_types, 'get_volume_type_by_name',
                       return_volume_types_get_by_name)
        req = webob.Request.blank('/v1.1/123/os-volume-types')
        req.method = 'POST'
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, res.status_int)
