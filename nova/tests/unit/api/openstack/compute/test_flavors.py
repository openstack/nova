# Copyright 2012 OpenStack Foundation
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
import six.moves.urllib.parse as urlparse
import webob

from nova.api.openstack import common
from nova.api.openstack.compute import flavors as flavors_v21
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import matchers

NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


def fake_get_limit_and_marker(request, max_limit=1):
    params = common.get_pagination_params(request)
    limit = params.get('limit', max_limit)
    limit = min(max_limit, limit)
    marker = params.get('marker')

    return limit, marker


def return_flavor_not_found(context, flavor_id, read_deleted=None):
    raise exception.FlavorNotFound(flavor_id=flavor_id)


class FlavorsTestV21(test.TestCase):
    _prefix = "/v2/fake"
    Controller = flavors_v21.FlavorsController
    fake_request = fakes.HTTPRequestV21
    _rspv = "v2/fake"
    _fake = "/fake"
    microversion = '2.1'
    # Flag to tell the test if a description should be expected in a response.
    expect_description = False
    # Flag to tell the test if a extra_specs should be expected in a response.
    expect_extra_specs = False

    def setUp(self):
        super(FlavorsTestV21, self).setUp()
        fakes.stub_out_networking(self)
        fakes.stub_out_flavor_get_all(self)
        fakes.stub_out_flavor_get_by_flavor_id(self)
        self.controller = self.Controller()

    def _build_request(self, url):
        return self.fake_request.blank(
            self._prefix + url, version=self.microversion)

    def _set_expected_body(self, expected, flavor):
        # NOTE(oomichi): On v2.1 API, some extensions of v2.0 are merged
        # as core features and we can get the following parameters as the
        # default.
        expected['OS-FLV-EXT-DATA:ephemeral'] = flavor.ephemeral_gb
        expected['OS-FLV-DISABLED:disabled'] = flavor.disabled
        expected['swap'] = flavor.swap
        if self.expect_description:
            expected['description'] = flavor.description
        if self.expect_extra_specs:
            expected['extra_specs'] = flavor.extra_specs

    @mock.patch('nova.objects.Flavor.get_by_flavor_id',
                side_effect=return_flavor_not_found)
    def test_get_flavor_by_invalid_id(self, mock_get):
        req = self._build_request('/flavors/asdf')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'asdf')

    def test_get_flavor_by_id(self):
        req = self._build_request('/flavors/1')
        flavor = self.controller.show(req, '1')
        expected = {
            "flavor": {
                "id": fakes.FLAVORS['1'].flavorid,
                "name": fakes.FLAVORS['1'].name,
                "ram": fakes.FLAVORS['1'].memory_mb,
                "disk": fakes.FLAVORS['1'].root_gb,
                "vcpus": fakes.FLAVORS['1'].vcpus,
                "os-flavor-access:is_public": True,
                "rxtx_factor": 1.0,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/" + self._rspv +
                             "/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost" + self._fake +
                             "/flavors/1",
                    },
                ],
            },
        }
        self._set_expected_body(expected['flavor'], fakes.FLAVORS['1'])
        self.assertEqual(flavor, expected)

    def test_get_flavor_with_custom_link_prefix(self):
        self.flags(compute_link_prefix='http://zoo.com:42',
                   glance_link_prefix='http://circus.com:34',
                   group='api')
        req = self._build_request('/flavors/1')
        flavor = self.controller.show(req, '1')
        expected = {
            "flavor": {
                "id": fakes.FLAVORS['1'].flavorid,
                "name": fakes.FLAVORS['1'].name,
                "ram": fakes.FLAVORS['1'].memory_mb,
                "disk": fakes.FLAVORS['1'].root_gb,
                "vcpus": fakes.FLAVORS['1'].vcpus,
                "os-flavor-access:is_public": True,
                "rxtx_factor": 1.0,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://zoo.com:42/" + self._rspv +
                             "/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://zoo.com:42" + self._fake +
                             "/flavors/1",
                    },
                ],
            },
        }
        self._set_expected_body(expected['flavor'], fakes.FLAVORS['1'])
        self.assertEqual(expected, flavor)

    def test_get_flavor_list(self):
        req = self._build_request('/flavors')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": fakes.FLAVORS['1'].flavorid,
                    "name": fakes.FLAVORS['1'].name,
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/" + self._rspv +
                                 "/flavors/1",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost" + self._fake +
                                 "/flavors/1",
                        },
                    ],
                },
                {
                    "id": fakes.FLAVORS['2'].flavorid,
                    "name": fakes.FLAVORS['2'].name,
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/" + self._rspv +
                                 "/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost" + self._fake +
                                 "/flavors/2",
                        },
                    ],
                },
            ],
        }
        if self.expect_description:
            for idx, _flavor in enumerate(expected['flavors']):
                expected['flavors'][idx]['description'] = (
                    fakes.FLAVORS[_flavor['id']].description)
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_with_marker(self):
        self.maxDiff = None
        url = '/flavors?limit=1&marker=1'
        req = self._build_request(url)
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": fakes.FLAVORS['2'].flavorid,
                    "name": fakes.FLAVORS['2'].name,
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/" + self._rspv +
                                 "/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost" + self._fake +
                                 "/flavors/2",
                        },
                    ],
                },
            ],
            'flavors_links': [
                {'href': 'http://localhost/' + self._rspv +
                    '/flavors?limit=1&marker=2',
                 'rel': 'next'}
            ]
        }
        if self.expect_description:
            expected['flavors'][0]['description'] = (
                fakes.FLAVORS['2'].description)
        self.assertThat(flavor, matchers.DictMatches(expected))

    def test_get_flavor_list_with_invalid_marker(self):
        req = self._build_request('/flavors?marker=99999')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_detail_with_limit(self):
        url = '/flavors/detail?limit=1'
        req = self._build_request(url)
        response = self.controller.detail(req)
        response_list = response["flavors"]
        response_links = response["flavors_links"]

        expected_flavors = [
            {
                "id": fakes.FLAVORS['1'].flavorid,
                "name": fakes.FLAVORS['1'].name,
                "ram": fakes.FLAVORS['1'].memory_mb,
                "disk": fakes.FLAVORS['1'].root_gb,
                "vcpus": fakes.FLAVORS['1'].vcpus,
                "os-flavor-access:is_public": True,
                "rxtx_factor": 1.0,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/" + self._rspv +
                             "/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost" + self._fake +
                             "/flavors/1",
                    },
                ],
            },
        ]
        self._set_expected_body(expected_flavors[0], fakes.FLAVORS['1'])

        self.assertEqual(response_list, expected_flavors)
        self.assertEqual(response_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/' + self._rspv + '/flavors/detail', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['1'], 'marker': ['1']},
                        matchers.DictMatches(params))

    def test_get_flavor_with_limit(self):
        req = self._build_request('/flavors?limit=2')
        response = self.controller.index(req)
        response_list = response["flavors"]
        response_links = response["flavors_links"]

        expected_flavors = [
            {
                "id": fakes.FLAVORS['1'].flavorid,
                "name": fakes.FLAVORS['1'].name,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/" + self._rspv +
                             "/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost" + self._fake +
                             "/flavors/1",
                    },
                ],
            },
            {
                "id": fakes.FLAVORS['2'].flavorid,
                "name": fakes.FLAVORS['2'].name,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/" + self._rspv +
                             "/flavors/2",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost" + self._fake +
                             "/flavors/2",
                    },
                ],
            }
        ]
        if self.expect_description:
            for idx, _flavor in enumerate(expected_flavors):
                expected_flavors[idx]['description'] = (
                    fakes.FLAVORS[_flavor['id']].description)
        self.assertEqual(response_list, expected_flavors)
        self.assertEqual(response_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/' + self._rspv + '/flavors', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['2'], 'marker': ['2']},
                        matchers.DictMatches(params))

    def test_get_flavor_with_default_limit(self):
        self.stub_out('nova.api.openstack.common.get_limit_and_marker',
                      fake_get_limit_and_marker)
        self.flags(max_limit=1, group='api')
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?limit=2')
        response = self.controller.index(req)
        response_list = response["flavors"]
        response_links = response["flavors_links"]

        expected_flavors = [
            {
                "id": fakes.FLAVORS['1'].flavorid,
                "name": fakes.FLAVORS['1'].name,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/1",
                    }
                ]
           }
        ]

        self.assertEqual(response_list, expected_flavors)
        self.assertEqual(response_links[0]['rel'], 'next')
        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/v2/fake/flavors', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['2'], 'marker': ['1']},
                        matchers.DictMatches(params))

    def test_get_flavor_list_detail(self):
        req = self._build_request('/flavors/detail')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": fakes.FLAVORS['1'].flavorid,
                    "name": fakes.FLAVORS['1'].name,
                    "ram": fakes.FLAVORS['1'].memory_mb,
                    "disk": fakes.FLAVORS['1'].root_gb,
                    "vcpus": fakes.FLAVORS['1'].vcpus,
                    "os-flavor-access:is_public": True,
                    "rxtx_factor": 1.0,
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/" + self._rspv +
                                 "/flavors/1",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost" + self._fake +
                                 "/flavors/1",
                        },
                    ],
                },
                {
                    "id": fakes.FLAVORS['2'].flavorid,
                    "name": fakes.FLAVORS['2'].name,
                    "ram": fakes.FLAVORS['2'].memory_mb,
                    "disk": fakes.FLAVORS['2'].root_gb,
                    "vcpus": fakes.FLAVORS['2'].vcpus,
                    "os-flavor-access:is_public": True,
                    "rxtx_factor": '',
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/" + self._rspv +
                                 "/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost" + self._fake +
                                 "/flavors/2",
                        },
                    ],
                },
            ],
        }
        self._set_expected_body(expected['flavors'][0], fakes.FLAVORS['1'])
        self._set_expected_body(expected['flavors'][1], fakes.FLAVORS['2'])
        self.assertEqual(expected, flavor)

    @mock.patch('nova.objects.FlavorList.get_all',
                return_value=objects.FlavorList())
    def test_get_empty_flavor_list(self, mock_get):
        req = self._build_request('/flavors')
        flavors = self.controller.index(req)
        expected = {'flavors': []}
        self.assertEqual(flavors, expected)

    def test_get_flavor_list_filter_min_ram(self):
        # Flavor lists may be filtered by minRam.
        req = self._build_request('/flavors?minRam=512')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": fakes.FLAVORS['2'].flavorid,
                    "name": fakes.FLAVORS['2'].name,
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/" + self._rspv +
                                 "/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost" + self._fake +
                                 "/flavors/2",
                        },
                    ],
                },
            ],
        }
        if self.expect_description:
            expected['flavors'][0]['description'] = (
                fakes.FLAVORS['2'].description)
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_filter_invalid_min_ram(self):
        # Ensure you cannot list flavors with invalid minRam param.
        req = self._build_request('/flavors?minRam=NaN')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_list_filter_min_disk(self):
        # Flavor lists may be filtered by minDisk.
        req = self._build_request('/flavors?minDisk=20')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": fakes.FLAVORS['2'].flavorid,
                    "name": fakes.FLAVORS['2'].name,
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/" + self._rspv +
                                 "/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost" + self._fake +
                                 "/flavors/2",
                        },
                    ],
                },
            ],
        }
        if self.expect_description:
            expected['flavors'][0]['description'] = (
                fakes.FLAVORS['2'].description)
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_filter_invalid_min_disk(self):
        # Ensure you cannot list flavors with invalid minDisk param.
        req = self._build_request('/flavors?minDisk=NaN')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_list_detail_min_ram_and_min_disk(self):
        """Tests that filtering work on flavor details and that minRam and
        minDisk filters can be combined
        """
        req = self._build_request('/flavors/detail?minRam=256&minDisk=20')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": fakes.FLAVORS['2'].flavorid,
                    "name": fakes.FLAVORS['2'].name,
                    "ram": fakes.FLAVORS['2'].memory_mb,
                    "disk": fakes.FLAVORS['2'].root_gb,
                    "vcpus": fakes.FLAVORS['2'].vcpus,
                    "os-flavor-access:is_public": True,
                    "rxtx_factor": '',
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/" + self._rspv +
                                 "/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost" + self._fake +
                                 "/flavors/2",
                        },
                    ],
                },
            ],
        }
        self._set_expected_body(expected['flavors'][0], fakes.FLAVORS['2'])
        self.assertEqual(expected, flavor)

    def _test_list_flavors_with_invalid_filter(
        self, url, expected_exception=exception.ValidationError):
        controller_list = self.controller.index
        if 'detail' in url:
            controller_list = self.controller.detail
        req = self.fake_request.blank(self._prefix + url)
        self.assertRaises(expected_exception,
                          controller_list, req)

    def test_list_flavors_with_invalid_non_int_limit(self):
        self._test_list_flavors_with_invalid_filter('/flavors?limit=-9')

    def test_list_detail_flavors_with_invalid_non_int_limit(self):
        self._test_list_flavors_with_invalid_filter('/flavors/detail?limit=-9')

    def test_list_flavors_with_invalid_string_limit(self):
        self._test_list_flavors_with_invalid_filter('/flavors?limit=abc')

    def test_list_detail_flavors_with_invalid_string_limit(self):
        self._test_list_flavors_with_invalid_filter(
            '/flavors/detail?limit=abc')

    def test_list_duplicate_query_with_invalid_string_limit(self):
        self._test_list_flavors_with_invalid_filter(
            '/flavors?limit=1&limit=abc')

    def test_list_detail_duplicate_query_with_invalid_string_limit(self):
        self._test_list_flavors_with_invalid_filter(
            '/flavors/detail?limit=1&limit=abc')

    def _test_list_flavors_duplicate_query_parameters_validation(
        self, url, expected=None):
        controller_list = self.controller.index
        if 'detail' in url:
            controller_list = self.controller.detail
        expected_resp = [{
            "id": fakes.FLAVORS['2'].flavorid,
            "name": fakes.FLAVORS['2'].name,
            "links": [
                {
                    "rel": "self",
                    "href": "http://localhost/" + self._rspv +
                         "/flavors/2",
                },
                {
                    "rel": "bookmark",
                    "href": "http://localhost" + self._fake +
                         "/flavors/2",
                },
            ],
        }]
        if expected:
            expected_resp[0].update(expected)
        params = {
            'limit': 1,
            'marker': 1,
            'is_public': 't',
            'minRam': 2,
            'minDisk': 2,
            'sort_key': 'id',
            'sort_dir': 'asc'
        }

        for param, value in params.items():
            req = self.fake_request.blank(
                self._prefix + url + '?marker=1&%s=%s&%s=%s' %
                (param, value, param, value))
            result = controller_list(req)
            self.assertEqual(expected_resp, result['flavors'])

    def test_list_duplicate_query_parameters_validation(self):
        self._test_list_flavors_duplicate_query_parameters_validation(
            '/flavors')

    def test_list_detail_duplicate_query_parameters_validation(self):
        expected = {
            "ram": fakes.FLAVORS['2'].memory_mb,
            "disk": fakes.FLAVORS['2'].root_gb,
            "vcpus": fakes.FLAVORS['2'].vcpus,
            "os-flavor-access:is_public": True,
            "rxtx_factor": '',
            "OS-FLV-EXT-DATA:ephemeral": fakes.FLAVORS['2'].ephemeral_gb,
            "OS-FLV-DISABLED:disabled": fakes.FLAVORS['2'].disabled,
            "swap": fakes.FLAVORS['2'].swap
        }
        self._test_list_flavors_duplicate_query_parameters_validation(
            '/flavors/detail', expected)

    def _test_list_flavors_with_allowed_filter(
        self, url, expected=None):
        controller_list = self.controller.index
        if 'detail' in url:
            controller_list = self.controller.detail
        expected_resp = [{
            "id": fakes.FLAVORS['2'].flavorid,
            "name": fakes.FLAVORS['2'].name,
            "links": [
                {
                    "rel": "self",
                    "href": "http://localhost/" + self._rspv +
                            "/flavors/2",
                 },
                 {
                    "rel": "bookmark",
                    "href": "http://localhost" + self._fake +
                            "/flavors/2",
                  },
            ],
        }]
        if expected:
            expected_resp[0].update(expected)
        req = self.fake_request.blank(self._prefix + url + '&limit=1&marker=1')
        result = controller_list(req)
        self.assertEqual(expected_resp, result['flavors'])

    def test_list_flavors_with_additional_filter(self):
        self._test_list_flavors_with_allowed_filter(
            '/flavors?limit=1&marker=1&additional=something')

    def test_list_detail_flavors_with_additional_filter(self):
        expected = {
            "ram": fakes.FLAVORS['2'].memory_mb,
            "disk": fakes.FLAVORS['2'].root_gb,
            "vcpus": fakes.FLAVORS['2'].vcpus,
            "os-flavor-access:is_public": True,
            "rxtx_factor": '',
            "OS-FLV-EXT-DATA:ephemeral": fakes.FLAVORS['2'].ephemeral_gb,
            "OS-FLV-DISABLED:disabled": fakes.FLAVORS['2'].disabled,
            "swap": fakes.FLAVORS['2'].swap
        }
        self._test_list_flavors_with_allowed_filter(
            '/flavors/detail?limit=1&marker=1&additional=something',
            expected)

    def test_list_flavors_with_min_ram_filter_as_negative_int(self):
        self._test_list_flavors_with_allowed_filter(
            '/flavors?minRam=-2')

    def test_list_detail_flavors_with_min_ram_filter_as_negative_int(self):
        expected = {
            "ram": fakes.FLAVORS['2'].memory_mb,
            "disk": fakes.FLAVORS['2'].root_gb,
            "vcpus": fakes.FLAVORS['2'].vcpus,
            "os-flavor-access:is_public": True,
            "rxtx_factor": '',
            "OS-FLV-EXT-DATA:ephemeral": fakes.FLAVORS['2'].ephemeral_gb,
            "OS-FLV-DISABLED:disabled": fakes.FLAVORS['2'].disabled,
            "swap": fakes.FLAVORS['2'].swap
        }
        self._test_list_flavors_with_allowed_filter(
            '/flavors/detail?minRam=-2', expected)

    def test_list_flavors_with_min_ram_filter_as_float(self):
        self._test_list_flavors_with_invalid_filter(
            '/flavors?minRam=1.2', expected_exception=webob.exc.HTTPBadRequest)

    def test_list_detail_flavors_with_min_ram_filter_as_float(self):
        self._test_list_flavors_with_invalid_filter(
            '/flavors/detail?minRam=1.2',
            expected_exception=webob.exc.HTTPBadRequest)

    def test_list_flavors_with_min_disk_filter_as_negative_int(self):
        self._test_list_flavors_with_allowed_filter('/flavors?minDisk=-2')

    def test_list_detail_flavors_with_min_disk_filter_as_negative_int(self):
        expected = {
            "ram": fakes.FLAVORS['2'].memory_mb,
            "disk": fakes.FLAVORS['2'].root_gb,
            "vcpus": fakes.FLAVORS['2'].vcpus,
            "os-flavor-access:is_public": True,
            "rxtx_factor": '',
            "OS-FLV-EXT-DATA:ephemeral": fakes.FLAVORS['2'].ephemeral_gb,
            "OS-FLV-DISABLED:disabled": fakes.FLAVORS['2'].disabled,
            "swap": fakes.FLAVORS['2'].swap
        }
        self._test_list_flavors_with_allowed_filter(
            '/flavors/detail?minDisk=-2', expected)

    def test_list_flavors_with_min_disk_filter_as_float(self):
        self._test_list_flavors_with_invalid_filter(
            '/flavors?minDisk=1.2',
            expected_exception=webob.exc.HTTPBadRequest)

    def test_list_detail_flavors_with_min_disk_filter_as_float(self):
        self._test_list_flavors_with_invalid_filter(
            '/flavors/detail?minDisk=1.2',
            expected_exception=webob.exc.HTTPBadRequest)

    def test_list_flavors_with_is_public_filter_as_string_none(self):
        self._test_list_flavors_with_allowed_filter(
            '/flavors?is_public=none')

    def test_list_detail_flavors_with_is_public_filter_as_string_none(self):
        expected = {
            "ram": fakes.FLAVORS['2'].memory_mb,
            "disk": fakes.FLAVORS['2'].root_gb,
            "vcpus": fakes.FLAVORS['2'].vcpus,
            "os-flavor-access:is_public": True,
            "rxtx_factor": '',
            "OS-FLV-EXT-DATA:ephemeral": fakes.FLAVORS['2'].ephemeral_gb,
            "OS-FLV-DISABLED:disabled": fakes.FLAVORS['2'].disabled,
            "swap": fakes.FLAVORS['2'].swap
        }
        self._test_list_flavors_with_allowed_filter(
            '/flavors/detail?is_public=none', expected)

    def test_list_flavors_with_is_public_filter_as_valid_bool(self):
        self._test_list_flavors_with_allowed_filter(
            '/flavors?is_public=false')

    def test_list_detail_flavors_with_is_public_filter_as_valid_bool(self):
        expected = {
            "ram": fakes.FLAVORS['2'].memory_mb,
            "disk": fakes.FLAVORS['2'].root_gb,
            "vcpus": fakes.FLAVORS['2'].vcpus,
            "OS-FLV-EXT-DATA:ephemeral": fakes.FLAVORS['2'].ephemeral_gb,
            "os-flavor-access:is_public": True,
            "rxtx_factor": '',
            "OS-FLV-DISABLED:disabled": fakes.FLAVORS['2'].disabled,
            "swap": fakes.FLAVORS['2'].swap
        }
        self._test_list_flavors_with_allowed_filter(
            '/flavors/detail?is_public=false', expected)

    def test_list_flavors_with_is_public_filter_as_invalid_string(self):
        self._test_list_flavors_with_allowed_filter(
            '/flavors?is_public=invalid')

    def test_list_detail_flavors_with_is_public_filter_as_invalid_string(self):
        expected = {
            "ram": fakes.FLAVORS['2'].memory_mb,
            "disk": fakes.FLAVORS['2'].root_gb,
            "vcpus": fakes.FLAVORS['2'].vcpus,
            "os-flavor-access:is_public": True,
            "rxtx_factor": '',
            "OS-FLV-EXT-DATA:ephemeral": fakes.FLAVORS['2'].ephemeral_gb,
            "OS-FLV-DISABLED:disabled": fakes.FLAVORS['2'].disabled,
            "swap": fakes.FLAVORS['2'].swap
        }
        self._test_list_flavors_with_allowed_filter(
            '/flavors/detail?is_public=invalid', expected)


