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

import mock
import webob

from nova.api.openstack.compute.plugins.v3 import flavors_extraspecs
import nova.db
from nova import exception
from nova.openstack.common.db import exception as db_exc
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
        self.controller = flavors_extraspecs.FlavorExtraSpecsController()

    def test_index(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_get',
                       return_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs')
        res_dict = self.controller.index(req, 1)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    def test_index_no_data(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_get',
                       return_empty_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs')
        res_dict = self.controller.index(req, 1)

        self.assertEqual(0, len(res_dict['extra_specs']))

    def test_show(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_get_item',
                       return_flavor_extra_specs_item)

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key5')
        res_dict = self.controller.show(req, 1, 'key5')

        self.assertEqual('value5', res_dict['key5'])

    def test_show_spec_not_found(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_get',
                       return_empty_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key6')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 1, 'key6')

    def test_delete(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_delete',
                       delete_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key5',
                                      use_admin_context=True)
        self.controller.delete(req, 1, 'key5')

    def test_delete_no_admin(self):
        self.stubs.Set(nova.db, 'flavor_extra_specs_delete',
                       delete_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key5')
        self.assertRaises(exception.NotAuthorized, self.controller.delete,
                          req, 1, 'key 5')

    def test_delete_spec_not_found(self):
        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key6',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 1, 'key6')

    def test_create(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"extra_specs": {"key1": "value1"}}

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs',
                                       use_admin_context=True)
        res_dict = self.controller.create(req, 1, body)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])
        self.assertEqual(self.controller.create.wsgi_code, 201)

    def test_create_no_admin(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"extra_specs": {"key1": "value1"}}

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs')
        self.assertRaises(exception.NotAuthorized, self.controller.create,
                          req, 1, body)

    def test_create_empty_body(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, 1, '')

    def test_create_flavor_not_found(self):
        def fake_instance_type_extra_specs_update_or_create(*args, **kwargs):
            raise exception.FlavorNotFound(flavor_id='')

        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       fake_instance_type_extra_specs_update_or_create)
        body = {"extra_specs": {"key1": "value1"}}
        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, 1, body)

    def test_create_flavor_db_duplicate(self):
        def fake_instance_type_extra_specs_update_or_create(*args, **kwargs):
            raise db_exc.DBDuplicateEntry()

        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       fake_instance_type_extra_specs_update_or_create)
        body = {"extra_specs": {"key1": "value1"}}
        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPConflict, self.controller.create,
                          req, 1, body)

    @mock.patch('nova.db.flavor_extra_specs_update_or_create')
    def test_create_invalid_specs_key(self, mock_flavor_extra_specs):
        invalid_keys = ("key1/", "<key>", "$$akey$", "!akey", "")
        mock_flavor_extra_specs.side_effects = return_create_flavor_extra_specs

        for key in invalid_keys:
            body = {"extra_specs": {key: "value1"}}

            req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs',
                                       use_admin_context=True)
            self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, 1, body)

    @mock.patch('nova.db.flavor_extra_specs_update_or_create')
    def test_create_valid_specs_key(self, mock_flavor_extra_specs):
        valid_keys = ("key1", "month.price", "I_am-a Key", "finance:g2")
        mock_flavor_extra_specs.side_effects = return_create_flavor_extra_specs

        for key in valid_keys:
            body = {"extra_specs": {key: "value1"}}

            req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs',
                                       use_admin_context=True)
            res_dict = self.controller.create(req, 1, body)
            self.assertEqual('value1', res_dict['extra_specs'][key])
            self.assertEqual(self.controller.create.wsgi_code, 201)

    def test_update_item(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key1',
                                      use_admin_context=True)
        res_dict = self.controller.update(req, 1, 'key1', body)

        self.assertEqual('value1', res_dict['key1'])

    def test_update_item_no_admin(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key1')
        self.assertRaises(exception.NotAuthorized, self.controller.update,
                          req, 1, 'key1', body)

    def test_update_item_empty_body(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key1',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'key1', '')

    def test_update_item_too_many_keys(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"key1": "value1", "key2": "value2"}

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key1',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'key1', body)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       return_create_flavor_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/bad',
                                     use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'bad', body)

    def test_update_flavor_not_found(self):
        def fake_instance_type_extra_specs_update_or_create(*args, **kwargs):
            raise exception.FlavorNotFound(flavor_id='')

        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       fake_instance_type_extra_specs_update_or_create)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key1',
                                     use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, 1, 'key1', body)

    def test_update_flavor_db_duplicate(self):
        def fake_instance_type_extra_specs_update_or_create(*args, **kwargs):
            raise db_exc.DBDuplicateEntry()

        self.stubs.Set(nova.db,
                       'flavor_extra_specs_update_or_create',
                       fake_instance_type_extra_specs_update_or_create)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank('/v3/flavors/1/extra-specs/key1',
                                     use_admin_context=True)
        self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                          req, 1, 'key1', body)
