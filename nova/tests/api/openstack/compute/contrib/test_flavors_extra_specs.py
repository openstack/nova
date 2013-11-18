# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import webob

from nova.api.openstack.compute.contrib import flavorextraspecs
import nova.db
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes


def return_create_flavor_extra_specs(context, flavor_id, extra_specs):
    return stub_flavor_extra_specs()


def return_flavor_extra_specs(context, flavor_id):
    return stub_flavor_extra_specs()


def return_flavor_extra_specs_item(context, flavor_id, key):
    return {key: stub_flavor_extra_specs()[key]}


def return_empty_flavor_extra_specs(context, flavor_id):
    return {}


def delete_flavor_extra_specs(context, flavor_id, key):
    pass


def stub_flavor_extra_specs():
    specs = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5"}
    return specs


class FlavorsExtraSpecsTest(test.TestCase):

    def setUp(self):
        super(FlavorsExtraSpecsTest, self).setUp()
        fakes.stub_out_key_pair_funcs(self.stubs)
        self.controller = flavorextraspecs.FlavorExtraSpecsController()

    def test_index(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_get',
                       return_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs')
        res_dict = self.controller.index(req, 1)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    def test_index_no_data(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_get',
                       return_empty_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs')
        res_dict = self.controller.index(req, 1)

        self.assertEqual(0, len(res_dict['extra_specs']))

    def test_show(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_get_item',
                       return_flavor_extra_specs_item)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key5')
        res_dict = self.controller.show(req, 1, 'key5')

        self.assertEqual('value5', res_dict['key5'])

    def test_show_spec_not_found(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_get',
                       return_empty_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key6')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 1, 'key6')

    def test_delete(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_delete',
                       delete_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key5', use_admin_context=True)
        self.controller.delete(req, 1, 'key5')

    def test_delete_no_admin(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_delete',
                       delete_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key5')
        self.assertRaises(exception.NotAuthorized, self.controller.delete,
                          req, 1, 'key 5')

    def test_delete_spec_not_found(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key6', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 1, 'key6')

    def test_create(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"extra_specs": {"key1": "value1"}}

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs',
                                       use_admin_context=True)
        res_dict = self.controller.create(req, 1, body)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    def test_create_no_admin(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"extra_specs": {"key1": "value1"}}

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs')
        self.assertRaises(exception.NotAuthorized, self.controller.create,
                          req, 1, body)

    def test_create_empty_body(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, 1, '')

    def test_update_item(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key1', use_admin_context=True)
        res_dict = self.controller.update(req, 1, 'key1', body)

        self.assertEqual('value1', res_dict['key1'])

    def test_update_item_no_admin(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key1')
        self.assertRaises(exception.NotAuthorized, self.controller.update,
                          req, 1, 'key1', body)

    def test_update_item_empty_body(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key1', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'key1', '')

    def test_update_item_too_many_keys(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"key1": "value1", "key2": "value2"}

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs' +
                                      '/key1', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'key1', body)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1/os-extra_specs/bad',
                                     use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'bad', body)


class FlavorsExtraSpecsXMLSerializerTest(test.TestCase):
    def test_serializer(self):
        serializer = flavorextraspecs.ExtraSpecsTemplate()
        expected = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                    '<extra_specs><key1>value1</key1></extra_specs>')
        text = serializer.serialize(dict(extra_specs={"key1": "value1"}))
        self.assertEqual(text, expected)

    def test_show_update_serializer(self):
        serializer = flavorextraspecs.ExtraSpecTemplate()
        expected = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                    '<extra_spec key="key1">value1</extra_spec>')
        text = serializer.serialize(dict({"key1": "value1"}))
        self.assertEqual(text, expected)

    def test_serializer_with_colon_tagname(self):
        # Our test object to serialize
        obj = {'extra_specs': {'foo:bar': '999'}}
        serializer = flavorextraspecs.ExtraSpecsTemplate()
        expected_xml = (("<?xml version='1.0' encoding='UTF-8'?>\n"
                    '<extra_specs><foo:bar xmlns:foo="foo">999</foo:bar>'
                    '</extra_specs>'))
        result = serializer.serialize(obj)
        self.assertEqual(expected_xml, result)
