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

from nova.tests.api.openstack import fakes
from nova import context
from nova import exception
from nova.image import glance
from nova import test
from nova.tests.glance import stubs as glance_stubs


class NullWriter(object):
    """Used to test ImageService.get which takes a writer object"""

    def write(self, *arg, **kwargs):
        pass


class TestGlanceSerializer(test.TestCase):
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


class TestGlanceImageService(test.TestCase):
    """
    Tests the Glance image service.

    At a high level, the translations involved are:

        1. Glance -> ImageService - This is needed so we can support
           multple ImageServices (Glance, Local, etc)

        2. ImageService -> API - This is needed so we can support multple
           APIs (OpenStack, EC2)

    """
    NOW_GLANCE_OLD_FORMAT = "2010-10-11T10:30:22"
    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22.000000"
    NOW_DATETIME = datetime.datetime(2010, 10, 11, 10, 30, 22)

    def setUp(self):
        super(TestGlanceImageService, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_compute_api_snapshot(self.stubs)
        client = glance_stubs.StubGlanceClient()
        self.service = glance.GlanceImageService(client=client)
        self.context = context.RequestContext('fake', 'fake', auth_token=True)
        self.service.delete_all()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(TestGlanceImageService, self).tearDown()

    @staticmethod
    def _make_fixture(**kwargs):
        fixture = {'name': None,
                   'properties': {},
                   'status': None,
                   'is_public': None}
        fixture.update(kwargs)
        return fixture

    def _make_datetime_fixture(self):
        return self._make_fixture(created_at=self.NOW_GLANCE_FORMAT,
                                  updated_at=self.NOW_GLANCE_FORMAT,
                                  deleted_at=self.NOW_GLANCE_FORMAT)

    def test_create_with_instance_id(self):
        """Ensure instance_id is persisted as an image-property"""
        fixture = {'name': 'test image',
                   'is_public': False,
                   'properties': {'instance_id': '42', 'user_id': 'fake'}}

        image_id = self.service.create(self.context, fixture)['id']
        image_meta = self.service.show(self.context, image_id)
        expected = {
            'id': image_id,
            'name': 'test image',
            'is_public': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {'instance_id': '42', 'user_id': 'fake'},
        }
        self.assertDictMatch(image_meta, expected)

        image_metas = self.service.detail(self.context)
        self.assertDictMatch(image_metas[0], expected)

    def test_create_without_instance_id(self):
        """
        Ensure we can create an image without having to specify an
        instance_id. Public images are an example of an image not tied to an
        instance.
        """
        fixture = {'name': 'test image', 'is_public': False}
        image_id = self.service.create(self.context, fixture)['id']

        expected = {
            'id': image_id,
            'name': 'test image',
            'is_public': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
        }
        actual = self.service.show(self.context, image_id)
        self.assertDictMatch(actual, expected)

    def test_create(self):
        fixture = self._make_fixture(name='test image')
        num_images = len(self.service.index(self.context))
        image_id = self.service.create(self.context, fixture)['id']

        self.assertNotEquals(None, image_id)
        self.assertEquals(num_images + 1,
                          len(self.service.index(self.context)))

    def test_create_and_show_non_existing_image(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']

        self.assertNotEquals(None, image_id)
        self.assertRaises(exception.NotFound,
                          self.service.show,
                          self.context,
                          'bad image id')

    def test_create_and_show_non_existing_image_by_name(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']

        self.assertNotEquals(None, image_id)
        self.assertRaises(exception.ImageNotFound,
                          self.service.show_by_name,
                          self.context,
                          'bad image id')

    def test_index(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']
        image_metas = self.service.index(self.context)
        expected = [{'id': image_id, 'name': 'test image'}]
        self.assertDictListMatch(image_metas, expected)

    def test_index_default_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
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
            fixture = self._make_fixture(name='TestImage %d' % (i))
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
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.index(self.context, limit=5)
        self.assertEquals(len(image_metas), 5)

    def test_index_marker_and_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.index(self.context, marker=ids[3], limit=1)
        self.assertEquals(len(image_metas), 1)
        i = 4
        for meta in image_metas:
            expected = {'id': ids[i],
                        'name': 'TestImage %d' % (i)}
            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_index_private_image(self):
        fixture = self._make_fixture(name='test image')
        fixture['is_public'] = False
        properties = {'owner_id': 'proj1'}
        fixture['properties'] = properties

        image_id = self.service.create(self.context, fixture)['id']

        proj = self.context.project_id
        self.context.project_id = 'proj1'

        image_metas = self.service.index(self.context)

        self.context.project_id = proj

        expected = [{'id': 'DONTCARE', 'name': 'test image'}]
        self.assertDictListMatch(image_metas, expected)

    def test_detail_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, marker=ids[1])
        self.assertEquals(len(image_metas), 8)
        i = 2
        for meta in image_metas:
            expected = {
                'id': ids[i],
                'status': None,
                'is_public': None,
                'name': 'TestImage %d' % (i),
                'properties': {},
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None
            }

            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_detail_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, limit=5)
        self.assertEquals(len(image_metas), 5)

    def test_detail_marker_and_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, marker=ids[3], limit=5)
        self.assertEquals(len(image_metas), 5)
        i = 4
        for meta in image_metas:
            expected = {
                'id': ids[i],
                'status': None,
                'is_public': None,
                'name': 'TestImage %d' % (i),
                'properties': {},
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None
            }
            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_update(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']
        fixture['name'] = 'new image name'
        self.service.update(self.context, image_id, fixture)

        new_image_data = self.service.show(self.context, image_id)
        self.assertEquals('new image name', new_image_data['name'])

    def test_delete(self):
        fixture1 = self._make_fixture(name='test image 1')
        fixture2 = self._make_fixture(name='test image 2')
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

    def test_delete_not_by_owner(self):
        # this test is only relevant for deprecated auth mode
        self.flags(use_deprecated_auth=True)

        fixture = self._make_fixture(name='test image')
        properties = {'project_id': 'proj1'}
        fixture['properties'] = properties

        num_images = len(self.service.index(self.context))
        self.assertEquals(0, num_images)

        image_id = self.service.create(self.context, fixture)['id']
        num_images = len(self.service.index(self.context))
        self.assertEquals(1, num_images)

        proj_id = self.context.project_id
        self.context.project_id = 'proj2'

        self.assertRaises(exception.NotAuthorized, self.service.delete,
                          self.context, image_id)

        self.context.project_id = proj_id

        num_images = len(self.service.index(self.context))
        self.assertEquals(1, num_images)

    def test_show_passes_through_to_client(self):
        fixture = self._make_fixture(name='image1', is_public=True)
        image_id = self.service.create(self.context, fixture)['id']

        image_meta = self.service.show(self.context, image_id)
        expected = {
            'id': image_id,
            'name': 'image1',
            'is_public': True,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
        }
        self.assertEqual(image_meta, expected)

    def test_show_raises_when_no_authtoken_in_the_context(self):
        fixture = self._make_fixture(name='image1',
                                     is_public=False,
                                     properties={'one': 'two'})
        image_id = self.service.create(self.context, fixture)['id']
        self.context.auth_token = False
        self.assertRaises(exception.ImageNotFound,
                          self.service.show,
                          self.context,
                          image_id)

    def test_detail_passes_through_to_client(self):
        fixture = self._make_fixture(name='image10', is_public=True)
        image_id = self.service.create(self.context, fixture)['id']
        image_metas = self.service.detail(self.context)
        expected = [
            {
                'id': image_id,
                'name': 'image10',
                'is_public': True,
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None,
                'status': None,
                'properties': {},
            },
        ]
        self.assertEqual(image_metas, expected)

    def test_show_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        image_id = self.service.create(self.context, fixture)['id']
        image_meta = self.service.show(self.context, image_id)
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

    def test_detail_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        self.service.create(self.context, fixture)
        image_meta = self.service.detail(self.context)[0]
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

    def test_get_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        image_id = self.service.create(self.context, fixture)['id']
        writer = NullWriter()
        image_meta = self.service.get(self.context, image_id, writer)
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

    def test_get_with_retries(self):
        tries = [0]

        class GlanceBusyException(Exception):
            pass

        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that fails the first time, then succeeds."""
            def get_image(self, image_id):
                if tries[0] == 0:
                    tries[0] = 1
                    raise GlanceBusyException()
                else:
                    return {}, []

        client = MyGlanceStubClient()
        service = glance.GlanceImageService(client=client)
        image_id = 1  # doesn't matter
        writer = NullWriter()

        # When retries are disabled, we should get an exception
        self.flags(glance_num_retries=0)
        self.assertRaises(GlanceBusyException, service.get, self.context,
                          image_id, writer)

        # Now lets enable retries. No exception should happen now.
        self.flags(glance_num_retries=1)
        service.get(self.context, image_id, writer)

    def test_glance_client_image_id(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']
        client, same_id = glance.get_glance_client(self.context, image_id)
        self.assertEquals(same_id, image_id)

    def test_glance_client_image_ref(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']
        image_url = 'http://foo/%s' % image_id
        client, same_id = glance.get_glance_client(self.context, image_url)
        self.assertEquals(same_id, image_id)
