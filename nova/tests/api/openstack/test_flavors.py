# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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
import webob
import xml.dom.minidom as minidom

from nova.api.openstack import flavors
import nova.db.api
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes
from nova import wsgi


def stub_flavor(flavorid, name, memory_mb="256", local_gb="10"):
    return {
        "flavorid": str(flavorid),
        "name": name,
        "memory_mb": memory_mb,
        "local_gb": local_gb,
    }


def return_instance_type_by_flavor_id(context, flavorid):
    return stub_flavor(flavorid, "flavor %s" % (flavorid,))


def return_instance_types(context, num=2):
    instance_types = {}
    for i in xrange(1, num + 1):
        name = "flavor %s" % (i,)
        instance_types[name] = stub_flavor(i, name)
    return instance_types


def return_instance_type_not_found(context, flavor_id):
    raise exception.InstanceTypeNotFound(flavor_id=flavor_id)


class FlavorsTest(test.TestCase):
    def setUp(self):
        super(FlavorsTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(nova.db.api, "instance_type_get_all",
                       return_instance_types)
        self.stubs.Set(nova.db.api, "instance_type_get_by_flavor_id",
                       return_instance_type_by_flavor_id)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(FlavorsTest, self).tearDown()

    def test_get_flavor_list_v1_0(self):
        req = webob.Request.blank('/v1.0/flavors')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavors = json.loads(res.body)["flavors"]
        expected = [
            {
                "id": "1",
                "name": "flavor 1",
            },
            {
                "id": "2",
                "name": "flavor 2",
            },
        ]
        self.assertEqual(flavors, expected)

    def test_get_empty_flavor_list_v1_0(self):
        def _return_empty(self):
            return {}
        self.stubs.Set(nova.db.api, "instance_type_get_all",
                       _return_empty)

        req = webob.Request.blank('/v1.0/flavors')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavors = json.loads(res.body)["flavors"]
        expected = []
        self.assertEqual(flavors, expected)

    def test_get_flavor_list_detail_v1_0(self):
        req = webob.Request.blank('/v1.0/flavors/detail')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavors = json.loads(res.body)["flavors"]
        expected = [
            {
                "id": "1",
                "name": "flavor 1",
                "ram": "256",
                "disk": "10",
                "rxtx_cap": "",
                "rxtx_quota": "",
                "swap": "",
                "vcpus": "",
            },
            {
                "id": "2",
                "name": "flavor 2",
                "ram": "256",
                "disk": "10",
                "rxtx_cap": "",
                "rxtx_quota": "",
                "swap": "",
                "vcpus": "",
            },
        ]
        self.assertEqual(flavors, expected)

    def test_get_flavor_by_id_v1_0(self):
        req = webob.Request.blank('/v1.0/flavors/12')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavor = json.loads(res.body)["flavor"]
        expected = {
            "id": "12",
            "name": "flavor 12",
            "ram": "256",
            "disk": "10",
            "rxtx_cap": "",
            "rxtx_quota": "",
            "swap": "",
            "vcpus": "",
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_by_invalid_id(self):
        self.stubs.Set(nova.db.api, "instance_type_get_by_flavor_id",
                       return_instance_type_not_found)
        req = webob.Request.blank('/v1.0/flavors/asdf')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_get_flavor_by_id_v1_1(self):
        req = webob.Request.blank('/v1.1/fake/flavors/12')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavor = json.loads(res.body)
        expected = {
            "flavor": {
                "id": "12",
                "name": "flavor 12",
                "ram": "256",
                "disk": "10",
                "rxtx_cap": "",
                "rxtx_quota": "",
                "swap": "",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_v1_1(self):
        req = webob.Request.blank('/v1.1/fake/flavors')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavor = json.loads(res.body)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v1.1/fake/flavors/1",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/1",
                        },
                    ],
                },
                {
                    "id": "2",
                    "name": "flavor 2",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v1.1/fake/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/2",
                        },
                    ],
                },
            ],
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_detail_v1_1(self):
        req = webob.Request.blank('/v1.1/fake/flavors/detail')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavor = json.loads(res.body)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
                    "ram": "256",
                    "disk": "10",
                    "rxtx_cap": "",
                    "rxtx_quota": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v1.1/fake/flavors/1",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/1",
                        },
                    ],
                },
                {
                    "id": "2",
                    "name": "flavor 2",
                    "ram": "256",
                    "disk": "10",
                    "rxtx_cap": "",
                    "rxtx_quota": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v1.1/fake/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/2",
                        },
                    ],
                },
            ],
        }
        self.assertEqual(flavor, expected)

    def test_get_empty_flavor_list_v1_1(self):
        def _return_empty(self):
            return {}
        self.stubs.Set(nova.db.api, "instance_type_get_all", _return_empty)

        req = webob.Request.blank('/v1.1/fake/flavors')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavors = json.loads(res.body)["flavors"]
        expected = []
        self.assertEqual(flavors, expected)


