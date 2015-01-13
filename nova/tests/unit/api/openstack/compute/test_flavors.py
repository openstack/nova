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

import six.moves.urllib.parse as urlparse
import webob

from nova.api.openstack import common
from nova.api.openstack.compute import flavors as flavors_v2
from nova.api.openstack.compute.plugins.v3 import flavors as flavors_v3
import nova.compute.flavors
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import matchers

NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


FAKE_FLAVORS = {
    'flavor 1': {
        "flavorid": '1',
        "name": 'flavor 1',
        "memory_mb": '256',
        "root_gb": '10',
        "ephemeral_gb": '20',
        "swap": '10',
        "disabled": False,
        "vcpus": '',
    },
    'flavor 2': {
        "flavorid": '2',
        "name": 'flavor 2',
        "memory_mb": '512',
        "root_gb": '20',
        "ephemeral_gb": '10',
        "swap": '5',
        "disabled": False,
        "vcpus": '',
    },
}


def fake_flavor_get_by_flavor_id(flavorid, ctxt=None):
    return FAKE_FLAVORS['flavor %s' % flavorid]


def fake_get_all_flavors_sorted_list(context=None, inactive=False,
                                     filters=None, sort_key='flavorid',
                                     sort_dir='asc', limit=None, marker=None):
    if marker in ['99999']:
        raise exception.MarkerNotFound(marker)

    def reject_min(db_attr, filter_attr):
        return (filter_attr in filters and
                int(flavor[db_attr]) < int(filters[filter_attr]))

    filters = filters or {}
    res = []
    for (flavor_name, flavor) in FAKE_FLAVORS.items():
        if reject_min('memory_mb', 'min_memory_mb'):
            continue
        elif reject_min('root_gb', 'min_root_gb'):
            continue

        res.append(flavor)

    res = sorted(res, key=lambda item: item[sort_key])
    output = []
    marker_found = True if marker is None else False
    for flavor in res:
        if not marker_found and marker == flavor['flavorid']:
            marker_found = True
        elif marker_found:
            if limit is None or len(output) < int(limit):
                output.append(flavor)

    return output


def fake_get_limit_and_marker(request, max_limit=1):
    params = common.get_pagination_params(request)
    limit = params.get('limit', max_limit)
    limit = min(max_limit, limit)
    marker = params.get('marker')

    return limit, marker


def empty_get_all_flavors_sorted_list(context=None, inactive=False,
                                      filters=None, sort_key='flavorid',
                                      sort_dir='asc', limit=None, marker=None):
    return []


def return_flavor_not_found(flavor_id, ctxt=None):
    raise exception.FlavorNotFound(flavor_id=flavor_id)


