# Copyright 2010-2011 OpenStack Foundation
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

import copy

from oslo_serialization import jsonutils

from nova.api.openstack import api_version_request as avr
from nova.api.openstack.compute import views
from nova.api import wsgi
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import matchers
from nova.tests import uuidsentinel as uuids


NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'ns': 'http://docs.openstack.org/common/api/v1.0'
}

MAX_API_VERSION = avr.max_api_version().get_string()

EXP_LINKS = {
   'v2.0': {
       'html': 'http://docs.openstack.org/',
    },
   'v2.1': {
       'html': 'http://docs.openstack.org/'
    },
}


EXP_VERSIONS = {
    "v2.0": {
        "id": "v2.0",
        "status": "SUPPORTED",
        "version": "",
        "min_version": "",
        "updated": "2011-01-21T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "text/html",
                "href": EXP_LINKS['v2.0']['html'],
            },
        ],
        "media-types": [
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute+json;version=2",
            },
        ],
    },
    "v2.1": {
        "id": "v2.1",
        "status": "CURRENT",
        "version": MAX_API_VERSION,
        "min_version": "2.1",
        "updated": "2013-07-23T11:33:21Z",
        "links": [
            {
                "rel": "self",
                "href": "http://localhost/v2.1/",
            },
            {
                "rel": "describedby",
                "type": "text/html",
                "href": EXP_LINKS['v2.1']['html'],
            },
        ],
        "media-types": [
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute+json;version=2.1",
            }
        ],
    }
}


def _get_self_href(response):
    """Extract the URL to self from response data."""
    data = jsonutils.loads(response.body)
    for link in data['versions'][0]['links']:
        if link['rel'] == 'self':
            return link['href']
    return ''


class VersionsTestV21WithV2CompatibleWrapper(test.NoDBTestCase):

    @property
    def wsgi_app(self):
        return fakes.wsgi_app_v21(v2_compatible=True)

    def test_get_version_list(self):
        req = fakes.HTTPRequest.blank('/', base_url='')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        versions = jsonutils.loads(res.body)["versions"]
        expected = [
            {
                "id": "v2.0",
                "status": "SUPPORTED",
                "version": "",
                "min_version": "",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/",
                    }],
            },
            {
                "id": "v2.1",
                "status": "CURRENT",
                "version": MAX_API_VERSION,
                "min_version": "2.1",
                "updated": "2013-07-23T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2.1/",
                    }],
            },
        ]
        self.assertEqual(expected, versions)

    def test_get_version_list_302(self):
        req = fakes.HTTPRequest.blank('/v2')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(302, res.status_int)
        redirect_req = fakes.HTTPRequest.blank('/v2/')
        self.assertEqual(redirect_req.url, res.location)

    def _test_get_version_2_detail(self, url, accept=None):
        if accept is None:
            accept = "application/json"
        req = fakes.HTTPRequest.blank(url, base_url='')
        req.accept = accept
        res = req.get_response(self.wsgi_app)
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        version = jsonutils.loads(res.body)
        expected = {
            "version": {
                "id": "v2.0",
                "status": "SUPPORTED",
                "version": "",
                "min_version": "",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/",
                    },
                    {
                        "rel": "describedby",
                        "type": "text/html",
                        "href": EXP_LINKS['v2.0']['html'],
                    },
                ],
                "media-types": [
                    {
                        "base": "application/json",
                        "type": "application/"
                                "vnd.openstack.compute+json;version=2",
                    },
                ],
            },
        }
        self.assertEqual(expected, version)

    def test_get_version_2_detail(self):
        self._test_get_version_2_detail('/v2/')

    def test_get_version_2_detail_content_type(self):
        accept = "application/json;version=2"
        self._test_get_version_2_detail('/', accept=accept)

    def test_get_version_2_versions_invalid(self):
        req = fakes.HTTPRequest.blank('/v2/versions/1234/foo')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(404, res.status_int)

    def test_multi_choice_image(self):
        req = fakes.HTTPRequest.blank('/images/1', base_url='')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(300, res.status_int)
        self.assertEqual("application/json", res.content_type)

        expected = {
        "choices": [
            {
                "id": "v2.0",
                "status": "SUPPORTED",
                "links": [
                    {
                        "href": "http://localhost/v2/images/1",
                        "rel": "self",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/json",
                        "type": "application/vnd.openstack.compute+json"
                                ";version=2"
                    },
                ],
            },
            {
                "id": "v2.1",
                "status": "CURRENT",
                "links": [
                    {
                        "href": "http://localhost/v2.1/images/1",
                        "rel": "self",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/json",
                        "type":
                        "application/vnd.openstack.compute+json;version=2.1",
                    }
                ],
            },
        ], }

        self.assertThat(jsonutils.loads(res.body),
                        matchers.DictMatches(expected))

    def test_multi_choice_server_atom(self):
        """Make sure multi choice responses do not have content-type
        application/atom+xml (should use default of json)
        """
        req = fakes.HTTPRequest.blank('/servers')
        req.accept = "application/atom+xml"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(300, res.status_int)
        self.assertEqual("application/json", res.content_type)

    def test_multi_choice_server(self):
        uuid = uuids.fake
        req = fakes.HTTPRequest.blank('/servers/' + uuid, base_url='')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(300, res.status_int)
        self.assertEqual("application/json", res.content_type)

        expected = {
        "choices": [
            {
                "id": "v2.0",
                "status": "SUPPORTED",
                "links": [
                    {
                        "href": "http://localhost/v2/servers/" + uuid,
                        "rel": "self",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/json",
                        "type": "application/vnd.openstack.compute+json"
                                ";version=2"
                    },
                ],
            },
            {
                "id": "v2.1",
                "status": "CURRENT",
                "links": [
                    {
                        "href": "http://localhost/v2.1/servers/" + uuid,
                        "rel": "self",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/json",
                        "type":
                        "application/vnd.openstack.compute+json;version=2.1",
                    }
                ],
            },
        ], }

        self.assertThat(jsonutils.loads(res.body),
                        matchers.DictMatches(expected))


