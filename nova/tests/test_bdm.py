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
Tests for Block Device Mapping Code.
"""

from nova.api.ec2 import cloud
from nova import test


class BlockDeviceMappingEc2CloudTestCase(test.TestCase):
    """Test Case for Block Device Mapping"""

    def setUp(self):
        super(BlockDeviceMappingEc2CloudTestCase, self).setUp()

    def tearDown(self):
        super(BlockDeviceMappingEc2CloudTestCase, self).tearDown()

    def _assertApply(self, action, bdm_list):
        for bdm, expected_result in bdm_list:
            self.assertDictMatch(action(bdm), expected_result)

    def test_parse_block_device_mapping(self):
        bdm_list = [
            ({'device_name': '/dev/fake0',
              'ebs': {'snapshot_id': 'snap-12345678',
                      'volume_size': 1}},
            {'device_name': '/dev/fake0',
             'snapshot_id': 0x12345678,
             'volume_size': 1,
             'delete_on_termination': True}),

            ({'device_name': '/dev/fake1',
              'ebs': {'snapshot_id': 'snap-23456789',
                      'delete_on_termination': False}},
             {'device_name': '/dev/fake1',
              'snapshot_id': 0x23456789,
              'delete_on_termination': False}),

            ({'device_name': '/dev/fake2',
              'ebs': {'snapshot_id': 'vol-87654321',
                      'volume_size': 2}},
            {'device_name': '/dev/fake2',
             'volume_id': 0x87654321,
             'volume_size': 2,
             'delete_on_termination': True}),

            ({'device_name': '/dev/fake3',
              'ebs': {'snapshot_id': 'vol-98765432',
                      'delete_on_termination': False}},
             {'device_name': '/dev/fake3',
              'volume_id': 0x98765432,
              'delete_on_termination': False}),

            ({'device_name': '/dev/fake4',
              'ebs': {'no_device': True}},
             {'device_name': '/dev/fake4',
              'no_device': True}),

            ({'device_name': '/dev/fake5',
             'virtual_name': 'ephemeral0'},
            {'device_name': '/dev/fake5',
             'virtual_name': 'ephemeral0'}),

            ({'device_name': '/dev/fake6',
             'virtual_name': 'swap'},
            {'device_name': '/dev/fake6',
             'virtual_name': 'swap'}),
            ]
        self._assertApply(cloud._parse_block_device_mapping, bdm_list)

    def test_format_block_device_mapping(self):
        bdm_list = [
            ({'device_name': '/dev/fake0',
              'snapshot_id': 0x12345678,
              'volume_size': 1,
              'delete_on_termination': True},
             {'deviceName': '/dev/fake0',
              'ebs': {'snapshotId': 'snap-12345678',
                      'volumeSize': 1,
                      'deleteOnTermination': True}}),

            ({'device_name': '/dev/fake1',
              'snapshot_id': 0x23456789},
             {'deviceName': '/dev/fake1',
              'ebs': {'snapshotId': 'snap-23456789'}}),

            ({'device_name': '/dev/fake2',
              'snapshot_id': 0x23456789,
              'delete_on_termination': False},
             {'deviceName': '/dev/fake2',
              'ebs': {'snapshotId': 'snap-23456789',
                      'deleteOnTermination': False}}),

            ({'device_name': '/dev/fake3',
              'volume_id': 0x12345678,
              'volume_size': 1,
              'delete_on_termination': True},
             {'deviceName': '/dev/fake3',
              'ebs': {'snapshotId': 'vol-12345678',
                      'volumeSize': 1,
                      'deleteOnTermination': True}}),

            ({'device_name': '/dev/fake4',
              'volume_id': 0x23456789},
             {'deviceName': '/dev/fake4',
              'ebs': {'snapshotId': 'vol-23456789'}}),

            ({'device_name': '/dev/fake5',
              'volume_id': 0x23456789,
              'delete_on_termination': False},
             {'deviceName': '/dev/fake5',
              'ebs': {'snapshotId': 'vol-23456789',
                      'deleteOnTermination': False}}),
            ]
        self._assertApply(cloud._format_block_device_mapping, bdm_list)

    def test_format_mapping(self):
        properties = {
            'mappings': [
                {'virtual': 'ami',
                 'device': 'sda1'},
                {'virtual': 'root',
                 'device': '/dev/sda1'},

                {'virtual': 'swap',
                 'device': 'sdb1'},
                {'virtual': 'swap',
                 'device': 'sdb2'},
                {'virtual': 'swap',
                 'device': 'sdb3'},
                {'virtual': 'swap',
                 'device': 'sdb4'},

                {'virtual': 'ephemeral0',
                 'device': 'sdc1'},
                {'virtual': 'ephemeral1',
                 'device': 'sdc2'},
                {'virtual': 'ephemeral2',
                 'device': 'sdc3'},
                ],

            'block_device_mapping': [
                # root
                {'device_name': '/dev/sda1',
                 'snapshot_id': 0x12345678,
                 'delete_on_termination': False},


                # overwrite swap
                {'device_name': '/dev/sdb2',
                 'snapshot_id': 0x23456789,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdb3',
                 'snapshot_id': 0x3456789A},
                {'device_name': '/dev/sdb4',
                 'no_device': True},

                # overwrite ephemeral
                {'device_name': '/dev/sdc2',
                 'snapshot_id': 0x3456789A,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdc3',
                 'snapshot_id': 0x456789AB},
                {'device_name': '/dev/sdc4',
                 'no_device': True},

                # volume
                {'device_name': '/dev/sdd1',
                 'snapshot_id': 0x87654321,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdd2',
                 'snapshot_id': 0x98765432},
                {'device_name': '/dev/sdd3',
                 'snapshot_id': 0xA9875463},
                {'device_name': '/dev/sdd4',
                 'no_device': True}]}

        expected_result = {
            'blockDeviceMapping': [
                # root
                {'deviceName': '/dev/sda1',
                 'ebs': {'snapshotId': 'snap-12345678',
                         'deleteOnTermination': False}},

                # swap
                {'deviceName': '/dev/sdb1',
                 'virtualName': 'swap'},
                {'deviceName': '/dev/sdb2',
                 'ebs': {'snapshotId': 'snap-23456789',
                         'deleteOnTermination': False}},
                {'deviceName': '/dev/sdb3',
                 'ebs': {'snapshotId': 'snap-3456789a'}},

                # ephemeral
                {'deviceName': '/dev/sdc1',
                 'virtualName': 'ephemeral0'},
                {'deviceName': '/dev/sdc2',
                 'ebs': {'snapshotId': 'snap-3456789a',
                         'deleteOnTermination': False}},
                {'deviceName': '/dev/sdc3',
                 'ebs': {'snapshotId': 'snap-456789ab'}},

                # volume
                {'deviceName': '/dev/sdd1',
                 'ebs': {'snapshotId': 'snap-87654321',
                         'deleteOnTermination': False}},
                {'deviceName': '/dev/sdd2',
                 'ebs': {'snapshotId': 'snap-98765432'}},
                {'deviceName': '/dev/sdd3',
                 'ebs': {'snapshotId': 'snap-a9875463'}}]}

        result = {}
        cloud._format_mappings(properties, result)
        print result
        self.assertEqual(result['blockDeviceMapping'].sort(),
                         expected_result['blockDeviceMapping'].sort())
