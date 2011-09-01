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

from nova import context
from nova import exception
from nova import test
from nova.image import glance


class StubGlanceClient(object):

    def __init__(self, images, add_response=None, update_response=None):
        self.images = images
        self.add_response = add_response
        self.update_response = update_response

    def set_auth_token(self, auth_tok):
        pass

    def get_image_meta(self, image_id):
        return self.images[image_id]

    def get_images_detailed(self, filters=None, marker=None, limit=None):
        images = self.images.values()
        if marker is None:
            index = 0
        else:
            for index, image in enumerate(images):
                if image['id'] == marker:
                    index += 1
                    break
        # default to a page size of 3 to ensure we flex the pagination code
        return images[index:index + 3]

    def get_image(self, image_id):
        return self.images[image_id], []

    def add_image(self, metadata, data):
        return self.add_response

    def update_image(self, image_id, metadata, data):
        return self.update_response


class NullWriter(object):
    """Used to test ImageService.get which takes a writer object"""

    def write(self, *arg, **kwargs):
        pass


class BaseGlanceTest(unittest.TestCase):
    NOW_GLANCE_OLD_FORMAT = "2010-10-11T10:30:22"
    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22.000000"
    NOW_DATETIME = datetime.datetime(2010, 10, 11, 10, 30, 22)

    def setUp(self):
        self.client = StubGlanceClient(None)
        self.service = glance.GlanceImageService(client=self.client)
        self.context = context.RequestContext(None, None)

    def assertDateTimesFilled(self, image_meta):
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['deleted_at'], self.NOW_DATETIME)

    def assertDateTimesEmpty(self, image_meta):
        self.assertEqual(image_meta['updated_at'], None)
        self.assertEqual(image_meta['deleted_at'], None)

    def assertDateTimesBlank(self, image_meta):
        self.assertEqual(image_meta['updated_at'], '')
        self.assertEqual(image_meta['deleted_at'], '')


class TestGlanceImageServiceProperties(BaseGlanceTest):
    def test_show_passes_through_to_client(self):
        """Ensure attributes which aren't BASE_IMAGE_ATTRS are stored in the
        properties dict
        """
        fixtures = {'image1': {'id': '1', 'name': 'image1', 'is_public': True,
                               'foo': 'bar',
                               'properties': {'prop1': 'propvalue1'}}}
        self.client.images = fixtures
        image_meta = self.service.show(self.context, 'image1')

        expected = {'id': '1', 'name': 'image1', 'is_public': True,
                    'properties': {'prop1': 'propvalue1', 'foo': 'bar'}}
        self.assertEqual(image_meta, expected)

    def test_show_raises_when_no_authtoken_in_the_context(self):
        fixtures = {'image1': {'name': 'image1', 'is_public': False,
                               'foo': 'bar',
                               'properties': {'prop1': 'propvalue1'}}}
        self.client.images = fixtures
        self.context.auth_token = False

        expected = {'name': 'image1', 'is_public': True,
                    'properties': {'prop1': 'propvalue1', 'foo': 'bar'}}
        self.assertRaises(exception.ImageNotFound,
                          self.service.show, self.context, 'image1')

    def test_show_passes_through_to_client_with_authtoken_in_context(self):
        fixtures = {'image1': {'name': 'image1', 'is_public': False,
                               'foo': 'bar',
                               'properties': {'prop1': 'propvalue1'}}}
        self.client.images = fixtures
        self.context.auth_token = True

        expected = {'name': 'image1', 'is_public': False,
                    'properties': {'prop1': 'propvalue1', 'foo': 'bar'}}

        image_meta = self.service.show(self.context, 'image1')
        self.assertEqual(image_meta, expected)

    def test_detail_passes_through_to_client(self):
        fixtures = {'image1': {'id': '1', 'name': 'image1', 'is_public': True,
                               'foo': 'bar',
                               'properties': {'prop1': 'propvalue1'}}}
        self.client.images = fixtures
        image_meta = self.service.detail(self.context)
        expected = [{'id': '1', 'name': 'image1', 'is_public': True,
                    'properties': {'prop1': 'propvalue1', 'foo': 'bar'}}]
        self.assertEqual(image_meta, expected)