class VersionsViewBuilderTests(test.NoDBTestCase):
    def test_view_builder(self):
        base_url = "http://example.org/"

        version_data = {
            "v3.2.1": {
                "id": "3.2.1",
                "status": "CURRENT",
                "version": "2.3",
                "min_version": "2.1",
                "updated": "2011-07-18T11:30:00Z",
            }
        }

        expected = {
            "versions": [
                {
                    "id": "3.2.1",
                    "status": "CURRENT",
                    "version": "2.3",
                    "min_version": "2.1",
                    "updated": "2011-07-18T11:30:00Z",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://example.org/v2/",
                        },
                    ],
                }
            ]
        }

        builder = views.versions.ViewBuilder(base_url)
        output = builder.build_versions(version_data)

        self.assertEqual(expected, output)

    def _test_view_builder_compute_link_prefix(self, href=None):
        base_url = "http://example.org/v2.1/"
        if href is None:
            href = base_url

        version_data = {
            "id": "v2.1",
            "status": "CURRENT",
            "version": "2.8",
            "min_version": "2.1",
            "updated": "2013-07-23T11:33:21Z",
            "links": [
                {
                    "rel": "describedby",
                    "type": "text/html",
                    "href": EXP_LINKS['v2.1']['html'],
                }
            ],
            "media-types": [
                {
                    "base": "application/json",
                    "type": ("application/vnd.openstack."
                             "compute+json;version=2.1")
                }
            ],
        }
        expected_data = copy.deepcopy(version_data)
        expected = {'version': expected_data}
        expected['version']['links'].insert(0, {
                        "rel": "self",
                        "href": href,
                    })
        builder = views.versions.ViewBuilder(base_url)
        output = builder.build_version(version_data)
        self.assertEqual(expected, output)

    def test_view_builder_with_compute_link_prefix(self):
        self.flags(compute_link_prefix='http://zoo.com:42', group='api')
        href = "http://zoo.com:42/v2.1/"
        self._test_view_builder_compute_link_prefix(href)

    def test_view_builder_without_compute_link_prefix(self):
        self._test_view_builder_compute_link_prefix()

    def test_generate_href(self):
        base_url = "http://example.org/app/"

        expected = "http://example.org/app/v2/"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href('v2')

        self.assertEqual(expected, actual)

    def test_generate_href_v21(self):
        base_url = "http://example.org/app/"

        expected = "http://example.org/app/v2.1/"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href('v2.1')

        self.assertEqual(expected, actual)

    def test_generate_href_unknown(self):
        base_url = "http://example.org/app/"

        expected = "http://example.org/app/v2/"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href('foo')

        self.assertEqual(expected, actual)

    def test_generate_href_with_path(self):
        path = "random/path"
        base_url = "http://example.org/app/"
        expected = "http://example.org/app/v2/%s" % path
        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href("v2", path)
        self.assertEqual(actual, expected)

    def test_generate_href_with_empty_path(self):
        path = ""
        base_url = "http://example.org/app/"
        expected = "http://example.org/app/v2/"
        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href("v2", path)
        self.assertEqual(actual, expected)


