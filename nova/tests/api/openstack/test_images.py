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

import json
import datetime
import os
import shutil
import tempfile

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


class BaseImageServiceTests(object):
    """Tasks to test for all image services"""

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
        fixture = {'name': 'test image',
                   'updated': None,
                   'created': None,
                   'status': None,
                   'is_public': True}
        return fixture


class LocalImageServiceTest(test.TestCase,
                            BaseImageServiceTests):

    """Tests the local image service"""

    def setUp(self):
        super(LocalImageServiceTest, self).setUp()
        self.tempdir = tempfile.mkdtemp()
        self.flags(images_path=self.tempdir)
        self.stubs = stubout.StubOutForTesting()
        service_class = 'nova.image.local.LocalImageService'
        self.service = utils.import_object(service_class)
        self.context = context.RequestContext(None, None)

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        self.stubs.UnsetAll()
        super(LocalImageServiceTest, self).tearDown()

    def test_get_all_ids_with_incorrect_directory_formats(self):
        # create some old-style image directories (starting with 'ami-')
        for x in [1, 2, 3]:
            tempfile.mkstemp(prefix='ami-', dir=self.tempdir)
        # create some valid image directories names
        for x in ["1485baed", "1a60f0ee",  "3123a73d"]:
            os.makedirs(os.path.join(self.tempdir, x))
        found_image_ids = self.service._ids()
        self.assertEqual(True, isinstance(found_image_ids, list))
        self.assertEqual(3, len(found_image_ids), len(found_image_ids))


class GlanceImageServiceTest(test.TestCase,
                             BaseImageServiceTests):

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

        expected = {'id': image_id,
                    'name': 'test image',
                    'is_public': False,
                    'properties': {'instance_id': '42', 'user_id': '1'}}
        self.assertDictMatch(self.sent_to_glance['metadata'], expected)

        image_meta = self.service.show(self.context, image_id)
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

        expected = {'id': image_id, 'name': 'test image', 'properties': {}}
        self.assertDictMatch(self.sent_to_glance['metadata'], expected)


class ImageControllerWithGlanceServiceTest(test.TestCase):

    """Test of the OpenStack API /images application controller"""

    # FIXME(sirp): The ImageService and API use two different formats for
    # timestamps. Ultimately, the ImageService should probably use datetime
    # objects
    NOW_SERVICE_STR = "2010-10-11T10:30:22"
    NOW_API_STR = "2010-10-11T10:30:22Z"

    def setUp(self):
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
        fixtures = self._make_image_fixtures()
        fakes.stub_out_glance(self.stubs, initial_fixtures=fixtures)

    def tearDown(self):
        self.stubs.UnsetAll()
        FLAGS.image_service = self.orig_image_service
        super(ImageControllerWithGlanceServiceTest, self).tearDown()

    def test_get_image_index(self):
        req = webob.Request.blank('/v1.0/images')
        res = req.get_response(fakes.wsgi_app())
        image_metas = json.loads(res.body)['images']

        expected = [{'id': 123, 'name': 'public image'},
                    {'id': 124, 'name': 'queued backup'},
                    {'id': 125, 'name': 'saving backup'},
                    {'id': 126, 'name': 'active backup'},
                    {'id': 127, 'name': 'killed backup'}]

        self.assertDictListMatch(image_metas, expected)

    def test_get_image_details(self):
        req = webob.Request.blank('/v1.0/images/detail')
        res = req.get_response(fakes.wsgi_app())
        image_metas = json.loads(res.body)['images']

        expected = [
            {'id': 123, 'name': 'public image', 'updated': self.NOW_API_STR,
             'created': self.NOW_API_STR, 'status': 'ACTIVE'},
            {'id': 124, 'name': 'queued backup', 'serverId': 42,
             'updated': self.NOW_API_STR, 'created': self.NOW_API_STR,
             'status': 'QUEUED'},
            {'id': 125, 'name': 'saving backup', 'serverId': 42,
             'updated': self.NOW_API_STR, 'created': self.NOW_API_STR,
             'status': 'SAVING', 'progress': 0},
            {'id': 126, 'name': 'active backup', 'serverId': 42,
             'updated': self.NOW_API_STR, 'created': self.NOW_API_STR,
             'status': 'ACTIVE'},
            {'id': 127, 'name': 'killed backup', 'serverId': 42,
             'updated': self.NOW_API_STR, 'created': self.NOW_API_STR,
             'status': 'FAILED'}
        ]

        self.assertDictListMatch(image_metas, expected)

    def test_get_image_found(self):
        req = webob.Request.blank('/v1.0/images/123')
        res = req.get_response(fakes.wsgi_app())
        image_meta = json.loads(res.body)['image']
        expected = {'id': 123, 'name': 'public image',
                    'updated': self.NOW_API_STR, 'created': self.NOW_API_STR,
                    'status': 'ACTIVE'}
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

    @classmethod
    def _make_image_fixtures(cls):
        image_id = 123
        base_attrs = {'created_at': cls.NOW_SERVICE_STR,
                      'updated_at': cls.NOW_SERVICE_STR,
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

        return fixtures