class FlavorsXMLSerializationTest(test.TestCase):

    def test_show(self):
        serializer = flavors.FlavorXMLSerializer()

        input = {
            "flavor": {
                "id": "12",
                "name": "asdf",
                "ram": "256",
                "disk": "10",
                "rxtx_cap": "",
                "rxtx_quota": "",
                "swap": "",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }

        output = serializer.serialize(input, 'show')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
        <flavor xmlns="http://docs.openstack.org/compute/api/v1.1"
                xmlns:atom="http://www.w3.org/2005/Atom"
                id="12"
                name="asdf"
                ram="256"
                disk="10"
                rxtx_cap=""
                rxtx_quota=""
                swap=""
                vcpus="">
            <atom:link href="http://localhost/v1.1/fake/flavors/12"
                 rel="self"/>
            <atom:link href="http://localhost/fake/flavors/12"
                 rel="bookmark"/>
        </flavor>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_show_handles_integers(self):
        serializer = flavors.FlavorXMLSerializer()

        input = {
            "flavor": {
                "id": 12,
                "name": "asdf",
                "ram": 256,
                "disk": 10,
                "rxtx_cap": "",
                "rxtx_quota": "",
                "swap": "",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }

        output = serializer.serialize(input, 'show')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
        <flavor xmlns="http://docs.openstack.org/compute/api/v1.1"
                xmlns:atom="http://www.w3.org/2005/Atom"
                id="12"
                name="asdf"
                ram="256"
                disk="10"
                rxtx_cap=""
                rxtx_quota=""
                swap=""
                vcpus="">
            <atom:link href="http://localhost/v1.1/fake/flavors/12"
                 rel="self"/>
            <atom:link href="http://localhost/fake/flavors/12"
                 rel="bookmark"/>
        </flavor>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_detail(self):
        serializer = flavors.FlavorXMLSerializer()

        input = {
            "flavors": [
                {
                    "id": "23",
                    "name": "flavor 23",
                    "ram": "512",
                    "disk": "20",
                    "rxtx_cap": "",
                    "rxtx_quota": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v1.1/fake/flavors/23",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/23",
                        },
                    ],
                },
                {
                    "id": "13",
                    "name": "flavor 13",
                    "ram": "256",
                    "disk": "10",
                    "rxtx_cap": "",
                    "rxtx_quota": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v1.1/fake/flavors/13",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/13",
                        },
                    ],
                },
            ],
        }

        output = serializer.serialize(input, 'detail')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
        <flavors xmlns="http://docs.openstack.org/compute/api/v1.1"
                 xmlns:atom="http://www.w3.org/2005/Atom">
            <flavor id="23"
                    name="flavor 23"
                    ram="512"
                    disk="20"
                    rxtx_cap=""
                    rxtx_quota=""
                    swap=""
                    vcpus="">
                <atom:link href="http://localhost/v1.1/fake/flavors/23"
                     rel="self"/>
                <atom:link href="http://localhost/fake/flavors/23"
                     rel="bookmark"/>
            </flavor>
            <flavor id="13"
                    name="flavor 13"
                    ram="256"
                    disk="10"
                    rxtx_cap=""
                    rxtx_quota=""
                    swap=""
                    vcpus="">
                <atom:link href="http://localhost/v1.1/fake/flavors/13"
                     rel="self"/>
                <atom:link href="http://localhost/fake/flavors/13"
                     rel="bookmark"/>
            </flavor>
        </flavors>
        """.replace("  ", "") % locals())

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_index(self):
        serializer = flavors.FlavorXMLSerializer()

        input = {
            "flavors": [
                {
                    "id": "23",
                    "name": "flavor 23",
                    "ram": "512",
                    "disk": "20",
                    "rxtx_cap": "",
                    "rxtx_quota": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v1.1/fake/flavors/23",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/23",
                        },
                    ],
                },
                {
                    "id": "13",
                    "name": "flavor 13",
                    "ram": "256",
                    "disk": "10",
                    "rxtx_cap": "",
                    "rxtx_quota": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v1.1/fake/flavors/13",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/13",
                        },
                    ],
                },
            ],
        }

        output = serializer.serialize(input, 'index')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
        <flavors xmlns="http://docs.openstack.org/compute/api/v1.1"
                 xmlns:atom="http://www.w3.org/2005/Atom">
            <flavor id="23" name="flavor 23">
                <atom:link href="http://localhost/v1.1/fake/flavors/23"
                     rel="self"/>
                <atom:link href="http://localhost/fake/flavors/23"
                     rel="bookmark"/>
            </flavor>
            <flavor id="13" name="flavor 13">
                <atom:link href="http://localhost/v1.1/fake/flavors/13"
                     rel="self"/>
                <atom:link href="http://localhost/fake/flavors/13"
                     rel="bookmark"/>
            </flavor>
        </flavors>
        """.replace("  ", "") % locals())

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_index_empty(self):
        serializer = flavors.FlavorXMLSerializer()

        input = {
            "flavors": [],
        }

        output = serializer.serialize(input, 'index')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
        <flavors xmlns="http://docs.openstack.org/compute/api/v1.1"
                 xmlns:atom="http://www.w3.org/2005/Atom" />
        """.replace("  ", "") % locals())

        self.assertEqual(expected.toxml(), actual.toxml())
