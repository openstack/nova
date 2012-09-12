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

from lxml import etree
import webob

from nova.api.openstack.volume.contrib import types_extra_specs
from nova import test
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


def volume_type_get(context, volume_type_id):
    pass


class VolumeTypesExtraSpecsTest(test.TestCase):

    def setUp(self):
        super(VolumeTypesExtraSpecsTest, self).setUp()
        self.stubs.Set(nova.db, 'volume_type_get', volume_type_get)
        self.api_path = '/v1/fake/os-volume-types/1/extra_specs'
        self.controller = types_extra_specs.VolumeTypeExtraSpecsController()

    def test_index(self):
        self.stubs.Set(nova.db, 'volume_type_extra_specs_get',
                       return_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path)
        res_dict = self.controller.index(req, 1)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    def test_index_no_data(self):
        self.stubs.Set(nova.db, 'volume_type_extra_specs_get',
                       return_empty_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path)
        res_dict = self.controller.index(req, 1)

        self.assertEqual(0, len(res_dict['extra_specs']))

    def test_show(self):
        self.stubs.Set(nova.db, 'volume_type_extra_specs_get',
                       return_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path + '/key5')
        res_dict = self.controller.show(req, 1, 'key5')

        self.assertEqual('value5', res_dict['key5'])

    def test_show_spec_not_found(self):
        self.stubs.Set(nova.db, 'volume_type_extra_specs_get',
                       return_empty_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path + '/key6')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 1, 'key6')

    def test_delete(self):
        self.stubs.Set(nova.db, 'volume_type_extra_specs_delete',
                       delete_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path + '/key5')
        self.controller.delete(req, 1, 'key5')

    def test_create(self):
        self.stubs.Set(nova.db,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        body = {"extra_specs": {"key1": "value1"}}

        req = fakes.HTTPRequest.blank(self.api_path)
        res_dict = self.controller.create(req, 1, body)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    def test_update_item(self):
        self.stubs.Set(nova.db,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank(self.api_path + '/key1')
        res_dict = self.controller.update(req, 1, 'key1', body)

        self.assertEqual('value1', res_dict['key1'])

    def test_update_item_too_many_keys(self):
        self.stubs.Set(nova.db,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        body = {"key1": "value1", "key2": "value2"}

        req = fakes.HTTPRequest.blank(self.api_path + '/key1')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'key1', body)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(nova.db,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank(self.api_path + '/bad')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'bad', body)


class VolumeTypeExtraSpecsSerializerTest(test.TestCase):
    def test_index_create_serializer(self):
        serializer = types_extra_specs.VolumeTypeExtraSpecsTemplate()

        # Just getting some input data
        extra_specs = stub_volume_type_extra_specs()
        text = serializer.serialize(dict(extra_specs=extra_specs))

        print text
        tree = etree.fromstring(text)

        self.assertEqual('extra_specs', tree.tag)
        self.assertEqual(len(extra_specs), len(tree))
        seen = set(extra_specs.keys())
        for child in tree:
            self.assertTrue(child.tag in seen)
            self.assertEqual(extra_specs[child.tag], child.text)
            seen.remove(child.tag)
        self.assertEqual(len(seen), 0)

    def test_update_show_serializer(self):
        serializer = types_extra_specs.VolumeTypeExtraSpecTemplate()

        exemplar = dict(key1='value1')
        text = serializer.serialize(exemplar)

        print text
        tree = etree.fromstring(text)

        self.assertEqual('key1', tree.tag)
        self.assertEqual('value1', tree.text)
        self.assertEqual(0, len(tree))


class VolumeTypeExtraSpecsUnprocessableEntityTestCase(test.TestCase):

    """
    Tests of places we throw 422 Unprocessable Entity from
    """

    def setUp(self):
        super(VolumeTypeExtraSpecsUnprocessableEntityTestCase, self).setUp()
        self.controller = types_extra_specs.VolumeTypeExtraSpecsController()

    def _unprocessable_extra_specs_create(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/types/1/extra_specs')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, '1', body)

    def test_create_no_body(self):
        self._unprocessable_extra_specs_create(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._unprocessable_extra_specs_create(body=body)

    def test_create_malformed_entity(self):
        body = {'extra_specs': 'string'}
        self._unprocessable_extra_specs_create(body=body)

    def _unprocessable_extra_specs_update(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/types/1/extra_specs')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.update, req, '1', body)

    def test_update_no_body(self):
        self._unprocessable_extra_specs_update(body=None)

    def test_update_empty_body(self):
        self._unprocessable_extra_specs_update(body={})
