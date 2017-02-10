# Copyright 2011 Isaku Yamahata
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

"""
Tests for Block Device utility functions.
"""

from nova import block_device
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit import matchers
from nova.tests import uuidsentinel as uuids


class BlockDeviceTestCase(test.NoDBTestCase):
    def setUp(self):
        super(BlockDeviceTestCase, self).setUp()
        BDM = block_device.BlockDeviceDict

        self.new_mapping = [
            BDM({'id': 1, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sdb1',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'delete_on_termination': True,
                 'volume_size': 1,
                 'guest_format': 'swap',
                 'boot_index': -1}),
            BDM({'id': 2, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sdc1',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'volume_size': 10,
                 'delete_on_termination': True,
                 'boot_index': -1}),
            BDM({'id': 3, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sda1',
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'volume_id': 'fake-volume-id-1',
                 'connection_info': "{'fake': 'connection_info'}",
                 'boot_index': 0}),
            BDM({'id': 4, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sda2',
                 'source_type': 'snapshot',
                 'destination_type': 'volume',
                 'connection_info': "{'fake': 'connection_info'}",
                 'snapshot_id': 'fake-snapshot-id-1',
                 'volume_id': 'fake-volume-id-2',
                 'boot_index': -1}),
            BDM({'id': 5, 'instance_uuid': uuids.instance,
                 'no_device': True,
                 'device_name': '/dev/vdc'}),
        ]

    def test_properties(self):
        root_device0 = '/dev/sda'
        root_device1 = '/dev/sdb'
        mappings = [{'virtual': 'root',
                     'device': root_device0}]

        properties0 = {'mappings': mappings}
        properties1 = {'mappings': mappings,
                       'root_device_name': root_device1}

        self.assertIsNone(block_device.properties_root_device_name({}))
        self.assertEqual(root_device0,
                         block_device.properties_root_device_name(properties0))
        self.assertEqual(root_device1,
                         block_device.properties_root_device_name(properties1))

    def test_ephemeral(self):
        self.assertFalse(block_device.is_ephemeral('ephemeral'))
        self.assertTrue(block_device.is_ephemeral('ephemeral0'))
        self.assertTrue(block_device.is_ephemeral('ephemeral1'))
        self.assertTrue(block_device.is_ephemeral('ephemeral11'))
        self.assertFalse(block_device.is_ephemeral('root'))
        self.assertFalse(block_device.is_ephemeral('swap'))
        self.assertFalse(block_device.is_ephemeral('/dev/sda1'))

        self.assertEqual(0, block_device.ephemeral_num('ephemeral0'))
        self.assertEqual(1, block_device.ephemeral_num('ephemeral1'))
        self.assertEqual(11, block_device.ephemeral_num('ephemeral11'))

        self.assertFalse(block_device.is_swap_or_ephemeral('ephemeral'))
        self.assertTrue(block_device.is_swap_or_ephemeral('ephemeral0'))
        self.assertTrue(block_device.is_swap_or_ephemeral('ephemeral1'))
        self.assertTrue(block_device.is_swap_or_ephemeral('swap'))
        self.assertFalse(block_device.is_swap_or_ephemeral('root'))
        self.assertFalse(block_device.is_swap_or_ephemeral('/dev/sda1'))

    def test_mappings_prepend_dev(self):
        mapping = [
            {'virtual': 'ami', 'device': '/dev/sda'},
            {'virtual': 'root', 'device': 'sda'},
            {'virtual': 'ephemeral0', 'device': 'sdb'},
            {'virtual': 'swap', 'device': 'sdc'},
            {'virtual': 'ephemeral1', 'device': 'sdd'},
            {'virtual': 'ephemeral2', 'device': 'sde'}]

        expected = [
            {'virtual': 'ami', 'device': '/dev/sda'},
            {'virtual': 'root', 'device': 'sda'},
            {'virtual': 'ephemeral0', 'device': '/dev/sdb'},
            {'virtual': 'swap', 'device': '/dev/sdc'},
            {'virtual': 'ephemeral1', 'device': '/dev/sdd'},
            {'virtual': 'ephemeral2', 'device': '/dev/sde'}]

        prepended = block_device.mappings_prepend_dev(mapping)
        self.assertEqual(sorted(expected, key=lambda v: v['virtual']),
                         sorted(prepended, key=lambda v: v['virtual']))

    def test_strip_dev(self):
        self.assertEqual('sda', block_device.strip_dev('/dev/sda'))
        self.assertEqual('sda', block_device.strip_dev('sda'))
        self.assertIsNone(block_device.strip_dev(None))

    def test_strip_prefix(self):
        self.assertEqual('a', block_device.strip_prefix('/dev/sda'))
        self.assertEqual('a', block_device.strip_prefix('a'))
        self.assertEqual('a', block_device.strip_prefix('xvda'))
        self.assertEqual('a', block_device.strip_prefix('vda'))
        self.assertEqual('a', block_device.strip_prefix('hda'))
        self.assertIsNone(block_device.strip_prefix(None))

    def test_get_device_letter(self):
        self.assertEqual('', block_device.get_device_letter(''))
        self.assertEqual('a', block_device.get_device_letter('/dev/sda1'))
        self.assertEqual('b', block_device.get_device_letter('/dev/xvdb'))
        self.assertEqual('d', block_device.get_device_letter('/dev/d'))
        self.assertEqual('a', block_device.get_device_letter('a'))
        self.assertEqual('b', block_device.get_device_letter('sdb2'))
        self.assertEqual('c', block_device.get_device_letter('vdc'))
        self.assertEqual('c', block_device.get_device_letter('hdc'))
        self.assertIsNone(block_device.get_device_letter(None))

    def test_volume_in_mapping(self):
        swap = {'device_name': '/dev/sdb',
                'swap_size': 1}
        ephemerals = [{'num': 0,
                       'virtual_name': 'ephemeral0',
                       'device_name': '/dev/sdc1',
                       'size': 1},
                      {'num': 2,
                       'virtual_name': 'ephemeral2',
                       'device_name': '/dev/sdd',
                       'size': 1}]
        block_device_mapping = [{'mount_device': '/dev/sde',
                                 'device_path': 'fake_device'},
                                {'mount_device': '/dev/sdf',
                                 'device_path': 'fake_device'}]
        block_device_info = {
                'root_device_name': '/dev/sda',
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

        def _assert_volume_in_mapping(device_name, true_or_false):
            in_mapping = block_device.volume_in_mapping(
                    device_name, block_device_info)
            self.assertEqual(true_or_false, in_mapping)

        _assert_volume_in_mapping('sda', False)
        _assert_volume_in_mapping('sdb', True)
        _assert_volume_in_mapping('sdc1', True)
        _assert_volume_in_mapping('sdd', True)
        _assert_volume_in_mapping('sde', True)
        _assert_volume_in_mapping('sdf', True)
        _assert_volume_in_mapping('sdg', False)
        _assert_volume_in_mapping('sdh1', False)

    def test_get_root_bdm(self):
        root_bdm = {'device_name': 'vda', 'boot_index': 0}
        bdms = [root_bdm,
                {'device_name': 'vdb', 'boot_index': 1},
                {'device_name': 'vdc', 'boot_index': -1},
                {'device_name': 'vdd'}]
        self.assertEqual(root_bdm, block_device.get_root_bdm(bdms))
        self.assertEqual(root_bdm, block_device.get_root_bdm([bdms[0]]))
        self.assertIsNone(block_device.get_root_bdm(bdms[1:]))
        self.assertIsNone(block_device.get_root_bdm(bdms[2:]))
        self.assertIsNone(block_device.get_root_bdm(bdms[3:]))
        self.assertIsNone(block_device.get_root_bdm([]))

    def test_get_bdm_ephemeral_disk_size(self):
        size = block_device.get_bdm_ephemeral_disk_size(self.new_mapping)
        self.assertEqual(10, size)

    def test_get_bdm_swap_list(self):
        swap_list = block_device.get_bdm_swap_list(self.new_mapping)
        self.assertEqual(1, len(swap_list))
        self.assertEqual(1, swap_list[0].get('id'))

    def test_get_bdm_local_disk_num(self):
        size = block_device.get_bdm_local_disk_num(self.new_mapping)
        self.assertEqual(2, size)

    def test_new_format_is_swap(self):
        expected_results = [True, False, False, False, False]
        for expected, bdm in zip(expected_results, self.new_mapping):
            res = block_device.new_format_is_swap(bdm)
            self.assertEqual(expected, res)

    def test_new_format_is_ephemeral(self):
        expected_results = [False, True, False, False, False]
        for expected, bdm in zip(expected_results, self.new_mapping):
            res = block_device.new_format_is_ephemeral(bdm)
            self.assertEqual(expected, res)

    def test_validate_device_name(self):
        for value in [' ', 10, None, 'a' * 260]:
            self.assertRaises(exception.InvalidBDMFormat,
                              block_device.validate_device_name,
                              value)

    def test_validate_and_default_volume_size(self):
        bdm = {}
        for value in [-1, 'a', 2.5]:
            bdm['volume_size'] = value
            self.assertRaises(exception.InvalidBDMFormat,
                              block_device.validate_and_default_volume_size,
                              bdm)

    def test_get_bdms_to_connect(self):
        root_bdm = {'device_name': 'vda', 'boot_index': 0}
        bdms = [root_bdm,
                {'device_name': 'vdb', 'boot_index': 1},
                {'device_name': 'vdc', 'boot_index': -1},
                {'device_name': 'vde', 'boot_index': None},
                {'device_name': 'vdd'}]
        self.assertNotIn(root_bdm, block_device.get_bdms_to_connect(bdms,
                                                exclude_root_mapping=True))
        self.assertIn(root_bdm, block_device.get_bdms_to_connect(bdms))


class TestBlockDeviceDict(test.NoDBTestCase):
    def setUp(self):
        super(TestBlockDeviceDict, self).setUp()

        BDM = block_device.BlockDeviceDict

        self.api_mapping = [
            {'id': 1, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sdb1',
             'source_type': 'blank',
             'destination_type': 'local',
             'delete_on_termination': True,
             'guest_format': 'swap',
             'boot_index': -1},
            {'id': 2, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sdc1',
             'source_type': 'blank',
             'destination_type': 'local',
             'delete_on_termination': True,
             'boot_index': -1},
            {'id': 3, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sda1',
             'source_type': 'volume',
             'destination_type': 'volume',
             'uuid': 'fake-volume-id-1',
             'boot_index': 0},
            {'id': 4, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sda2',
             'source_type': 'snapshot',
             'destination_type': 'volume',
             'uuid': 'fake-snapshot-id-1',
             'boot_index': -1},
            {'id': 5, 'instance_uuid': uuids.instance,
             'no_device': True,
             'device_name': '/dev/vdc'},
        ]

        self.new_mapping = [
            BDM({'id': 1, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sdb1',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'delete_on_termination': True,
                 'guest_format': 'swap',
                 'boot_index': -1}),
            BDM({'id': 2, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sdc1',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'delete_on_termination': True,
                 'boot_index': -1}),
            BDM({'id': 3, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sda1',
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'volume_id': 'fake-volume-id-1',
                 'connection_info': "{'fake': 'connection_info'}",
                 'boot_index': 0}),
            BDM({'id': 4, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sda2',
                 'source_type': 'snapshot',
                 'destination_type': 'volume',
                 'connection_info': "{'fake': 'connection_info'}",
                 'snapshot_id': 'fake-snapshot-id-1',
                 'volume_id': 'fake-volume-id-2',
                 'boot_index': -1}),
            BDM({'id': 5, 'instance_uuid': uuids.instance,
                 'no_device': True,
                 'device_name': '/dev/vdc'}),
        ]

        self.legacy_mapping = [
            {'id': 1, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sdb1',
             'delete_on_termination': True,
             'virtual_name': 'swap'},
            {'id': 2, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sdc1',
             'delete_on_termination': True,
             'virtual_name': 'ephemeral0'},
            {'id': 3, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sda1',
             'volume_id': 'fake-volume-id-1',
             'connection_info': "{'fake': 'connection_info'}"},
            {'id': 4, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sda2',
             'connection_info': "{'fake': 'connection_info'}",
             'snapshot_id': 'fake-snapshot-id-1',
             'volume_id': 'fake-volume-id-2'},
            {'id': 5, 'instance_uuid': uuids.instance,
             'no_device': True,
             'device_name': '/dev/vdc'},
        ]

        self.new_mapping_source_image = [
            BDM({'id': 6, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sda3',
                 'source_type': 'image',
                 'destination_type': 'volume',
                 'connection_info': "{'fake': 'connection_info'}",
                 'volume_id': 'fake-volume-id-3',
                 'boot_index': -1}),
            BDM({'id': 7, 'instance_uuid': uuids.instance,
                 'device_name': '/dev/sda4',
                 'source_type': 'image',
                 'destination_type': 'local',
                 'connection_info': "{'fake': 'connection_info'}",
                 'image_id': 'fake-image-id-2',
                 'boot_index': -1}),
        ]

        self.legacy_mapping_source_image = [
            {'id': 6, 'instance_uuid': uuids.instance,
             'device_name': '/dev/sda3',
             'connection_info': "{'fake': 'connection_info'}",
             'volume_id': 'fake-volume-id-3'},
        ]

    def test_init(self):
        def fake_validate(obj, dct):
            pass

        self.stub_out('nova.block_device.BlockDeviceDict._fields',
                       set(['field1', 'field2']))
        self.stub_out('nova.block_device.BlockDeviceDict._db_only_fields',
                       set(['db_field1', 'db_field2']))
        self.stub_out('nova.block_device.BlockDeviceDict._validate',
                       fake_validate)

        # Make sure db fields are not picked up if they are not
        # in the original dict
        dev_dict = block_device.BlockDeviceDict({'field1': 'foo',
                                                 'field2': 'bar',
                                                 'db_field1': 'baz'})
        self.assertIn('field1', dev_dict)
        self.assertIn('field2', dev_dict)
        self.assertIn('db_field1', dev_dict)
        self.assertNotIn('db_field2', dev_dict)

        # Make sure all expected fields are defaulted
        dev_dict = block_device.BlockDeviceDict({'field1': 'foo'})
        self.assertIn('field1', dev_dict)
        self.assertIn('field2', dev_dict)
        self.assertIsNone(dev_dict['field2'])
        self.assertNotIn('db_field1', dev_dict)
        self.assertNotIn('db_field2', dev_dict)

        # Unless they are not meant to be
        dev_dict = block_device.BlockDeviceDict({'field1': 'foo'},
            do_not_default=set(['field2']))
        self.assertIn('field1', dev_dict)
        self.assertNotIn('field2', dev_dict)
        self.assertNotIn('db_field1', dev_dict)
        self.assertNotIn('db_field2', dev_dict)

        # Passing kwargs to constructor works
        dev_dict = block_device.BlockDeviceDict(field1='foo')
        self.assertIn('field1', dev_dict)
        self.assertIn('field2', dev_dict)
        self.assertIsNone(dev_dict['field2'])
        dev_dict = block_device.BlockDeviceDict(
                {'field1': 'foo'}, field2='bar')
        self.assertEqual('foo', dev_dict['field1'])
        self.assertEqual('bar', dev_dict['field2'])

    def test_init_prepend_dev_to_device_name(self):
        bdm = {'id': 3, 'instance_uuid': uuids.instance,
               'device_name': 'vda',
               'source_type': 'volume',
               'destination_type': 'volume',
               'volume_id': 'fake-volume-id-1',
               'boot_index': 0}
        bdm_dict = block_device.BlockDeviceDict(bdm)
        self.assertEqual('/dev/vda', bdm_dict['device_name'])

        bdm['device_name'] = '/dev/vdb'
        bdm_dict = block_device.BlockDeviceDict(bdm)
        self.assertEqual('/dev/vdb', bdm_dict['device_name'])

        bdm['device_name'] = None
        bdm_dict = block_device.BlockDeviceDict(bdm)
        self.assertIsNone(bdm_dict['device_name'])

    def test_init_boolify_delete_on_termination(self):
        # Make sure that when delete_on_termination is not passed it's
        # still set to False and not None
        bdm = {'id': 3, 'instance_uuid': uuids.instance,
               'device_name': 'vda',
               'source_type': 'volume',
               'destination_type': 'volume',
               'volume_id': 'fake-volume-id-1',
               'boot_index': 0}
        bdm_dict = block_device.BlockDeviceDict(bdm)
        self.assertFalse(bdm_dict['delete_on_termination'])

    def test_validate(self):
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict,
                          {'bogus_field': 'lame_val'})

        lame_bdm = dict(self.new_mapping[2])
        del lame_bdm['source_type']
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict,
                          lame_bdm)

        lame_bdm['no_device'] = True
        block_device.BlockDeviceDict(lame_bdm)

        lame_dev_bdm = dict(self.new_mapping[2])
        lame_dev_bdm['device_name'] = "not a valid name"
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict,
                          lame_dev_bdm)

        lame_dev_bdm['device_name'] = ""
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict,
                          lame_dev_bdm)

        cool_volume_size_bdm = dict(self.new_mapping[2])
        cool_volume_size_bdm['volume_size'] = '42'
        cool_volume_size_bdm = block_device.BlockDeviceDict(
            cool_volume_size_bdm)
        self.assertEqual(42, cool_volume_size_bdm['volume_size'])

        lame_volume_size_bdm = dict(self.new_mapping[2])
        lame_volume_size_bdm['volume_size'] = 'some_non_int_string'
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict,
                          lame_volume_size_bdm)

        truthy_bdm = dict(self.new_mapping[2])
        truthy_bdm['delete_on_termination'] = '1'
        truthy_bdm = block_device.BlockDeviceDict(truthy_bdm)
        self.assertTrue(truthy_bdm['delete_on_termination'])

        verbose_bdm = dict(self.new_mapping[2])
        verbose_bdm['boot_index'] = 'first'
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict,
                          verbose_bdm)

    def test_from_legacy(self):
        for legacy, new in zip(self.legacy_mapping, self.new_mapping):
            self.assertThat(
                block_device.BlockDeviceDict.from_legacy(legacy),
                matchers.IsSubDictOf(new))

    def test_from_legacy_mapping(self):
        def _get_image_bdms(bdms):
            return [bdm for bdm in bdms if bdm['source_type'] == 'image']

        def _get_bootable_bdms(bdms):
            return [bdm for bdm in bdms
                    if (bdm['boot_index'] is not None and
                        bdm['boot_index'] >= 0)]

        new_no_img = block_device.from_legacy_mapping(self.legacy_mapping)
        self.assertEqual(0, len(_get_image_bdms(new_no_img)))

        for new, expected in zip(new_no_img, self.new_mapping):
            self.assertThat(new, matchers.IsSubDictOf(expected))

        new_with_img = block_device.from_legacy_mapping(
            self.legacy_mapping, 'fake_image_ref')
        image_bdms = _get_image_bdms(new_with_img)
        boot_bdms = _get_bootable_bdms(new_with_img)
        self.assertEqual(1, len(image_bdms))
        self.assertEqual(1, len(boot_bdms))
        self.assertEqual(0, image_bdms[0]['boot_index'])
        self.assertEqual('image', boot_bdms[0]['source_type'])

        new_with_img_and_root = block_device.from_legacy_mapping(
            self.legacy_mapping, 'fake_image_ref', 'sda1')
        image_bdms = _get_image_bdms(new_with_img_and_root)
        boot_bdms = _get_bootable_bdms(new_with_img_and_root)
        self.assertEqual(0, len(image_bdms))
        self.assertEqual(1, len(boot_bdms))
        self.assertEqual(0, boot_bdms[0]['boot_index'])
        self.assertEqual('volume', boot_bdms[0]['source_type'])

        new_no_root = block_device.from_legacy_mapping(
            self.legacy_mapping, 'fake_image_ref', 'sda1', no_root=True)
        self.assertEqual(0, len(_get_image_bdms(new_no_root)))
        self.assertEqual(0, len(_get_bootable_bdms(new_no_root)))

    def test_from_api(self):
        for api, new in zip(self.api_mapping, self.new_mapping):
            new['connection_info'] = None
            if new['snapshot_id']:
                new['volume_id'] = None
            self.assertThat(
                block_device.BlockDeviceDict.from_api(api, False),
                matchers.IsSubDictOf(new))

    def test_from_api_invalid_blank_id(self):
        api_dict = {'id': 1,
                    'source_type': 'blank',
                    'destination_type': 'volume',
                    'uuid': 'fake-volume-id-1',
                    'delete_on_termination': True,
                    'boot_index': -1}
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict.from_api, api_dict,
                          False)

    def test_from_api_invalid_source_to_local_mapping(self):
        api_dict = {'id': 1,
                    'source_type': 'image',
                    'destination_type': 'local',
                    'uuid': 'fake-volume-id-1'}
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict.from_api, api_dict,
                          False)

    def test_from_api_valid_source_to_local_mapping(self):
        api_dict = {'id': 1,
                    'source_type': 'image',
                    'destination_type': 'local',
                    'volume_id': 'fake-volume-id-1',
                    'uuid': 1,
                    'boot_index': 0}

        retexp = block_device.BlockDeviceDict(
            {'id': 1,
             'source_type': 'image',
             'image_id': 1,
             'destination_type': 'local',
             'volume_id': 'fake-volume-id-1',
             'boot_index': 0})
        self.assertEqual(retexp,
                         block_device.BlockDeviceDict.from_api(api_dict, True))

    def test_from_api_valid_source_to_local_mapping_with_string_bi(self):
        api_dict = {'id': 1,
                    'source_type': 'image',
                    'destination_type': 'local',
                    'volume_id': 'fake-volume-id-1',
                    'uuid': 1,
                    'boot_index': '0'}

        retexp = block_device.BlockDeviceDict(
            {'id': 1,
             'source_type': 'image',
             'image_id': 1,
             'destination_type': 'local',
             'volume_id': 'fake-volume-id-1',
             'boot_index': 0})
        self.assertEqual(retexp,
                         block_device.BlockDeviceDict.from_api(api_dict, True))

    def test_legacy(self):
        for legacy, new in zip(self.legacy_mapping, self.new_mapping):
            self.assertThat(
                legacy,
                matchers.IsSubDictOf(new.legacy()))

    def test_legacy_mapping(self):
        got_legacy = block_device.legacy_mapping(self.new_mapping)

        for legacy, expected in zip(got_legacy, self.legacy_mapping):
            self.assertThat(expected, matchers.IsSubDictOf(legacy))

    def test_legacy_source_image(self):
        for legacy, new in zip(self.legacy_mapping_source_image,
                               self.new_mapping_source_image):
            if new['destination_type'] == 'volume':
                self.assertThat(legacy, matchers.IsSubDictOf(new.legacy()))
            else:
                self.assertRaises(exception.InvalidBDMForLegacy, new.legacy)

    def test_legacy_mapping_source_image(self):
        got_legacy = block_device.legacy_mapping(self.new_mapping)

        for legacy, expected in zip(got_legacy, self.legacy_mapping):
            self.assertThat(expected, matchers.IsSubDictOf(legacy))

    def test_legacy_mapping_from_object_list(self):
        bdm1 = objects.BlockDeviceMapping()
        bdm1 = objects.BlockDeviceMapping._from_db_object(
            None, bdm1, fake_block_device.FakeDbBlockDeviceDict(
                self.new_mapping[0]))
        bdm2 = objects.BlockDeviceMapping()
        bdm2 = objects.BlockDeviceMapping._from_db_object(
            None, bdm2, fake_block_device.FakeDbBlockDeviceDict(
                self.new_mapping[1]))
        bdmlist = objects.BlockDeviceMappingList()
        bdmlist.objects = [bdm1, bdm2]
        block_device.legacy_mapping(bdmlist)

    def test_image_mapping(self):
        removed_fields = ['id', 'instance_uuid', 'connection_info',
                          'created_at', 'updated_at', 'deleted_at', 'deleted']
        for bdm in self.new_mapping:
            mapping_bdm = fake_block_device.FakeDbBlockDeviceDict(
                    bdm).get_image_mapping()
            for fld in removed_fields:
                self.assertNotIn(fld, mapping_bdm)

    def _test_snapshot_from_bdm(self, template):
        snapshot = block_device.snapshot_from_bdm('new-snapshot-id', template)
        self.assertEqual('new-snapshot-id', snapshot['snapshot_id'])
        self.assertEqual('snapshot', snapshot['source_type'])
        self.assertEqual('volume', snapshot['destination_type'])
        self.assertEqual(template.volume_size, snapshot['volume_size'])
        self.assertEqual(template.delete_on_termination,
                         snapshot['delete_on_termination'])
        self.assertEqual(template.device_name, snapshot['device_name'])
        for key in ['disk_bus', 'device_type', 'boot_index']:
            self.assertEqual(template[key], snapshot[key])

    def test_snapshot_from_bdm(self):
        for bdm in self.new_mapping:
            self._test_snapshot_from_bdm(objects.BlockDeviceMapping(**bdm))

    def test_snapshot_from_object(self):
        for bdm in self.new_mapping[:-1]:
            obj = objects.BlockDeviceMapping()
            obj = objects.BlockDeviceMapping._from_db_object(
                   None, obj, fake_block_device.FakeDbBlockDeviceDict(
                       bdm))
            self._test_snapshot_from_bdm(obj)
