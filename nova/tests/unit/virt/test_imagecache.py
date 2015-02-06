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

from oslo_config import cfg

from nova import block_device
from nova.compute import vm_states
from nova import context
from nova import objects
from nova import test
from nova.tests.unit import fake_instance
from nova.virt import imagecache

CONF = cfg.CONF

swap_bdm_128 = [block_device.BlockDeviceDict(
        {'id': 1, 'instance_uuid': 'fake-instance',
         'device_name': '/dev/sdb1',
         'source_type': 'blank',
         'destination_type': 'local',
         'delete_on_termination': True,
         'guest_format': 'swap',
         'disk_bus': 'scsi',
         'volume_size': 128,
         'boot_index': -1})]

swap_bdm_256 = [block_device.BlockDeviceDict(
        {'id': 1, 'instance_uuid': 'fake-instance',
         'device_name': '/dev/sdb1',
         'source_type': 'blank',
         'destination_type': 'local',
         'delete_on_termination': True,
         'guest_format': 'swap',
         'disk_bus': 'scsi',
         'volume_size': 256,
         'boot_index': -1})]


class ImageCacheManagerTests(test.NoDBTestCase):

    def test_configurationi_defaults(self):
        self.assertEqual(2400, CONF.image_cache_manager_interval)
        self.assertEqual('_base', CONF.image_cache_subdirectory_name)
        self.assertTrue(CONF.remove_unused_base_images)
        self.assertEqual(24 * 3600,
                         CONF.remove_unused_original_minimum_age_seconds)

    def test_cache_manager(self):
        cache_manager = imagecache.ImageCacheManager()
        self.assertTrue(cache_manager.remove_unused_base_images)
        self.assertRaises(NotImplementedError,
                          cache_manager.update, None, [])
        self.assertRaises(NotImplementedError,
                          cache_manager._get_base)
        base_images = cache_manager._list_base_images(None)
        self.assertEqual([], base_images['unexplained_images'])
        self.assertEqual([], base_images['originals'])
        self.assertRaises(NotImplementedError,
                          cache_manager._age_and_verify_cached_images,
                          None, [], None)

    def test_list_running_instances(self):
        instances = [{'image_ref': '1',
                      'host': CONF.host,
                      'id': '1',
                      'uuid': '123',
                      'vm_state': '',
                      'task_state': ''},
                     {'image_ref': '2',
                      'host': CONF.host,
                      'id': '2',
                      'uuid': '456',
                      'vm_state': '',
                      'task_state': ''},
                     {'image_ref': '2',
                      'kernel_id': '21',
                      'ramdisk_id': '22',
                      'host': 'remotehost',
                      'id': '3',
                      'uuid': '789',
                      'vm_state': '',
                      'task_state': ''}]

        all_instances = [fake_instance.fake_instance_obj(None, **instance)
                         for instance in instances]

        image_cache_manager = imagecache.ImageCacheManager()

        self.mox.StubOutWithMock(objects.block_device.BlockDeviceMappingList,
                   'get_by_instance_uuid')

        ctxt = context.get_admin_context()
        objects.block_device.BlockDeviceMappingList.get_by_instance_uuid(
                ctxt, '123').AndReturn(swap_bdm_256)
        objects.block_device.BlockDeviceMappingList.get_by_instance_uuid(
                ctxt, '456').AndReturn(swap_bdm_128)
        objects.block_device.BlockDeviceMappingList.get_by_instance_uuid(
                ctxt, '789').AndReturn(swap_bdm_128)

        self.mox.ReplayAll()

        # The argument here should be a context, but it's mocked out
        running = image_cache_manager._list_running_instances(ctxt,
            all_instances)

        self.assertEqual(4, len(running['used_images']))
        self.assertEqual((1, 0, ['instance-00000001']),
                         running['used_images']['1'])
        self.assertEqual((1, 1, ['instance-00000002',
                                 'instance-00000003']),
                         running['used_images']['2'])
        self.assertEqual((0, 1, ['instance-00000003']),
                         running['used_images']['21'])
        self.assertEqual((0, 1, ['instance-00000003']),
                         running['used_images']['22'])

        self.assertIn('instance-00000001', running['instance_names'])
        self.assertIn('123', running['instance_names'])

        self.assertEqual(4, len(running['image_popularity']))
        self.assertEqual(1, running['image_popularity']['1'])
        self.assertEqual(2, running['image_popularity']['2'])
        self.assertEqual(1, running['image_popularity']['21'])
        self.assertEqual(1, running['image_popularity']['22'])

        self.assertEqual(len(running['used_swap_images']), 2)
        self.assertIn('swap_128', running['used_swap_images'])
        self.assertIn('swap_256', running['used_swap_images'])

    def test_list_resizing_instances(self):
        instances = [{'image_ref': '1',
                      'host': CONF.host,
                      'id': '1',
                      'uuid': '123',
                      'vm_state': vm_states.RESIZED,
                      'task_state': None}]

        all_instances = [fake_instance.fake_instance_obj(None, **instance)
                         for instance in instances]

        image_cache_manager = imagecache.ImageCacheManager()
        self.mox.StubOutWithMock(objects.block_device.BlockDeviceMappingList,
                   'get_by_instance_uuid')

        ctxt = context.get_admin_context()
        objects.block_device.BlockDeviceMappingList.get_by_instance_uuid(
                ctxt, '123').AndReturn(swap_bdm_256)

        self.mox.ReplayAll()
        running = image_cache_manager._list_running_instances(ctxt,
            all_instances)

        self.assertEqual(1, len(running['used_images']))
        self.assertEqual((1, 0, ['instance-00000001']),
                         running['used_images']['1'])
        self.assertEqual(set(['instance-00000001', '123',
                              'instance-00000001_resize', '123_resize']),
                         running['instance_names'])

        self.assertEqual(1, len(running['image_popularity']))
        self.assertEqual(1, running['image_popularity']['1'])
