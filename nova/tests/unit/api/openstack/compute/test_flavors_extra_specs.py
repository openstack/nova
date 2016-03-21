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

from nova.api.openstack.compute import flavors_extraspecs \
        as flavorextraspecs_v21
from nova.api.openstack.compute.legacy_v2.contrib import flavorextraspecs \
        as flavorextraspecs_v2
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.objects import test_flavor


def return_create_flavor_extra_specs(context, flavor_id, extra_specs,
                                     *args, **kwargs):
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


class FlavorsExtraSpecsTestV21(test.TestCase):
    bad_request = exception.ValidationError
    flavorextraspecs = flavorextraspecs_v21

    def _get_request(self, url, use_admin_context=False):
        req_url = '/v2/fake/flavors/' + url
        return fakes.HTTPRequest.blank(req_url,
                                       use_admin_context=use_admin_context)

    def setUp(self):
        super(FlavorsExtraSpecsTestV21, self).setUp()
        fakes.stub_out_key_pair_funcs(self.stubs)
        self.controller = self.flavorextraspecs.FlavorExtraSpecsController()

    def test_index(self):
        flavor = dict(test_flavor.fake_flavor,
                      extra_specs={'key1': 'value1'})

        req = self._get_request('1/os-extra_specs')
        with mock.patch('nova.objects.Flavor._flavor_get_by_flavor_id_from_db'
                ) as mock_get:
            mock_get.return_value = flavor
            res_dict = self.controller.index(req, 1)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    def test_index_no_data(self, mock_get):
        flavor = objects.Flavor(flavorid='1', extra_specs={})
        mock_get.return_value = flavor

        req = self._get_request('1/os-extra_specs')
        res_dict = self.controller.index(req, 1)

        self.assertEqual(0, len(res_dict['extra_specs']))

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    def test_index_flavor_not_found(self, mock_get):
        req = self._get_request('1/os-extra_specs',
                                use_admin_context=True)
        mock_get.side_effect = exception.FlavorNotFound(flavor_id='1')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.index,
                          req, 1)

    def test_show(self):
        flavor = objects.Flavor(flavorid='1', extra_specs={'key5': 'value5'})
        req = self._get_request('1/os-extra_specs/key5')
        with mock.patch('nova.objects.Flavor.get_by_flavor_id') as mock_get:
            mock_get.return_value = flavor
            res_dict = self.controller.show(req, 1, 'key5')

        self.assertEqual('value5', res_dict['key5'])

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    def test_show_spec_not_found(self, mock_get):
        mock_get.return_value = objects.Flavor(extra_specs={})

        req = self._get_request('1/os-extra_specs/key6')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 1, 'key6')

    def test_not_found_because_flavor(self):
        req = self._get_request('1/os-extra_specs/key5',
                                use_admin_context=True)
        with mock.patch('nova.objects.Flavor.get_by_flavor_id') as mock_get:
            mock_get.side_effect = exception.FlavorNotFound(flavor_id='1')
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                              req, 1, 'key5')
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                              req, 1, 'key5', body={'key5': 'value5'})
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                              req, 1, 'key5')

        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        with mock.patch('nova.objects.Flavor.get_by_flavor_id') as mock_get:
            mock_get.side_effect = exception.FlavorNotFound(flavor_id='1')
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                              req, 1, body={'extra_specs': {'key5': 'value5'}})

    @mock.patch('nova.objects.Flavor._flavor_get_by_flavor_id_from_db')
    def test_delete(self, mock_get):
        flavor = dict(test_flavor.fake_flavor,
                      extra_specs={'key5': 'value5'})
        req = self._get_request('1/os-extra_specs/key5',
                                use_admin_context=True)
        mock_get.return_value = flavor
        with mock.patch('nova.objects.Flavor.save'):
            self.controller.delete(req, 1, 'key5')

    def test_delete_no_admin(self):
        self.stub_out('nova.objects.flavor._flavor_extra_specs_del',
                      delete_flavor_extra_specs)

        req = self._get_request('1/os-extra_specs/key5')
        self.assertRaises(exception.Forbidden, self.controller.delete,
                          req, 1, 'key 5')

    def test_delete_spec_not_found(self):
        req = self._get_request('1/os-extra_specs/key6',
                                use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 1, 'key6')

    def test_create(self):
        body = {"extra_specs": {"key1": "value1", "key2": 0.5, "key3": 5}}

        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        res_dict = self.controller.create(req, 1, body=body)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])
        self.assertEqual(0.5, res_dict['extra_specs']['key2'])
        self.assertEqual(5, res_dict['extra_specs']['key3'])

    def test_create_no_admin(self):
        body = {"extra_specs": {"key1": "value1"}}

        req = self._get_request('1/os-extra_specs')
        self.assertRaises(exception.Forbidden, self.controller.create,
                          req, 1, body=body)

    def test_create_flavor_not_found(self):
        body = {"extra_specs": {"key1": "value1"}}
        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        with mock.patch('nova.objects.Flavor.save',
                        side_effect=exception.FlavorNotFound(flavor_id='')):
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                              req, 1, body=body)

    def test_create_flavor_db_duplicate(self):
        body = {"extra_specs": {"key1": "value1"}}
        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        with mock.patch(
                'nova.objects.Flavor.save',
                side_effect=exception.FlavorExtraSpecUpdateCreateFailed(
                    id='', retries=10)):
            self.assertRaises(webob.exc.HTTPConflict, self.controller.create,
                              req, 1, body=body)

    def _test_create_bad_request(self, body):
        self.stub_out('nova.objects.flavor._flavor_extra_specs_add',
                      return_create_flavor_extra_specs)

        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        self.assertRaises(self.bad_request, self.controller.create,
                          req, 1, body=body)

    def test_create_empty_body(self):
        self._test_create_bad_request('')

    def test_create_non_dict_extra_specs(self):
        self._test_create_bad_request({"extra_specs": "non_dict"})

    def test_create_non_string_key(self):
        self._test_create_bad_request({"extra_specs": {None: "value1"}})

    def test_create_non_string_value(self):
        self._test_create_bad_request({"extra_specs": {"key1": None}})

    def test_create_zero_length_key(self):
        self._test_create_bad_request({"extra_specs": {"": "value1"}})

    def test_create_long_key(self):
        key = "a" * 256
        self._test_create_bad_request({"extra_specs": {key: "value1"}})

    def test_create_long_value(self):
        value = "a" * 256
        self._test_create_bad_request({"extra_specs": {"key1": value}})

    def test_create_really_long_integer_value(self):
        value = 10 ** 1000

        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, 1, body={"extra_specs": {"key1": value}})

    def test_create_invalid_specs_key(self):
        invalid_keys = ("key1/", "<key>", "$$akey$", "!akey", "")

        for key in invalid_keys:
            body = {"extra_specs": {key: "value1"}}
            req = self._get_request('1/os-extra_specs', use_admin_context=True)
            self.assertRaises(self.bad_request, self.controller.create,
                              req, 1, body=body)

    @mock.patch('nova.objects.flavor._flavor_extra_specs_add')
    def test_create_valid_specs_key(self, mock_flavor_extra_specs):
        valid_keys = ("key1", "month.price", "I_am-a Key", "finance:g2")
        mock_flavor_extra_specs.side_effects = return_create_flavor_extra_specs

        for key in valid_keys:
            body = {"extra_specs": {key: "value1"}}
            req = self._get_request('1/os-extra_specs', use_admin_context=True)
            res_dict = self.controller.create(req, 1, body=body)
            self.assertEqual('value1', res_dict['extra_specs'][key])

    @mock.patch('nova.objects.flavor._flavor_extra_specs_add')
    def test_update_item(self, mock_add):
        mock_add.side_effect = return_create_flavor_extra_specs
        body = {"key1": "value1"}

        req = self._get_request('1/os-extra_specs/key1',
                                use_admin_context=True)
        res_dict = self.controller.update(req, 1, 'key1', body=body)

        self.assertEqual('value1', res_dict['key1'])

    def test_update_item_no_admin(self):
        body = {"key1": "value1"}

        req = self._get_request('1/os-extra_specs/key1')
        self.assertRaises(exception.Forbidden, self.controller.update,
                          req, 1, 'key1', body=body)

    def _test_update_item_bad_request(self, body):
        req = self._get_request('1/os-extra_specs/key1',
                                use_admin_context=True)
        self.assertRaises(self.bad_request, self.controller.update,
                          req, 1, 'key1', body=body)

    def test_update_item_empty_body(self):
        self._test_update_item_bad_request('')

    def test_update_item_too_many_keys(self):
        body = {"key1": "value1", "key2": "value2"}
        self._test_update_item_bad_request(body)

    def test_update_item_non_dict_extra_specs(self):
        self._test_update_item_bad_request("non_dict")

    def test_update_item_non_string_key(self):
        self._test_update_item_bad_request({None: "value1"})

    def test_update_item_non_string_value(self):
        self._test_update_item_bad_request({"key1": None})

    def test_update_item_zero_length_key(self):
        self._test_update_item_bad_request({"": "value1"})

    def test_update_item_long_key(self):
        key = "a" * 256
        self._test_update_item_bad_request({key: "value1"})

    def test_update_item_long_value(self):
        value = "a" * 256
        self._test_update_item_bad_request({"key1": value})

    def test_update_item_body_uri_mismatch(self):
        body = {"key1": "value1"}

        req = self._get_request('1/os-extra_specs/bad', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'bad', body=body)

    def test_update_flavor_not_found(self):
        body = {"key1": "value1"}

        req = self._get_request('1/os-extra_specs/key1',
                                use_admin_context=True)
        with mock.patch('nova.objects.Flavor.save',
                        side_effect=exception.FlavorNotFound(flavor_id='')):
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                              req, 1, 'key1', body=body)

    def test_update_flavor_db_duplicate(self):
        body = {"key1": "value1"}

        req = self._get_request('1/os-extra_specs/key1',
                                use_admin_context=True)
        with mock.patch(
                'nova.objects.Flavor.save',
                side_effect=exception.FlavorExtraSpecUpdateCreateFailed(
                    id=1, retries=5)):
            self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                              req, 1, 'key1', body=body)

    def test_update_really_long_integer_value(self):
        value = 10 ** 1000

        req = self._get_request('1/os-extra_specs/key1',
                                use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'key1', body={"key1": value})


class FlavorsExtraSpecsTestV2(FlavorsExtraSpecsTestV21):
    bad_request = webob.exc.HTTPBadRequest
    flavorextraspecs = flavorextraspecs_v2
