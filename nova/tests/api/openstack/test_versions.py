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

from nova import context
from nova import test
from nova.tests.api.openstack import fakes
from nova.api.openstack import versions
from nova.api.openstack import views


class VersionsTest(test.TestCase):
    def setUp(self):
        super(VersionsTest, self).setUp()
        self.context = context.get_admin_context()
        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_auth(self.stubs)


    def tearDown(self):
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
                "updated": "2011-07-18T11:30:00Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/",
                    }],
            },
            {
                "id": "v1.0",
                "status": "DEPRECATED",
                "updated": "2010-10-09T11:30:00Z",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.0/",
                    }],
            },
        ]
        self.assertEqual(versions, expected)

    def test_get_version_1_1_detail(self):
        req = webob.Request.blank('/v1.1/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        print res.body
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        versions = json.loads(res.body)["versions"]
        expected = [
            {
                "version" : {
                    "id" : "v1.1",
                    "status" : "CURRENT",
                    "updated" : "2011-01-21T11:33:21-06:00",
                    "links": [
                        {
                            "rel" : "self",
                            "href" : "http://servers.api.openstack.org/v1.0/"
                        },
                        {
                            "rel" : "describedby",
                            "type" : "application/pdf",
                            "href" : "http://docs.rackspacecloud.com/"
                                "servers/api/v1.1/cs-devguide-20110125.pdf"
                        },
                        {
                            "rel" : "describedby",
                            "type" : "application/vnd.sun.wadl+xml",
                            "href" : "http://docs.rackspacecloud.com/"
                                "servers/api/v1.1/application.wadl"
                        }
                    ],
                    "media-types": [
                        {
                            "base" : "application/xml",
                            "type" : "application/"
                                "vnd.openstack.compute-v1.1+xml"
                        },
                        {
                            "base" : "application/json",
                            "type" : "application/"
                                "vnd.openstack.compute-v1.1+json"
                        }
                    ]
                }
            }
        ]
        self.assertEqual(versions, expected)

    def test_get_version_list_xml(self):
        req = webob.Request.blank('/')
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/xml")

        expected = """<versions>
            <version id="v1.1" status="CURRENT" updated="2011-07-18T11:30:00Z">
                <atom:link href="http://localhost/v1.1/" rel="self"/>
            </version>
            <version id="v1.0" status="DEPRECATED"
                 updated="2010-10-09T11:30:00Z">
                <atom:link href="http://localhost/v1.0/" rel="self"/>
            </version>
        </versions>""".replace("  ", "").replace("\n", "")

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
            <updated>2011-07-18T11:30:00Z</updated>
            <id>http://localhost/</id>
            <author>
                <name>Rackspace</name>
                <uri>http://www.rackspace.com/</uri>
            </author>
            <link href="http://localhost/" rel="self"/>
            <entry>
                <id>http://localhost/v1.1/</id>
                <title type="text">Version v1.1</title>
                <updated>2011-07-18T11:30:00Z</updated>
                <link href="http://localhost/v1.1/" rel="self"/>
                <content type="text">
                    Version v1.1 CURRENT (2011-07-18T11:30:00Z)
                </content>
            </entry>
            <entry>
                <id>http://localhost/v1.0/</id>
                <title type="text">Version v1.0</title>
                <updated>2010-10-09T11:30:00Z</updated>
                <link href="http://localhost/v1.0/" rel="self"/>
                <content type="text">
                    Version v1.0 DEPRECATED (2010-10-09T11:30:00Z)
                </content>
            </entry>
        </feed>
        """.replace("  ", "").replace("\n", "")

        actual = res.body.replace("  ", "").replace("\n", "")

        self.assertEqual(expected, actual)

    def test_view_builder(self):
        base_url = "http://example.org/"

        version_data = {
            "id": "3.2.1",
            "status": "CURRENT",
            "updated": "2011-07-18T11:30:00Z"}

        expected = {
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

        builder = views.versions.ViewBuilder(base_url)
        output = builder.build(version_data)

        self.assertEqual(output, expected)

    def test_generate_href(self):
        base_url = "http://example.org/app/"
        version_number = "v1.4.6"

        expected = "http://example.org/app/v1.4.6/"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href(version_number)

        self.assertEqual(actual, expected)

    def test_xml_serializer(self):
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
                        }
                    ],
                },
            ]
        }

        expected = """
            <versions>
                <version id="2.7.1" status="DEPRECATED"
                 updated="2011-07-18T11:30:00Z">
                    <atom:link href="http://test/2.7.1" rel="self"/>
                </version>
            </versions>""".replace("  ", "").replace("\n", "")

        serializer = versions.VersionsXMLSerializer()
        response = serializer.default(versions_data)
        response = response.replace("  ", "").replace("\n", "")
        self.assertEqual(expected, response)

    def test_atom_serializer(self):
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
                        }
                    ],
                },
            ]
        }

        expected = """
            <feed xmlns="http://www.w3.org/2005/Atom">
                <title type="text">
                    Available API Versions
                </title>
                <updated>
                    2011-07-20T11:40:00Z
                </updated>
                <id>
                    http://test/
                </id>
                <author>
                    <name>
                        Rackspace
                    </name>
                    <uri>
                        http://www.rackspace.com/
                    </uri>
                </author>
                <link href="http://test/" rel="self"/>
                <entry>
                    <id>
                        http://test/2.9.8
                    </id>
                    <title type="text">
                        Version 2.9.8
                    </title>
                    <updated>
                        2011-07-20T11:40:00Z
                    </updated>
                    <link href="http://test/2.9.8" rel="self"/>
                    <content type="text">
                        Version 2.9.8 CURRENT (2011-07-20T11:40:00Z)
                    </content>
                </entry>
            </feed>""".replace("  ", "").replace("\n", "")

        serializer = versions.VersionsAtomSerializer()
        response = serializer.default(versions_data)
        print response
        response = response.replace("  ", "").replace("\n", "")
        self.assertEqual(expected, response)
