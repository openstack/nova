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

import copy
import json
import os
import shutil
import tempfile
import xml.dom.minidom as minidom

import mox
import stubout
import webob

from glance import client as glance_client
from nova import context
from nova import exception
from nova import flags
from nova import test
from nova import utils
import nova.api.openstack
from nova.api.openstack import images
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS


class _BaseImageServiceTests(test.TestCase):
    """Tasks to test for all image services"""

    def __init__(self, *args, **kwargs):
        super(_BaseImageServiceTests, self).__init__(*args, **kwargs)
        self.service = None
        self.context = None

    def test_create(self):
        fixture = self._make_fixture('test image')
        num_images = len(self.service.index(self.context))

        image_id = self.service.create(self.context, fixture)['id']

        self.assertNotEquals(None, image_id)
        self.assertEquals(num_images + 1,
                          len(self.service.index(self.context)))

    def test_create_and_show_non_existing_image(self):
        fixture = self._make_fixture('test image')
        num_images = len(self.service.index(self.context))

        image_id = self.service.create(self.context, fixture)['id']

        self.assertNotEquals(None, image_id)
        self.assertRaises(exception.NotFound,
                          self.service.show,
                          self.context,
                          'bad image id')

    def test_create_and_show_non_existing_image_by_name(self):
        fixture = self._make_fixture('test image')
        num_images = len(self.service.index(self.context))

        image_id = self.service.create(self.context, fixture)['id']

        self.assertNotEquals(None, image_id)
        self.assertRaises(exception.ImageNotFound,
                          self.service.show_by_name,
                          self.context,
                          'bad image id')

    def test_update(self):
        fixture = self._make_fixture('test image')
        image_id = self.service.create(self.context, fixture)['id']
        fixture['status'] = 'in progress'

        self.service.update(self.context, image_id, fixture)

        new_image_data = self.service.show(self.context, image_id)
        self.assertEquals('in progress', new_image_data['status'])

    def test_delete(self):
        fixture1 = self._make_fixture('test image 1')
        fixture2 = self._make_fixture('test image 2')
        fixtures = [fixture1, fixture2]

        num_images = len(self.service.index(self.context))
        self.assertEquals(0, num_images, str(self.service.index(self.context)))

        ids = []
        for fixture in fixtures:
            new_id = self.service.create(self.context, fixture)['id']
            ids.append(new_id)

        num_images = len(self.service.index(self.context))
        self.assertEquals(2, num_images, str(self.service.index(self.context)))

        self.service.delete(self.context, ids[0])

        num_images = len(self.service.index(self.context))
        self.assertEquals(1, num_images)

    def test_index(self):
        fixture = self._make_fixture('test image')
        image_id = self.service.create(self.context, fixture)['id']
        image_metas = self.service.index(self.context)
        expected = [{'id': 'DONTCARE', 'name': 'test image'}]
        self.assertDictListMatch(image_metas, expected)

    @staticmethod
    def _make_fixture(name):
        fixture = {'name': name,
                   'updated': None,
                   'created': None,
                   'status': None,
                   'is_public': True}
        return fixture


