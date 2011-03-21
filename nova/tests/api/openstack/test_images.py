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
import shutil
import tempfile

import stubout
import webob

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

        fixture = {'name': 'test image',
                   'updated': None,
                   'created': None,
                   'status': None,
                   'instance_id': None,
                   'progress': None}

        num_images = len(self.service.index(self.context))

        id = self.service.create(self.context, fixture)['id']

        self.assertNotEquals(None, id)
        self.assertEquals(num_images + 1,
                          len(self.service.index(self.context)))

    def test_create_and_show_non_existing_image(self):

        fixture = {'name': 'test image',
                   'updated': None,
                   'created': None,
                   'status': None,
                   'instance_id': None,
                   'progress': None}

        num_images = len(self.service.index(self.context))

        id = self.service.create(self.context, fixture)['id']

        self.assertNotEquals(None, id)

        self.assertRaises(exception.NotFound,
                          self.service.show,
                          self.context,
                          'bad image id')

    def test_update(self):

        fixture = {'name': 'test image',
                   'updated': None,
                   'created': None,
                   'status': None,
                   'instance_id': None,
                   'progress': None}

        id = self.service.create(self.context, fixture)['id']

        fixture['status'] = 'in progress'

        self.service.update(self.context, id, fixture)
        new_image_data = self.service.show(self.context, id)
        self.assertEquals('in progress', new_image_data['status'])

    def test_delete(self):

        fixtures = [
                    {'name': 'test image 1',
                     'updated': None,
                     'created': None,
                     'status': None,
                     'instance_id': None,
                     'progress': None},
                    {'name': 'test image 2',
                     'updated': None,
                     'created': None,
                     'status': None,
                     'instance_id': None,
                     'progress': None}]

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


class GlanceImageServiceTest(test.TestCase,
                             BaseImageServiceTests):

    """Tests the local image service"""

    def setUp(self):
        super(GlanceImageServiceTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_glance(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        service_class = 'nova.image.glance.GlanceImageService'
        self.service = utils.import_object(service_class)
        self.context = context.RequestContext(None, None)
        self.service.delete_all()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(GlanceImageServiceTest, self).tearDown()


class ImageControllerWithGlanceServiceTest(test.TestCase):

    """Test of the OpenStack API /images application controller"""

    # Registered images at start of each test.
    now = datetime.datetime.utcnow()
    IMAGE_FIXTURES = [
        {'id': '23g2ogk23k4hhkk4k42l',
         'imageId': '23g2ogk23k4hhkk4k42l',
         'name': 'public image #1',
         'created_at': now.isoformat(),
         'updated_at': now.isoformat(),
         'deleted_at': None,
         'deleted': False,
         'is_public': True,
         'status': 'available',
         'image_type': 'kernel'},
        {'id': 'slkduhfas73kkaskgdas',
         'imageId': 'slkduhfas73kkaskgdas',
         'name': 'public image #2',
         'created_at': now.isoformat(),
         'updated_at': now.isoformat(),
         'deleted_at': None,
         'deleted': False,
         'is_public': True,
         'status': 'available',
         'image_type': 'ramdisk'}]

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
        fakes.stub_out_glance(self.stubs, initial_fixtures=self.IMAGE_FIXTURES)

    def tearDown(self):
        self.stubs.UnsetAll()
        FLAGS.image_service = self.orig_image_service
        super(ImageControllerWithGlanceServiceTest, self).tearDown()

    def test_get_image_index(self):
        req = webob.Request.blank('/v1.0/images')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        fixture_index = [dict(id=f['id'], name=f['name']) for f
                         in self.IMAGE_FIXTURES]

        for image in res_dict['images']:
            self.assertEquals(1, fixture_index.count(image),
                              "image %s not in fixture index!" % str(image))

    def test_get_image_details(self):
        req = webob.Request.blank('/v1.0/images/detail')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        for image in self.IMAGE_FIXTURES:
            expected = {
                'id': abs(hash(image['imageId'])),
                'name': image['name'],
                'status': 'active',
            }
            self.assertTrue(expected in res_dict['images'])

    def test_show_image(self):
        expected = self.IMAGE_FIXTURES[0]
        id = abs(hash(expected['id']))
        expected_time = self.now.strftime('%Y-%m-%dT%H:%M:%SZ')
        req = webob.Request.blank('/v1.0/images/%s' % id)
        res = req.get_response(fakes.wsgi_app())
        actual = json.loads(res.body)['image']
        self.assertEqual(expected_time, actual['created_at'])
        self.assertEqual(expected_time, actual['updated_at'])
