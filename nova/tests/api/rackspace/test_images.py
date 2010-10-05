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

import logging
import unittest

import stubout

from nova import exception
from nova import utils
from nova.api.rackspace import images
from nova.tests.api.rackspace import fakes


class BaseImageServiceTests():

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

        ids = []
        for fixture in fixtures:
            new_id = self.service.create(fixture)
            ids.append(new_id)

        num_images = len(self.service.index())
        self.assertEquals(2, num_images)
        
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

    def tearDown(self):
        self.service.delete_all()
        self.stubs.UnsetAll()
