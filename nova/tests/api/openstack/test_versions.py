# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

import feedparser
import json
import stubout
import webob
from lxml import etree

from nova import context
from nova import test
from nova.api.openstack import versions
from nova.api.openstack import views
from nova.api.openstack import wsgi
from nova.tests.api.openstack import common
from nova.tests.api.openstack import fakes

NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'ns': 'http://docs.openstack.org/compute/api/v1.1'
}
VERSIONS = {
    "v1.0": {
        "id": "v1.0",
        "status": "DEPRECATED",
        "updated": "2011-01-21T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "application/pdf",
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.0/cs-devguide-20110125.pdf",
            },
            {
                "rel": "describedby",
                "type": "application/vnd.sun.wadl+xml",
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.0/application.wadl",
            },
        ],
        "media-types": [
            {
                "base": "application/xml",
                "type": "application/vnd.openstack.compute-v1.0+xml",
            },
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute-v1.0+json",
            },
        ],
    },
    "v1.1": {
        "id": "v1.1",
        "status": "CURRENT",
        "updated": "2011-01-21T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "application/pdf",
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.1/cs-devguide-20110125.pdf",
            },
            {
                "rel": "describedby",
                "type": "application/vnd.sun.wadl+xml",
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.1/application.wadl",
            },
        ],
        "media-types": [
            {
                "base": "application/xml",
                "type": "application/vnd.openstack.compute-v1.1+xml",
            },
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute-v1.1+json",
            },
        ],
    },
}


