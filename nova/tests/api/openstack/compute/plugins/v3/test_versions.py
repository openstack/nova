# Copyright 2013 IBM Corp.
# Copyright 2010-2011 OpenStack Foundation
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

from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes


NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'ns': 'http://docs.openstack.org/common/api/v1.0'
}


EXP_LINKS = {
   'v2.0': {
       'pdf': 'http://docs.openstack.org/'
               'api/openstack-compute/2/os-compute-devguide-2.pdf',
       'wadl': 'http://docs.openstack.org/'
               'api/openstack-compute/2/wadl/os-compute-2.wadl'
    },
   'v3.0': {
       'pdf': 'http://docs.openstack.org/'
               'api/openstack-compute/3/os-compute-devguide-3.pdf',
       'wadl': 'http://docs.openstack.org/'
               'api/openstack-compute/3/wadl/os-compute-3.wadl'
    },
}


EXP_VERSIONS = {
    "v2.0": {
        "id": "v2.0",
        "status": "CURRENT",
        "updated": "2011-01-21T11:33:21Z",
        "links": [
            {
                "rel": "self",
                "href": "http://localhost/v3/",
            },
            {
                "rel": "describedby",
                "type": "application/pdf",
                "href": EXP_LINKS['v2.0']['pdf'],
            },
            {
                "rel": "describedby",
                "type": "application/vnd.sun.wadl+xml",
                "href": EXP_LINKS['v2.0']['wadl'],
            },
        ],
        "media-types": [
            {
                "base": "application/xml",
                "type": "application/vnd.openstack.compute+xml;version=2",
            },
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute+json;version=2",
            }
        ],
    },
    "v3.0": {
        "id": "v3.0",
        "status": "EXPERIMENTAL",
        "updated": "2013-07-23T11:33:21Z",
        "links": [
            {
                "rel": "self",
                "href": "http://localhost/v3/",
            },
            {
                "rel": "describedby",
                "type": "application/pdf",
                "href": EXP_LINKS['v3.0']['pdf'],
            },
            {
                "rel": "describedby",
                "type": "application/vnd.sun.wadl+xml",
                "href": EXP_LINKS['v3.0']['wadl'],
            },
        ],
        "media-types": [
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute+json;version=3",
            }
        ],
    }
}


class VersionsTest(test.NoDBTestCase):

    def test_get_version_list_302(self):
        req = webob.Request.blank('/v3')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 302)
        redirect_req = webob.Request.blank('/v3/')
        self.assertEqual(res.location, redirect_req.url)

    def test_get_version_3_detail(self):
        req = webob.Request.blank('/v3/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {"version": EXP_VERSIONS['v3.0']}
        self.assertEqual(expected, version)

    def test_get_version_3_versions_v3_detail(self):
        req = webob.Request.blank('/v3/versions/v3.0')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {"version": EXP_VERSIONS['v3.0']}
        self.assertEqual(expected, version)

    def test_get_version_3_versions_v2_detail(self):
        req = webob.Request.blank('/v3/versions/v2.0')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {"version": EXP_VERSIONS['v2.0']}
        self.assertEqual(expected, version)

    def test_get_version_3_versions_invalid(self):
        req = webob.Request.blank('/v3/versions/1234')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 404)
        self.assertEqual(res.content_type, "application/json")

    def test_get_version_3_detail_content_type(self):
        req = webob.Request.blank('/')
        req.accept = "application/json;version=3"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {"version": EXP_VERSIONS['v3.0']}
        self.assertEqual(expected, version)
