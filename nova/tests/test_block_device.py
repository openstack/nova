# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from nova import test
from nova.tests import matchers


class BlockDeviceTestCase(test.TestCase):
    def test_properties(self):
        root_device0 = '/dev/sda'
        root_device1 = '/dev/sdb'
        mappings = [{'virtual': 'root',
                     'device': root_device0}]

        properties0 = {'mappings': mappings}
        properties1 = {'mappings': mappings,
                       'root_device_name': root_device1}

        self.assertEqual(block_device.properties_root_device_name({}), None)
        self.assertEqual(
            block_device.properties_root_device_name(properties0),
            root_device0)
        self.assertEqual(
            block_device.properties_root_device_name(properties1),
            root_device1)

    def test_ephemeral(self):
        self.assertFalse(block_device.is_ephemeral('ephemeral'))
        self.assertTrue(block_device.is_ephemeral('ephemeral0'))
        self.assertTrue(block_device.is_ephemeral('ephemeral1'))
        self.assertTrue(block_device.is_ephemeral('ephemeral11'))
        self.assertFalse(block_device.is_ephemeral('root'))
        self.assertFalse(block_device.is_ephemeral('swap'))
        self.assertFalse(block_device.is_ephemeral('/dev/sda1'))

        self.assertEqual(block_device.ephemeral_num('ephemeral0'), 0)
        self.assertEqual(block_device.ephemeral_num('ephemeral1'), 1)
        self.assertEqual(block_device.ephemeral_num('ephemeral11'), 11)

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
        self.assertEqual(prepended.sort(), expected.sort())

    def test_strip_dev(self):
        self.assertEqual(block_device.strip_dev('/dev/sda'), 'sda')
        self.assertEqual(block_device.strip_dev('sda'), 'sda')

    def test_strip_prefix(self):
        self.assertEqual(block_device.strip_prefix('/dev/sda'), 'a')
        self.assertEqual(block_device.strip_prefix('a'), 'a')
        self.assertEqual(block_device.strip_prefix('xvda'), 'a')
        self.assertEqual(block_device.strip_prefix('vda'), 'a')

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
            self.assertEquals(in_mapping, true_or_false)

        _assert_volume_in_mapping('sda', False)
        _assert_volume_in_mapping('sdb', True)
        _assert_volume_in_mapping('sdc1', True)
        _assert_volume_in_mapping('sdd', True)
        _assert_volume_in_mapping('sde', True)
        _assert_volume_in_mapping('sdf', True)
        _assert_volume_in_mapping('sdg', False)
        _assert_volume_in_mapping('sdh1', False)


class TestBlockDeviceDict(test.TestCase):
    def setUp(self):
        super(TestBlockDeviceDict, self).setUp()

        BDM = block_device.BlockDeviceDict

        self.new_mapping = [
            BDM({'id': 1, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/sdb1',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'delete_on_termination': True,
                 'guest_format': 'swap',
                 'boot_index': -1}),
            BDM({'id': 2, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/sdc1',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'delete_on_termination': True,
                 'boot_index': -1}),
            BDM({'id': 3, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/sda1',
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'volume_id': 'fake-folume-id-1',
                 'connection_info': "{'fake': 'connection_info'}",
                 'boot_index': -1}),
            BDM({'id': 4, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/sda2',
                 'source_type': 'snapshot',
                 'destination_type': 'volume',
                 'connection_info': "{'fake': 'connection_info'}",
                 'snapshot_id': 'fake-snapshot-id-1',
                 'volume_id': 'fake-volume-id-2',
                 'boot_index': -1}),
            BDM({'id': 5, 'instance_uuid': 'fake-instance',
                 'no_device': True,
                 'device_name': '/dev/vdc'}),
        ]

        self.legacy_mapping = [
            {'id': 1, 'instance_uuid': 'fake-instance',
             'device_name': '/dev/sdb1',
             'delete_on_termination': True,
             'virtual_name': 'swap'},
            {'id': 2, 'instance_uuid': 'fake-instance',
             'device_name': '/dev/sdc1',
             'delete_on_termination': True,
             'virtual_name': 'ephemeral0'},
            {'id': 3, 'instance_uuid': 'fake-instance',
             'device_name': '/dev/sda1',
             'volume_id': 'fake-folume-id-1',
             'connection_info': "{'fake': 'connection_info'}"},
            {'id': 4, 'instance_uuid': 'fake-instance',
             'device_name': '/dev/sda2',
             'connection_info': "{'fake': 'connection_info'}",
             'snapshot_id': 'fake-snapshot-id-1',
             'volume_id': 'fake-volume-id-2'},
            {'id': 5, 'instance_uuid': 'fake-instance',
             'no_device': True,
             'device_name': '/dev/vdc'},
        ]

    def test_init(self):
        self.stubs.Set(block_device.BlockDeviceDict, '_fields',
                       set(['field1', 'field2']))
        self.stubs.Set(block_device.BlockDeviceDict, '_db_only_fields',
                       set(['db_field1', 'db_field2']))

        # Make sure db fields are not picked up if they are not
        # in the original dict
        dev_dict = block_device.BlockDeviceDict({'field1': 'foo',
                                                 'field2': 'bar',
                                                 'db_field1': 'baz'})
        self.assertTrue('field1' in dev_dict)
        self.assertTrue('field2' in dev_dict)
        self.assertTrue('db_field1' in dev_dict)
        self.assertFalse('db_field2'in dev_dict)

        # Make sure all expected fields are defaulted
        dev_dict = block_device.BlockDeviceDict({'field1': 'foo'})
        self.assertTrue('field1' in dev_dict)
        self.assertTrue('field2' in dev_dict)
        self.assertTrue(dev_dict['field2'] is None)
        self.assertFalse('db_field1' in dev_dict)
        self.assertFalse('db_field2'in dev_dict)

        # Unless they are not meant to be
        dev_dict = block_device.BlockDeviceDict({'field1': 'foo'},
            do_not_default=set(['field2']))
        self.assertTrue('field1' in dev_dict)
        self.assertFalse('field2' in dev_dict)
        self.assertFalse('db_field1' in dev_dict)
        self.assertFalse('db_field2'in dev_dict)

        # Assert basic validation works
        # NOTE (ndipanov):  Move to separate test once we have
        #                   more complex validations in place
        self.assertRaises(exception.InvalidBDMFormat,
                          block_device.BlockDeviceDict,
                          {'field1': 'foo', 'bogus_field': 'lame_val'})

    def test_from_legacy(self):
        for legacy, new in zip(self.legacy_mapping, self.new_mapping):
            self.assertThat(
                block_device.BlockDeviceDict.from_legacy(legacy),
                matchers.IsSubDictOf(new))

    def test_legacy(self):
        for legacy, new in zip(self.legacy_mapping, self.new_mapping):
            self.assertThat(
                legacy,
                matchers.IsSubDictOf(new.legacy()))

    def test_legacy_mapping(self):
        got_legacy = block_device.legacy_mapping(self.new_mapping)

        for legacy, expected in zip(got_legacy, self.legacy_mapping):
            self.assertThat(expected, matchers.IsSubDictOf(legacy))
