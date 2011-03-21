# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Openstack LLC.
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


import datetime
import unittest

from nova.image import glance


class StubGlanceClient(object):

    def __init__(self, images, add_response=None, update_response=None):
        self.images = images
        self.add_response = add_response
        self.update_response = update_response

    def get_image_meta(self, id):
        return self.images[id]

    def get_images_detailed(self):
        return self.images.itervalues()

    def get_image(self, id):
        return self.images[id], []

    def add_image(self, metadata, data):
        return self.add_response

    def update_image(self, image_id, metadata, data):
        return self.update_response


class NullWriter(object):

    def write(self, *arg, **kwargs):
        pass


class TestGlanceImageServiceDatetimes(unittest.TestCase):

    def setUp(self):
        self.client = StubGlanceClient(None)
        self.service = glance.GlanceImageService(self.client)

    def test_show_passes_through_to_client(self):
        self.client.images = {'xyz': {'foo': 'bar'}}
        self.assertEqual(self.service.show({}, 'xyz'), {'foo': 'bar'})

    def test_detail_passes_through_to_client(self):
        self.client.images = {1: {'foo': 'bar'}}
        self.assertEqual(list(self.service.detail({})), [{'foo': 'bar'}])

    def test_show_makes_create_datetimes(self):
        create_time = datetime.datetime.utcnow()
        self.client.images = {'xyz': {
            'id': "id",
            'name': "my awesome image",
            'created_at': create_time.isoformat(),
        }}
        actual = self.service.show({}, 'xyz')
        self.assertEqual(actual['created_at'], create_time)

    def test_show_makes_update_datetimes(self):
        update_time = datetime.datetime.utcnow()
        self.client.images = {'abc': {
            'id': "id",
            'name': "my okay image",
            'updated_at': update_time.isoformat(),
        }}
        actual = self.service.show({}, 'abc')
        self.assertEqual(actual['updated_at'], update_time)

    def test_show_makes_delete_datetimes(self):
        delete_time = datetime.datetime.utcnow()
        self.client.images = {'123': {
            'id': "123",
            'name': "my lame image",
            'deleted_at': delete_time.isoformat(),
        }}
        actual = self.service.show({}, '123')
        self.assertEqual(actual['deleted_at'], delete_time)

    def test_show_handles_deleted_at_none(self):
        self.client.images = {'747': {
            'id': "747",
            'name': "not deleted",
            'deleted_at': None,
        }}
        actual = self.service.show({}, '747')
        self.assertEqual(actual['deleted_at'], None)

    def test_detail_handles_timestamps(self):
        now = datetime.datetime.utcnow()
        image1 = {
            'id': 1,
            'name': 'image 1',
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'deleted_at': None,
        }
        image2 = {
            'id': 2,
            'name': 'image 2',
            'deleted_at': now.isoformat(),
        }
        self.client.images = {1: image1, 2: image2}
        i1, i2 = self.service.detail({})
        self.assertEqual(i1['created_at'], now)
        self.assertEqual(i1['updated_at'], now)
        self.assertEqual(i1['deleted_at'], None)
        self.assertEqual(i2['deleted_at'], now)

    def test_get_handles_timestamps(self):
        now = datetime.datetime.utcnow()
        self.client.images = {'abcd': {
            'id': 'abcd',
            'name': 'nifty image',
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'deleted_at': now.isoformat(),
        }}
        actual = self.service.get({}, 'abcd', NullWriter())
        for attr in ('created_at', 'updated_at', 'deleted_at'):
            self.assertEqual(actual[attr], now)

    def test_get_handles_deleted_at_none(self):
        self.client.images = {'abcd': {'deleted_at': None}}
        actual = self.service.get({}, 'abcd', NullWriter())
        self.assertEqual(actual['deleted_at'], None)

    def test_create_handles_timestamps(self):
        now = datetime.datetime.utcnow()
        self.client.add_response = {
            'id': 'abcd',
            'name': 'blah',
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'deleted_at': now.isoformat(),
        }
        actual = self.service.create({}, {})
        for attr in ('created_at', 'updated_at', 'deleted_at'):
            self.assertEqual(actual[attr], now)

    def test_create_handles_deleted_at_none(self):
        self.client.add_response = {
            'id': 'abcd',
            'name': 'blah',
            'deleted_at': None,
        }
        actual = self.service.create({}, {})
        self.assertEqual(actual['deleted_at'], None)

    def test_update_handles_timestamps(self):
        now = datetime.datetime.utcnow()
        self.client.update_response = {
            'id': 'abcd',
            'name': 'blah',
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'deleted_at': now.isoformat(),
        }
        actual = self.service.update({}, 'dummy_id', {})
        for attr in ('created_at', 'updated_at', 'deleted_at'):
            self.assertEqual(actual[attr], now)

    def test_create_handles_deleted_at_none(self):
        self.client.update_response = {
            'id': 'abcd',
            'name': 'blah',
            'deleted_at': None,
        }
        actual = self.service.update({}, 'dummy_id', {})
        self.assertEqual(actual['deleted_at'], None)
