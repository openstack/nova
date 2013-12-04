# Copyright 2013 OpenStack Foundation
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

from oslo.config import cfg

from nova.compute import vm_states
from nova import test
from nova.virt import imagecache

CONF = cfg.CONF


class ImageCacheManagerTests(test.NoDBTestCase):

    def test_configurationi_defaults(self):
        self.assertEqual(CONF.image_cache_manager_interval,
                         2400)
        self.assertEqual(CONF.image_cache_subdirectory_name,
                         '_base')
        self.assertTrue(CONF.remove_unused_base_images)
        self.assertEqual(CONF.remove_unused_original_minimum_age_seconds,
                         24 * 3600)

    def test_cache_manager(self):
        cache_manager = imagecache.ImageCacheManager()
        self.assertTrue(cache_manager.remove_unused_base_images)
        self.assertRaises(NotImplementedError,
                          cache_manager.update, None, [])
        self.assertRaises(NotImplementedError,
                          cache_manager._get_base)
        base_images = cache_manager._list_base_images(None)
        self.assertEqual(base_images['unexplained_images'], [])
        self.assertEqual(base_images['originals'], [])
        self.assertRaises(NotImplementedError,
                          cache_manager._age_and_verify_cached_images,
                          None, [], None)

    def test_list_running_instances(self):
        all_instances = [{'image_ref': '1',
                          'host': CONF.host,
                          'name': 'inst-1',
                          'uuid': '123',
                          'vm_state': '',
                          'task_state': ''},
                         {'image_ref': '2',
                          'host': CONF.host,
                          'name': 'inst-2',
                          'uuid': '456',
                          'vm_state': '',
                          'task_state': ''},
                         {'image_ref': '2',
                          'kernel_id': '21',
                          'ramdisk_id': '22',
                          'host': 'remotehost',
                          'name': 'inst-3',
                          'uuid': '789',
                          'vm_state': '',
                          'task_state': ''}]

        image_cache_manager = imagecache.ImageCacheManager()

        # The argument here should be a context, but it's mocked out
        running = image_cache_manager._list_running_instances(None,
                                                              all_instances)

        self.assertEqual(len(running['used_images']), 4)
        self.assertTrue(running['used_images']['1'] == (1, 0, ['inst-1']))
        self.assertTrue(running['used_images']['2'] == (1, 1, ['inst-2',
                                                               'inst-3']))
        self.assertTrue(running['used_images']['21'] == (0, 1, ['inst-3']))
        self.assertTrue(running['used_images']['22'] == (0, 1, ['inst-3']))

        self.assertIn('inst-1', running['instance_names'])
        self.assertIn('123', running['instance_names'])

        self.assertEqual(len(running['image_popularity']), 4)
        self.assertEqual(running['image_popularity']['1'], 1)
        self.assertEqual(running['image_popularity']['2'], 2)
        self.assertEqual(running['image_popularity']['21'], 1)
        self.assertEqual(running['image_popularity']['22'], 1)

    def test_list_resizing_instances(self):
        all_instances = [{'image_ref': '1',
                          'host': CONF.host,
                          'name': 'inst-1',
                          'uuid': '123',
                          'vm_state': vm_states.RESIZED,
                          'task_state': None}]

        image_cache_manager = imagecache.ImageCacheManager()
        running = image_cache_manager._list_running_instances(None,
                                                              all_instances)

        self.assertEqual(len(running['used_images']), 1)
        self.assertTrue(running['used_images']['1'] == (1, 0, ['inst-1']))
        self.assertTrue(running['instance_names'] ==
                        set(['inst-1', '123', 'inst-1_resize', '123_resize']))

        self.assertEqual(len(running['image_popularity']), 1)
        self.assertEqual(running['image_popularity']['1'], 1)
