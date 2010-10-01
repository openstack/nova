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

from nova import utils
from nova.api.rackspace import images


#{ Fixtures


fixture_images = [
    {
     'name': 'image #1',
     'updated': None,
     'created': None,
     'status': None,
     'serverId': None,
     'progress': None},
    {
     'name': 'image #2',
     'updated': None,
     'created': None,
     'status': None,
     'serverId': None,
     'progress': None},
    {
     'name': 'image #3',
     'updated': None,
     'created': None,
     'status': None,
     'serverId': None,
     'progress': None}]


#}


class BaseImageServiceTests():

    """Tasks to test for all image services"""

    def test_create_and_index(self):
        for i in fixture_images:
            self.service.create(i)

        self.assertEquals(len(fixture_images), len(self.service.index()))

    def test_create_and_update(self):
        ids = {}
        temp = 0
        for i in fixture_images:
            ids[self.service.create(i)] = temp
            temp += 1

        self.assertEquals(len(fixture_images), len(self.service.index()))

        for image_id, num in ids.iteritems():
            new_data = fixture_images[num]
            new_data['updated'] = 'test' + str(num)
            self.service.update(image_id, new_data)

        images = self.service.index()

        for i in images:
            self.assertEquals('test' + str(ids[i['id']]),
                              i['updated'])

    def test_create_and_show(self):
        ids = {}
        temp = 0
        for i in fixture_images:
            ids[self.service.create(i)] = temp
            temp += 1

        for i in fixture_images:
            image = self.service.show(i['id'])
            index = ids[i['id']]
            self.assertEquals(image, fixture_images[index])


class LocalImageServiceTest(unittest.TestCase,
                            BaseImageServiceTests):

    """Tests the local image service"""

    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        self.service = utils.import_object('nova.image.service.LocalImageService')

    def tearDown(self):
        self.service.delete_all()
        self.stubs.UnsetAll()


#class GlanceImageServiceTest(unittest.TestCase,
#                             BaseImageServiceTests):
#
#    """Tests the local image service"""
#
#    def setUp(self):
#        self.stubs = stubout.StubOutForTesting()
#        self.service = utils.import_object('nova.image.service.GlanceImageService')
#
#    def tearDown(self):
#        self.service.delete_all()
#        self.stubs.UnsetAll()