class TestGetterDateTimeNoneTests(BaseGlanceTest):

    def test_show_handles_none_datetimes(self):
        self.client.images = self._make_none_datetime_fixtures()
        image_meta = self.service.show(self.context, 'image1')
        self.assertDateTimesEmpty(image_meta)

    def test_show_handles_blank_datetimes(self):
        self.client.images = self._make_blank_datetime_fixtures()
        image_meta = self.service.show(self.context, 'image1')
        self.assertDateTimesBlank(image_meta)

    def test_detail_handles_none_datetimes(self):
        self.client.images = self._make_none_datetime_fixtures()
        image_meta = self.service.detail(self.context)[0]
        self.assertDateTimesEmpty(image_meta)

    def test_detail_handles_blank_datetimes(self):
        self.client.images = self._make_blank_datetime_fixtures()
        image_meta = self.service.detail(self.context)[0]
        self.assertDateTimesBlank(image_meta)

    def test_get_handles_none_datetimes(self):
        self.client.images = self._make_none_datetime_fixtures()
        writer = NullWriter()
        image_meta = self.service.get(self.context, 'image1', writer)
        self.assertDateTimesEmpty(image_meta)

    def test_get_handles_blank_datetimes(self):
        self.client.images = self._make_blank_datetime_fixtures()
        writer = NullWriter()
        image_meta = self.service.get(self.context, 'image1', writer)
        self.assertDateTimesBlank(image_meta)

    def test_show_makes_datetimes(self):
        self.client.images = self._make_datetime_fixtures()
        image_meta = self.service.show(self.context, 'image1')
        self.assertDateTimesFilled(image_meta)
        image_meta = self.service.show(self.context, 'image2')
        self.assertDateTimesFilled(image_meta)

    def test_detail_makes_datetimes(self):
        self.client.images = self._make_datetime_fixtures()
        image_meta = self.service.detail(self.context)[0]
        self.assertDateTimesFilled(image_meta)
        image_meta = self.service.detail(self.context)[1]
        self.assertDateTimesFilled(image_meta)

    def test_get_makes_datetimes(self):
        self.client.images = self._make_datetime_fixtures()
        writer = NullWriter()
        image_meta = self.service.get(self.context, 'image1', writer)
        self.assertDateTimesFilled(image_meta)
        image_meta = self.service.get(self.context, 'image2', writer)
        self.assertDateTimesFilled(image_meta)

    def _make_datetime_fixtures(self):
        fixtures = {
            'image1': {
                'id': '1',
                'name': 'image1',
                'is_public': True,
                'created_at': self.NOW_GLANCE_FORMAT,
                'updated_at': self.NOW_GLANCE_FORMAT,
                'deleted_at': self.NOW_GLANCE_FORMAT,
            },
            'image2': {
                'id': '2',
                'name': 'image2',
                'is_public': True,
                'created_at': self.NOW_GLANCE_OLD_FORMAT,
                'updated_at': self.NOW_GLANCE_OLD_FORMAT,
                'deleted_at': self.NOW_GLANCE_OLD_FORMAT,
            },
        }
        return fixtures

    def _make_none_datetime_fixtures(self):
        fixtures = {'image1': {'id': '1',
                               'name': 'image1',
                               'is_public': True,
                               'updated_at': None,
                               'deleted_at': None}}
        return fixtures

    def _make_blank_datetime_fixtures(self):
        fixtures = {'image1': {'id': '1',
                               'name': 'image1',
                               'is_public': True,
                               'updated_at': '',
                               'deleted_at': ''}}
        return fixtures


class TestMutatorDateTimeTests(BaseGlanceTest):
    """Tests create(), update()"""

    def test_create_handles_datetimes(self):
        self.client.add_response = self._make_datetime_fixture()
        image_meta = self.service.create(self.context, {})
        self.assertDateTimesFilled(image_meta)

    def test_create_handles_none_datetimes(self):
        self.client.add_response = self._make_none_datetime_fixture()
        dummy_meta = {}
        image_meta = self.service.create(self.context, dummy_meta)
        self.assertDateTimesEmpty(image_meta)

    def test_update_handles_datetimes(self):
        self.client.images = {'image1': self._make_datetime_fixture()}
        self.client.update_response = self._make_datetime_fixture()
        dummy_meta = {}
        image_meta = self.service.update(self.context, 'image1', dummy_meta)
        self.assertDateTimesFilled(image_meta)

    def test_update_handles_none_datetimes(self):
        self.client.images = {'image1': self._make_datetime_fixture()}
        self.client.update_response = self._make_none_datetime_fixture()
        dummy_meta = {}
        image_meta = self.service.update(self.context, 'image1', dummy_meta)
        self.assertDateTimesEmpty(image_meta)

    def _make_datetime_fixture(self):
        fixture = {'id': 'image1', 'name': 'image1', 'is_public': True,
                   'created_at': self.NOW_GLANCE_FORMAT,
                   'updated_at': self.NOW_GLANCE_FORMAT,
                   'deleted_at': self.NOW_GLANCE_FORMAT}
        return fixture

    def _make_none_datetime_fixture(self):
        fixture = {'id': 'image1', 'name': 'image1', 'is_public': True,
                   'updated_at': None,
                   'deleted_at': None}
        return fixture


class TestGlanceSerializer(unittest.TestCase):
    def test_serialize(self):
        metadata = {'name': 'image1',
                    'is_public': True,
                    'foo': 'bar',
                    'properties': {
                        'prop1': 'propvalue1',
                        'mappings': [
                            {'virtual': 'aaa',
                             'device': 'bbb'},
                            {'virtual': 'xxx',
                             'device': 'yyy'}],
                        'block_device_mapping': [
                            {'virtual_device': 'fake',
                             'device_name': '/dev/fake'},
                            {'virtual_device': 'ephemeral0',
                             'device_name': '/dev/fake0'}]}}

        converted_expected = {
            'name': 'image1',
            'is_public': True,
            'foo': 'bar',
            'properties': {
                'prop1': 'propvalue1',
                'mappings':
                '[{"device": "bbb", "virtual": "aaa"}, '
                '{"device": "yyy", "virtual": "xxx"}]',
                'block_device_mapping':
                '[{"virtual_device": "fake", "device_name": "/dev/fake"}, '
                '{"virtual_device": "ephemeral0", '
                '"device_name": "/dev/fake0"}]'}}
        converted = glance._convert_to_string(metadata)
        self.assertEqual(converted, converted_expected)
        self.assertEqual(glance._convert_from_string(converted), metadata)