class FlavorsTestV21(test.TestCase):
    _prefix = "/v3"
    Controller = flavors_v3.FlavorsController
    fake_request = fakes.HTTPRequestV3
    _rspv = "v3"
    _fake = ""

    def setUp(self):
        super(FlavorsTestV21, self).setUp()
        self.flags(osapi_compute_extension=[])
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(nova.compute.flavors, "get_all_flavors_sorted_list",
                       fake_get_all_flavors_sorted_list)
        self.stubs.Set(nova.compute.flavors,
                       "get_flavor_by_flavor_id",
                       fake_flavor_get_by_flavor_id)
        self.controller = self.Controller()

    def _set_expected_body(self, expected, ephemeral, swap, disabled):
        # NOTE(oomichi): On v2.1 API, some extensions of v2.0 are merged
        # as core features and we can get the following parameters as the
        # default.
        expected['OS-FLV-EXT-DATA:ephemeral'] = ephemeral
        expected['OS-FLV-DISABLED:disabled'] = disabled
        expected['swap'] = swap

    def test_get_flavor_by_invalid_id(self):
        self.stubs.Set(nova.compute.flavors,
                       "get_flavor_by_flavor_id",
                       return_flavor_not_found)
        req = self.fake_request.blank(self._prefix + '/flavors/asdf')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'asdf')

    def test_get_flavor_by_id(self):
        req = self.fake_request.blank(self._prefix + '/flavors/1')
        flavor = self.controller.show(req, '1')
        expected = {
            "flavor": {
                "id": "1",
                "name": "flavor 1",
                "ram": "256",
                "disk": "10",
                "vcpus": "",
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
        self._set_expected_body(expected['flavor'], ephemeral='20',
                                swap='10', disabled=False)
        self.assertEqual(flavor, expected)

    def test_get_flavor_with_custom_link_prefix(self):
        self.flags(osapi_compute_link_prefix='http://zoo.com:42',
                   osapi_glance_link_prefix='http://circus.com:34')
        req = self.fake_request.blank(self._prefix + '/flavors/1')
        flavor = self.controller.show(req, '1')
        expected = {
            "flavor": {
                "id": "1",
                "name": "flavor 1",
                "ram": "256",
                "disk": "10",
                "vcpus": "",
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
        self._set_expected_body(expected['flavor'], ephemeral='20',
                                swap='10', disabled=False)
        self.assertEqual(expected, flavor)

    def test_get_flavor_list(self):
        req = self.fake_request.blank(self._prefix + '/flavors')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
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
                    "id": "2",
                    "name": "flavor 2",
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
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_with_marker(self):
        self.maxDiff = None
        url = self._prefix + '/flavors?limit=1&marker=1'
        req = self.fake_request.blank(url)
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
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
        self.assertThat(flavor, matchers.DictMatches(expected))

    def test_get_flavor_list_with_invalid_marker(self):
        req = self.fake_request.blank(self._prefix + '/flavors?marker=99999')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_detail_with_limit(self):
        url = self._prefix + '/flavors/detail?limit=1'
        req = self.fake_request.blank(url)
        response = self.controller.detail(req)
        response_list = response["flavors"]
        response_links = response["flavors_links"]

        expected_flavors = [
            {
                "id": "1",
                "name": "flavor 1",
                "ram": "256",
                "disk": "10",
                "vcpus": "",
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
        self._set_expected_body(expected_flavors[0], ephemeral='20',
                                swap='10', disabled=False)

        self.assertEqual(response_list, expected_flavors)
        self.assertEqual(response_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/' + self._rspv + '/flavors/detail', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['1'], 'marker': ['1']},
                        matchers.DictMatches(params))

    def test_get_flavor_with_limit(self):
        req = self.fake_request.blank(self._prefix + '/flavors?limit=2')
        response = self.controller.index(req)
        response_list = response["flavors"]
        response_links = response["flavors_links"]

        expected_flavors = [
            {
                "id": "1",
                "name": "flavor 1",
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
                "id": "2",
                "name": "flavor 2",
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
        self.assertEqual(response_list, expected_flavors)
        self.assertEqual(response_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/' + self._rspv + '/flavors', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['2'], 'marker': ['2']},
                        matchers.DictMatches(params))

    def test_get_flavor_with_default_limit(self):
        self.stubs.Set(common, "get_limit_and_marker",
                       fake_get_limit_and_marker)
        self.flags(osapi_max_limit=1)
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?limit=2')
        response = self.controller.index(req)
        response_list = response["flavors"]
        response_links = response["flavors_links"]

        expected_flavors = [
            {
                "id": "1",
                "name": "flavor 1",
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
        req = self.fake_request.blank(self._prefix + '/flavors/detail')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
                    "ram": "256",
                    "disk": "10",
                    "vcpus": "",
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
                    "id": "2",
                    "name": "flavor 2",
                    "ram": "512",
                    "disk": "20",
                    "vcpus": "",
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
        self._set_expected_body(expected['flavors'][0], ephemeral='20',
                                swap='10', disabled=False)
        self._set_expected_body(expected['flavors'][1], ephemeral='10',
                                swap='5', disabled=False)
        self.assertEqual(expected, flavor)

    def test_get_empty_flavor_list(self):
        self.stubs.Set(nova.compute.flavors, "get_all_flavors_sorted_list",
                       empty_get_all_flavors_sorted_list)

        req = self.fake_request.blank(self._prefix + '/flavors')
        flavors = self.controller.index(req)
        expected = {'flavors': []}
        self.assertEqual(flavors, expected)

    def test_get_flavor_list_filter_min_ram(self):
        # Flavor lists may be filtered by minRam.
        req = self.fake_request.blank(self._prefix + '/flavors?minRam=512')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
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
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_filter_invalid_min_ram(self):
        # Ensure you cannot list flavors with invalid minRam param.
        req = self.fake_request.blank(self._prefix + '/flavors?minRam=NaN')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_list_filter_min_disk(self):
        # Flavor lists may be filtered by minDisk.
        req = self.fake_request.blank(self._prefix + '/flavors?minDisk=20')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
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
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_filter_invalid_min_disk(self):
        # Ensure you cannot list flavors with invalid minDisk param.
        req = self.fake_request.blank(self._prefix + '/flavors?minDisk=NaN')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_list_detail_min_ram_and_min_disk(self):
        """Tests that filtering work on flavor details and that minRam and
        minDisk filters can be combined
        """
        req = self.fake_request.blank(self._prefix + '/flavors/detail'
                                      '?minRam=256&minDisk=20')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
                    "ram": "512",
                    "disk": "20",
                    "vcpus": "",
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
        self._set_expected_body(expected['flavors'][0], ephemeral='10',
                                swap='5', disabled=False)
        self.assertEqual(expected, flavor)


class FlavorsTestV20(FlavorsTestV21):
    _prefix = "/v2/fake"
    Controller = flavors_v2.Controller
    fake_request = fakes.HTTPRequest
    _rspv = "v2/fake"
    _fake = "/fake"

    def _set_expected_body(self, expected, ephemeral, swap, disabled):
        pass


class DisabledFlavorsWithRealDBTestV21(test.TestCase):
    """Tests that disabled flavors should not be shown nor listed."""
    Controller = flavors_v3.FlavorsController
    _prefix = "/v3"
    fake_request = fakes.HTTPRequestV3

    def setUp(self):
        super(DisabledFlavorsWithRealDBTestV21, self).setUp()

        # Add a new disabled type to the list of flavors
        self.req = self.fake_request.blank(self._prefix + '/flavors')
        self.context = self.req.environ['nova.context']
        self.admin_context = context.get_admin_context()

        self.disabled_type = self._create_disabled_instance_type()
        self.inst_types = db.flavor_get_all(
                self.admin_context)
        self.controller = self.Controller()

    def tearDown(self):
        db.flavor_destroy(
                self.admin_context, self.disabled_type['name'])

        super(DisabledFlavorsWithRealDBTestV21, self).tearDown()

    def _create_disabled_instance_type(self):
        inst_types = db.flavor_get_all(self.admin_context)

        inst_type = inst_types[0]

        del inst_type['id']
        inst_type['name'] += '.disabled'
        inst_type['flavorid'] = unicode(max(
                [int(flavor['flavorid']) for flavor in inst_types]) + 1)
        inst_type['disabled'] = True

        disabled_type = db.flavor_create(
                self.admin_context, inst_type)

        return disabled_type

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


class DisabledFlavorsWithRealDBTestV20(DisabledFlavorsWithRealDBTestV21):
    """Tests that disabled flavors should not be shown nor listed."""
    Controller = flavors_v2.Controller
    _prefix = "/v2/fake"
    fake_request = fakes.HTTPRequest


class ParseIsPublicTestV21(test.TestCase):
    Controller = flavors_v3.FlavorsController

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


class ParseIsPublicTestV20(ParseIsPublicTestV21):
    Controller = flavors_v2.Controller
