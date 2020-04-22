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
import testtools
import webob

from nova.api.openstack.compute import flavors_extraspecs \
        as flavorextraspecs_v21
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
        'hw:cpu_policy': 'shared',
        'hw:numa_nodes': '1',
    }
    return specs


class FlavorsExtraSpecsTestV21(test.TestCase):
    bad_request = exception.ValidationError
    flavorextraspecs = flavorextraspecs_v21

    def _get_request(self, url, use_admin_context=False, version=None):
        kwargs = {}
        if version:
            kwargs['version'] = version
        req_url = '/v2/%s/flavors/%s' % (fakes.FAKE_PROJECT_ID, url)
        return fakes.HTTPRequest.blank(
            req_url, use_admin_context=use_admin_context, **kwargs,
        )

    def setUp(self):
        super(FlavorsExtraSpecsTestV21, self).setUp()
        fakes.stub_out_key_pair_funcs(self)
        self.controller = self.flavorextraspecs.FlavorExtraSpecsController()

    def test_index(self):
        flavor = dict(test_flavor.fake_flavor,
                      extra_specs={'hw:numa_nodes': '1'})

        req = self._get_request('1/os-extra_specs')
        with mock.patch(
            'nova.objects.Flavor._flavor_get_by_flavor_id_from_db'
        ) as mock_get:
            mock_get.return_value = flavor
            res_dict = self.controller.index(req, 1)

        self.assertEqual('1', res_dict['extra_specs']['hw:numa_nodes'])

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
        flavor = objects.Flavor(
            flavorid='1', extra_specs={'hw:numa_nodes': '1'}
        )
        req = self._get_request('1/os-extra_specs/hw:numa_nodes')
        with mock.patch('nova.objects.Flavor.get_by_flavor_id') as mock_get:
            mock_get.return_value = flavor
            res_dict = self.controller.show(req, 1, 'hw:numa_nodes')

        self.assertEqual('1', res_dict['hw:numa_nodes'])

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    def test_show_spec_not_found(self, mock_get):
        mock_get.return_value = objects.Flavor(extra_specs={})

        req = self._get_request('1/os-extra_specs/hw:cpu_thread_policy')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 1, 'hw:cpu_thread_policy')

    def test_not_found_because_flavor(self):
        req = self._get_request('1/os-extra_specs/hw:numa_nodes',
                                use_admin_context=True)
        with mock.patch('nova.objects.Flavor.get_by_flavor_id') as mock_get:
            mock_get.side_effect = exception.FlavorNotFound(flavor_id='1')
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                              req, 1, 'hw:numa_nodes')
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                              req, 1, 'hw:numa_nodes',
                              body={'hw:numa_nodes': '1'})
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                              req, 1, 'hw:numa_nodes')

        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        with mock.patch('nova.objects.Flavor.get_by_flavor_id') as mock_get:
            mock_get.side_effect = exception.FlavorNotFound(flavor_id='1')
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                              req, 1, body={'extra_specs': {
                                  'hw:numa_nodes': '1'}})

    @mock.patch('nova.objects.Flavor._flavor_get_by_flavor_id_from_db')
    def test_delete(self, mock_get):
        flavor = dict(test_flavor.fake_flavor,
                      extra_specs={'hw:numa_nodes': '1'})
        req = self._get_request('1/os-extra_specs/hw:numa_nodes',
                                use_admin_context=True)
        mock_get.return_value = flavor
        with mock.patch('nova.objects.Flavor.save'):
            self.controller.delete(req, 1, 'hw:numa_nodes')

    def test_delete_spec_not_found(self):
        req = self._get_request('1/os-extra_specs/key6',
                                use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 1, 'key6')

    def test_create(self):
        body = {
            'extra_specs': {
                'hw:cpu_policy': 'shared',
                'hw:numa_nodes': '1',
            }
        }

        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        res_dict = self.controller.create(req, 1, body=body)

        self.assertEqual('shared', res_dict['extra_specs']['hw:cpu_policy'])
        self.assertEqual('1', res_dict['extra_specs']['hw:numa_nodes'])

    def test_create_flavor_not_found(self):
        body = {'extra_specs': {'hw:numa_nodes': '1'}}
        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        with mock.patch('nova.objects.Flavor.save',
                        side_effect=exception.FlavorNotFound(flavor_id='')):
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                              req, 1, body=body)

    def test_create_flavor_db_duplicate(self):
        body = {'extra_specs': {'hw:numa_nodes': '1'}}
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
        self._test_create_bad_request({"extra_specs": {"hw:numa_nodes": None}})

    def test_create_zero_length_key(self):
        self._test_create_bad_request({"extra_specs": {"": "value1"}})

    def test_create_long_key(self):
        key = "a" * 256
        self._test_create_bad_request({"extra_specs": {key: "value1"}})

    def test_create_long_value(self):
        value = "a" * 256
        self._test_create_bad_request(
            {"extra_specs": {"hw_numa_nodes": value}}
        )

    def test_create_really_long_integer_value(self):
        value = 10 ** 1000

        req = self._get_request('1/os-extra_specs', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, 1, body={"extra_specs": {"key1": value}})

    def test_create_invalid_specs(self):
        """Test generic invalid specs.

        These are invalid regardless of the validation scheme, if any, in use.
        """
        invalid_specs = {
            'key1/': 'value1',
            '<key>': 'value1',
            '$$akey$': 'value1',
            '!akey': 'value1',
            '': 'value1',
        }

        for key, value in invalid_specs.items():
            body = {"extra_specs": {key: value}}
            req = self._get_request('1/os-extra_specs', use_admin_context=True)
            self.assertRaises(self.bad_request, self.controller.create,
                              req, 1, body=body)

    def test_create_invalid_known_namespace(self):
        """Test behavior of validator with specs from known namespace."""
        invalid_specs = {
            'hw:numa_nodes': 'foo',
            'hw:cpu_policy': 'sharrred',
            'hw:cpu_policyyyyyyy': 'shared',
            'hw:foo': 'bar',
            'resources:VCPU': 'N',
            'resources_foo:VCPU': 'N',
            'resources:VVCPU': '1',
            'resources_foo:VVCPU': '1',
            'trait:STORAGE_DISK_SSD': 'forbiden',
            'trait_foo:HW_CPU_X86_AVX2': 'foo',
            'trait:bar': 'required',
            'trait_foo:bar': 'required',
            'trait:CUSTOM_foo': 'required',
            'trait:CUSTOM_FOO': 'bar',
            'trait_foo:CUSTOM_BAR': 'foo',
        }
        for key, value in invalid_specs.items():
            body = {'extra_specs': {key: value}}
            req = self._get_request(
                '1/os-extra_specs', use_admin_context=True, version='2.86',
            )
            with testtools.ExpectedException(
                self.bad_request, 'Validation failed; .*'
            ):
                self.controller.create(req, 1, body=body)

    def test_create_invalid_unknown_namespace(self):
        """Test behavior of validator with specs from unknown namespace."""
        unknown_specs = {
            'foo': 'bar',
            'foo:bar': 'baz',
            'hww:cpu_policy': 'sharrred',
        }
        for key, value in unknown_specs.items():
            body = {'extra_specs': {key: value}}
            req = self._get_request(
                '1/os-extra_specs', use_admin_context=True, version='2.86',
            )
            self.controller.create(req, 1, body=body)

    @mock.patch('nova.objects.flavor._flavor_extra_specs_add')
    def test_create_valid_specs(self, mock_flavor_extra_specs):
        valid_specs = {
            'hide_hypervisor_id': 'true',
            'hw:hide_hypervisor_id': 'true',
            'hw:numa_nodes': '1',
            'hw:numa_cpus.0': '0-3,8-9,11,10',
            'resources:VCPU': '4',
            'resources_foo:VCPU': '4',
            'resources:CUSTOM_FOO': '1',
            'resources_foo:CUSTOM_BAR': '2',
            'trait:STORAGE_DISK_SSD': 'forbidden',
            'trait_foo:HW_CPU_X86_AVX2': 'required',
            'trait:CUSTOM_FOO': 'forbidden',
            'trait_foo:CUSTOM_BAR': 'required',
        }
        mock_flavor_extra_specs.side_effect = return_create_flavor_extra_specs

        for key, value in valid_specs.items():
            body = {"extra_specs": {key: value}}
            req = self._get_request(
                '1/os-extra_specs', use_admin_context=True, version='2.86',
            )
            res_dict = self.controller.create(req, 1, body=body)
            self.assertEqual(value, res_dict['extra_specs'][key])

    @mock.patch('nova.objects.flavor._flavor_extra_specs_add')
    def test_update_item(self, mock_add):
        mock_add.side_effect = return_create_flavor_extra_specs
        body = {'hw:cpu_policy': 'shared'}

        req = self._get_request('1/os-extra_specs/hw:cpu_policy',
                                use_admin_context=True)
        res_dict = self.controller.update(req, 1, 'hw:cpu_policy', body=body)

        self.assertEqual('shared', res_dict['hw:cpu_policy'])

    def _test_update_item_bad_request(self, body):
        req = self._get_request('1/os-extra_specs/hw:cpu_policy',
                                use_admin_context=True)
        self.assertRaises(self.bad_request, self.controller.update,
                          req, 1, 'hw:cpu_policy', body=body)

    def test_update_item_empty_body(self):
        self._test_update_item_bad_request('')

    def test_update_item_too_many_keys(self):
        body = {"hw:cpu_policy": "dedicated", "hw:numa_nodes": "2"}
        self._test_update_item_bad_request(body)

    def test_update_item_non_dict_extra_specs(self):
        self._test_update_item_bad_request("non_dict")

    def test_update_item_non_string_key(self):
        self._test_update_item_bad_request({None: "value1"})

    def test_update_item_non_string_value(self):
        self._test_update_item_bad_request({"hw:cpu_policy": None})

    def test_update_item_zero_length_key(self):
        self._test_update_item_bad_request({"": "value1"})

    def test_update_item_long_key(self):
        key = "a" * 256
        self._test_update_item_bad_request({key: "value1"})

    def test_update_item_long_value(self):
        value = "a" * 256
        self._test_update_item_bad_request({"key1": value})

    def test_update_item_body_uri_mismatch(self):
        body = {'hw:cpu_policy': 'shared'}

        req = self._get_request('1/os-extra_specs/bad', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'bad', body=body)

    def test_update_flavor_not_found(self):
        body = {'hw:cpu_policy': 'shared'}

        req = self._get_request('1/os-extra_specs/hw:cpu_policy',
                                use_admin_context=True)
        with mock.patch('nova.objects.Flavor.save',
                        side_effect=exception.FlavorNotFound(flavor_id='')):
            self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                              req, 1, 'hw:cpu_policy', body=body)

    def test_update_flavor_db_duplicate(self):
        body = {'hw:cpu_policy': 'shared'}

        req = self._get_request('1/os-extra_specs/hw:cpu_policy',
                                use_admin_context=True)
        with mock.patch(
                'nova.objects.Flavor.save',
                side_effect=exception.FlavorExtraSpecUpdateCreateFailed(
                    id=1, retries=5)):
            self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                              req, 1, 'hw:cpu_policy', body=body)

    def test_update_really_long_integer_value(self):
        body = {'hw:numa_nodes': 10 ** 1000}

        req = self._get_request('1/os-extra_specs/hw:numa_nodes',
                                use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'hw:numa_nodes', body=body)

    def test_update_invalid_specs_known_namespace(self):
        """Test behavior of validator with specs from known namespace."""
        invalid_specs = {
            'hw:numa_nodes': 'foo',
            'hw:cpu_policy': 'sharrred',
            'hw:cpu_policyyyyyyy': 'shared',
            'hw:foo': 'bar',
        }
        for key, value in invalid_specs.items():
            body = {key: value}
            req = self._get_request(
                '1/os-extra_specs/{key}',
                use_admin_context=True, version='2.86',
            )
            with testtools.ExpectedException(
                self.bad_request, 'Validation failed; .*'
            ):
                self.controller.update(req, 1, key, body=body)

    def test_update_invalid_specs_unknown_namespace(self):
        """Test behavior of validator with specs from unknown namespace."""
        unknown_specs = {
            'foo': 'bar',
            'foo:bar': 'baz',
            'hww:cpu_policy': 'sharrred',
        }
        for key, value in unknown_specs.items():
            body = {key: value}
            req = self._get_request(
                f'1/os-extra_specs/{key}',
                use_admin_context=True, version='2.86',
            )
            self.controller.update(req, 1, key, body=body)

    @mock.patch('nova.objects.flavor._flavor_extra_specs_add')
    def test_update_valid_specs(self, mock_flavor_extra_specs):
        valid_specs = {
            'hide_hypervisor_id': 'true',
            'hw:numa_nodes': '1',
            'hw:numa_cpus.0': '0-3,8-9,11,10',
        }
        mock_flavor_extra_specs.side_effect = return_create_flavor_extra_specs

        for key, value in valid_specs.items():
            body = {key: value}
            req = self._get_request(
                f'1/os-extra_specs/{key}', use_admin_context=True,
                version='2.86',
            )
            res_dict = self.controller.update(req, 1, key, body=body)
            self.assertEqual(value, res_dict[key])
