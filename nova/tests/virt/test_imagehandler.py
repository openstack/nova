#    Copyright 2014 IBM Corp.
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

import mock
import stevedore

from nova import context
from nova import exception
from nova import test
from nova.tests.image import fake as fake_image
from nova.virt import imagehandler
from nova.virt.imagehandler import download as download_imagehandler


class ImageHandlerTestCase(test.TestCase):
    def setUp(self):
        super(ImageHandlerTestCase, self).setUp()
        self.fake_driver = mock.MagicMock()
        self.context = context.get_admin_context()
        self.image_service = fake_image.stub_out_image_service(self.stubs)
        imagehandler._IMAGE_HANDLERS = []
        imagehandler._IMAGE_HANDLERS_ASSO = {}

    def tearDown(self):
        fake_image.FakeImageService_reset()
        super(ImageHandlerTestCase, self).tearDown()

    def test_match_locations_empty(self):
        matched = imagehandler._match_locations([], ())
        self.assertEqual([], matched)
        matched = imagehandler._match_locations(None, ())
        self.assertEqual([], matched)
        matched = imagehandler._match_locations([], None)
        self.assertEqual([], matched)

    def test_match_locations_location_dependent(self):
        fake_locations = [{'url': 'fake1://url', 'metadata': {}},
                          {'url': 'fake2://url', 'metadata': {}}]
        matched = imagehandler._match_locations(fake_locations, ('fake1'))
        self.assertEqual([{'url': 'fake1://url', 'metadata': {}}], matched)
        matched = imagehandler._match_locations(fake_locations,
                                                ('no_existing'))
        self.assertEqual([], matched)

    def test_match_locations_location_independent(self):
        fake_locations = [{'url': 'fake1://url', 'metadata': {}},
                          {'url': 'fake2://url', 'metadata': {}}]
        matched = imagehandler._match_locations(fake_locations, ())
        self.assertEqual(fake_locations, matched)

    def test_image_handler_association_hooks(self):
        handler = 'fake_handler'
        path = 'fake/image/path'
        location = 'fake://image_location_url'
        image_meta = 'fake_image_meta'
        self.assertEqual(0, len(imagehandler._IMAGE_HANDLERS_ASSO))
        imagehandler._image_handler_asso(handler, path, location, image_meta)
        self.assertEqual(1, len(imagehandler._IMAGE_HANDLERS_ASSO))
        self.assertIn(path, imagehandler._IMAGE_HANDLERS_ASSO)
        self.assertEqual((handler, location, image_meta),
                         imagehandler._IMAGE_HANDLERS_ASSO[path])
        imagehandler._image_handler_disasso('another_handler',
                                            'another/fake/image/path')
        self.assertEqual(1, len(imagehandler._IMAGE_HANDLERS_ASSO))
        imagehandler._image_handler_disasso(handler, path)
        self.assertEqual(0, len(imagehandler._IMAGE_HANDLERS_ASSO))

    def test_load_image_handlers(self):
        self.flags(image_handlers=['download'])
        imagehandler.load_image_handlers(self.fake_driver)
        self.assertEqual(1, len(imagehandler._IMAGE_HANDLERS))
        self.assertIsInstance(imagehandler._IMAGE_HANDLERS[0],
                              download_imagehandler.DownloadImageHandler)
        self.assertEqual(0, len(imagehandler._IMAGE_HANDLERS_ASSO))

    def test_load_image_handlers_with_invalid_handler_name(self):
        self.flags(image_handlers=['invaild1', 'download', 'invaild2'])
        imagehandler.load_image_handlers(self.fake_driver)
        self.assertEqual(1, len(imagehandler._IMAGE_HANDLERS))
        self.assertIsInstance(imagehandler._IMAGE_HANDLERS[0],
                              download_imagehandler.DownloadImageHandler)
        self.assertEqual(0, len(imagehandler._IMAGE_HANDLERS_ASSO))

    @mock.patch.object(stevedore.extension, 'ExtensionManager')
    @mock.patch.object(stevedore.driver, 'DriverManager')
    def test_load_image_handlers_with_deduplicating(self,
                                                    mock_DriverManager,
                                                    mock_ExtensionManager):
        handlers = ['handler1', 'handler2', 'handler3']

        def _fake_stevedore_driver_manager(*args, **kwargs):
            return mock.MagicMock(**{'driver': kwargs['name']})

        mock_ExtensionManager.return_value = mock.MagicMock(
                                        **{'names.return_value': handlers})
        mock_DriverManager.side_effect = _fake_stevedore_driver_manager

        self.flags(image_handlers=['invaild1', 'handler1  ', '  handler3',
                                   'invaild2', '  handler2  '])
        imagehandler.load_image_handlers(self.fake_driver)
        self.assertEqual(3, len(imagehandler._IMAGE_HANDLERS))
        for handler in imagehandler._IMAGE_HANDLERS:
            self.assertTrue(handler in handlers)
        self.assertEqual(['handler1', 'handler3', 'handler2'],
                         imagehandler._IMAGE_HANDLERS)
        self.assertEqual(0, len(imagehandler._IMAGE_HANDLERS_ASSO))

    @mock.patch.object(stevedore.extension, 'ExtensionManager')
    @mock.patch.object(stevedore.driver, 'DriverManager')
    def test_load_image_handlers_with_load_handler_failure(self,
                                                    mock_DriverManager,
                                                    mock_ExtensionManager):
        handlers = ['raise_exception', 'download']

        def _fake_stevedore_driver_manager(*args, **kwargs):
            if kwargs['name'] == 'raise_exception':
                raise Exception('handler failed to initialize.')
            else:
                return mock.MagicMock(**{'driver': kwargs['name']})

        mock_ExtensionManager.return_value = mock.MagicMock(
                                        **{'names.return_value': handlers})
        mock_DriverManager.side_effect = _fake_stevedore_driver_manager

        self.flags(image_handlers=['raise_exception', 'download',
                                   'raise_exception', 'download'])
        imagehandler.load_image_handlers(self.fake_driver)
        self.assertEqual(1, len(imagehandler._IMAGE_HANDLERS))
        self.assertEqual(['download'], imagehandler._IMAGE_HANDLERS)
        self.assertEqual(0, len(imagehandler._IMAGE_HANDLERS_ASSO))

    @mock.patch.object(download_imagehandler.DownloadImageHandler,
                       '_fetch_image')
    def _handle_image_without_associated_handle(self, image_id,
                                                expected_locations,
                                                expected_handled_location,
                                                expected_handled_path,
                                                mock__fetch_image):
        def _fake_handler_fetch(context, image_meta, path,
                                user_id=None, project_id=None, location=None):
            return location == expected_handled_location

        mock__fetch_image.side_effect = _fake_handler_fetch

        self.flags(image_handlers=['download'])
        imagehandler.load_image_handlers(self.fake_driver)
        self.assertEqual(1, len(imagehandler._IMAGE_HANDLERS))
        self.assertEqual(0, len(imagehandler._IMAGE_HANDLERS_ASSO))

        check_left_loc_count = expected_handled_location in expected_locations
        if check_left_loc_count:
            unused_location_count = (len(expected_locations) -
                 expected_locations.index(expected_handled_location) - 1)

        self._fetch_image(image_id, expected_locations,
                          expected_handled_location, expected_handled_path)

        if check_left_loc_count:
            self.assertEqual(unused_location_count, len(expected_locations))
        self.assertEqual(1, len(imagehandler._IMAGE_HANDLERS_ASSO))
        self.assertEqual(
             (imagehandler._IMAGE_HANDLERS[0], expected_handled_location),
             imagehandler._IMAGE_HANDLERS_ASSO[expected_handled_path][:2])

    @mock.patch.object(download_imagehandler.DownloadImageHandler,
                       '_fetch_image')
    def _fetch_image(self, image_id, expected_locations,
                     expected_handled_location, expected_handled_path,
                     mock__fetch_image):
        def _fake_handler_fetch(context, image_id, image_meta, path,
                                user_id=None, project_id=None, location=None):
            return location == expected_handled_location

        mock__fetch_image.side_effect = _fake_handler_fetch

        for handler_context in imagehandler.handle_image(self.context,
                                image_id, target_path=expected_handled_path):
            (handler, loc, image_meta) = handler_context
            self.assertEqual(handler, imagehandler._IMAGE_HANDLERS[0])
            if (len(expected_locations) > 0):
                self.assertEqual(expected_locations.pop(0), loc)
            handler.fetch_image(context, image_id, image_meta,
                                expected_handled_path, location=loc)

    def test_handle_image_without_associated_handle(self):
        image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        expected_locations = ['fake_location', 'fake_location2']
        # Image will be handled successful on second location.
        expected_handled_location = 'fake_location2'
        expected_handled_path = 'fake/image/path2'
        self._handle_image_without_associated_handle(image_id,
                                                     expected_locations,
                                                     expected_handled_location,
                                                     expected_handled_path)

    def test_handle_image_with_associated_handler(self):
        self.get_locations_called = False

        def _fake_get_locations(*args, **kwargs):
            self.get_locations_called = True

        image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        expected_locations = ['fake_location', 'fake_location2']
        expected_handled_location = 'fake_location'
        expected_handled_path = 'fake/image/path'

        # 1) Handle image without cached association information
        self._handle_image_without_associated_handle(image_id,
                                                     list(expected_locations),
                                                     expected_handled_location,
                                                     expected_handled_path)

        self.image_service.get_locations = mock.MagicMock(
                                    **{'side_effect': _fake_get_locations})

        # 2) Handle image with cached association information
        self._fetch_image(image_id, expected_locations,
                          expected_handled_location, expected_handled_path)

        self.assertFalse(self.get_locations_called)
        del self.get_locations_called

    def test_handle_image_with_association_discarded(self):
        self.get_locations_called = False
        original_get_locations = self.image_service.get_locations

        def _fake_get_locations(*args, **kwargs):
            self.get_locations_called = True
            return original_get_locations(*args, **kwargs)

        image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        expected_locations = ['fake_location', 'fake_location2']
        expected_handled_location = 'fake_location'
        expected_handled_path = 'fake/image/path'

        # 1) Handle image without cached association information
        self._handle_image_without_associated_handle(image_id,
                                                     list(expected_locations),
                                                     expected_handled_location,
                                                     expected_handled_path)

        # 2) Clear cached association information
        imagehandler._IMAGE_HANDLERS_ASSO = {}

        # 3) Handle image with discarded association information
        self.image_service.get_locations = mock.MagicMock(
                                    **{'side_effect': _fake_get_locations})

        self._fetch_image(image_id, expected_locations,
                          expected_handled_location, expected_handled_path)

        self.assertTrue(self.get_locations_called)
        del self.get_locations_called

    def test_handle_image_no_handler_available(self):
        image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        expected_locations = ['fake_location', 'fake_location2']
        expected_handled_location = 'fake_location3'
        expected_handled_path = 'fake/image/path'

        self.assertRaises(exception.NoImageHandlerAvailable,
                          self._handle_image_without_associated_handle,
                          image_id,
                          expected_locations,
                          expected_handled_location,
                          expected_handled_path)
