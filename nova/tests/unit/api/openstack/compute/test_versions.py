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
import uuid as stdlib_uuid

from oslo.serialization import jsonutils
import webob

from nova.api.openstack.compute import views
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import matchers


NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'ns': 'http://docs.openstack.org/common/api/v1.0'
}


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
        "status": "CURRENT",
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
        "status": "EXPERIMENTAL",
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


class VersionsTestV20(test.NoDBTestCase):

    def test_get_version_list(self):
        req = webob.Request.blank('/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        versions = jsonutils.loads(res.body)["versions"]
        expected = [
            {
                "id": "v2.0",
                "status": "CURRENT",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/",
                    }],
            },
            {
                "id": "v2.1",
                "status": "EXPERIMENTAL",
                "updated": "2013-07-23T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/",
                    }],
            },
        ]
        self.assertEqual(versions, expected)

    def test_get_version_list_302(self):
        req = webob.Request.blank('/v2')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 302)
        redirect_req = webob.Request.blank('/v2/')
        self.assertEqual(res.location, redirect_req.url)

    def _test_get_version_2_detail(self, url, accept=None):
        if accept is None:
            accept = "application/json"
        req = webob.Request.blank(url)
        req.accept = accept
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {
            "version": {
                "id": "v2.0",
                "status": "CURRENT",
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
        req = webob.Request.blank('/v2/versions/1234')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(404, res.status_int)

    def test_multi_choice_image(self):
        req = webob.Request.blank('/images/1')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 300)
        self.assertEqual(res.content_type, "application/json")

        expected = {
        "choices": [
            {
                "id": "v2.0",
                "status": "CURRENT",
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
                "status": "EXPERIMENTAL",
                "links": [
                    {
                        "href": "http://localhost/v2/images/1",
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
        req = webob.Request.blank('/servers')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 300)
        self.assertEqual(res.content_type, "application/json")

    def test_multi_choice_server(self):
        uuid = str(stdlib_uuid.uuid4())
        req = webob.Request.blank('/servers/' + uuid)
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 300)
        self.assertEqual(res.content_type, "application/json")

        expected = {
        "choices": [
            {
                "id": "v2.0",
                "status": "CURRENT",
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
                "status": "EXPERIMENTAL",
                "links": [
                    {
                        "href": "http://localhost/v2/servers/" + uuid,
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
                "updated": "2011-07-18T11:30:00Z",
            }
        }

        expected = {
            "versions": [
                {
                    "id": "3.2.1",
                    "status": "CURRENT",
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

        self.assertEqual(output, expected)

    def test_generate_href(self):
        base_url = "http://example.org/app/"

        expected = "http://example.org/app/v2/"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href('v2')

        self.assertEqual(actual, expected)

    def test_generate_href_v21(self):
        base_url = "http://example.org/app/"

        expected = "http://example.org/app/v2/"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href('v2.1')

        self.assertEqual(actual, expected)

    def test_generate_href_unknown(self):
        base_url = "http://example.org/app/"

        expected = "http://example.org/app/v2/"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href('foo')

        self.assertEqual(actual, expected)


# NOTE(oomichi): Now version API of v2.0 covers "/"(root).
# So this class tests "/v2.1" only for v2.1 API.
class VersionsTestV21(test.NoDBTestCase):
    exp_versions = copy.deepcopy(EXP_VERSIONS)
    exp_versions['v2.0']['links'].insert(0,
        {'href': 'http://localhost/v2.1/', 'rel': 'self'},
    )

    def test_get_version_list_302(self):
        req = webob.Request.blank('/v2.1')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(res.status_int, 302)
        redirect_req = webob.Request.blank('/v2.1/')
        self.assertEqual(res.location, redirect_req.url)

    def test_get_version_21_detail(self):
        req = webob.Request.blank('/v2.1/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {"version": self.exp_versions['v2.1']}
        self.assertEqual(expected, version)

    def test_get_version_21_versions_v21_detail(self):
        req = webob.Request.blank('/v2.1/fake/versions/v2.1')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {"version": self.exp_versions['v2.1']}
        self.assertEqual(expected, version)

    def test_get_version_21_versions_v20_detail(self):
        req = webob.Request.blank('/v2.1/fake/versions/v2.0')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {"version": self.exp_versions['v2.0']}
        self.assertEqual(expected, version)

    def test_get_version_21_versions_invalid(self):
        req = webob.Request.blank('/v2.1/versions/1234')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(res.status_int, 404)

    def test_get_version_21_detail_content_type(self):
        req = webob.Request.blank('/')
        req.accept = "application/json;version=2.1"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {"version": self.exp_versions['v2.1']}
        self.assertEqual(expected, version)
