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

import webob

from nova.api.openstack.volume.contrib import types_manage
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes
from nova.volume import volume_types


def stub_volume_type(id):
    specs = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5"}
    return dict(id=id, name='vol_type_%s' % str(id), extra_specs=specs)


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


class VolumeTypesManageApiTest(test.TestCase):
    def setUp(self):
        super(VolumeTypesManageApiTest, self).setUp()
        self.controller = types_manage.VolumeTypesManageController()

    def test_volume_types_delete(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        self.stubs.Set(volume_types, 'destroy',
                       return_volume_types_destroy)

        req = fakes.HTTPRequest.blank('/v1/fake/types/1')
        self.controller._delete(req, 1)

    def test_volume_types_delete_not_found(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        self.stubs.Set(volume_types, 'destroy',
                       return_volume_types_destroy)

        req = fakes.HTTPRequest.blank('/v1/fake/types/777')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller._delete,
                          req, '777')

    def test_create(self):
        self.stubs.Set(volume_types, 'create',
                       return_volume_types_create)
        self.stubs.Set(volume_types, 'get_volume_type_by_name',
                       return_volume_types_get_by_name)

        body = {"volume_type": {"name": "vol_type_1",
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v1/fake/types')
        res_dict = self.controller._create(req, body)

        self.assertEqual(1, len(res_dict))
        self.assertEqual('vol_type_1', res_dict['volume_type']['name'])


class VolumeTypesUnprocessableEntityTestCase(test.TestCase):

    """
    Tests of places we throw 422 Unprocessable Entity from
    """

    def setUp(self):
        super(VolumeTypesUnprocessableEntityTestCase, self).setUp()
        self.controller = types_manage.VolumeTypesManageController()

    def _unprocessable_volume_type_create(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/types')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller._create, req, body)

    def test_create_no_body(self):
        self._unprocessable_volume_type_create(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._unprocessable_volume_type_create(body=body)

    def test_create_malformed_entity(self):
        body = {'volume_type': 'string'}
        self._unprocessable_volume_type_create(body=body)
