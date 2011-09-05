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
import stubout
import unittest

from nova.tests.api.openstack import fakes
from nova import context
from nova import exception
from nova.image import glance
from nova import test
from nova import utils


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
    """
    Ensure attributes which aren't base attributes are ignored.

    Missingattributes should be added as None

    """

    def test_show_passes_through_to_client(self):
        fixtures = {'image1': {'id': '1', 'name': 'image1', 'is_public': True,
                               'foo': 'bar',
                               'properties': {'prop1': 'propvalue1'}}}
        self.client.images = fixtures
        image_meta = self.service.show(self.context, 'image1')

        expected = {'id': '1', 'name': 'image1', 'is_public': True,
                    'size': None, 'location': None, 'disk_format': None,
                    'container_format': None, 'checksum': None,
                    'created_at': None, 'updated_at': None,
                    'deleted_at': None, 'deleted': None, 'status': None,
                    'properties': {'prop1': 'propvalue1'}}
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
                     'size': None, 'location': None, 'disk_format': None,
                     'container_format': None, 'checksum': None,
                     'created_at': None, 'updated_at': None,
                     'deleted_at': None, 'deleted': None, 'status': None,
                     'properties': {'prop1': 'propvalue1'}}]
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


class GlanceImageServiceTest(test.TestCase):
    """
    Tests the Glance image service.

    At a high level, the translations involved are:

        1. Glance -> ImageService - This is needed so we can support
           multple ImageServices (Glance, Local, etc)

        2. ImageService -> API - This is needed so we can support multple
           APIs (OpenStack, EC2)

    """
    def __init__(self, *args, **kwargs):
        super(GlanceImageServiceTest, self).__init__(*args, **kwargs)
        self.service = None
        self.context = None

    @staticmethod
    def _make_fixture(name):
        fixture = {'name': name,
                   'properties': {'one': 'two'},
                   'status': None,
                   'is_public': True}
        return fixture

    def setUp(self):
        super(GlanceImageServiceTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_glance(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        service_class = 'nova.image.glance.GlanceImageService'
        self.service = utils.import_object(service_class)
        self.context = context.RequestContext('fake', 'fake')
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
                   'properties': {'instance_id': '42', 'user_id': 'fake'}}

        image_id = self.service.create(self.context, fixture)['id']
        expected = fixture
        self.assertDictMatch(self.sent_to_glance['metadata'], expected)

        image_meta = self.service.show(self.context, image_id)
        expected = {'id': image_id, 'name': 'test image', 'is_public': False,
                    'size': None, 'location': None, 'disk_format': None,
                    'container_format': None, 'checksum': None,
                    'created_at': None, 'updated_at': None,
                    'deleted_at': None, 'deleted': None, 'status': None,
                    'properties': {'instance_id': '42', 'user_id': 'fake'}}
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

        expected = {'name': 'test image'}
        self.assertDictMatch(self.sent_to_glance['metadata'], expected)

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

    def test_index(self):
        fixture = self._make_fixture('test image')
        image_id = self.service.create(self.context, fixture)['id']
        image_metas = self.service.index(self.context)
        expected = [{'id': 'DONTCARE', 'name': 'test image'}]
        self.assertDictListMatch(image_metas, expected)

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
                'properties': {'one': 'two'},
                'size': None,
                'location': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': None,
                'updated_at': None,
                'deleted_at': None,
                'deleted': None
            }

            print meta
            print expected
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
                'properties': {'one': 'two'},
                'size': None,
                'location': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': None,
                'updated_at': None,
                'deleted_at': None,
                'deleted': None
            }
            self.assertDictMatch(meta, expected)
            i = i + 1

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
