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
from unittest import mock
from urllib import parse as urlparse

import webob

from nova.api.openstack.compute import images as images_v21
from nova.api.openstack.compute.views import images as images_view
from nova import exception
from nova.image import glance
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import image_fixtures
from nova.tests.unit import matchers

NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
NOW_API_FORMAT = "2010-10-11T10:30:22Z"
IMAGE_FIXTURES = image_fixtures.get_image_fixtures()


class ImagesControllerTestV21(test.NoDBTestCase):
    """Test of the OpenStack API /images application controller w/Glance.
    """
    url_base = '/v2.1'
    http_request = fakes.HTTPRequestV21

    def setUp(self):
        """Run before each test."""
        super(ImagesControllerTestV21, self).setUp()
        self.flags(api_servers=['http://localhost:9292'], group='glance')
        fakes.stub_out_networking(self)
        fakes.stub_out_key_pair_funcs(self)
        fakes.stub_out_compute_api_snapshot(self)
        fakes.stub_out_compute_api_backup(self)

        self.controller = images_v21.ImagesController()
        self.url_prefix = "http://localhost%s/images" % self.url_base
        self.bookmark_prefix = "http://localhost/images"
        self.uuid = 'fa95aaf5-ab3b-4cd8-88c0-2be7dd051aaf'
        self.server_uuid = "aa640691-d1a7-4a67-9d3c-d35ee6b3cc74"
        self.server_href = (
            "http://localhost%s/servers/%s" % (self.url_base,
                                               self.server_uuid))
        self.server_bookmark = (
             "http://localhost/servers/%s" % self.server_uuid)
        self.alternate = "%s/images/%s"

        self.image_a_uuid = IMAGE_FIXTURES[0]['id']
        self.expected_image_a = {
            "image": {
                'id': self.image_a_uuid,
                'name': 'public image',
                'metadata': {'key1': 'value1'},
                'updated': NOW_API_FORMAT,
                'created': NOW_API_FORMAT,
                'status': 'ACTIVE',
                'minDisk': 10,
                'progress': 100,
                'minRam': 128,
                'OS-EXT-IMG-SIZE:size': 25165824,
                "links": [
                    {
                        "rel": "self",
                        "href": f"{self.url_prefix}/{self.image_a_uuid}"
                    },
                    {
                        "rel": "bookmark",
                        "href": f"{self.bookmark_prefix}/{self.image_a_uuid}"
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": self.alternate % (
                            glance.generate_glance_url('ctx'),
                            self.image_a_uuid,
                        ),
                    }
                ],
            },
        }

        self.image_b_uuid = IMAGE_FIXTURES[1]['id']
        self.expected_image_b = {
            "image": {
                'id': self.image_b_uuid,
                'name': 'queued snapshot',
                'metadata': {
                    'instance_uuid': self.server_uuid,
                    'user_id': 'fake',
                },
                'updated': NOW_API_FORMAT,
                'created': NOW_API_FORMAT,
                'status': 'SAVING',
                'progress': 25,
                'minDisk': 0,
                'minRam': 0,
                'OS-EXT-IMG-SIZE:size': 25165824,
                'server': {
                    'id': self.server_uuid,
                    "links": [
                        {
                            "rel": "self",
                            "href": self.server_href,
                        },
                        {
                            "rel": "bookmark",
                            "href": self.server_bookmark,
                        }
                    ],
                },
                "links": [
                    {
                        "rel": "self",
                        "href": f"{self.url_prefix}/{self.image_b_uuid}"
                    },
                    {
                        "rel": "bookmark",
                        "href": f"{self.bookmark_prefix}/{self.image_b_uuid}"
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": self.alternate % (
                            glance.generate_glance_url('ctx'),
                            self.image_b_uuid,
                        ),
                    },
                ],
            },
        }

    @mock.patch('nova.image.glance.API.get', return_value=IMAGE_FIXTURES[0])
    def test_get_image(self, get_mocked):
        request = self.http_request.blank(
            self.url_base + f'images/{self.image_a_uuid}')
        actual_image = self.controller.show(request, self.image_a_uuid)
        self.assertThat(actual_image,
                        matchers.DictMatches(self.expected_image_a))
        get_mocked.assert_called_once_with(mock.ANY, self.image_a_uuid)

    @mock.patch('nova.image.glance.API.get', return_value=IMAGE_FIXTURES[1])
    def test_get_image_with_custom_prefix(self, _get_mocked):
        self.flags(compute_link_prefix='https://zoo.com:42',
                   glance_link_prefix='http://circus.com:34',
                   group='api')
        fake_req = self.http_request.blank(
            self.url_base + f'images/{self.image_b_uuid}')
        actual_image = self.controller.show(fake_req, self.image_b_uuid)

        expected_image = self.expected_image_b
        expected_image["image"]["links"][0]["href"] = (
            f"https://zoo.com:42{self.url_base}/images/{self.image_b_uuid}")
        expected_image["image"]["links"][1]["href"] = (
            f"https://zoo.com:42/images/{self.image_b_uuid}")
        expected_image["image"]["links"][2]["href"] = (
            f"http://circus.com:34/images/{self.image_b_uuid}")
        expected_image["image"]["server"]["links"][0]["href"] = (
            "https://zoo.com:42%s/servers/%s" % (self.url_base,
                                                 self.server_uuid))
        expected_image["image"]["server"]["links"][1]["href"] = (
            "https://zoo.com:42/servers/%s" % (self.server_uuid))

        self.assertThat(actual_image, matchers.DictMatches(expected_image))

    @mock.patch('nova.image.glance.API.get',
                side_effect=exception.ImageNotFound(image_id=''))
    def test_get_image_404(self, _get_mocked):
        fake_req = self.http_request.blank(self.url_base + 'images/unknown')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, fake_req, 'unknown')

    @mock.patch('nova.image.glance.API.get_all', return_value=IMAGE_FIXTURES)
    def test_get_image_details(self, get_all_mocked):
        request = self.http_request.blank(self.url_base + 'images/detail')
        response = self.controller.detail(request)

        get_all_mocked.assert_called_once_with(mock.ANY, filters={})
        response_list = response["images"]

        image_c = copy.deepcopy(self.expected_image_b["image"])
        image_c['id'] = IMAGE_FIXTURES[2]['id']
        image_c['name'] = 'saving snapshot'
        image_c['progress'] = 50
        image_c["links"][0]["href"] = "%s/%s" % (
            self.url_prefix, IMAGE_FIXTURES[2]['id'])
        image_c["links"][1]["href"] = "%s/%s" % (
            self.bookmark_prefix, IMAGE_FIXTURES[2]['id'])
        image_c["links"][2]["href"] = "%s/images/%s" % (
            glance.generate_glance_url('ctx'), IMAGE_FIXTURES[2]['id'])

        image_d = copy.deepcopy(self.expected_image_b["image"])
        image_d['id'] = IMAGE_FIXTURES[3]['id']
        image_d['name'] = 'active snapshot'
        image_d['status'] = 'ACTIVE'
        image_d['progress'] = 100
        image_d["links"][0]["href"] = "%s/%s" % (
            self.url_prefix, IMAGE_FIXTURES[3]['id'])
        image_d["links"][1]["href"] = "%s/%s" % (
            self.bookmark_prefix, IMAGE_FIXTURES[3]['id'])
        image_d["links"][2]["href"] = "%s/images/%s" % (
            glance.generate_glance_url('ctx'), IMAGE_FIXTURES[3]['id'])

        image_e = copy.deepcopy(self.expected_image_b["image"])
        image_e['id'] = IMAGE_FIXTURES[4]['id']
        image_e['name'] = 'killed snapshot'
        image_e['status'] = 'ERROR'
        image_e['progress'] = 0
        image_e["links"][0]["href"] = "%s/%s" % (
            self.url_prefix, IMAGE_FIXTURES[4]['id'])
        image_e["links"][1]["href"] = "%s/%s" % (
            self.bookmark_prefix, IMAGE_FIXTURES[4]['id'])
        image_e["links"][2]["href"] = "%s/images/%s" % (
            glance.generate_glance_url('ctx'), IMAGE_FIXTURES[4]['id'])

        image_f = copy.deepcopy(self.expected_image_b["image"])
        image_f['id'] = IMAGE_FIXTURES[5]['id']
        image_f['name'] = 'deleted snapshot'
        image_f['status'] = 'DELETED'
        image_f['progress'] = 0
        image_f["links"][0]["href"] = "%s/%s" % (
            self.url_prefix, IMAGE_FIXTURES[5]['id'])
        image_f["links"][1]["href"] = "%s/%s" % (
            self.bookmark_prefix, IMAGE_FIXTURES[5]['id'])
        image_f["links"][2]["href"] = "%s/images/%s" % (
            glance.generate_glance_url('ctx'), IMAGE_FIXTURES[5]['id'])

        image_g = copy.deepcopy(self.expected_image_b["image"])
        image_g['id'] = IMAGE_FIXTURES[6]['id']
        image_g['name'] = 'pending_delete snapshot'
        image_g['status'] = 'DELETED'
        image_g['progress'] = 0
        image_g["links"][0]["href"] = "%s/%s" % (
            self.url_prefix, IMAGE_FIXTURES[6]['id'])
        image_g["links"][1]["href"] = "%s/%s" % (
            self.bookmark_prefix, IMAGE_FIXTURES[6]['id'])
        image_g["links"][2]["href"] = "%s/images/%s" % (
            glance.generate_glance_url('ctx'), IMAGE_FIXTURES[6]['id'])

        image_h = copy.deepcopy(self.expected_image_a["image"])
        image_h['id'] = IMAGE_FIXTURES[7]['id']
        image_h['name'] = None
        image_h['metadata'] = {}
        image_h['minDisk'] = 0
        image_h['minRam'] = 0
        image_h["links"][0]["href"] = "%s/%s" % (
            self.url_prefix, IMAGE_FIXTURES[7]['id'])
        image_h["links"][1]["href"] = "%s/%s" % (
            self.bookmark_prefix, IMAGE_FIXTURES[7]['id'])
        image_h["links"][2]["href"] = "%s/images/%s" % (
            glance.generate_glance_url('ctx'), IMAGE_FIXTURES[7]['id'])

        image_i = copy.deepcopy(self.expected_image_a["image"])
        image_i['id'] = IMAGE_FIXTURES[8]['id']
        image_i['name'] = None
        image_i['metadata'] = {}
        image_i['minDisk'] = 0
        image_i['minRam'] = 0
        image_i["links"][0]["href"] = "%s/%s" % (
            self.url_prefix, IMAGE_FIXTURES[8]['id'])
        image_i["links"][1]["href"] = "%s/%s" % (
            self.bookmark_prefix, IMAGE_FIXTURES[8]['id'])
        image_i["links"][2]["href"] = "%s/images/%s" % (
            glance.generate_glance_url('ctx'), IMAGE_FIXTURES[8]['id'])

        expected = [self.expected_image_a["image"],
                    self.expected_image_b["image"],
                    image_c, image_d, image_e,
                    image_f, image_g, image_h,
                    image_i]

        self.assertThat(expected, matchers.DictListMatches(response_list))

    @mock.patch('nova.image.glance.API.get_all')
    def test_get_image_details_with_limit(self, get_all_mocked):
        request = self.http_request.blank(self.url_base +
                                          'images/detail?limit=2')
        self.controller.detail(request)
        get_all_mocked.assert_called_once_with(mock.ANY, limit=2, filters={})

    @mock.patch('nova.image.glance.API.get_all')
    def test_get_image_details_with_limit_and_page_size(self, get_all_mocked):
        request = self.http_request.blank(
            self.url_base + 'images/detail?limit=2&page_size=1')
        self.controller.detail(request)
        get_all_mocked.assert_called_once_with(mock.ANY, limit=2, filters={},
                                               page_size=1)

    @mock.patch('nova.image.glance.API.get_all')
    def _detail_request(self, filters, request, get_all_mocked):
        self.controller.detail(request)
        get_all_mocked.assert_called_once_with(mock.ANY, filters=filters)

    def test_image_detail_filter_with_name(self):
        filters = {'name': 'testname'}
        request = self.http_request.blank(self.url_base + 'images/detail'
                                          '?name=testname')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_status(self):
        filters = {'status': 'active'}
        request = self.http_request.blank(self.url_base + 'images/detail'
                                          '?status=ACTIVE')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_property(self):
        filters = {'property-test': '3'}
        request = self.http_request.blank(self.url_base + 'images/detail'
                                          '?property-test=3')
        self._detail_request(filters, request)

    def test_image_detail_filter_server_href(self):
        filters = {'property-instance_uuid': self.uuid}
        request = self.http_request.blank(
            self.url_base + 'images/detail?server=' + self.uuid)
        self._detail_request(filters, request)

    def test_image_detail_filter_server_uuid(self):
        filters = {'property-instance_uuid': self.uuid}
        request = self.http_request.blank(
            self.url_base + 'images/detail?server=' + self.uuid)
        self._detail_request(filters, request)

    def test_image_detail_filter_changes_since(self):
        filters = {'changes-since': '2011-01-24T17:08Z'}
        request = self.http_request.blank(self.url_base + 'images/detail'
                                          '?changes-since=2011-01-24T17:08Z')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_type(self):
        filters = {'property-image_type': 'BASE'}
        request = self.http_request.blank(
            self.url_base + 'images/detail?type=BASE')
        self._detail_request(filters, request)

    def test_image_detail_filter_not_supported(self):
        filters = {'status': 'active'}
        request = self.http_request.blank(
            self.url_base + 'images/detail?status='
            'ACTIVE&UNSUPPORTEDFILTER=testname')
        self._detail_request(filters, request)

    def test_image_detail_no_filters(self):
        filters = {}
        request = self.http_request.blank(self.url_base + 'images/detail')
        self._detail_request(filters, request)

    @mock.patch('nova.image.glance.API.get_all', side_effect=exception.Invalid)
    def test_image_detail_invalid_marker(self, _get_all_mocked):
        request = self.http_request.blank(self.url_base + '?marker=invalid')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.detail,
                          request)

    def test_generate_alternate_link(self):
        view = images_view.ViewBuilder()
        request = self.http_request.blank(self.url_base + 'images/1')
        generated_url = view._get_alternate_link(request, 1)
        actual_url = "%s/images/1" % glance.generate_glance_url('ctx')
        self.assertEqual(generated_url, actual_url)

    @mock.patch('nova.image.glance.API.delete')
    def test_delete_image(self, delete_mocked):
        request = self.http_request.blank(
            self.url_base + f'images/{self.image_a_uuid}')
        request.method = 'DELETE'
        delete_method = self.controller.delete
        delete_method(request, self.image_a_uuid)
        self.assertEqual(204, delete_method.wsgi_codes(request))
        delete_mocked.assert_called_once_with(mock.ANY, self.image_a_uuid)

    def test_delete_deleted_image(self):
        # If you try to delete a deleted image, you get back 403 Forbidden.
        request = self.http_request.blank(
            self.url_base + f'images/{self.image_a_uuid}')
        request.method = 'DELETE'
        with mock.patch(
            'nova.image.glance.API.delete',
            side_effect=exception.ImageNotAuthorized(
                image_id=self.image_a_uuid
            )
        ):
            self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                              request, self.image_a_uuid)

    def test_delete_image_not_found(self):
        request = self.http_request.blank(self.url_base + 'images/300')
        request.method = 'DELETE'
        with mock.patch(
            'nova.image.glance.API.delete',
            side_effect=exception.ImageNotFound(image_id='300')
        ):
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.controller.delete, request, '300')

    @mock.patch('nova.image.glance.API.get_all',
                return_value=[IMAGE_FIXTURES[0]])
    def test_get_image_next_link(self, get_all_mocked):
        request = self.http_request.blank(
            self.url_base + 'imagesl?limit=1')
        response = self.controller.index(request)
        response_links = response['images_links']
        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual(self.url_base + '/images', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['1'], 'marker': [IMAGE_FIXTURES[0]['id']]},
                        matchers.DictMatches(params))

    @mock.patch('nova.image.glance.API.get_all',
                return_value=[IMAGE_FIXTURES[0]])
    def test_get_image_details_next_link(self, get_all_mocked):
        request = self.http_request.blank(
            self.url_base + 'images/detail?limit=1')
        response = self.controller.detail(request)
        response_links = response['images_links']
        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual(self.url_base + '/images/detail', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['1'], 'marker': [IMAGE_FIXTURES[0]['id']]},
                        matchers.DictMatches(params))


class ImagesControllerDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(ImagesControllerDeprecationTest, self).setUp()
        self.controller = images_v21.ImagesController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_not_found_for_all_images_api(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.delete, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.detail, self.req)
