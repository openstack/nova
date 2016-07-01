#    Copyright 2011 OpenStack Foundation
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

from six.moves import StringIO

from nova import context
from nova import exception
from nova import test
import nova.tests.unit.image.fake


class FakeImageServiceTestCase(test.NoDBTestCase):
    def setUp(self):
        super(FakeImageServiceTestCase, self).setUp()
        self.image_service = nova.tests.unit.image.fake.FakeImageService()
        self.context = context.get_admin_context()

    def tearDown(self):
        super(FakeImageServiceTestCase, self).tearDown()
        nova.tests.unit.image.fake.FakeImageService_reset()

    def test_detail(self):
        res = self.image_service.detail(self.context)
        for image in res:
            keys = set(image.keys())
            self.assertEqual(keys, set(['id', 'name', 'created_at',
                                        'updated_at', 'deleted_at', 'deleted',
                                        'status', 'is_public', 'properties',
                                        'disk_format', 'container_format',
                                        'size']))
            self.assertIsInstance(image['created_at'], datetime.datetime)
            self.assertIsInstance(image['updated_at'], datetime.datetime)

            if not (isinstance(image['deleted_at'], datetime.datetime) or
                                      image['deleted_at'] is None):
                self.fail('image\'s "deleted_at" attribute was neither a '
                          'datetime object nor None')

            def check_is_bool(image, key):
                val = image.get('deleted')
                if not isinstance(val, bool):
                    self.fail('image\'s "%s" attribute wasn\'t '
                              'a bool: %r' % (key, val))

            check_is_bool(image, 'deleted')
            check_is_bool(image, 'is_public')

    def test_show_raises_imagenotfound_for_invalid_id(self):
        self.assertRaises(exception.ImageNotFound,
                          self.image_service.show,
                          self.context,
                          'this image does not exist')

    def test_create_adds_id(self):
        index = self.image_service.detail(self.context)
        image_count = len(index)

        self.image_service.create(self.context, {})

        index = self.image_service.detail(self.context)
        self.assertEqual(len(index), image_count + 1)

        self.assertTrue(index[0]['id'])

    def test_create_keeps_id(self):
        self.image_service.create(self.context, {'id': '34'})
        self.image_service.show(self.context, '34')

    def test_create_rejects_duplicate_ids(self):
        self.image_service.create(self.context, {'id': '34'})
        self.assertRaises(exception.CouldNotUploadImage,
                          self.image_service.create,
                          self.context,
                          {'id': '34'})

        # Make sure there's still one left
        self.image_service.show(self.context, '34')

    def test_update(self):
        self.image_service.create(self.context,
                                  {'id': '34', 'foo': 'bar'})

        self.image_service.update(self.context, '34',
                                  {'id': '34', 'foo': 'baz'})

        img = self.image_service.show(self.context, '34')
        self.assertEqual(img['foo'], 'baz')

    def test_delete(self):
        self.image_service.create(self.context, {'id': '34', 'foo': 'bar'})
        self.image_service.delete(self.context, '34')
        self.assertRaises(exception.NotFound,
                          self.image_service.show,
                          self.context,
                          '34')

    def test_create_then_get(self):
        blob = 'some data'
        s1 = StringIO(blob)
        self.image_service.create(self.context,
                                  {'id': '32', 'foo': 'bar'},
                                  data=s1)
        s2 = StringIO()
        self.image_service.download(self.context, '32', data=s2)
        self.assertEqual(s2.getvalue(), blob, 'Did not get blob back intact')
