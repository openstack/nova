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

import json
import stubout
import webob
import xml.etree.ElementTree


from nova import context
from nova import test
from nova.tests.api.openstack import fakes
from nova.api.openstack import versions
from nova.api.openstack import views
from nova.api.openstack import wsgi

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
                "id": "v1.1",
                "status": "CURRENT",
                "updated": "2011-01-21T11:33:21Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/",
                    }],
            },
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
        root = xml.etree.ElementTree.XML(res.body)
        self.assertEqual(root.tag.split('}')[1], "version")
        self.assertEqual(root.tag.split('}')[0].strip('{'), wsgi.XMLNS_V11)

        children = list(root)
        media_types = children[0]
        media_type_nodes = list(media_types)
        links = (children[1], children[2], children[3])

        self.assertEqual(media_types.tag.split('}')[1], 'media-types')
        for media_node in media_type_nodes:
            self.assertEqual(media_node.tag.split('}')[1], 'media-type')

        expected = """
        <version id="v1.0" status="DEPRECATED"
             updated="2011-01-21T11:33:21Z"
             xmlns="%s"
             xmlns:atom="http://www.w3.org/2005/Atom">

            <media-types>
                <media-type base="application/xml"
                     type="application/vnd.openstack.compute-v1.0+xml"/>
                <media-type base="application/json"
                     type="application/vnd.openstack.compute-v1.0+json"/>
            </media-types>

            <atom:link href="http://localhost/v1.0/"
                 rel="self"/>

            <atom:link href="http://docs.rackspacecloud.com/servers/
                api/v1.0/cs-devguide-20110125.pdf"
                 rel="describedby"
                 type="application/pdf"/>

            <atom:link href="http://docs.rackspacecloud.com/servers/
                api/v1.0/application.wadl"
                 rel="describedby"
                 type="application/vnd.sun.wadl+xml"/>
        </version>""".replace("  ", "").replace("\n", "") % wsgi.XMLNS_V11

        actual = res.body.replace("  ", "").replace("\n", "")
        self.assertEqual(expected, actual)

    def test_get_version_1_1_detail_xml(self):
        req = webob.Request.blank('/v1.1/')
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/xml")
        expected = """
        <version id="v1.1" status="CURRENT"
             updated="2011-01-21T11:33:21Z"
             xmlns="%s"
             xmlns:atom="http://www.w3.org/2005/Atom">

            <media-types>
                <media-type base="application/xml"
                     type="application/vnd.openstack.compute-v1.1+xml"/>
                <media-type base="application/json"
                     type="application/vnd.openstack.compute-v1.1+json"/>
            </media-types>

            <atom:link href="http://localhost/v1.1/"
                 rel="self"/>

            <atom:link href="http://docs.rackspacecloud.com/servers/
                api/v1.1/cs-devguide-20110125.pdf"
                 rel="describedby"
                 type="application/pdf"/>

            <atom:link href="http://docs.rackspacecloud.com/servers/
                api/v1.1/application.wadl"
                 rel="describedby"
                 type="application/vnd.sun.wadl+xml"/>
        </version>""".replace("  ", "").replace("\n", "") % wsgi.XMLNS_V11

        actual = res.body.replace("  ", "").replace("\n", "")
        self.assertEqual(expected, actual)

    def test_get_version_list_xml(self):
        req = webob.Request.blank('/')
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/xml")

        expected = """
        <versions xmlns="%s" xmlns:atom="%s">
            <version id="v1.1" status="CURRENT" updated="2011-01-21T11:33:21Z">
                <atom:link href="http://localhost/v1.1/" rel="self"/>
            </version>
            <version id="v1.0" status="DEPRECATED"
                 updated="2011-01-21T11:33:21Z">
                <atom:link href="http://localhost/v1.0/" rel="self"/>
            </version>
        </versions>""".replace("  ", "").replace("\n", "") % (wsgi.XMLNS_V11,
                                                              wsgi.XMLNS_ATOM)

        actual = res.body.replace("  ", "").replace("\n", "")

        self.assertEqual(expected, actual)

    def test_get_version_1_0_detail_atom(self):
        req = webob.Request.blank('/v1.0/')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual("application/atom+xml", res.content_type)
        expected = """
        <feed xmlns="http://www.w3.org/2005/Atom">
            <title type="text">About This Version</title>
            <updated>2011-01-21T11:33:21Z</updated>
            <id>http://localhost/v1.0/</id>
            <author>
                <name>Rackspace</name>
                <uri>http://www.rackspace.com/</uri>
            </author>
            <link href="http://localhost/v1.0/" rel="self"/>
            <entry>
                <id>http://localhost/v1.0/</id>
                <title type="text">Version v1.0</title>
                <updated>2011-01-21T11:33:21Z</updated>
                <link href="http://localhost/v1.0/"
                     rel="self"/>
                <link href="http://docs.rackspacecloud.com/servers/
                    api/v1.0/cs-devguide-20110125.pdf"
                     rel="describedby" type="application/pdf"/>
                <link href="http://docs.rackspacecloud.com/servers/
                    api/v1.0/application.wadl"
                     rel="describedby" type="application/vnd.sun.wadl+xml"/>
                <content type="text">
                    Version v1.0 DEPRECATED (2011-01-21T11:33:21Z)
                </content>
            </entry>
        </feed>""".replace("  ", "").replace("\n", "")

        actual = res.body.replace("  ", "").replace("\n", "")
        self.assertEqual(expected, actual)

    def test_get_version_1_1_detail_atom(self):
        req = webob.Request.blank('/v1.1/')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual("application/atom+xml", res.content_type)
        expected = """
        <feed xmlns="http://www.w3.org/2005/Atom">
            <title type="text">About This Version</title>
            <updated>2011-01-21T11:33:21Z</updated>
            <id>http://localhost/v1.1/</id>
            <author>
                <name>Rackspace</name>
                <uri>http://www.rackspace.com/</uri>
            </author>
            <link href="http://localhost/v1.1/" rel="self"/>
            <entry>
                <id>http://localhost/v1.1/</id>
                <title type="text">Version v1.1</title>
                <updated>2011-01-21T11:33:21Z</updated>
                <link href="http://localhost/v1.1/"
                     rel="self"/>
                <link href="http://docs.rackspacecloud.com/servers/
                    api/v1.1/cs-devguide-20110125.pdf"
                     rel="describedby" type="application/pdf"/>
                <link href="http://docs.rackspacecloud.com/servers/
                    api/v1.1/application.wadl"
                     rel="describedby" type="application/vnd.sun.wadl+xml"/>
                <content type="text">
                    Version v1.1 CURRENT (2011-01-21T11:33:21Z)
                </content>
            </entry>
        </feed>""".replace("  ", "").replace("\n", "")

        actual = res.body.replace("  ", "").replace("\n", "")
        self.assertEqual(expected, actual)

    def test_get_version_list_atom(self):
        req = webob.Request.blank('/')
        req.accept = "application/atom+xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/atom+xml")

        expected = """
        <feed xmlns="http://www.w3.org/2005/Atom">
            <title type="text">Available API Versions</title>
            <updated>2011-01-21T11:33:21Z</updated>
            <id>http://localhost/</id>
            <author>
                <name>Rackspace</name>
                <uri>http://www.rackspace.com/</uri>
            </author>
            <link href="http://localhost/" rel="self"/>
            <entry>
                <id>http://localhost/v1.1/</id>
                <title type="text">Version v1.1</title>
                <updated>2011-01-21T11:33:21Z</updated>
                <link href="http://localhost/v1.1/" rel="self"/>
                <content type="text">
                    Version v1.1 CURRENT (2011-01-21T11:33:21Z)
                </content>
            </entry>
            <entry>
                <id>http://localhost/v1.0/</id>
                <title type="text">Version v1.0</title>
                <updated>2011-01-21T11:33:21Z</updated>
                <link href="http://localhost/v1.0/" rel="self"/>
                <content type="text">
                    Version v1.0 DEPRECATED (2011-01-21T11:33:21Z)
                </content>
            </entry>
        </feed>
        """.replace("  ", "").replace("\n", "")

        actual = res.body.replace("  ", "").replace("\n", "")

        self.assertEqual(expected, actual)

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

        expected = """
        <choices xmlns="%s" xmlns:atom="%s">
          <version id="v1.1" status="CURRENT">
            <media-types>
              <media-type base="application/xml"
                 type="application/vnd.openstack.compute-v1.1+xml"/>
              <media-type base="application/json"
                 type="application/vnd.openstack.compute-v1.1+json"/>
            </media-types>
            <atom:link href="http://localhost/v1.1/images/1" rel="self"/>
          </version>
          <version id="v1.0" status="DEPRECATED">
            <media-types>
              <media-type base="application/xml"
                 type="application/vnd.openstack.compute-v1.0+xml"/>
              <media-type base="application/json"
                 type="application/vnd.openstack.compute-v1.0+json"/>
            </media-types>
            <atom:link href="http://localhost/v1.0/images/1" rel="self"/>
          </version>
        </choices>""".replace("  ", "").replace("\n", "") % (wsgi.XMLNS_V11,
                                                            wsgi.XMLNS_ATOM)

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

        root = xml.etree.ElementTree.XML(response)
        self.assertEqual(root.tag.split('}')[1], "versions")
        self.assertEqual(root.tag.split('}')[0].strip('{'), wsgi.XMLNS_V11)
        version = list(root)[0]
        self.assertEqual(version.tag.split('}')[1], "version")
        self.assertEqual(version.get('id'),
                         versions_data['versions'][0]['id'])
        self.assertEqual(version.get('status'),
                         versions_data['versions'][0]['status'])

        link = list(version)[0]

        self.assertEqual(link.tag.split('}')[1], "link")
        self.assertEqual(link.tag.split('}')[0].strip('{'), wsgi.XMLNS_ATOM)
        for key, val in versions_data['versions'][0]['links'][0].items():
            self.assertEqual(link.get(key), val)

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

        root = xml.etree.ElementTree.XML(response)
        self.assertEqual(root.tag.split('}')[1], "choices")
        self.assertEqual(root.tag.split('}')[0].strip('{'), wsgi.XMLNS_V11)
        version = list(root)[0]
        self.assertEqual(version.tag.split('}')[1], "version")
        self.assertEqual(version.get('id'), versions_data['choices'][0]['id'])
        self.assertEqual(version.get('status'),
                         versions_data['choices'][0]['status'])

        media_types = list(version)[0]
        media_type_nodes = list(media_types)
        self.assertEqual(media_types.tag.split('}')[1], "media-types")

        set_types = versions_data['choices'][0]['media-types']
        for i, type in enumerate(set_types):
            node = media_type_nodes[i]
            self.assertEqual(node.tag.split('}')[1], "media-type")
            for key, val in set_types[i].items():
                self.assertEqual(node.get(key), val)

        link = list(version)[1]

        self.assertEqual(link.tag.split('}')[1], "link")
        self.assertEqual(link.tag.split('}')[0].strip('{'), wsgi.XMLNS_ATOM)
        for key, val in versions_data['choices'][0]['links'][0].items():
            self.assertEqual(link.get(key), val)

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

        root = xml.etree.ElementTree.XML(response)
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

        root = xml.etree.ElementTree.XML(response)
        self.assertEqual(root.tag.split('}')[1], "feed")
        self.assertEqual(root.tag.split('}')[0].strip('{'),
                         "http://www.w3.org/2005/Atom")

        children = list(root)
        title = children[0]
        updated = children[1]
        id = children[2]
        author = children[3]
        link = children[4]
        entry = children[5]

        self.assertEqual(title.tag.split('}')[1], 'title')
        self.assertEqual(title.text, 'Available API Versions')
        self.assertEqual(updated.tag.split('}')[1], 'updated')
        self.assertEqual(updated.text, '2011-07-20T11:40:00Z')
        self.assertEqual(id.tag.split('}')[1], 'id')
        self.assertEqual(id.text, 'http://test/')

        self.assertEqual(author.tag.split('}')[1], 'author')
        author_name = list(author)[0]
        author_uri = list(author)[1]
        self.assertEqual(author_name.tag.split('}')[1], 'name')
        self.assertEqual(author_name.text, 'Rackspace')
        self.assertEqual(author_uri.tag.split('}')[1], 'uri')
        self.assertEqual(author_uri.text, 'http://www.rackspace.com/')

        self.assertEqual(link.get('href'), 'http://test/')
        self.assertEqual(link.get('rel'), 'self')

        self.assertEqual(entry.tag.split('}')[1], 'entry')
        entry_children = list(entry)
        entry_id = entry_children[0]
        entry_title = entry_children[1]
        entry_updated = entry_children[2]
        entry_link = entry_children[3]
        entry_content = entry_children[4]
        self.assertEqual(entry_id.tag.split('}')[1], "id")
        self.assertEqual(entry_id.text, "http://test/2.9.8")
        self.assertEqual(entry_title.tag.split('}')[1], "title")
        self.assertEqual(entry_title.get('type'), "text")
        self.assertEqual(entry_title.text, "Version 2.9.8")
        self.assertEqual(entry_updated.tag.split('}')[1], "updated")
        self.assertEqual(entry_updated.text, "2011-07-20T11:40:00Z")
        self.assertEqual(entry_link.tag.split('}')[1], "link")
        self.assertEqual(entry_link.get('href'), "http://test/2.9.8")
        self.assertEqual(entry_link.get('rel'), "self")
        self.assertEqual(entry_content.tag.split('}')[1], "content")
        self.assertEqual(entry_content.get('type'), "text")
        self.assertEqual(entry_content.text,
                         "Version 2.9.8 CURRENT (2011-07-20T11:40:00Z)")

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

        root = xml.etree.ElementTree.XML(response)
        self.assertEqual(root.tag.split('}')[1], "feed")
        self.assertEqual(root.tag.split('}')[0].strip('{'),
                         "http://www.w3.org/2005/Atom")

        children = list(root)
        title = children[0]
        updated = children[1]
        id = children[2]
        author = children[3]
        link = children[4]
        entry = children[5]

        self.assertEqual(root.tag.split('}')[1], 'feed')
        self.assertEqual(title.tag.split('}')[1], 'title')
        self.assertEqual(title.text, 'About This Version')
        self.assertEqual(updated.tag.split('}')[1], 'updated')
        self.assertEqual(updated.text, '2011-01-21T11:33:21Z')
        self.assertEqual(id.tag.split('}')[1], 'id')
        self.assertEqual(id.text, 'http://localhost/v1.1/')

        self.assertEqual(author.tag.split('}')[1], 'author')
        author_name = list(author)[0]
        author_uri = list(author)[1]
        self.assertEqual(author_name.tag.split('}')[1], 'name')
        self.assertEqual(author_name.text, 'Rackspace')
        self.assertEqual(author_uri.tag.split('}')[1], 'uri')
        self.assertEqual(author_uri.text, 'http://www.rackspace.com/')

        self.assertEqual(link.get('href'),
                         'http://localhost/v1.1/')
        self.assertEqual(link.get('rel'), 'self')

        self.assertEqual(entry.tag.split('}')[1], 'entry')
        entry_children = list(entry)
        entry_id = entry_children[0]
        entry_title = entry_children[1]
        entry_updated = entry_children[2]
        entry_links = (entry_children[3], entry_children[4], entry_children[5])
        entry_content = entry_children[6]

        self.assertEqual(entry_id.tag.split('}')[1], "id")
        self.assertEqual(entry_id.text,
                         "http://localhost/v1.1/")
        self.assertEqual(entry_title.tag.split('}')[1], "title")
        self.assertEqual(entry_title.get('type'), "text")
        self.assertEqual(entry_title.text, "Version v1.1")
        self.assertEqual(entry_updated.tag.split('}')[1], "updated")
        self.assertEqual(entry_updated.text, "2011-01-21T11:33:21Z")

        for i, link in enumerate(versions_data["version"]["links"]):
            self.assertEqual(entry_links[i].tag.split('}')[1], "link")
            for key, val in versions_data["version"]["links"][i].items():
                self.assertEqual(entry_links[i].get(key), val)

        self.assertEqual(entry_content.tag.split('}')[1], "content")
        self.assertEqual(entry_content.get('type'), "text")
        self.assertEqual(entry_content.text,
                         "Version v1.1 CURRENT (2011-01-21T11:33:21Z)")
