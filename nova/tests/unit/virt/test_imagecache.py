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

import mock
from oslo_utils.fixture import uuidsentinel as uuids

from nova import block_device
from nova.compute import vm_states
import nova.conf
from nova import context
from nova import objects
from nova.objects import block_device as block_device_obj
from nova import test
from nova.tests.unit import fake_instance
from nova.virt import imagecache

CONF = nova.conf.CONF

swap_bdm_128 = [block_device.BlockDeviceDict(
        {'id': 1, 'instance_uuid': uuids.instance,
         'device_name': '/dev/sdb1',
         'source_type': 'blank',
         'destination_type': 'local',
         'delete_on_termination': True,
         'guest_format': 'swap',
         'disk_bus': 'scsi',
         'volume_size': 128,
         'boot_index': -1})]

swap_bdm_256 = [block_device.BlockDeviceDict(
        {'id': 1, 'instance_uuid': uuids.instance,
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
        self.assertEqual(2400, CONF.image_cache.manager_interval)
        self.assertEqual('_base', CONF.image_cache.subdirectory_name)
        self.assertTrue(CONF.image_cache.remove_unused_base_images)
        self.assertEqual(
            24 * 3600,
            CONF.image_cache.remove_unused_original_minimum_age_seconds)

    def test_cache_manager(self):
        cache_manager = imagecache.ImageCacheManager()
        self.assertTrue(cache_manager.remove_unused_base_images)
        self.assertRaises(NotImplementedError,
                          cache_manager.update, None, [])
        self.assertRaises(NotImplementedError,
                          cache_manager._get_base)
        self.assertRaises(NotImplementedError,
                          cache_manager._scan_base_images, None)
        self.assertRaises(NotImplementedError,
                          cache_manager._age_and_verify_cached_images,
                          None, [], None)

    @mock.patch.object(objects.BlockDeviceMappingList,
                       'bdms_by_instance_uuid')
    def test_list_running_instances(self, mock_bdms_by_uuid):
        instances = [{'image_ref': '1',
                      'host': CONF.host,
                      'id': '1',
                      'uuid': uuids.instance_1,
                      'vm_state': '',
                      'task_state': ''},
                     {'image_ref': '2',
                      'host': CONF.host,
                      'id': '2',
                      'uuid': uuids.instance_2,
                      'vm_state': '',
                      'task_state': ''},
                     {'image_ref': '2',
                      'kernel_id': '21',
                      'ramdisk_id': '22',
                      'host': 'remotehost',
                      'id': '3',
                      'uuid': uuids.instance_3,
                      'vm_state': '',
                      'task_state': ''}]

        all_instances = [fake_instance.fake_instance_obj(None, **instance)
                         for instance in instances]

        image_cache_manager = imagecache.ImageCacheManager()

        ctxt = context.get_admin_context()
        swap_bdm_256_list = block_device_obj.block_device_make_list_from_dicts(
            ctxt, swap_bdm_256)
        swap_bdm_128_list = block_device_obj.block_device_make_list_from_dicts(
            ctxt, swap_bdm_128)
        mock_bdms_by_uuid.return_value = {uuids.instance_1: swap_bdm_256_list,
                                          uuids.instance_2: swap_bdm_128_list,
                                          uuids.instance_3: swap_bdm_128_list}
        # The argument here should be a context, but it's mocked out
        running = image_cache_manager._list_running_instances(ctxt,
            all_instances)

        mock_bdms_by_uuid.assert_called_once_with(ctxt,
                     [uuids.instance_1, uuids.instance_2, uuids.instance_3])
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
        self.assertIn(uuids.instance_1, running['instance_names'])

        self.assertEqual(len(running['used_swap_images']), 2)
        self.assertIn('swap_128', running['used_swap_images'])
        self.assertIn('swap_256', running['used_swap_images'])

    @mock.patch.object(objects.BlockDeviceMappingList,
                       'bdms_by_instance_uuid')
    def test_list_resizing_instances(self, mock_bdms_by_uuid):
        instances = [{'image_ref': '1',
                      'host': CONF.host,
                      'id': '1',
                      'uuid': uuids.instance,
                      'vm_state': vm_states.RESIZED,
                      'task_state': None}]

        all_instances = [fake_instance.fake_instance_obj(None, **instance)
                         for instance in instances]

        image_cache_manager = imagecache.ImageCacheManager()

        ctxt = context.get_admin_context()
        bdms = block_device_obj.block_device_make_list_from_dicts(
            ctxt, swap_bdm_256)
        mock_bdms_by_uuid.return_value = {uuids.instance: bdms}

        running = image_cache_manager._list_running_instances(ctxt,
            all_instances)

        mock_bdms_by_uuid.assert_called_once_with(ctxt, [uuids.instance])
        self.assertEqual(1, len(running['used_images']))
        self.assertEqual((1, 0, ['instance-00000001']),
                         running['used_images']['1'])
        self.assertEqual(set(['instance-00000001', uuids.instance,
                              'instance-00000001_resize',
                              '%s_resize' % uuids.instance]),
                         running['instance_names'])