# NOTE(oomichi): Now version API of v2.0 covers "/"(root).
# So this class tests "/v2.1" only for v2.1 API.
class VersionsTestV21(test.NoDBTestCase):
    exp_versions = copy.deepcopy(EXP_VERSIONS)
    exp_versions['v2.0']['links'].insert(0,
        {'href': 'http://localhost/v2.1/', 'rel': 'self'},
    )

    @property
    def wsgi_app(self):
        return fakes.wsgi_app_v21()

    def test_get_version_list_302(self):
        req = fakes.HTTPRequest.blank('/v2.1')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(302, res.status_int)
        redirect_req = fakes.HTTPRequest.blank('/v2.1/')
        self.assertEqual(redirect_req.url, res.location)

    def test_get_version_21_detail(self):
        req = fakes.HTTPRequest.blank('/v2.1/', base_url='')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        version = jsonutils.loads(res.body)
        expected = {"version": self.exp_versions['v2.1']}
        self.assertEqual(expected, version)

    def test_get_version_21_versions_v21_detail(self):
        req = fakes.HTTPRequest.blank('/v2.1/fake/versions/v2.1', base_url='')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        version = jsonutils.loads(res.body)
        expected = {"version": self.exp_versions['v2.1']}
        self.assertEqual(expected, version)

    def test_get_version_21_versions_v20_detail(self):
        req = fakes.HTTPRequest.blank('/v2.1/fake/versions/v2.0', base_url='')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        version = jsonutils.loads(res.body)
        expected = {"version": self.exp_versions['v2.0']}
        self.assertEqual(expected, version)

    def test_get_version_21_versions_invalid(self):
        req = fakes.HTTPRequest.blank('/v2.1/versions/1234/foo')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(404, res.status_int)

    def test_get_version_21_detail_content_type(self):
        req = fakes.HTTPRequest.blank('/', base_url='')
        req.accept = "application/json;version=2.1"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        version = jsonutils.loads(res.body)
        expected = {"version": self.exp_versions['v2.1']}
        self.assertEqual(expected, version)


class VersionBehindSslTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VersionBehindSslTestCase, self).setUp()
        self.flags(secure_proxy_ssl_header='HTTP_X_FORWARDED_PROTO',
                   group='wsgi')

    @property
    def wsgi_app(self):
        return fakes.wsgi_app_v21(v2_compatible=True)

    def test_versions_without_headers(self):
        req = wsgi.Request.blank('/')
        req.accept = "application/json"
        res = req.get_response(self.wsgi_app)
        self.assertEqual(200, res.status_int)
        href = _get_self_href(res)
        self.assertTrue(href.startswith('http://'))

    def test_versions_with_header(self):
        req = wsgi.Request.blank('/')
        req.accept = "application/json"
        req.headers['X-Forwarded-Proto'] = 'https'
        res = req.get_response(self.wsgi_app)
        self.assertEqual(200, res.status_int)
        href = _get_self_href(res)
        self.assertTrue(href.startswith('https://'))