class FlavorsTestV2_55(FlavorsTestV21):
    """Run the same tests as we would for v2.1 but with a description."""
    microversion = '2.55'
    expect_description = True


class FlavorsTestV2_61(FlavorsTestV2_55):
    """Run the same tests as we would for v2.55 but with a extra_specs."""
    microversion = '2.61'
    expect_extra_specs = True


class FlavorsPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(FlavorsPolicyEnforcementV21, self).setUp()
        self.flavor_controller = flavors_v21.FlavorsController()
        fakes.stub_out_flavor_get_by_flavor_id(self)
        fakes.stub_out_flavor_get_all(self)
        self.req = fakes.HTTPRequest.blank('')

    def test_show_flavor_access_policy_failed(self):
        rule_name = "os_compute_api:os-flavor-access"
        self.policy.set_rules({rule_name: "project:non_fake"})
        resp = self.flavor_controller.show(self.req, '1')
        self.assertNotIn('os-flavor-access:is_public', resp['flavor'])

    def test_detail_flavor_access_policy_failed(self):
        rule_name = "os_compute_api:os-flavor-access"
        self.policy.set_rules({rule_name: "project:non_fake"})
        resp = self.flavor_controller.detail(self.req)
        self.assertNotIn('os-flavor-access:is_public', resp['flavors'][0])

    def test_show_flavor_rxtx_policy_failed(self):
        rule_name = "os_compute_api:os-flavor-rxtx"
        self.policy.set_rules({rule_name: "project:non_fake"})
        resp = self.flavor_controller.show(self.req, '1')
        self.assertNotIn('rxtx_factor', resp['flavor'])

    def test_detail_flavor_rxtx_policy_failed(self):
        rule_name = "os_compute_api:os-flavor-rxtx"
        self.policy.set_rules({rule_name: "project:non_fake"})
        resp = self.flavor_controller.detail(self.req)
        self.assertNotIn('rxtx_factor', resp['flavors'][0])

    def test_create_flavor_extended_policy_failed(self):
        rules = {"os_compute_api:os-flavor-rxtx": "project:non_fake",
                 "os_compute_api:os-flavor-access": "project:non_fake"}
        self.policy.set_rules(rules)
        resp = self.flavor_controller.detail(self.req)
        self.assertNotIn('rxtx_factor', resp['flavors'][0])

    def test_update_flavor_extended_policy_failed(self):
        rules = {"os_compute_api:os-flavor-rxtx": "project:non_fake",
                 "os_compute_api:os-flavor-access": "project:non_fake"}
        self.policy.set_rules(rules)
        resp = self.flavor_controller.detail(self.req)
        self.assertNotIn('rxtx_factor', resp['flavors'][0])


