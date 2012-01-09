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

from lxml import etree
import webob

from nova.api.openstack.v2 import flavors
from nova.api.openstack import xmlutil
import nova.compute.instance_types
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes


NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


FAKE_FLAVORS = {
    'flavor 1': {
        "flavorid": '1',
        "name": 'flavor 1',
        "memory_mb": '256',
        "local_gb": '10'
    },
    'flavor 2': {
        "flavorid": '2',
        "name": 'flavor 2',
        "memory_mb": '512',
        "local_gb": '20'
    },
}


def fake_instance_type_get_by_flavor_id(flavorid):
    return FAKE_FLAVORS['flavor %s' % flavorid]


def fake_instance_type_get_all(inactive=False, filters=None):
    def reject_min(db_attr, filter_attr):
        return filter_attr in filters and\
               int(flavor[db_attr]) < int(filters[filter_attr])

    filters = filters or {}
    output = {}
    for (flavor_name, flavor) in FAKE_FLAVORS.items():
        if reject_min('memory_mb', 'min_memory_mb'):
            continue
        elif reject_min('local_gb', 'min_local_gb'):
            continue

        output[flavor_name] = flavor

    return output


def empty_instance_type_get_all(inactive=False, filters=None):
    return {}


def return_instance_type_not_found(flavor_id):
    raise exception.InstanceTypeNotFound(flavor_id=flavor_id)


class FlavorsTest(test.TestCase):
    def setUp(self):
        super(FlavorsTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(nova.compute.instance_types, "get_all_types",
                       fake_instance_type_get_all)
        self.stubs.Set(nova.compute.instance_types,
                       "get_instance_type_by_flavor_id",
                       fake_instance_type_get_by_flavor_id)

        self.controller = flavors.Controller()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(FlavorsTest, self).tearDown()

    def test_get_flavor_by_invalid_id(self):
        self.stubs.Set(nova.compute.instance_types,
                       "get_instance_type_by_flavor_id",
                       return_instance_type_not_found)
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/asdf')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'asdf')

    def test_get_flavor_by_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1')
        flavor = self.controller.show(req, '1')
        expected = {
            "flavor": {
                "id": "1",
                "name": "flavor 1",
                "ram": "256",
                "disk": "10",
                "rxtx_factor": "",
                "swap": "",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/1",
                    },
                ],
            },
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_list(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
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
                        },
                    ],
                },
                {
                    "id": "2",
                    "name": "flavor 2",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
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

    def test_get_flavor_list_detail(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/detail')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
                    "ram": "256",
                    "disk": "10",
                    "rxtx_factor": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/1",
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
                    "ram": "512",
                    "disk": "20",
                    "rxtx_factor": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
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

    def test_get_empty_flavor_list(self):
        self.stubs.Set(nova.compute.instance_types, "get_all_types",
                       empty_instance_type_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors')
        flavors = self.controller.index(req)
        expected = {'flavors': []}
        self.assertEqual(flavors, expected)

    def test_get_flavor_list_filter_min_ram(self):
        """Flavor lists may be filtered by minRam"""
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?minRam=512')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
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

    def test_get_flavor_list_filter_min_disk(self):
        """Flavor lists may be filtered by minRam"""
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?minDisk=20')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
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

    def test_get_flavor_list_detail_min_ram_and_min_disk(self):
        """Tests that filtering work on flavor details and that minRam and
        minDisk filters can be combined
        """
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/detail'
                                      '?minRam=256&minDisk=20')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
                    "ram": "512",
                    "disk": "20",
                    "rxtx_factor": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
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

    def test_get_flavor_list_detail_bogus_min_ram(self):
        """Tests that bogus minRam filtering values are ignored"""
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/detail?minRam=16GB')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
                    "ram": "256",
                    "disk": "10",
                    "rxtx_factor": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/1",
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
                    "ram": "512",
                    "disk": "20",
                    "rxtx_factor": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
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

    def test_get_flavor_list_detail_bogus_min_disk(self):
        """Tests that bogus minDisk filtering values are ignored"""
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/detail?minDisk=16GB')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
                    "ram": "256",
                    "disk": "10",
                    "rxtx_factor": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/1",
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
                    "ram": "512",
                    "disk": "20",
                    "rxtx_factor": "",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
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


class FlavorsXMLSerializationTest(test.TestCase):

    def test_xml_declaration(self):
        serializer = flavors.FlavorTemplate()

        fixture = {
            "flavor": {
                "id": "12",
                "name": "asdf",
                "ram": "256",
                "disk": "10",
                "rxtx_factor": "1",
                "swap": "",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        print output
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_show(self):
        serializer = flavors.FlavorTemplate()

        fixture = {
            "flavor": {
                "id": "12",
                "name": "asdf",
                "ram": "256",
                "disk": "10",
                "rxtx_factor": "1",
                "swap": "",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavor')
        flavor_dict = fixture['flavor']

        for key in ['name', 'id', 'ram', 'disk']:
            self.assertEqual(root.get(key), str(flavor_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(flavor_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_handles_integers(self):
        serializer = flavors.FlavorTemplate()

        fixture = {
            "flavor": {
                "id": 12,
                "name": "asdf",
                "ram": 256,
                "disk": 10,
                "rxtx_factor": "1",
                "swap": "",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavor')
        flavor_dict = fixture['flavor']

        for key in ['name', 'id', 'ram', 'disk']:
            self.assertEqual(root.get(key), str(flavor_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(flavor_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_detail(self):
        serializer = flavors.FlavorsTemplate()

        fixture = {
            "flavors": [
                {
                    "id": "23",
                    "name": "flavor 23",
                    "ram": "512",
                    "disk": "20",
                    "rxtx_factor": "1",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/23",
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
                    "rxtx_factor": "1",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/13",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/13",
                        },
                    ],
                },
            ],
        }

        output = serializer.serialize(fixture)
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavors')
        flavor_elems = root.findall('{0}flavor'.format(NS))
        self.assertEqual(len(flavor_elems), 2)
        for i, flavor_elem in enumerate(flavor_elems):
            flavor_dict = fixture['flavors'][i]

            for key in ['name', 'id', 'ram', 'disk']:
                self.assertEqual(flavor_elem.get(key), str(flavor_dict[key]))

            link_nodes = flavor_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(flavor_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

    def test_index(self):
        serializer = flavors.MinimalFlavorsTemplate()

        fixture = {
            "flavors": [
                {
                    "id": "23",
                    "name": "flavor 23",
                    "ram": "512",
                    "disk": "20",
                    "rxtx_factor": "1",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/23",
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
                    "rxtx_factor": "1",
                    "swap": "",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/13",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/13",
                        },
                    ],
                },
            ],
        }

        output = serializer.serialize(fixture)
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavors_index')
        flavor_elems = root.findall('{0}flavor'.format(NS))
        self.assertEqual(len(flavor_elems), 2)
        for i, flavor_elem in enumerate(flavor_elems):
            flavor_dict = fixture['flavors'][i]

            for key in ['name', 'id']:
                self.assertEqual(flavor_elem.get(key), str(flavor_dict[key]))

            link_nodes = flavor_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(flavor_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

    def test_index_empty(self):
        serializer = flavors.MinimalFlavorsTemplate()

        fixture = {
            "flavors": [],
        }

        output = serializer.serialize(fixture)
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavors_index')
        flavor_elems = root.findall('{0}flavor'.format(NS))
        self.assertEqual(len(flavor_elems), 0)
