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

"""
Tests of the new image services, both as a service layer,
and as a WSGI layer
"""

import urlparse

from lxml import etree
import stubout
import webob

from nova.api.openstack.compute import images
from nova.api.openstack.compute.views import images as images_view
from nova.api.openstack import xmlutil
from nova import test
from nova import utils
from nova.tests.api.openstack import fakes


NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
NOW_API_FORMAT = "2010-10-11T10:30:22Z"


class ImagesControllerTest(test.TestCase):
    """
    Test of the OpenStack API /images application controller w/Glance.
    """

    def setUp(self):
        """Run before each test."""
        super(ImagesControllerTest, self).setUp()
        self.maxDiff = None
        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        fakes.stub_out_compute_api_backup(self.stubs)
        fakes.stub_out_glance(self.stubs)

        self.controller = images.Controller()

    def tearDown(self):
        """Run after each test."""
        self.stubs.UnsetAll()
        super(ImagesControllerTest, self).tearDown()

    def test_get_image(self):
        fake_req = fakes.HTTPRequest.blank('/v2/fake/images/123')
        actual_image = self.controller.show(fake_req, '124')

        href = "http://localhost/v2/fake/images/124"
        bookmark = "http://localhost/fake/images/124"
        alternate = "%s/fake/images/124" % utils.generate_glance_url()
        server_uuid = "aa640691-d1a7-4a67-9d3c-d35ee6b3cc74"
        server_href = "http://localhost/v2/servers/" + server_uuid
        server_bookmark = "http://localhost/servers/" + server_uuid

        expected_image = {
            "image": {
                "id": "124",
                "name": "queued snapshot",
                "updated": NOW_API_FORMAT,
                "created": NOW_API_FORMAT,
                "status": "SAVING",
                "progress": 25,
                "minDisk": 0,
                "minRam": 0,
                'server': {
                    'id': server_uuid,
                    "links": [{
                        "rel": "self",
                        "href": server_href,
                    },
                    {
                        "rel": "bookmark",
                        "href": server_bookmark,
                    }],
                },
                "metadata": {
                    "instance_ref": server_href,
                    "user_id": "fake",
                },
                "links": [{
                    "rel": "self",
                    "href": href,
                },
                {
                    "rel": "bookmark",
                    "href": bookmark,
                },
                {
                    "rel": "alternate",
                    "type": "application/vnd.openstack.image",
                    "href": alternate
                }],
            },
        }

        self.assertDictMatch(expected_image, actual_image)

    def test_get_image_404(self):
        fake_req = fakes.HTTPRequest.blank('/v2/fake/images/unknown')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, fake_req, 'unknown')

    def test_get_image_index(self):
        fake_req = fakes.HTTPRequest.blank('/v2/fake/images')
        response_list = self.controller.index(fake_req)['images']

        expected_images = [
            {
                "id": "123",
                "name": "public image",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/123",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/123",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": "%s/fake/images/123" %
                                utils.generate_glance_url()
                    },
                ],
            },
            {
                "id": "124",
                "name": "queued snapshot",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/124",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/124",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": "%s/fake/images/124" %
                                utils.generate_glance_url()
                    },
                ],
            },
            {
                "id": "125",
                "name": "saving snapshot",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/125",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/125",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": "%s/fake/images/125" %
                                utils.generate_glance_url()
                    },
                ],
            },
            {
                "id": "126",
                "name": "active snapshot",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/126",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/126",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": "%s/fake/images/126" %
                                utils.generate_glance_url()
                    },
                ],
            },
            {
                "id": "127",
                "name": "killed snapshot",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/127",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/127",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": "%s/fake/images/127" %
                                utils.generate_glance_url()
                    },
                ],
            },
            {
                "id": "128",
                "name": "deleted snapshot",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/128",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/128",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": "%s/fake/images/128" %
                                utils.generate_glance_url()
                    },
                ],
            },
            {
                "id": "129",
                "name": "pending_delete snapshot",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/129",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/129",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": "%s/fake/images/129" %
                                utils.generate_glance_url()
                    },
                ],
            },
            {
                "id": "130",
                "name": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/130",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/130",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": "%s/fake/images/130" %
                                utils.generate_glance_url()
                    },
                ],
            },
        ]

        self.assertDictListMatch(response_list, expected_images)

    def test_get_image_index_with_limit(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images?limit=3')
        response = self.controller.index(request)
        response_list = response["images"]
        response_links = response["images_links"]

        alternate = "%s/fake/images/%s"

        expected_images = [
            {
                "id": "123",
                "name": "public image",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/123",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/123",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": alternate % (utils.generate_glance_url(), 123),
                    },
                ],
            },
            {
                "id": "124",
                "name": "queued snapshot",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/124",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/124",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": alternate % (utils.generate_glance_url(), 124),
                    },
                ],
            },
            {
                "id": "125",
                "name": "saving snapshot",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/images/125",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/images/125",
                    },
                    {
                        "rel": "alternate",
                        "type": "application/vnd.openstack.image",
                        "href": alternate % (utils.generate_glance_url(), 125),
                    },
                ],
            },
        ]

        self.assertDictListMatch(response_list, expected_images)
        self.assertEqual(response_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/v2/fake/images', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertDictMatch({'limit': ['3'], 'marker': ['125']}, params)

    def test_get_image_index_with_limit_and_extra_params(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images?limit=3&extra=bo')
        response = self.controller.index(request)
        response_links = response["images_links"]

        self.assertEqual(response_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/v2/fake/images', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertDictMatch(
            {'limit': ['3'], 'marker': ['125'], 'extra': ['bo']},
            params)

    def test_get_image_index_with_big_limit(self):
        """
        Make sure we don't get images_links if limit is set
        and the number of images returned is < limit
        """
        request = fakes.HTTPRequest.blank('/v2/fake/images?limit=30')
        response = self.controller.index(request)

        self.assertEqual(response.keys(), ['images'])
        self.assertEqual(len(response['images']), 8)

    def test_get_image_details(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail')
        response = self.controller.detail(request)
        response_list = response["images"]

        server_uuid = "aa640691-d1a7-4a67-9d3c-d35ee6b3cc74"
        server_href = "http://localhost/v2/servers/" + server_uuid
        server_bookmark = "http://localhost/servers/" + server_uuid
        alternate = "%s/fake/images/%s"

        expected = [{
            'id': '123',
            'name': 'public image',
            'metadata': {'key1': 'value1'},
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'ACTIVE',
            'progress': 100,
            'minDisk': 10,
            'minRam': 128,
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/123",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/123",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": alternate % (utils.generate_glance_url(), 123),
            }],
        },
        {
            'id': '124',
            'name': 'queued snapshot',
            'metadata': {
                u'instance_ref': server_href,
                u'user_id': u'fake',
            },
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'SAVING',
            'progress': 25,
            'minDisk': 0,
            'minRam': 0,
            'server': {
                'id': server_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_href,
                },
                {
                    "rel": "bookmark",
                    "href": server_bookmark,
                }],
            },
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/124",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/124",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": alternate % (utils.generate_glance_url(), 124),
            }],
        },
        {
            'id': '125',
            'name': 'saving snapshot',
            'metadata': {
                u'instance_ref': server_href,
                u'user_id': u'fake',
            },
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'SAVING',
            'progress': 50,
            'minDisk': 0,
            'minRam': 0,
            'server': {
                'id': server_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_href,
                },
                {
                    "rel": "bookmark",
                    "href": server_bookmark,
                }],
            },
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/125",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/125",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": "%s/fake/images/125" % utils.generate_glance_url()
            }],
        },
        {
            'id': '126',
            'name': 'active snapshot',
            'metadata': {
                u'instance_ref': server_href,
                u'user_id': u'fake',
            },
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'ACTIVE',
            'progress': 100,
            'minDisk': 0,
            'minRam': 0,
            'server': {
                'id': server_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_href,
                },
                {
                    "rel": "bookmark",
                    "href": server_bookmark,
                }],
            },
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/126",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/126",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": "%s/fake/images/126" % utils.generate_glance_url()
            }],
        },
        {
            'id': '127',
            'name': 'killed snapshot',
            'metadata': {
                u'instance_ref': server_href,
                u'user_id': u'fake',
            },
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'ERROR',
            'progress': 0,
            'minDisk': 0,
            'minRam': 0,
            'server': {
                'id': server_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_href,
                },
                {
                    "rel": "bookmark",
                    "href": server_bookmark,
                }],
            },
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/127",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/127",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": "%s/fake/images/127" % utils.generate_glance_url()
            }],
        },
        {
            'id': '128',
            'name': 'deleted snapshot',
            'metadata': {
                u'instance_ref': server_href,
                u'user_id': u'fake',
            },
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'DELETED',
            'progress': 0,
            'minDisk': 0,
            'minRam': 0,
            'server': {
                'id': server_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_href,
                },
                {
                    "rel": "bookmark",
                    "href": server_bookmark,
                }],
            },
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/128",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/128",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": "%s/fake/images/128" % utils.generate_glance_url()
            }],
        },
        {
            'id': '129',
            'name': 'pending_delete snapshot',
            'metadata': {
                u'instance_ref': server_href,
                u'user_id': u'fake',
            },
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'DELETED',
            'progress': 0,
            'minDisk': 0,
            'minRam': 0,
            'server': {
                'id': server_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_href,
                },
                {
                    "rel": "bookmark",
                    "href": server_bookmark,
                }],
            },
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/129",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/129",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": "%s/fake/images/129" % utils.generate_glance_url()
            }],
        },
        {
            'id': '130',
            'name': None,
            'metadata': {},
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'ACTIVE',
            'progress': 100,
            'minDisk': 0,
            'minRam': 0,
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/130",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/130",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": "%s/fake/images/130" % utils.generate_glance_url()
            }],
        },
        ]

        self.assertDictListMatch(expected, response_list)

    def test_get_image_details_with_limit(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail?limit=2')
        response = self.controller.detail(request)
        response_list = response["images"]
        response_links = response["images_links"]

        server_uuid = "aa640691-d1a7-4a67-9d3c-d35ee6b3cc74"
        server_href = "http://localhost/v2/servers/" + server_uuid
        server_bookmark = "http://localhost/servers/" + server_uuid
        alternate = "%s/fake/images/%s"

        expected = [{
            'id': '123',
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
                "href": "http://localhost/v2/fake/images/123",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/123",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": alternate % (utils.generate_glance_url(), 123),
            }],
        },
        {
            'id': '124',
            'name': 'queued snapshot',
            'metadata': {
                u'instance_ref': server_href,
                u'user_id': u'fake',
            },
            'updated': NOW_API_FORMAT,
            'created': NOW_API_FORMAT,
            'status': 'SAVING',
            'minDisk': 0,
            'progress': 25,
            'minRam': 0,
            'server': {
                'id': server_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_href,
                },
                {
                    "rel": "bookmark",
                    "href": server_bookmark,
                }],
            },
            "links": [{
                "rel": "self",
                "href": "http://localhost/v2/fake/images/124",
            },
            {
                "rel": "bookmark",
                "href": "http://localhost/fake/images/124",
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": alternate % (utils.generate_glance_url(), 124),
            }],
        }]

        self.assertDictListMatch(expected, response_list)

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/v2/fake/images', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)

        self.assertDictMatch({'limit': ['2'], 'marker': ['124']}, params)

    def test_image_filter_with_name(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'name': 'testname'}
        request = fakes.HTTPRequest.blank('/v2/images?name=testname')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_filter_with_min_ram(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'min_ram': '0'}
        request = fakes.HTTPRequest.blank('/v2/images?minRam=0')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_filter_with_min_disk(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'min_disk': '7'}
        request = fakes.HTTPRequest.blank('/v2/images?minDisk=7')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_filter_with_status(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'status': 'ACTIVE'}
        request = fakes.HTTPRequest.blank('/v2/images?status=ACTIVE')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_filter_with_property(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'property-test': '3'}
        request = fakes.HTTPRequest.blank('/v2/images?property-test=3')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_filter_server(self):
        image_service = self.mox.CreateMockAnything()
        uuid = 'fa95aaf5-ab3b-4cd8-88c0-2be7dd051aaf'
        ref = 'http://localhost:8774/servers/' + uuid
        filters = {'property-instance_ref': ref}
        request = fakes.HTTPRequest.blank('/v2/images?server=' + ref)
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_filter_changes_since(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'changes-since': '2011-01-24T17:08Z'}
        request = fakes.HTTPRequest.blank('/v2/images?changes-since='
                                          '2011-01-24T17:08Z')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_filter_with_type(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'property-image_type': 'BASE'}
        request = fakes.HTTPRequest.blank('/v2/images?type=BASE')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_filter_not_supported(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'status': 'ACTIVE'}
        request = fakes.HTTPRequest.blank('/v2/images?status=ACTIVE&'
                                          'UNSUPPORTEDFILTER=testname')
        context = request.environ['nova.context']
        image_service.detail(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.detail(request)
        self.mox.VerifyAll()

    def test_image_no_filters(self):
        image_service = self.mox.CreateMockAnything()
        filters = {}
        request = fakes.HTTPRequest.blank('/v2/images')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_detail_filter_with_name(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'name': 'testname'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail'
                                          '?name=testname')
        context = request.environ['nova.context']
        image_service.detail(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.detail(request)
        self.mox.VerifyAll()

    def test_image_detail_filter_with_status(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'status': 'ACTIVE'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail'
                                          '?status=ACTIVE')
        context = request.environ['nova.context']
        image_service.detail(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.detail(request)
        self.mox.VerifyAll()

    def test_image_detail_filter_with_property(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'property-test': '3'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail'
                                          '?property-test=3')
        context = request.environ['nova.context']
        image_service.detail(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.detail(request)
        self.mox.VerifyAll()

    def test_image_detail_filter_server(self):
        image_service = self.mox.CreateMockAnything()
        uuid = 'fa95aaf5-ab3b-4cd8-88c0-2be7dd051aaf'
        ref = 'http://localhost:8774/servers/' + uuid
        url = '/v2/fake/images/detail?server=' + ref
        filters = {'property-instance_ref': ref}
        request = fakes.HTTPRequest.blank(url)
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_detail_filter_changes_since(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'changes-since': '2011-01-24T17:08Z'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail'
                                          '?changes-since=2011-01-24T17:08Z')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_detail_filter_with_type(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'property-image_type': 'BASE'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail?type=BASE')
        context = request.environ['nova.context']
        image_service.index(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.index(request)
        self.mox.VerifyAll()

    def test_image_detail_filter_not_supported(self):
        image_service = self.mox.CreateMockAnything()
        filters = {'status': 'ACTIVE'}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail?status='
                                          'ACTIVE&UNSUPPORTEDFILTER=testname')
        context = request.environ['nova.context']
        image_service.detail(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.detail(request)
        self.mox.VerifyAll()

    def test_image_detail_no_filters(self):
        image_service = self.mox.CreateMockAnything()
        filters = {}
        request = fakes.HTTPRequest.blank('/v2/fake/images/detail')
        context = request.environ['nova.context']
        image_service.detail(context, filters=filters).AndReturn([])
        self.mox.ReplayAll()
        controller = images.Controller(image_service=image_service)
        controller.detail(request)
        self.mox.VerifyAll()

    def test_generate_alternate_link(self):
        view = images_view.ViewBuilder()
        request = fakes.HTTPRequest.blank('/v2/fake/images/1')
        generated_url = view._get_alternate_link(request, 1)
        actual_url = "%s/fake/images/1" % utils.generate_glance_url()
        self.assertEqual(generated_url, actual_url)

    def test_delete_image(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images/124')
        request.method = 'DELETE'
        response = self.controller.delete(request, '124')
        self.assertEqual(response.status_int, 204)

    def test_delete_image_not_found(self):
        request = fakes.HTTPRequest.blank('/v2/fake/images/300')
        request.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, request, '300')


class ImageXMLSerializationTest(test.TestCase):

    TIMESTAMP = "2010-10-11T10:30:22Z"
    SERVER_UUID = 'aa640691-d1a7-4a67-9d3c-d35ee6b3cc74'
    SERVER_HREF = 'http://localhost/v2/servers/' + SERVER_UUID
    SERVER_BOOKMARK = 'http://localhost/servers/' + SERVER_UUID
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