class DisabledFlavorsWithRealDBTestV21(test.TestCase):
    """Tests that disabled flavors should not be shown nor listed."""
    Controller = flavors_v21.FlavorsController
    _prefix = "/v2"
    fake_request = fakes.HTTPRequestV21

    def setUp(self):
        super(DisabledFlavorsWithRealDBTestV21, self).setUp()

        # Add a new disabled type to the list of flavors
        self.req = self.fake_request.blank(self._prefix + '/flavors')
        self.context = self.req.environ['nova.context']
        self.admin_context = context.get_admin_context()

        self.disabled_type = self._create_disabled_instance_type()
        self.addCleanup(self.disabled_type.destroy)
        self.inst_types = objects.FlavorList.get_all(self.admin_context)
        self.controller = self.Controller()

    def _create_disabled_instance_type(self):
        flavor = objects.Flavor(context=self.admin_context,
                                name='foo.disabled', flavorid='10.disabled',
                                memory_mb=512, vcpus=2, root_gb=1,
                                ephemeral_gb=0, swap=0, rxtx_factor=1.0,
                                vcpu_weight=1, disabled=True, is_public=True,
                                extra_specs={}, projects=[])
        flavor.create()
        return flavor

    def test_index_should_not_list_disabled_flavors_to_user(self):
        self.context.is_admin = False

        flavor_list = self.controller.index(self.req)['flavors']
        api_flavorids = set(f['id'] for f in flavor_list)

        db_flavorids = set(i['flavorid'] for i in self.inst_types)
        disabled_flavorid = str(self.disabled_type['flavorid'])

        self.assertIn(disabled_flavorid, db_flavorids)
        self.assertEqual(db_flavorids - set([disabled_flavorid]),
                         api_flavorids)

    def test_index_should_list_disabled_flavors_to_admin(self):
        self.context.is_admin = True

        flavor_list = self.controller.index(self.req)['flavors']
        api_flavorids = set(f['id'] for f in flavor_list)

        db_flavorids = set(i['flavorid'] for i in self.inst_types)
        disabled_flavorid = str(self.disabled_type['flavorid'])

        self.assertIn(disabled_flavorid, db_flavorids)
        self.assertEqual(db_flavorids, api_flavorids)

    def test_show_should_include_disabled_flavor_for_user(self):
        """Counterintuitively we should show disabled flavors to all users and
        not just admins. The reason is that, when a user performs a server-show
        request, we want to be able to display the pretty flavor name ('512 MB
        Instance') and not just the flavor-id even if the flavor id has been
        marked disabled.
        """
        self.context.is_admin = False

        flavor = self.controller.show(
                self.req, self.disabled_type['flavorid'])['flavor']

        self.assertEqual(flavor['name'], self.disabled_type['name'])

    def test_show_should_include_disabled_flavor_for_admin(self):
        self.context.is_admin = True

        flavor = self.controller.show(
                self.req, self.disabled_type['flavorid'])['flavor']

        self.assertEqual(flavor['name'], self.disabled_type['name'])


class ParseIsPublicTestV21(test.TestCase):
    Controller = flavors_v21.FlavorsController

    def setUp(self):
        super(ParseIsPublicTestV21, self).setUp()
        self.controller = self.Controller()

    def assertPublic(self, expected, is_public):
        self.assertIs(expected, self.controller._parse_is_public(is_public),
                      '%s did not return %s' % (is_public, expected))

    def test_None(self):
        self.assertPublic(True, None)

    def test_truthy(self):
        self.assertPublic(True, True)
        self.assertPublic(True, 't')
        self.assertPublic(True, 'true')
        self.assertPublic(True, 'yes')
        self.assertPublic(True, '1')

    def test_falsey(self):
        self.assertPublic(False, False)
        self.assertPublic(False, 'f')
        self.assertPublic(False, 'false')
        self.assertPublic(False, 'no')
        self.assertPublic(False, '0')

    def test_string_none(self):
        self.assertPublic(None, 'none')
        self.assertPublic(None, 'None')

    def test_other(self):
        self.assertRaises(
                webob.exc.HTTPBadRequest, self.assertPublic, None, 'other')
