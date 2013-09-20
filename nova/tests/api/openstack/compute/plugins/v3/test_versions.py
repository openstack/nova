# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import feedparser
from lxml import etree
import webob

from nova.api.openstack import xmlutil
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import common
from nova.tests.api.openstack import fakes


NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'ns': 'http://docs.openstack.org/common/api/v1.0'
}


EXP_LINKS = {
   'v3.0': {
       'pdf': 'http://docs.openstack.org/'
               'api/openstack-compute/3/os-compute-devguide-3.pdf',
       'wadl': 'http://docs.openstack.org/'
               'api/openstack-compute/3/wadl/os-compute-3.wadl'
    },
}


EXP_VERSIONS = {
    "v3.0": {
        "id": "v3.0",
        "status": "EXPERIMENTAL",
        "updated": "2013-07-23T11:33:21Z",
        "links": [
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
                "base": "application/xml",
                "type": "application/vnd.openstack.compute+xml;version=3",
            },
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
        expected = {
            "version": {
                "id": "v3.0",
                "status": "EXPERIMENTAL",
                "updated": "2013-07-23T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v3/",
                    },
                ],
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
                        "base": "application/xml",
                        "type": "application/"
                                "vnd.openstack.compute+xml;version=3",
                    },
                    {
                        "base": "application/json",
                        "type": "application/"
                                "vnd.openstack.compute+json;version=3",
                    },
                ],
            },
        }
        self.assertEqual(expected, version)

    def test_get_version_3_detail_content_type(self):
        req = webob.Request.blank('/')
        req.accept = "application/json;version=3"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = jsonutils.loads(res.body)
        expected = {
            "version": {
                "id": "v3.0",
                "status": "EXPERIMENTAL",
                "updated": "2013-07-23T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v3/",
                    },
                ],
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
                        "base": "application/xml",
                        "type": "application/"
                                "vnd.openstack.compute+xml;version=3",
                    },
                    {
                        "base": "application/json",
                        "type": "application/"
                                "vnd.openstack.compute+json;version=3",
                    },
                ],
            },
        }
        self.assertEqual(expected, version)

    def test_get_version_3_detail_xml(self):
        req = webob.Request.blank('/v3/')
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/xml")

        version = etree.XML(res.body)
        xmlutil.validate_schema(version, 'version')

        expected = EXP_VERSIONS['v3.0']
        self.assertTrue(version.xpath('/ns:version', namespaces=NS))
        media_types = version.xpath('ns:media-types/ns:media-type',
                                    namespaces=NS)
        self.assertTrue(common.compare_media_types(media_types,
                                             expected['media-types']))
        for key in ['id', 'status', 'updated']:
            self.assertEqual(version.get(key), expected[key])
        links = version.xpath('atom:link', namespaces=NS)
        self.assertTrue(common.compare_links(links,
            [{'rel': 'self', 'href': 'http://localhost/v3/'}]
            + expected['links']))

    def test_get_version_3_detail_atom(self):
        req = webob.Request.blank('/v3/')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app_v3())
        self.assertEqual(res.status_int, 200)
        self.assertEqual("application/atom+xml", res.content_type)

        xmlutil.validate_schema(etree.XML(res.body), 'atom')

        f = feedparser.parse(res.body)
        self.assertEqual(f.feed.title, 'About This Version')
        self.assertEqual(f.feed.updated, '2013-07-23T11:33:21Z')
        self.assertEqual(f.feed.id, 'http://localhost/v3/')
        self.assertEqual(f.feed.author, 'Rackspace')
        self.assertEqual(f.feed.author_detail.href,
                         'http://www.rackspace.com/')
        self.assertEqual(f.feed.links[0]['href'], 'http://localhost/v3/')
        self.assertEqual(f.feed.links[0]['rel'], 'self')

        self.assertEqual(len(f.entries), 1)
        entry = f.entries[0]
        self.assertEqual(entry.id, 'http://localhost/v3/')
        self.assertEqual(entry.title, 'Version v3.0')
        self.assertEqual(entry.updated, '2013-07-23T11:33:21Z')
        self.assertEqual(len(entry.content), 1)
        self.assertEqual(entry.content[0].value,
            'Version v3.0 EXPERIMENTAL (2013-07-23T11:33:21Z)')
        self.assertEqual(len(entry.links), 3)
        self.assertEqual(entry.links[0]['href'], 'http://localhost/v3/')
        self.assertEqual(entry.links[0]['rel'], 'self')
        self.assertEqual(entry.links[1], {
            'href': EXP_LINKS['v3.0']['pdf'],
            'type': 'application/pdf',
            'rel': 'describedby'})
        self.assertEqual(entry.links[2], {
            'href': EXP_LINKS['v3.0']['wadl'],
            'type': 'application/vnd.sun.wadl+xml',
            'rel': 'describedby'})