class GlanceImageServiceTest(_BaseImageServiceTests):

    """Tests the Glance image service, in particular that metadata translation
    works properly.

    At a high level, the translations involved are:

        1. Glance -> ImageService - This is needed so we can support
           multple ImageServices (Glance, Local, etc)

        2. ImageService -> API - This is needed so we can support multple
           APIs (OpenStack, EC2)
    """
    def setUp(self):
        super(GlanceImageServiceTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_glance(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        service_class = 'nova.image.glance.GlanceImageService'
        self.service = utils.import_object(service_class)
        self.context = context.RequestContext(1, None)
        self.service.delete_all()
        self.sent_to_glance = {}
        fakes.stub_out_glance_add_image(self.stubs, self.sent_to_glance)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(GlanceImageServiceTest, self).tearDown()

    def test_create_with_instance_id(self):
        """Ensure instance_id is persisted as an image-property"""
        fixture = {'name': 'test image',
                   'is_public': False,
                   'properties': {'instance_id': '42', 'user_id': '1'}}

        image_id = self.service.create(self.context, fixture)['id']
        expected = fixture
        self.assertDictMatch(self.sent_to_glance['metadata'], expected)

        image_meta = self.service.show(self.context, image_id)
        expected = {'id': image_id,
                    'name': 'test image',
                    'is_public': False,
                    'properties': {'instance_id': '42', 'user_id': '1'}}
        self.assertDictMatch(image_meta, expected)

        image_metas = self.service.detail(self.context)
        self.assertDictMatch(image_metas[0], expected)

    def test_create_without_instance_id(self):
        """
        Ensure we can create an image without having to specify an
        instance_id. Public images are an example of an image not tied to an
        instance.
        """
        fixture = {'name': 'test image'}
        image_id = self.service.create(self.context, fixture)['id']

        expected = {'name': 'test image', 'properties': {}}
        self.assertDictMatch(self.sent_to_glance['metadata'], expected)

    def test_index_default_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture('TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.index(self.context)
        i = 0
        for meta in image_metas:
            expected = {'id': 'DONTCARE',
                        'name': 'TestImage %d' % (i)}
            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_index_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture('TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.index(self.context, marker=ids[1])
        self.assertEquals(len(image_metas), 8)
        i = 2
        for meta in image_metas:
            expected = {'id': 'DONTCARE',
                        'name': 'TestImage %d' % (i)}
            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_index_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture('TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.index(self.context, limit=3)
        self.assertEquals(len(image_metas), 3)

    def test_index_marker_and_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture('TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.index(self.context, marker=ids[3], limit=1)
        self.assertEquals(len(image_metas), 1)
        i = 4
        for meta in image_metas:
            expected = {'id': 'DONTCARE',
                        'name': 'TestImage %d' % (i)}
            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_detail_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture('TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, marker=ids[1])
        self.assertEquals(len(image_metas), 8)
        i = 2
        for meta in image_metas:
            expected = {
                'id': 'DONTCARE',
                'status': None,
                'is_public': True,
                'name': 'TestImage %d' % (i),
                'properties': {
                    'updated': None,
                    'created': None,
                },
            }

            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_detail_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture('TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, limit=3)
        self.assertEquals(len(image_metas), 3)

    def test_detail_marker_and_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture('TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, marker=ids[3], limit=3)
        self.assertEquals(len(image_metas), 3)
        i = 4
        for meta in image_metas:
            expected = {
                'id': 'DONTCARE',
                'status': None,
                'is_public': True,
                'name': 'TestImage %d' % (i),
                'properties': {
                    'updated': None, 'created': None},
            }
            self.assertDictMatch(meta, expected)
            i = i + 1


class ImageControllerWithGlanceServiceTest(test.TestCase):
    """
    Test of the OpenStack API /images application controller w/Glance.
    """
    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22"
    NOW_API_FORMAT = "2010-10-11T10:30:22Z"

    def setUp(self):
        """Run before each test."""
        super(ImageControllerWithGlanceServiceTest, self).setUp()
        self.orig_image_service = FLAGS.image_service
        FLAGS.image_service = 'nova.image.glance.GlanceImageService'
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        self.fixtures = self._make_image_fixtures()
        fakes.stub_out_glance(self.stubs, initial_fixtures=self.fixtures)
        fakes.stub_out_compute_api_snapshot(self.stubs)

    def tearDown(self):
        """Run after each test."""
        self.stubs.UnsetAll()
        FLAGS.image_service = self.orig_image_service
        super(ImageControllerWithGlanceServiceTest, self).tearDown()

    def _applicable_fixture(self, fixture, user_id):
        """Determine if this fixture is applicable for given user id."""
        is_public = fixture["is_public"]
        try:
            uid = int(fixture["properties"]["user_id"])
        except KeyError:
            uid = None
        return uid == user_id or is_public

    def test_get_image_index(self):
        request = webob.Request.blank('/v1.0/images')
        response = request.get_response(fakes.wsgi_app())

        response_dict = json.loads(response.body)
        response_list = response_dict["images"]

        expected = [{'id': 123, 'name': 'public image'},
                    {'id': 124, 'name': 'queued backup'},
                    {'id': 125, 'name': 'saving backup'},
                    {'id': 126, 'name': 'active backup'},
                    {'id': 127, 'name': 'killed backup'},
                    {'id': 129, 'name': None}]

        self.assertDictListMatch(response_list, expected)

    def test_get_image(self):
        request = webob.Request.blank('/v1.0/images/123')
        response = request.get_response(fakes.wsgi_app())

        self.assertEqual(200, response.status_int)

        actual_image = json.loads(response.body)

        expected_image = {
            "image": {
                "id": 123,
                "name": "public image",
                "updated": self.NOW_API_FORMAT,
                "created": self.NOW_API_FORMAT,
                "status": "ACTIVE",
            },
        }

        self.assertEqual(expected_image, actual_image)

    def test_get_image_v1_1(self):
        request = webob.Request.blank('/v1.1/images/123')
        response = request.get_response(fakes.wsgi_app())

        actual_image = json.loads(response.body)

        href = "http://localhost/v1.1/images/123"

        expected_image = {
            "image": {
                "id": 123,
                "name": "public image",
                "updated": self.NOW_API_FORMAT,
                "created": self.NOW_API_FORMAT,
                "status": "ACTIVE",
                "links": [{
                    "rel": "self",
                    "href": href,
                },
                {
                    "rel": "bookmark",
                    "type": "application/json",
                    "href": href,
                },
                {
                    "rel": "bookmark",
                    "type": "application/xml",
                    "href": href,
                }],
            },
        }

        self.assertEqual(expected_image, actual_image)

    def test_get_image_xml(self):
        request = webob.Request.blank('/v1.0/images/123')
        request.accept = "application/xml"
        response = request.get_response(fakes.wsgi_app())

        actual_image = minidom.parseString(response.body.replace("  ", ""))

        expected_now = self.NOW_API_FORMAT
        expected_image = minidom.parseString("""
            <image id="123"
                    name="public image"
                    updated="%(expected_now)s"
                    created="%(expected_now)s"
                    status="ACTIVE"
                    xmlns="http://docs.rackspacecloud.com/servers/api/v1.0" />
        """ % (locals()))

        self.assertEqual(expected_image.toxml(), actual_image.toxml())

    def test_get_image_xml_no_name(self):
        request = webob.Request.blank('/v1.0/images/129')
        request.accept = "application/xml"
        response = request.get_response(fakes.wsgi_app())

        actual_image = minidom.parseString(response.body.replace("  ", ""))

        expected_now = self.NOW_API_FORMAT
        expected_image = minidom.parseString("""
            <image id="129"
                    name="None"
                    updated="%(expected_now)s"
                    created="%(expected_now)s"
                    status="ACTIVE"
                    xmlns="http://docs.rackspacecloud.com/servers/api/v1.0" />
        """ % (locals()))

        self.assertEqual(expected_image.toxml(), actual_image.toxml())

    def test_get_image_v1_1_xml(self):
        request = webob.Request.blank('/v1.1/images/123')
        request.accept = "application/xml"
        response = request.get_response(fakes.wsgi_app())

        actual_image = minidom.parseString(response.body.replace("  ", ""))

        expected_href = "http://localhost/v1.1/images/123"
        expected_now = self.NOW_API_FORMAT
        expected_image = minidom.parseString("""
        <image id="123"
                name="public image"
                updated="%(expected_now)s"
                created="%(expected_now)s"
                status="ACTIVE"
                xmlns="http://docs.openstack.org/compute/api/v1.1">
            <links>
                <link href="%(expected_href)s" rel="self"/>
                <link href="%(expected_href)s" rel="bookmark"
                    type="application/json" />
                <link href="%(expected_href)s" rel="bookmark"
                    type="application/xml" />
            </links>
        </image>
        """.replace("  ", "") % (locals()))

        self.assertEqual(expected_image.toxml(), actual_image.toxml())

    def test_get_image_404_json(self):
        request = webob.Request.blank('/v1.0/images/NonExistantImage')
        response = request.get_response(fakes.wsgi_app())
        self.assertEqual(404, response.status_int)

        expected = {
            "itemNotFound": {
                "message": "Image not found.",
                "code": 404,
            },
        }

        actual = json.loads(response.body)

        self.assertEqual(expected, actual)

    def test_get_image_404_xml(self):
        request = webob.Request.blank('/v1.0/images/NonExistantImage')
        request.accept = "application/xml"
        response = request.get_response(fakes.wsgi_app())
        self.assertEqual(404, response.status_int)

        expected = minidom.parseString("""
            <itemNotFound code="404"
                    xmlns="http://docs.rackspacecloud.com/servers/api/v1.0">
                <message>
                    Image not found.
                </message>
            </itemNotFound>
        """.replace("  ", ""))

        actual = minidom.parseString(response.body.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_get_image_404_v1_1_json(self):
        request = webob.Request.blank('/v1.1/images/NonExistantImage')
        response = request.get_response(fakes.wsgi_app())
        self.assertEqual(404, response.status_int)

        expected = {
            "itemNotFound": {
                "message": "Image not found.",
                "code": 404,
            },
        }

        actual = json.loads(response.body)

        self.assertEqual(expected, actual)

    def test_get_image_404_v1_1_xml(self):
        request = webob.Request.blank('/v1.1/images/NonExistantImage')
        request.accept = "application/xml"
        response = request.get_response(fakes.wsgi_app())
        self.assertEqual(404, response.status_int)

        # NOTE(justinsb): I believe this should still use the v1.0 XSD,
        # because the element hasn't changed definition
        expected = minidom.parseString("""
            <itemNotFound code="404"
                    xmlns="http://docs.rackspacecloud.com/servers/api/v1.0">
                <message>
                    Image not found.
                </message>
            </itemNotFound>
        """.replace("  ", ""))

        actual = minidom.parseString(response.body.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_get_image_index_v1_1(self):
        request = webob.Request.blank('/v1.1/images')
        response = request.get_response(fakes.wsgi_app())

        response_dict = json.loads(response.body)
        response_list = response_dict["images"]

        fixtures = copy.copy(self.fixtures)

        for image in fixtures:
            if not self._applicable_fixture(image, 1):
                fixtures.remove(image)
                continue

            href = "http://localhost/v1.1/images/%s" % image["id"]
            test_image = {
                "id": image["id"],
                "name": image["name"],
                "links": [{
                    "rel": "self",
                    "href": "http://localhost/v1.1/images/%s" % image["id"],
                },
                {
                    "rel": "bookmark",
                    "type": "application/json",
                    "href": href,
                },
                {
                    "rel": "bookmark",
                    "type": "application/xml",
                    "href": href,
                }],
            }
            self.assertTrue(test_image in response_list)

        self.assertEqual(len(response_list), len(fixtures))

    def test_get_image_details(self):
        request = webob.Request.blank('/v1.0/images/detail')
        response = request.get_response(fakes.wsgi_app())

        response_dict = json.loads(response.body)
        response_list = response_dict["images"]

        expected = [{
            'id': 123,
            'name': 'public image',
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'ACTIVE',
        },
        {
            'id': 124,
            'name': 'queued backup',
            'serverId': 42,
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'QUEUED',
        },
        {
            'id': 125,
            'name': 'saving backup',
            'serverId': 42,
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'SAVING',
            'progress': 0,
        },
        {
            'id': 126,
            'name': 'active backup',
            'serverId': 42,
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'ACTIVE'
        },
        {
            'id': 127,
            'name': 'killed backup',
            'serverId': 42,
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'FAILED',
        },
        {
            'id': 129,
            'name': None,
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'ACTIVE',
        }]

        self.assertDictListMatch(expected, response_list)

    def test_get_image_details_v1_1(self):
        request = webob.Request.blank('/v1.1/images/detail')
        response = request.get_response(fakes.wsgi_app())

        response_dict = json.loads(response.body)
        response_list = response_dict["images"]

        expected = [{
            'id': 123,
            'name': 'public image',
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'ACTIVE',
            "links": [{
                "rel": "self",
                "href": "http://localhost/v1.1/images/123",
            },
            {
                "rel": "bookmark",
                "type": "application/json",
                "href": "http://localhost/v1.1/images/123",
            },
            {
                "rel": "bookmark",
                "type": "application/xml",
                "href": "http://localhost/v1.1/images/123",
            }],
        },
        {
            'id': 124,
            'name': 'queued backup',
            'serverRef': "http://localhost/v1.1/servers/42",
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'QUEUED',
            "links": [{
                "rel": "self",
                "href": "http://localhost/v1.1/images/124",
            },
            {
                "rel": "bookmark",
                "type": "application/json",
                "href": "http://localhost/v1.1/images/124",
            },
            {
                "rel": "bookmark",
                "type": "application/xml",
                "href": "http://localhost/v1.1/images/124",
            }],
        },
        {
            'id': 125,
            'name': 'saving backup',
            'serverRef': "http://localhost/v1.1/servers/42",
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'SAVING',
            'progress': 0,
            "links": [{
                "rel": "self",
                "href": "http://localhost/v1.1/images/125",
            },
            {
                "rel": "bookmark",
                "type": "application/json",
                "href": "http://localhost/v1.1/images/125",
            },
            {
                "rel": "bookmark",
                "type": "application/xml",
                "href": "http://localhost/v1.1/images/125",
            }],
        },
        {
            'id': 126,
            'name': 'active backup',
            'serverRef': "http://localhost/v1.1/servers/42",
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'ACTIVE',
            "links": [{
                "rel": "self",
                "href": "http://localhost/v1.1/images/126",
            },
            {
                "rel": "bookmark",
                "type": "application/json",
                "href": "http://localhost/v1.1/images/126",
            },
            {
                "rel": "bookmark",
                "type": "application/xml",
                "href": "http://localhost/v1.1/images/126",
            }],
        },
        {
            'id': 127,
            'name': 'killed backup',
            'serverRef': "http://localhost/v1.1/servers/42",
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'FAILED',
            "links": [{
                "rel": "self",
                "href": "http://localhost/v1.1/images/127",
            },
            {
                "rel": "bookmark",
                "type": "application/json",
                "href": "http://localhost/v1.1/images/127",
            },
            {
                "rel": "bookmark",
                "type": "application/xml",
                "href": "http://localhost/v1.1/images/127",
            }],
        },
        {
            'id': 129,
            'name': None,
            'updated': self.NOW_API_FORMAT,
            'created': self.NOW_API_FORMAT,
            'status': 'ACTIVE',
            "links": [{
                "rel": "self",
                "href": "http://localhost/v1.1/images/129",
            },
            {
                "rel": "bookmark",
                "type": "application/json",
                "href": "http://localhost/v1.1/images/129",
            },
            {
                "rel": "bookmark",
                "type": "application/xml",
                "href": "http://localhost/v1.1/images/129",
            }],
        },
        ]

        self.assertDictListMatch(expected, response_list)

    def test_image_filter_with_name(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {'name': 'testname'}
        image_service.index(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images?name=testname')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.index(request)
        mocker.VerifyAll()

    def test_image_filter_with_status(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {'status': 'ACTIVE'}
        image_service.index(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images?status=ACTIVE')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.index(request)
        mocker.VerifyAll()

    def test_image_filter_with_property(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {'property-test': '3'}
        image_service.index(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images?property-test=3')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.index(request)
        mocker.VerifyAll()

    def test_image_filter_not_supported(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {'status': 'ACTIVE'}
        image_service.index(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images?status=ACTIVE&UNSUPPORTEDFILTER=testname')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.index(request)
        mocker.VerifyAll()

    def test_image_no_filters(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {}
        image_service.index(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.index(request)
        mocker.VerifyAll()

    def test_image_detail_filter_with_name(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {'name': 'testname'}
        image_service.detail(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images/detail?name=testname')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.detail(request)
        mocker.VerifyAll()

    def test_image_detail_filter_with_status(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {'status': 'ACTIVE'}
        image_service.detail(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images/detail?status=ACTIVE')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.detail(request)
        mocker.VerifyAll()

    def test_image_detail_filter_with_property(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {'property-test': '3'}
        image_service.detail(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images/detail?property-test=3')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.detail(request)
        mocker.VerifyAll()

    def test_image_detail_filter_not_supported(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {'status': 'ACTIVE'}
        image_service.detail(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images/detail?status=ACTIVE&UNSUPPORTEDFILTER=testname')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.detail(request)
        mocker.VerifyAll()

    def test_image_detail_no_filters(self):
        mocker = mox.Mox()
        image_service = mocker.CreateMockAnything()
        context = object()
        filters = {}
        image_service.detail(
            context, filters=filters, marker=0, limit=0).AndReturn([])
        mocker.ReplayAll()
        request = webob.Request.blank(
            '/v1.1/images/detail')
        request.environ['nova.context'] = context
        controller = images.ControllerV11(image_service=image_service)
        controller.detail(request)
        mocker.VerifyAll()

    def test_get_image_found(self):
        req = webob.Request.blank('/v1.0/images/123')
        res = req.get_response(fakes.wsgi_app())
        image_meta = json.loads(res.body)['image']
        expected = {'id': 123, 'name': 'public image',
                    'updated': self.NOW_API_FORMAT,
                    'created': self.NOW_API_FORMAT, 'status': 'ACTIVE'}
        self.assertDictMatch(image_meta, expected)

    def test_get_image_non_existent(self):
        req = webob.Request.blank('/v1.0/images/4242')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_get_image_not_owned(self):
        """We should return a 404 if we request an image that doesn't belong
        to us
        """
        req = webob.Request.blank('/v1.0/images/128')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_create_image(self):

        body = dict(image=dict(serverId='123', name='Backup 1'))
        req = webob.Request.blank('/v1.0/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, response.status_int)

    def test_create_image_no_server_id(self):

        body = dict(image=dict(name='Backup 1'))
        req = webob.Request.blank('/v1.0/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)

    def test_create_image_v1_1(self):

        body = dict(image=dict(serverRef='123', name='Backup 1'))
        req = webob.Request.blank('/v1.1/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, response.status_int)

    def test_create_image_v1_1_xml_serialization(self):

        body = dict(image=dict(serverRef='123', name='Backup 1'))
        req = webob.Request.blank('/v1.1/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        req.headers["accept"] = "application/xml"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, response.status_int)
        resp_xml = minidom.parseString(response.body.replace("  ", ""))
        expected_href = "http://localhost/v1.1/images/123"
        expected_image = minidom.parseString("""
            <image
                   created="None"
                   id="123"
                   name="None"
                   serverRef="http://localhost/v1.1/servers/123"
                   status="ACTIVE"
                   updated="None"
                   xmlns="http://docs.openstack.org/compute/api/v1.1">
                <links>
                    <link href="%(expected_href)s" rel="self"/>
                    <link href="%(expected_href)s" rel="bookmark"
                        type="application/json" />
                    <link href="%(expected_href)s" rel="bookmark"
                        type="application/xml" />
                </links>
            </image>
        """.replace("  ", "") % (locals()))

        self.assertEqual(expected_image.toxml(), resp_xml.toxml())

    def test_create_image_v1_1_no_server_ref(self):

        body = dict(image=dict(name='Backup 1'))
        req = webob.Request.blank('/v1.1/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)

    @classmethod
    def _make_image_fixtures(cls):
        image_id = 123
        base_attrs = {'created_at': cls.NOW_GLANCE_FORMAT,
                      'updated_at': cls.NOW_GLANCE_FORMAT,
                      'deleted_at': None,
                      'deleted': False}

        fixtures = []

        def add_fixture(**kwargs):
            kwargs.update(base_attrs)
            fixtures.append(kwargs)

        # Public image
        add_fixture(id=image_id, name='public image', is_public=True,
                    status='active', properties={})
        image_id += 1

        # Backup for User 1
        backup_properties = {'instance_id': '42', 'user_id': '1'}
        for status in ('queued', 'saving', 'active', 'killed'):
            add_fixture(id=image_id, name='%s backup' % status,
                        is_public=False, status=status,
                        properties=backup_properties)
            image_id += 1

        # Backup for User 2
        other_backup_properties = {'instance_id': '43', 'user_id': '2'}
        add_fixture(id=image_id, name='someone elses backup', is_public=False,
                    status='active', properties=other_backup_properties)
        image_id += 1

        # Image without a name
        add_fixture(id=image_id, is_public=True, status='active',
                    properties={})
        image_id += 1

        return fixtures
