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

import mock
import six.moves.urllib.parse as urlparse
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
    image_controller_class = images_v21.ImagesController
    url_base = '/v2/fake'
    bookmark_base = '/fake'
    http_request = fakes.HTTPRequestV21

    def setUp(self):
        """Run before each test."""
        super(ImagesControllerTestV21, self).setUp()
        self.flags(api_servers=['http://localhost:9292'], group='glance')
        fakes.stub_out_networking(self)
        fakes.stub_out_key_pair_funcs(self)
        fakes.stub_out_compute_api_snapshot(self)
        fakes.stub_out_compute_api_backup(self)

        self.controller = self.image_controller_class()
        self.url_prefix = "http://localhost%s/images" % self.url_base
        self.bookmark_prefix = "http://localhost%s/images" % self.bookmark_base
        self.uuid = 'fa95aaf5-ab3b-4cd8-88c0-2be7dd051aaf'
        self.server_uuid = "aa640691-d1a7-4a67-9d3c-d35ee6b3cc74"
        self.server_href = (
            "http://localhost%s/servers/%s" % (self.url_base,
                                               self.server_uuid))
        self.server_bookmark = (
             "http://localhost%s/servers/%s" % (self.bookmark_base,
                                                self.server_uuid))
        self.alternate = "%s/images/%s"

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
                                    "href": "%s/123" % self.url_prefix
                                },
                                {
                                    "rel": "bookmark",
                                    "href":
                                        "%s/123" % self.bookmark_prefix
                                },
                                {
                                    "rel": "alternate",
                                    "type": "application/vnd.openstack.image",
                                    "href": self.alternate %
                                            (glance.generate_glance_url('ctx'),
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
                                    "href": "%s/124" % self.url_prefix
                                },
                                {
                                    "rel": "bookmark",
                                    "href":
                                        "%s/124" % self.bookmark_prefix
                                },
                                {
                                    "rel": "alternate",
                                    "type":
                                        "application/vnd.openstack.image",
                                    "href": self.alternate %
                                            (glance.generate_glance_url('ctx'),
                                             124),
                                }],
            },
        }

    @mock.patch('nova.image.api.API.get', return_value=IMAGE_FIXTURES[0])
    def test_get_image(self, get_mocked):
        request = self.http_request.blank(self.url_base + 'images/123')
        actual_image = self.controller.show(request, '123')
        self.assertThat(actual_image,
                        matchers.DictMatches(self.expected_image_123))
        get_mocked.assert_called_once_with(mock.ANY, '123')

    @mock.patch('nova.image.api.API.get', return_value=IMAGE_FIXTURES[1])
    def test_get_image_with_custom_prefix(self, _get_mocked):
        self.flags(compute_link_prefix='https://zoo.com:42',
                   glance_link_prefix='http://circus.com:34',
                   group='api')
        fake_req = self.http_request.blank(self.url_base + 'images/124')
        actual_image = self.controller.show(fake_req, '124')

        expected_image = self.expected_image_124
        expected_image["image"]["links"][0]["href"] = (
            "https://zoo.com:42%s/images/124" % self.url_base)
        expected_image["image"]["links"][1]["href"] = (
            "https://zoo.com:42%s/images/124" % self.bookmark_base)
        expected_image["image"]["links"][2]["href"] = (
            "http://circus.com:34/images/124")
        expected_image["image"]["server"]["links"][0]["href"] = (
            "https://zoo.com:42%s/servers/%s" % (self.url_base,
                                                 self.server_uuid))
        expected_image["image"]["server"]["links"][1]["href"] = (
            "https://zoo.com:42%s/servers/%s" % (self.bookmark_base,
                                                 self.server_uuid))

        self.assertThat(actual_image, matchers.DictMatches(expected_image))

    @mock.patch('nova.image.api.API.get',
                side_effect=exception.ImageNotFound(image_id=''))
    def test_get_image_404(self, _get_mocked):
        fake_req = self.http_request.blank(self.url_base + 'images/unknown')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, fake_req, 'unknown')

    @mock.patch('nova.image.api.API.get_all', return_value=IMAGE_FIXTURES)
    def test_get_image_details(self, get_all_mocked):
        request = self.http_request.blank(self.url_base + 'images/detail')
        response = self.controller.detail(request)

        get_all_mocked.assert_called_once_with(mock.ANY, filters={})
        response_list = response["images"]

        image_125 = copy.deepcopy(self.expected_image_124["image"])
        image_125['id'] = '125'
        image_125['name'] = 'saving snapshot'
        image_125['progress'] = 50
        image_125["links"][0]["href"] = "%s/125" % self.url_prefix
        image_125["links"][1]["href"] = "%s/125" % self.bookmark_prefix
        image_125["links"][2]["href"] = (
            "%s/images/125" % glance.generate_glance_url('ctx'))

        image_126 = copy.deepcopy(self.expected_image_124["image"])
        image_126['id'] = '126'
        image_126['name'] = 'active snapshot'
        image_126['status'] = 'ACTIVE'
        image_126['progress'] = 100
        image_126["links"][0]["href"] = "%s/126" % self.url_prefix
        image_126["links"][1]["href"] = "%s/126" % self.bookmark_prefix
        image_126["links"][2]["href"] = (
            "%s/images/126" % glance.generate_glance_url('ctx'))

        image_127 = copy.deepcopy(self.expected_image_124["image"])
        image_127['id'] = '127'
        image_127['name'] = 'killed snapshot'
        image_127['status'] = 'ERROR'
        image_127['progress'] = 0
        image_127["links"][0]["href"] = "%s/127" % self.url_prefix
        image_127["links"][1]["href"] = "%s/127" % self.bookmark_prefix
        image_127["links"][2]["href"] = (
            "%s/images/127" % glance.generate_glance_url('ctx'))

        image_128 = copy.deepcopy(self.expected_image_124["image"])
        image_128['id'] = '128'
        image_128['name'] = 'deleted snapshot'
        image_128['status'] = 'DELETED'
        image_128['progress'] = 0
        image_128["links"][0]["href"] = "%s/128" % self.url_prefix
        image_128["links"][1]["href"] = "%s/128" % self.bookmark_prefix
        image_128["links"][2]["href"] = (
            "%s/images/128" % glance.generate_glance_url('ctx'))

        image_129 = copy.deepcopy(self.expected_image_124["image"])
        image_129['id'] = '129'
        image_129['name'] = 'pending_delete snapshot'
        image_129['status'] = 'DELETED'
        image_129['progress'] = 0
        image_129["links"][0]["href"] = "%s/129" % self.url_prefix
        image_129["links"][1]["href"] = "%s/129" % self.bookmark_prefix
        image_129["links"][2]["href"] = (
            "%s/images/129" % glance.generate_glance_url('ctx'))

        image_130 = copy.deepcopy(self.expected_image_123["image"])
        image_130['id'] = '130'
        image_130['name'] = None
        image_130['metadata'] = {}
        image_130['minDisk'] = 0
        image_130['minRam'] = 0
        image_130["links"][0]["href"] = "%s/130" % self.url_prefix
        image_130["links"][1]["href"] = "%s/130" % self.bookmark_prefix
        image_130["links"][2]["href"] = (
            "%s/images/130" % glance.generate_glance_url('ctx'))

        image_131 = copy.deepcopy(self.expected_image_123["image"])
        image_131['id'] = '131'
        image_131['name'] = None
        image_131['metadata'] = {}
        image_131['minDisk'] = 0
        image_131['minRam'] = 0
        image_131["links"][0]["href"] = "%s/131" % self.url_prefix
        image_131["links"][1]["href"] = "%s/131" % self.bookmark_prefix
        image_131["links"][2]["href"] = (
            "%s/images/131" % glance.generate_glance_url('ctx'))

        expected = [self.expected_image_123["image"],
                    self.expected_image_124["image"],
                    image_125, image_126, image_127,
                    image_128, image_129, image_130,
                    image_131]

        self.assertThat(expected, matchers.DictListMatches(response_list))

    @mock.patch('nova.image.api.API.get_all')
    def test_get_image_details_with_limit(self, get_all_mocked):
        request = self.http_request.blank(self.url_base +
                                          'images/detail?limit=2')
        self.controller.detail(request)
        get_all_mocked.assert_called_once_with(mock.ANY, limit=2, filters={})

    @mock.patch('nova.image.api.API.get_all')
    def test_get_image_details_with_limit_and_page_size(self, get_all_mocked):
        request = self.http_request.blank(
            self.url_base + 'images/detail?limit=2&page_size=1')
        self.controller.detail(request)
        get_all_mocked.assert_called_once_with(mock.ANY, limit=2, filters={},
                                               page_size=1)

    @mock.patch('nova.image.api.API.get_all')
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

    @mock.patch('nova.image.api.API.get_all', side_effect=exception.Invalid)
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

    def _check_response(self, controller_method, response, expected_code):
        self.assertEqual(expected_code, controller_method.wsgi_code)

    @mock.patch('nova.image.api.API.delete')
    def test_delete_image(self, delete_mocked):
        request = self.http_request.blank(self.url_base + 'images/124')
        request.method = 'DELETE'
        delete_method = self.controller.delete
        response = delete_method(request, '124')
        self._check_response(delete_method, response, 204)
        delete_mocked.assert_called_once_with(mock.ANY, '124')

    @mock.patch('nova.image.api.API.delete',
                side_effect=exception.ImageNotAuthorized(image_id='123'))
    def test_delete_deleted_image(self, _delete_mocked):
        # If you try to delete a deleted image, you get back 403 Forbidden.
        request = self.http_request.blank(self.url_base + 'images/123')
        request.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          request, '123')

    @mock.patch('nova.image.api.API.delete',
                side_effect=exception.ImageNotFound(image_id='123'))
    def test_delete_image_not_found(self, _delete_mocked):
        request = self.http_request.blank(self.url_base + 'images/300')
        request.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, request, '300')

    @mock.patch('nova.image.api.API.get_all', return_value=[IMAGE_FIXTURES[0]])
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

    @mock.patch('nova.image.api.API.get_all', return_value=[IMAGE_FIXTURES[0]])
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
