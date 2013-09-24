# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack Foundation
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

"""
Tests of the new image services, both as a service layer,
and as a WSGI layer
"""

import copy
import urlparse

from lxml import etree
import webob

from nova.api.openstack.compute import images
from nova.api.openstack.compute.views import images as images_view
from nova.api.openstack import xmlutil
from nova import exception
from nova.image import glance
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import matchers

NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
NOW_API_FORMAT = "2010-10-11T10:30:22Z"


class ImagesControllerTest(test.NoDBTestCase):
    """
    Test of the OpenStack API /images application controller w/Glance.
    """

    def setUp(self):
        """Run before each test."""
        super(ImagesControllerTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        fakes.stub_out_compute_api_backup(self.stubs)
        fakes.stub_out_glance(self.stubs)

        self.controller = images.Controller()
        self.uuid = 'fa95aaf5-ab3b-4cd8-88c0-2be7dd051aaf'
        self.url = '/v2/fake/images/detail?server=' + self.uuid
        self.server_uuid = "aa640691-d1a7-4a67-9d3c-d35ee6b3cc74"
        self.server_href = (
            "http://localhost/v2/fake/servers/" + self.server_uuid)
        self.server_bookmark = (
            "http://localhost/fake/servers/" + self.server_uuid)
        self.alternate = "%s/fake/images/%s"
        self.fake_req = fakes.HTTPRequest.blank('/v2/fake/images/123')
        self.actual_image = self.controller.show(self.fake_req, '124')

        self.expected_image_123 = {
            "image": {'id': '123',
                      'name': 'public image',
                      'metadata': {'key1': 'value1'},
                      'updated': NOW_API_FORMAT,
                      'created': NOW_API_FORMAT,
                      'status': 'ACTIVE',
                      'minDisk': 10,
                      'progress': 100,
                      'minRam': 128,
                      "links": [{
                                    "rel": "self",
                                    "href":
                                        "http://localhost/v2/fake/images/123",
                                },
                                {
                                    "rel": "bookmark",
                                    "href":
                                        "http://localhost/fake/images/123",
                                },
                                {
                                    "rel": "alternate",
                                    "type": "application/vnd.openstack.image",
                                    "href": self.alternate %
                                            (glance.generate_glance_url(),
                                             123),
                                }],
            },
        }

        self.expected_image_124 = {
            "image": {'id': '124',
                      'name': 'queued snapshot',
                      'metadata': {
                          u'instance_uuid': self.server_uuid,
                          u'user_id': u'fake',
                      },
                      'updated': NOW_API_FORMAT,
                      'created': NOW_API_FORMAT,
                      'status': 'SAVING',
                      'progress': 25,
                      'minDisk': 0,
                      'minRam': 0,
                      'server': {
                          'id': self.server_uuid,
                          "links": [{
                                        "rel": "self",
                                        "href": self.server_href,
                                    },
                                    {
                                        "rel": "bookmark",
                                        "href": self.server_bookmark,
                                    }],
                      },
                      "links": [{
                                    "rel": "self",
                                    "href":
                                        "http://localhost/v2/fake/images/124",
                                },
                                {
                                    "rel": "bookmark",
                                    "href":
                                        "http://localhost/fake/images/124",
                                },
                                {
                                    "rel": "alternate",
                                    "type":
                                        "application/vnd.openstack.image",
                                    "href": self.alternate %
                                            (glance.generate_glance_url(),
                                             124),
                                }],
            },
        }

        self.image_service = self.mox.CreateMockAnything()

    def test_get_image(self):
        self.assertThat(self.actual_image,
                        matchers.DictMatches(self.expected_image_124))

    def test_get_image_with_custom_prefix(self):
        self.flags(osapi_compute_link_prefix='https://zoo.com:42',
                   osapi_glance_link_prefix='http://circus.com:34')
        fake_req = fakes.HTTPRequest.blank('/v2/fake/images/123')
        actual_image = self.controller.show(fake_req, '124')

        expected_image = self.expected_image_124
        expected_image["image"]["links"][0]["href"] = (
            "https://zoo.com:42/v2/fake/images/124")
        expected_image["image"]["links"][1]["href"] = (
            "https://zoo.com:42/fake/images/124")
        expected_image["image"]["links"][2]["href"] = (
            "http://circus.com:34/fake/images/124")
        expected_image["image"]["server"]["links"][0]["href"] = (
            "https://zoo.com:42/v2/fake/servers/" + self.server_uuid)
        expected_image["image"]["server"]["links"][1]["href"] = (
            "https://zoo.com:42/fake/servers/" + self.server_uuid)

        self.assertThat(actual_image, matchers.DictMatches(expected_image))

    def test_get_image_404(self):
        fake_req = fakes.HTTPRequest.blank('/v2/fake/images/unknown')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, fake_req, 'unknown')

    def test_get_image_details(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail')
        response = self.controller.detail(request)
        response_list = response["images"]

        image_125 = copy.deepcopy(self.expected_image_124["image"])
        image_125['id'] = '125'
        image_125['name'] = 'saving snapshot'
        image_125['progress'] = 50
        image_125["links"][0]["href"] = "http://localhost/v2/fake/images/125"
        image_125["links"][1]["href"] = "http://localhost/fake/images/125"
        image_125["links"][2]["href"] = (
            "%s/fake/images/125" % glance.generate_glance_url())

        image_126 = copy.deepcopy(self.expected_image_124["image"])
        image_126['id'] = '126'
        image_126['name'] = 'active snapshot'
        image_126['status'] = 'ACTIVE'
        image_126['progress'] = 100
        image_126["links"][0]["href"] = "http://localhost/v2/fake/images/126"
        image_126["links"][1]["href"] = "http://localhost/fake/images/126"
        image_126["links"][2]["href"] = (
            "%s/fake/images/126" % glance.generate_glance_url())

        image_127 = copy.deepcopy(self.expected_image_124["image"])
        image_127['id'] = '127'
        image_127['name'] = 'killed snapshot'
        image_127['status'] = 'ERROR'
        image_127['progress'] = 0
        image_127["links"][0]["href"] = "http://localhost/v2/fake/images/127"
        image_127["links"][1]["href"] = "http://localhost/fake/images/127"
        image_127["links"][2]["href"] = (
            "%s/fake/images/127" % glance.generate_glance_url())

        image_128 = copy.deepcopy(self.expected_image_124["image"])
        image_128['id'] = '128'
        image_128['name'] = 'deleted snapshot'
        image_128['status'] = 'DELETED'
        image_128['progress'] = 0
        image_128["links"][0]["href"] = "http://localhost/v2/fake/images/128"
        image_128["links"][1]["href"] = "http://localhost/fake/images/128"
        image_128["links"][2]["href"] = (
            "%s/fake/images/128" % glance.generate_glance_url())

        image_129 = copy.deepcopy(self.expected_image_124["image"])
        image_129['id'] = '129'
        image_129['name'] = 'pending_delete snapshot'
        image_129['status'] = 'DELETED'
        image_129['progress'] = 0
        image_129["links"][0]["href"] = "http://localhost/v2/fake/images/129"
        image_129["links"][1]["href"] = "http://localhost/fake/images/129"
        image_129["links"][2]["href"] = (
            "%s/fake/images/129" % glance.generate_glance_url())

        image_130 = copy.deepcopy(self.expected_image_123["image"])
        image_130['id'] = '130'
        image_130['name'] = None
        image_130['metadata'] = {}
        image_130['minDisk'] = 0
        image_130['minRam'] = 0
        image_130["links"][0]["href"] = "http://localhost/v2/fake/images/130"
        image_130["links"][1]["href"] = "http://localhost/fake/images/130"
        image_130["links"][2]["href"] = (
            "%s/fake/images/130" % glance.generate_glance_url())

        image_131 = copy.deepcopy(self.expected_image_123["image"])
        image_131['id'] = '131'
        image_131['name'] = None
        image_131['metadata'] = {}
        image_131['minDisk'] = 0
        image_131['minRam'] = 0
        image_131["links"][0]["href"] = "http://localhost/v2/fake/images/131"
        image_131["links"][1]["href"] = "http://localhost/fake/images/131"
        image_131["links"][2]["href"] = (
            "%s/fake/images/131" % glance.generate_glance_url())

        expected = [self.expected_image_123["image"],
                    self.expected_image_124["image"],
                    image_125, image_126, image_127,
                    image_128, image_129, image_130,
                    image_131]

        self.assertThat(expected, matchers.DictListMatches(response_list))

    def test_get_image_details_with_limit(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail?limit=2')
        response = self.controller.detail(request)
        response_list = response["images"]
        response_links = response["images_links"]

        expected = [self.expected_image_123["image"],
                    self.expected_image_124["image"]]

        self.assertThat(expected, matchers.DictListMatches(response_list))

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/v2/fake/images', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)

        self.assertThat({'limit': ['2'], 'marker': ['124']},
                        matchers.DictMatches(params))

    def test_get_image_details_with_limit_and_page_size(self):
        request = fakes.HTTPRequest.blank(
            '/v2/fake/images/detail?limit=2&page_size=1')
        response = self.controller.detail(request)
        response_list = response["images"]
        response_links = response["images_links"]

        expected = [self.expected_image_123["image"],
                    self.expected_image_124["image"]]

        self.assertThat(expected, matchers.DictListMatches(response_list))

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/v2/fake/images', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)

        self.assertThat({'limit': ['2'], 'page_size': ['1'],
                         'marker': ['124']}, matchers.DictMatches(params))

    def _detail_request(self, filters, request):
        context = request.environ['nova.context']
        self.image_service.detail(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=self.image_service)
        controller.detail(request)

    def test_image_detail_filter_with_name(self):
        filters = {'name': 'testname'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail'
                                          '?name=testname')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_status(self):
        filters = {'status': 'active'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail'
                                          '?status=ACTIVE')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_property(self):
        filters = {'property-test': '3'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail'
                                          '?property-test=3')
        self._detail_request(filters, request)

    def test_image_detail_filter_server_href(self):
        ref = 'http://localhost:8774/servers/' + self.uuid
        filters = {'property-instance_uuid': self.uuid}
        request = fakes.HTTPRequest.blank(self.url)
        self._detail_request(filters, request)

    def test_image_detail_filter_server_uuid(self):
        filters = {'property-instance_uuid': self.uuid}
        request = fakes.HTTPRequest.blank(self.url)
        self._detail_request(filters, request)

    def test_image_detail_filter_changes_since(self):
        filters = {'changes-since': '2011-01-24T17:08Z'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail'
                                          '?changes-since=2011-01-24T17:08Z')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_type(self):
        filters = {'property-image_type': 'BASE'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail?type=BASE')
        self._detail_request(filters, request)

    def test_image_detail_filter_not_supported(self):
        filters = {'status': 'active'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail?status='
                                          'ACTIVE&UNSUPPORTEDFILTER=testname')
        self._detail_request(filters, request)

    def test_image_detail_no_filters(self):
        filters = {}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail')
        self._detail_request(filters, request)

    def test_image_detail_invalid_marker(self):
        class InvalidImageService(object):
            def detail(self, *args, **kwargs):
                raise exception.Invalid('meow')

        request = fakes.HTTPRequest.blank('/v2/images?marker=invalid')
        controller = images.Controller(image_service=InvalidImageService())
        self.assertRaises(webob.exc.HTTPBadRequest, controller.detail, request)

    def test_generate_alternate_link(self):
        view = images_view.ViewBuilder()
        request = fakes.HTTPRequest.blank('/v2/fake/images/1')
        generated_url = view._get_alternate_link(request, 1)
        actual_url = "%s/fake/images/1" % glance.generate_glance_url()
        self.assertEqual(generated_url, actual_url)

    def test_delete_image(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images/124')
        request.method = 'DELETE'
        response = self.controller.delete(request, '124')
        self.assertEqual(response.status_int, 204)

    def test_delete_deleted_image(self):
        """If you try to delete a deleted image, you get back 403 Forbidden."""

        deleted_image_id = 128
        # see nova.tests.api.openstack.fakes:_make_image_fixtures

        request = fakes.HTTPRequest.blank(
              '/v2/fake/images/%s' % deleted_image_id)
        request.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
             request, '%s' % deleted_image_id)

    def test_delete_image_not_found(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images/300')
        request.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, request, '300')


class ImageXMLSerializationTest(test.NoDBTestCase):

    TIMESTAMP = "2010-10-11T10:30:22Z"
    SERVER_UUID = 'aa640691-d1a7-4a67-9d3c-d35ee6b3cc74'
    SERVER_HREF = 'http://localhost/v2/fake/servers/' + SERVER_UUID
    SERVER_BOOKMARK = 'http://localhost/fake/servers/' + SERVER_UUID
    IMAGE_HREF = 'http://localhost/v2/fake/images/%s'
    IMAGE_NEXT = 'http://localhost/v2/fake/images?limit=%s&marker=%s'
    IMAGE_BOOKMARK = 'http://localhost/fake/images/%s'

    def test_xml_declaration(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'progress': 80,
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_show(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'progress': 80,
                'minRam': 10,
                'minDisk': 100,
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status', 'progress']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = image_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_zero_metadata(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {},
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        meta_nodes = root.findall('{0}meta'.format(ATOMNS))
        self.assertEqual(len(meta_nodes), 0)

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_image_no_metadata_key(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        meta_nodes = root.findall('{0}meta'.format(ATOMNS))
        self.assertEqual(len(meta_nodes), 0)

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_no_server(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = image_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root, None)

    def test_show_with_min_ram(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'progress': 80,
                'minRam': 256,
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status', 'progress',
                    'minRam']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = image_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_with_min_disk(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'progress': 80,
                'minDisk': 5,
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status', 'progress',
                    'minDisk']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = image_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_index(self):
        serializer = images.MinimalImagesTemplate()

        fixture = {
            'images': [
                {
                    'id': 1,
                    'name': 'Image1',
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 1,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 1,
                            'rel': 'bookmark',
                        },
                    ],
                },
                {
                    'id': 2,
                    'name': 'Image2',
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 2,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 2,
                            'rel': 'bookmark',
                        },
                    ],
                },
            ]
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'images_index')
        image_elems = root.findall('{0}image'.format(NS))
        self.assertEqual(len(image_elems), 2)
        for i, image_elem in enumerate(image_elems):
            image_dict = fixture['images'][i]

            for key in ['name', 'id']:
                self.assertEqual(image_elem.get(key), str(image_dict[key]))

            link_nodes = image_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(image_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

    def test_index_with_links(self):
        serializer = images.MinimalImagesTemplate()

        fixture = {
            'images': [
                {
                    'id': 1,
                    'name': 'Image1',
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 1,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 1,
                            'rel': 'bookmark',
                        },
                    ],
                },
                {
                    'id': 2,
                    'name': 'Image2',
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 2,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 2,
                            'rel': 'bookmark',
                        },
                    ],
                },
            ],
            'images_links': [
                {
                    'rel': 'next',
                    'href': self.IMAGE_NEXT % (2, 2),
                }
            ],
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'images_index')
        image_elems = root.findall('{0}image'.format(NS))
        self.assertEqual(len(image_elems), 2)
        for i, image_elem in enumerate(image_elems):
            image_dict = fixture['images'][i]

            for key in ['name', 'id']:
                self.assertEqual(image_elem.get(key), str(image_dict[key]))

            link_nodes = image_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(image_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

            # Check images_links
            images_links = root.findall('{0}link'.format(ATOMNS))
            for i, link in enumerate(fixture['images_links']):
                for key, value in link.items():
                    self.assertEqual(images_links[i].get(key), value)

    def test_index_zero_images(self):
        serializer = images.MinimalImagesTemplate()

        fixtures = {
            'images': [],
        }

        output = serializer.serialize(fixtures)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'images_index')
        image_elems = root.findall('{0}image'.format(NS))
        self.assertEqual(len(image_elems), 0)

    def test_detail(self):
        serializer = images.ImagesTemplate()

        fixture = {
            'images': [
                {
                    'id': 1,
                    'name': 'Image1',
                    'created': self.TIMESTAMP,
                    'updated': self.TIMESTAMP,
                    'status': 'ACTIVE',
                    'server': {
                        'id': self.SERVER_UUID,
                        'links': [
                            {
                                'href': self.SERVER_HREF,
                                'rel': 'self',
                            },
                            {
                                'href': self.SERVER_BOOKMARK,
                                'rel': 'bookmark',
                            },
                        ],
                    },
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 1,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 1,
                            'rel': 'bookmark',
                        },
                    ],
                },
                {
                    'id': '2',
                    'name': 'Image2',
                    'created': self.TIMESTAMP,
                    'updated': self.TIMESTAMP,
                    'status': 'SAVING',
                    'progress': 80,
                    'metadata': {
                        'key1': 'value1',
                    },
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 2,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 2,
                            'rel': 'bookmark',
                        },
                    ],
                },
            ]
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'images')
        image_elems = root.findall('{0}image'.format(NS))
        self.assertEqual(len(image_elems), 2)
        for i, image_elem in enumerate(image_elems):
            image_dict = fixture['images'][i]

            for key in ['name', 'id', 'updated', 'created', 'status']:
                self.assertEqual(image_elem.get(key), str(image_dict[key]))

            link_nodes = image_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(image_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)