class VersionsTest(test.TestCase):
    def setUp(self):
        super(VersionsTest, self).setUp()
        self.context = context.get_admin_context()
        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_auth(self.stubs)
        #Stub out VERSIONS
        self.old_versions = versions.VERSIONS
        versions.VERSIONS = VERSIONS

    def tearDown(self):
        versions.VERSIONS = self.old_versions
        super(VersionsTest, self).tearDown()

    def test_get_version_list(self):
        req = webob.Request.blank('/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        versions = json.loads(res.body)["versions"]
        expected = [
            {
                "id": "v1.0",
                "status": "DEPRECATED",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.0/",
                    }],
            },
            {
                "id": "v1.1",
                "status": "CURRENT",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/",
                    }],
            },
        ]
        self.assertEqual(versions, expected)

    def test_get_version_1_0_detail(self):
        req = webob.Request.blank('/v1.0/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = json.loads(res.body)
        expected = {
            "version": {
                "id": "v1.0",
                "status": "DEPRECATED",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.0/",
                    },
                    {
                        "rel": "describedby",
                        "type": "application/pdf",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.0/cs-devguide-20110125.pdf",
                    },
                    {
                        "rel": "describedby",
                        "type": "application/vnd.sun.wadl+xml",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.0/application.wadl",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": "application/"
                                "vnd.openstack.compute-v1.0+xml",
                    },
                    {
                        "base": "application/json",
                        "type": "application/"
                                "vnd.openstack.compute-v1.0+json",
                    },
                ],
            },
        }
        self.assertEqual(expected, version)

    def test_get_version_1_1_detail(self):
        req = webob.Request.blank('/v1.1/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        version = json.loads(res.body)
        expected = {
            "version": {
                "id": "v1.1",
                "status": "CURRENT",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/",
                    },
                    {
                        "rel": "describedby",
                        "type": "application/pdf",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.1/cs-devguide-20110125.pdf",
                    },
                    {
                        "rel": "describedby",
                        "type": "application/vnd.sun.wadl+xml",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.1/application.wadl",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": "application/"
                                "vnd.openstack.compute-v1.1+xml",
                    },
                    {
                        "base": "application/json",
                        "type": "application/"
                                "vnd.openstack.compute-v1.1+json",
                    },
                ],
            },
        }
        self.assertEqual(expected, version)

    def test_get_version_1_0_detail_xml(self):
        req = webob.Request.blank('/v1.0/')
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/xml")

        version = etree.XML(res.body)
        expected = VERSIONS['v1.0']
        self.assertTrue(version.xpath('/ns:version', namespaces=NS))
        media_types = version.xpath('ns:media-types/ns:media-type',
                                    namespaces=NS)
        self.assertTrue(common.compare_media_types(media_types,
                                             expected['media-types']))
        for key in ['id', 'status', 'updated']:
            self.assertEqual(version.get(key), expected[key])
        links = version.xpath('atom:link', namespaces=NS)
        self.assertTrue(common.compare_links(links,
            [{'rel': 'self', 'href': 'http://localhost/v1.0/'}]
            + expected['links']))

    def test_get_version_1_1_detail_xml(self):
        req = webob.Request.blank('/v1.1/')
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/xml")

        version = etree.XML(res.body)
        expected = VERSIONS['v1.1']
        self.assertTrue(version.xpath('/ns:version', namespaces=NS))
        media_types = version.xpath('ns:media-types/ns:media-type',
                                    namespaces=NS)
        self.assertTrue(common.compare_media_types(media_types,
                                             expected['media-types']))
        for key in ['id', 'status', 'updated']:
            self.assertEqual(version.get(key), expected[key])
        links = version.xpath('atom:link', namespaces=NS)
        self.assertTrue(common.compare_links(links,
            [{'rel': 'self', 'href': 'http://localhost/v1.1/'}]
            + expected['links']))

    def test_get_version_list_xml(self):
        req = webob.Request.blank('/')
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/xml")

        root = etree.XML(res.body)
        self.assertTrue(root.xpath('/ns:versions', namespaces=NS))
        versions = root.xpath('ns:version', namespaces=NS)
        self.assertEqual(len(versions), 2)

        for i, v in enumerate(['v1.0', 'v1.1']):
            version = versions[i]
            expected = VERSIONS[v]
            for key in ['id', 'status', 'updated']:
                self.assertEqual(version.get(key), expected[key])
            (link,) = version.xpath('atom:link', namespaces=NS)
            self.assertTrue(common.compare_links(link,
                [{'rel': 'self', 'href': 'http://localhost/%s/' % v}]))

    def test_get_version_1_0_detail_atom(self):
        req = webob.Request.blank('/v1.0/')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual("application/atom+xml", res.content_type)

        f = feedparser.parse(res.body)
        self.assertEqual(f.feed.title, 'About This Version')
        self.assertEqual(f.feed.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(f.feed.id, 'http://localhost/v1.0/')
        self.assertEqual(f.feed.author, 'Rackspace')
        self.assertEqual(f.feed.author_detail.href,
                         'http://www.rackspace.com/')
        self.assertEqual(f.feed.links[0]['href'], 'http://localhost/v1.0/')
        self.assertEqual(f.feed.links[0]['rel'], 'self')

        self.assertEqual(len(f.entries), 1)
        entry = f.entries[0]
        self.assertEqual(entry.id, 'http://localhost/v1.0/')
        self.assertEqual(entry.title, 'Version v1.0')
        self.assertEqual(entry.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(len(entry.content), 1)
        self.assertEqual(entry.content[0].value,
            'Version v1.0 DEPRECATED (2011-01-21T11:33:21Z)')
        self.assertEqual(len(entry.links), 3)
        self.assertEqual(entry.links[0]['href'], 'http://localhost/v1.0/')
        self.assertEqual(entry.links[0]['rel'], 'self')
        self.assertEqual(entry.links[1], {
            'href': 'http://docs.rackspacecloud.com/servers/api/v1.0/'\
                    'cs-devguide-20110125.pdf',
            'type': 'application/pdf',
            'rel': 'describedby'})
        self.assertEqual(entry.links[2], {
            'href': 'http://docs.rackspacecloud.com/servers/api/v1.0/'\
                    'application.wadl',
            'type': 'application/vnd.sun.wadl+xml',
            'rel': 'describedby'})

    def test_get_version_1_1_detail_atom(self):
        req = webob.Request.blank('/v1.1/')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual("application/atom+xml", res.content_type)

        f = feedparser.parse(res.body)
        self.assertEqual(f.feed.title, 'About This Version')
        self.assertEqual(f.feed.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(f.feed.id, 'http://localhost/v1.1/')
        self.assertEqual(f.feed.author, 'Rackspace')
        self.assertEqual(f.feed.author_detail.href,
                         'http://www.rackspace.com/')
        self.assertEqual(f.feed.links[0]['href'], 'http://localhost/v1.1/')
        self.assertEqual(f.feed.links[0]['rel'], 'self')

        self.assertEqual(len(f.entries), 1)
        entry = f.entries[0]
        self.assertEqual(entry.id, 'http://localhost/v1.1/')
        self.assertEqual(entry.title, 'Version v1.1')
        self.assertEqual(entry.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(len(entry.content), 1)
        self.assertEqual(entry.content[0].value,
            'Version v1.1 CURRENT (2011-01-21T11:33:21Z)')
        self.assertEqual(len(entry.links), 3)
        self.assertEqual(entry.links[0]['href'], 'http://localhost/v1.1/')
        self.assertEqual(entry.links[0]['rel'], 'self')
        self.assertEqual(entry.links[1], {
            'href': 'http://docs.rackspacecloud.com/servers/api/v1.1/'\
                    'cs-devguide-20110125.pdf',
            'type': 'application/pdf',
            'rel': 'describedby'})
        self.assertEqual(entry.links[2], {
            'href': 'http://docs.rackspacecloud.com/servers/api/v1.1/'\
                    'application.wadl',
            'type': 'application/vnd.sun.wadl+xml',
            'rel': 'describedby'})

    def test_get_version_list_atom(self):
        req = webob.Request.blank('/')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/atom+xml")

        f = feedparser.parse(res.body)
        self.assertEqual(f.feed.title, 'Available API Versions')
        self.assertEqual(f.feed.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(f.feed.id, 'http://localhost/')
        self.assertEqual(f.feed.author, 'Rackspace')
        self.assertEqual(f.feed.author_detail.href,
                         'http://www.rackspace.com/')
        self.assertEqual(f.feed.links[0]['href'], 'http://localhost/')
        self.assertEqual(f.feed.links[0]['rel'], 'self')

        self.assertEqual(len(f.entries), 2)
        entry = f.entries[0]
        self.assertEqual(entry.id, 'http://localhost/v1.0/')
        self.assertEqual(entry.title, 'Version v1.0')
        self.assertEqual(entry.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(len(entry.content), 1)
        self.assertEqual(entry.content[0].value,
            'Version v1.0 DEPRECATED (2011-01-21T11:33:21Z)')
        self.assertEqual(len(entry.links), 1)
        self.assertEqual(entry.links[0]['href'], 'http://localhost/v1.0/')
        self.assertEqual(entry.links[0]['rel'], 'self')
        entry = f.entries[1]
        self.assertEqual(entry.id, 'http://localhost/v1.1/')
        self.assertEqual(entry.title, 'Version v1.1')
        self.assertEqual(entry.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(len(entry.content), 1)
        self.assertEqual(entry.content[0].value,
            'Version v1.1 CURRENT (2011-01-21T11:33:21Z)')
        self.assertEqual(len(entry.links), 1)
        self.assertEqual(entry.links[0]['href'], 'http://localhost/v1.1/')
        self.assertEqual(entry.links[0]['rel'], 'self')

    def test_multi_choice_image(self):
        req = webob.Request.blank('/images/1')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 300)
        self.assertEqual(res.content_type, "application/json")

        expected = {
        "choices": [
            {
                "id": "v1.1",
                "status": "CURRENT",
                "links": [
                    {
                        "href": "http://localhost/v1.1/images/1",
                        "rel": "self",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": "application/vnd.openstack.compute-v1.1+xml"
                    },
                    {
                        "base": "application/json",
                        "type": "application/vnd.openstack.compute-v1.1+json"
                    },
                ],
            },
            {
                "id": "v1.0",
                "status": "DEPRECATED",
                "links": [
                    {
                        "href": "http://localhost/v1.0/images/1",
                        "rel": "self",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": "application/vnd.openstack.compute-v1.0+xml"
                    },
                    {
                        "base": "application/json",
                        "type": "application/vnd.openstack.compute-v1.0+json"
                    },
                ],
            },
        ], }

        self.assertDictMatch(expected, json.loads(res.body))

    def test_multi_choice_image_xml(self):
        req = webob.Request.blank('/images/1')
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 300)
        self.assertEqual(res.content_type, "application/xml")

        root = etree.XML(res.body)
        self.assertTrue(root.xpath('/ns:choices', namespaces=NS))
        versions = root.xpath('ns:version', namespaces=NS)
        self.assertEqual(len(versions), 2)

        version = versions[0]
        self.assertEqual(version.get('id'), 'v1.1')
        self.assertEqual(version.get('status'), 'CURRENT')
        media_types = version.xpath('ns:media-types/ns:media-type',
                                    namespaces=NS)
        self.assertTrue(common.compare_media_types(media_types,
                                             VERSIONS['v1.1']['media-types']))
        links = version.xpath('atom:link', namespaces=NS)
        self.assertTrue(common.compare_links(links,
            [{'rel': 'self', 'href': 'http://localhost/v1.1/images/1'}]))

        version = versions[1]
        self.assertEqual(version.get('id'), 'v1.0')
        self.assertEqual(version.get('status'), 'DEPRECATED')
        media_types = version.xpath('ns:media-types/ns:media-type',
                                    namespaces=NS)
        self.assertTrue(common.compare_media_types(media_types,
                                             VERSIONS['v1.0']['media-types']))
        links = version.xpath('atom:link', namespaces=NS)
        self.assertTrue(common.compare_links(links,
            [{'rel': 'self', 'href': 'http://localhost/v1.0/images/1'}]))

    def test_multi_choice_server_atom(self):
        """
        Make sure multi choice responses do not have content-type
        application/atom+xml (should use default of json)
        """
        req = webob.Request.blank('/servers/2')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 300)
        self.assertEqual(res.content_type, "application/json")

    def test_multi_choice_server(self):
        req = webob.Request.blank('/servers/2')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 300)
        self.assertEqual(res.content_type, "application/json")

        expected = {
        "choices": [
            {
                "id": "v1.1",
                "status": "CURRENT",
                "links": [
                    {
                        "href": "http://localhost/v1.1/servers/2",
                        "rel": "self",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": "application/vnd.openstack.compute-v1.1+xml"
                    },
                    {
                        "base": "application/json",
                        "type": "application/vnd.openstack.compute-v1.1+json"
                    },
                ],
            },
            {
                "id": "v1.0",
                "status": "DEPRECATED",
                "links": [
                    {
                        "href": "http://localhost/v1.0/servers/2",
                        "rel": "self",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": "application/vnd.openstack.compute-v1.0+xml"
                    },
                    {
                        "base": "application/json",
                        "type": "application/vnd.openstack.compute-v1.0+json"
                    },
                ],
            },
        ], }

        self.assertDictMatch(expected, json.loads(res.body))


class VersionsViewBuilderTests(test.TestCase):
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
                            "href": "http://example.org/3.2.1/",
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
        version_number = "v1.4.6"

        expected = "http://example.org/app/v1.4.6/"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href(version_number)

        self.assertEqual(actual, expected)


class VersionsSerializerTests(test.TestCase):
    def test_versions_list_xml_serializer(self):
        versions_data = {
            'versions': [
                {
                    "id": "2.7.1",
                    "updated": "2011-07-18T11:30:00Z",
                    "status": "DEPRECATED",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://test/2.7.1",
                        },
                    ],
                },
            ]
        }

        serializer = versions.VersionsXMLSerializer()
        response = serializer.index(versions_data)

        root = etree.XML(response)
        self.assertTrue(root.xpath('/ns:versions', namespaces=NS))
        version_elems = root.xpath('ns:version', namespaces=NS)
        self.assertEqual(len(version_elems), 1)
        version = version_elems[0]
        self.assertEqual(version.get('id'), versions_data['versions'][0]['id'])
        self.assertEqual(version.get('status'),
                         versions_data['versions'][0]['status'])

        (link,) = version.xpath('atom:link', namespaces=NS)
        self.assertTrue(common.compare_links(link, [{
            'rel': 'self',
            'href': 'http://test/2.7.1',
            'type': 'application/atom+xml'}]))

    def test_versions_multi_xml_serializer(self):
        versions_data = {
            'choices': [
                {
                    "id": "2.7.1",
                    "updated": "2011-07-18T11:30:00Z",
                    "status": "DEPRECATED",
                    "media-types": VERSIONS['v1.1']['media-types'],
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://test/2.7.1/images",
                        },
                    ],
                },
            ]
        }

        serializer = versions.VersionsXMLSerializer()
        response = serializer.multi(versions_data)

        root = etree.XML(response)
        self.assertTrue(root.xpath('/ns:choices', namespaces=NS))
        (version,) = root.xpath('ns:version', namespaces=NS)
        self.assertEqual(version.get('id'), versions_data['choices'][0]['id'])
        self.assertEqual(version.get('status'),
                         versions_data['choices'][0]['status'])

        media_types = list(version)[0]
        media_type_nodes = list(media_types)
        self.assertEqual(media_types.tag.split('}')[1], "media-types")

        media_types = version.xpath('ns:media-types/ns:media-type',
                                    namespaces=NS)
        self.assertTrue(common.compare_media_types(media_types,
            versions_data['choices'][0]['media-types']))

        (link,) = version.xpath('atom:link', namespaces=NS)
        self.assertTrue(common.compare_links(link,
                                       versions_data['choices'][0]['links']))

    def test_version_detail_xml_serializer(self):
        version_data = {
            "version": {
                "id": "v1.0",
                "status": "CURRENT",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.0/",
                    },
                    {
                        "rel": "describedby",
                        "type": "application/pdf",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.0/cs-devguide-20110125.pdf",
                    },
                    {
                        "rel": "describedby",
                        "type": "application/vnd.sun.wadl+xml",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.0/application.wadl",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": "application/vnd.openstack.compute-v1.0+xml",
                    },
                    {
                        "base": "application/json",
                        "type": "application/vnd.openstack.compute-v1.0+json",
                    },
                ],
            },
        }

        serializer = versions.VersionsXMLSerializer()
        response = serializer.show(version_data)

        root = etree.XML(response)
        self.assertEqual(root.tag.split('}')[1], "version")
        self.assertEqual(root.tag.split('}')[0].strip('{'), wsgi.XMLNS_V11)

        children = list(root)
        media_types = children[0]
        media_type_nodes = list(media_types)
        links = (children[1], children[2], children[3])

        self.assertEqual(media_types.tag.split('}')[1], 'media-types')
        for i, media_node in enumerate(media_type_nodes):
            self.assertEqual(media_node.tag.split('}')[1], 'media-type')
            for key, val in version_data['version']['media-types'][i].items():
                self.assertEqual(val, media_node.get(key))

        for i, link in enumerate(links):
            self.assertEqual(link.tag.split('}')[0].strip('{'),
                             'http://www.w3.org/2005/Atom')
            self.assertEqual(link.tag.split('}')[1], 'link')
            for key, val in version_data['version']['links'][i].items():
                self.assertEqual(val, link.get(key))

    def test_versions_list_atom_serializer(self):
        versions_data = {
            'versions': [
                {
                    "id": "2.9.8",
                    "updated": "2011-07-20T11:40:00Z",
                    "status": "CURRENT",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://test/2.9.8",
                        },
                    ],
                },
            ]
        }

        serializer = versions.VersionsAtomSerializer()
        response = serializer.index(versions_data)
        f = feedparser.parse(response)

        self.assertEqual(f.feed.title, 'Available API Versions')
        self.assertEqual(f.feed.updated, '2011-07-20T11:40:00Z')
        self.assertEqual(f.feed.id, 'http://test/')
        self.assertEqual(f.feed.author, 'Rackspace')
        self.assertEqual(f.feed.author_detail.href,
                         'http://www.rackspace.com/')
        self.assertEqual(f.feed.links[0]['href'], 'http://test/')
        self.assertEqual(f.feed.links[0]['rel'], 'self')

        self.assertEqual(len(f.entries), 1)
        entry = f.entries[0]
        self.assertEqual(entry.id, 'http://test/2.9.8')
        self.assertEqual(entry.title, 'Version 2.9.8')
        self.assertEqual(entry.updated, '2011-07-20T11:40:00Z')
        self.assertEqual(len(entry.content), 1)
        self.assertEqual(entry.content[0].value,
            'Version 2.9.8 CURRENT (2011-07-20T11:40:00Z)')
        self.assertEqual(len(entry.links), 1)
        self.assertEqual(entry.links[0]['href'], 'http://test/2.9.8')
        self.assertEqual(entry.links[0]['rel'], 'self')

    def test_version_detail_atom_serializer(self):
        versions_data = {
            "version": {
                "id": "v1.1",
                "status": "CURRENT",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/",
                    },
                    {
                        "rel": "describedby",
                        "type": "application/pdf",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.1/cs-devguide-20110125.pdf",
                    },
                    {
                        "rel": "describedby",
                        "type": "application/vnd.sun.wadl+xml",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.1/application.wadl",
                    },
                ],
                "media-types": [
                    {
                        "base": "application/xml",
                        "type": "application/vnd.openstack.compute-v1.1+xml",
                    },
                    {
                        "base": "application/json",
                        "type": "application/vnd.openstack.compute-v1.1+json",
                    }
                ],
            },
        }

        serializer = versions.VersionsAtomSerializer()
        response = serializer.show(versions_data)
        f = feedparser.parse(response)

        self.assertEqual(f.feed.title, 'About This Version')
        self.assertEqual(f.feed.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(f.feed.id, 'http://localhost/v1.1/')
        self.assertEqual(f.feed.author, 'Rackspace')
        self.assertEqual(f.feed.author_detail.href,
                         'http://www.rackspace.com/')
        self.assertEqual(f.feed.links[0]['href'], 'http://localhost/v1.1/')
        self.assertEqual(f.feed.links[0]['rel'], 'self')

        self.assertEqual(len(f.entries), 1)
        entry = f.entries[0]
        self.assertEqual(entry.id, 'http://localhost/v1.1/')
        self.assertEqual(entry.title, 'Version v1.1')
        self.assertEqual(entry.updated, '2011-01-21T11:33:21Z')
        self.assertEqual(len(entry.content), 1)
        self.assertEqual(entry.content[0].value,
             'Version v1.1 CURRENT (2011-01-21T11:33:21Z)')
        self.assertEqual(len(entry.links), 3)
        self.assertEqual(entry.links[0]['href'], 'http://localhost/v1.1/')
        self.assertEqual(entry.links[0]['rel'], 'self')
        self.assertEqual(entry.links[1], {
            'rel': 'describedby',
            'type': 'application/pdf',
            'href': 'http://docs.rackspacecloud.com/'
                    'servers/api/v1.1/cs-devguide-20110125.pdf'})
        self.assertEqual(entry.links[2], {
            'rel': 'describedby',
            'type': 'application/vnd.sun.wadl+xml',
            'href': 'http://docs.rackspacecloud.com/'
                    'servers/api/v1.1/application.wadl',
        })
