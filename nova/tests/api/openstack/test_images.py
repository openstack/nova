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
import logging
import unittest

import stubout
import webob

from nova import exception
from nova import flags
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
                   'serverId': None,
                   'progress': None}

        num_images = len(self.service.index())

        id = self.service.create(fixture)

        self.assertNotEquals(None, id)
        self.assertEquals(num_images + 1, len(self.service.index()))

    def test_create_and_show_non_existing_image(self):

        fixture = {'name': 'test image',
                   'updated': None,
                   'created': None,
                   'status': None,
                   'serverId': None,
                   'progress': None}

        num_images = len(self.service.index())

        id = self.service.create(fixture)

        self.assertNotEquals(None, id)

        self.assertRaises(exception.NotFound,
                          self.service.show,
                          'bad image id')

    def test_update(self):

        fixture = {'name': 'test image',
                   'updated': None,
                   'created': None,
                   'status': None,
                   'serverId': None,
                   'progress': None}

        id = self.service.create(fixture)

        fixture['status'] = 'in progress'
        
        self.service.update(id, fixture)
        new_image_data = self.service.show(id)
        self.assertEquals('in progress', new_image_data['status'])

    def test_delete(self):

        fixtures = [
                    {'name': 'test image 1',
                     'updated': None,
                     'created': None,
                     'status': None,
                     'serverId': None,
                     'progress': None},
                    {'name': 'test image 2',
                     'updated': None,
                     'created': None,
                     'status': None,
                     'serverId': None,
                     'progress': None}]

        num_images = len(self.service.index())
        self.assertEquals(0, num_images, str(self.service.index()))

        ids = []
        for fixture in fixtures:
            new_id = self.service.create(fixture)
            ids.append(new_id)

        num_images = len(self.service.index())
        self.assertEquals(2, num_images, str(self.service.index()))
        
        self.service.delete(ids[0])

        num_images = len(self.service.index())
        self.assertEquals(1, num_images)


class LocalImageServiceTest(unittest.TestCase,
                            BaseImageServiceTests):

    """Tests the local image service"""

    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        self.service = utils.import_object('nova.image.service.LocalImageService')

    def tearDown(self):
        self.service.delete_all()
        self.stubs.UnsetAll()


class GlanceImageServiceTest(unittest.TestCase,
                             BaseImageServiceTests):

    """Tests the local image service"""

    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_glance(self.stubs)
        self.service = utils.import_object('nova.image.service.GlanceImageService')
        self.service.delete_all()

    def tearDown(self):
        self.stubs.UnsetAll()


class ImageControllerWithGlanceServiceTest(unittest.TestCase):

    """Test of the OpenStack API /images application controller"""

    # Registered images at start of each test.

    IMAGE_FIXTURES = [
        {'id': '23g2ogk23k4hhkk4k42l',
         'name': 'public image #1',
         'created_at': str(datetime.datetime.utcnow()),
         'modified_at': str(datetime.datetime.utcnow()),
         'deleted_at': None,
         'deleted': False,
         'is_public': True,
         'status': 'available',
         'image_type': 'kernel'
        },
        {'id': 'slkduhfas73kkaskgdas',
         'name': 'public image #2',
         'created_at': str(datetime.datetime.utcnow()),
         'modified_at': str(datetime.datetime.utcnow()),
         'deleted_at': None,
         'deleted': False,
         'is_public': True,
         'status': 'available',
         'image_type': 'ramdisk'
        },
    ]

    def setUp(self):
        self.orig_image_service = FLAGS.image_service
        FLAGS.image_service = 'nova.image.service.GlanceImageService'
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fakes.stub_out_glance(self.stubs, initial_fixtures=self.IMAGE_FIXTURES)

    def tearDown(self):
        self.stubs.UnsetAll()
        FLAGS.image_service = self.orig_image_service

    def test_get_image_index(self):
        req = webob.Request.blank('/v1.0/images')
        res = req.get_response(nova.api.API())
        res_dict = json.loads(res.body)

        fixture_index = [dict(id=f['id'], name=f['name']) for f
                         in self.IMAGE_FIXTURES]

        for image in res_dict['images']:
            self.assertEquals(1, fixture_index.count(image), "image %s not in fixture index!" % str(image)) 

    def test_get_image_details(self):
        req = webob.Request.blank('/v1.0/images/detail')
        res = req.get_response(nova.api.API())
        res_dict = json.loads(res.body)

        for image in res_dict['images']:
            self.assertEquals(1, self.IMAGE_FIXTURES.count(image), "image %s not in fixtures!" % str(image))
