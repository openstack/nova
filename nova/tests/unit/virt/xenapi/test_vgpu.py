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

from nova import test
from nova.virt.xenapi import host


class VGPUTestCase(test.NoDBTestCase):
    """Unit tests for Driver operations."""
    @mock.patch.object(host.HostState, 'update_status',
                       return_value='fake_stats_1')
    @mock.patch.object(host.HostState, '_get_vgpu_stats_in_group')
    def test_get_vgpu_stats_empty_cfg(self, mock_get, mock_update):
        # no vGPU type configured.
        self.flags(enabled_vgpu_types=[], group='devices')
        session = mock.Mock()

        host_obj = host.HostState(session)
        stats = host_obj._get_vgpu_stats()

        session.call_xenapi.assert_not_called()
        self.assertEqual(stats, {})

    @mock.patch.object(host.HostState, 'update_status',
                       return_value='fake_stats_1')
    @mock.patch.object(host.HostState, '_get_vgpu_stats_in_group')
    def test_get_vgpu_stats_single_type(self, mock_get, mock_update):
        # configured single vGPU type
        self.flags(enabled_vgpu_types=['type_name_1'], group='devices')
        session = mock.Mock()
        # multiple GPU groups
        session.call_xenapi.side_effect = [
            ['grp_ref1', 'grp_ref2'],  # GPU_group.get_all
            'uuid_1',  # GPU_group.get_uuid
            'uuid_2',  # GPU_group.get_uuid
        ]
        # Let it return None for the 2nd GPU group for the case
        # that it doesn't have the specified vGPU type enabled.
        mock_get.side_effect = ['fake_stats_1', None]
        host_obj = host.HostState(session)
        stats = host_obj._get_vgpu_stats()

        self.assertEqual(session.call_xenapi.call_count, 3)
        self.assertEqual(mock_update.call_count, 1)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(stats, {'uuid_1': 'fake_stats_1'})

    @mock.patch.object(host.HostState, 'update_status',
                       return_value='fake_stats_1')
    @mock.patch.object(host.HostState, '_get_vgpu_stats_in_group')
    def test_get_vgpu_stats_multi_types(self, mock_get, mock_update):
        # when multiple vGPU types configured, it use the first one.
        self.flags(enabled_vgpu_types=['type_name_1', 'type_name_2'],
                   group='devices')
        session = mock.Mock()
        session.call_xenapi.side_effect = [
            ['grp_ref1'],  # GPU_group.get_all
            'uuid_1',  # GPU_group.get_uuid
        ]
        mock_get.side_effect = ['fake_stats_1']
        host_obj = host.HostState(session)
        stats = host_obj._get_vgpu_stats()

        self.assertEqual(session.call_xenapi.call_count, 2)
        self.assertEqual(mock_update.call_count, 1)
        self.assertEqual(stats, {'uuid_1': 'fake_stats_1'})
        # called with the first vGPU type: 'type_name_1'
        mock_get.assert_called_with('grp_ref1', ['type_name_1'])

    @mock.patch.object(host.HostState, 'update_status',
                       return_value='fake_stats_1')
    @mock.patch.object(host.HostState, '_get_total_vgpu_in_grp',
                       return_value=7)
    def test_get_vgpu_stats_in_group(self, mock_get, mock_update):
        # Test it will return vGPU stat for the enabled vGPU type.
        enabled_vgpu_types = ['type_name_2']
        session = mock.Mock()
        session.call_xenapi.side_effect = [
            ['type_ref_1', 'type_ref_2'],  # GPU_group.get_enabled_VGPU_types
            'type_name_1',  # VGPU_type.get_model_name
            'type_name_2',  # VGPU_type.get_model_name
            'type_uuid_2',  # VGPU_type.get_uuid
            '4',  # VGPU_type.get_max_heads
            '6',  # GPU_group.get_remaining_capacity
        ]
        host_obj = host.HostState(session)

        stats = host_obj._get_vgpu_stats_in_group('grp_ref',
                                                  enabled_vgpu_types)

        expect_stats = {'uuid': 'type_uuid_2',
                        'type_name': 'type_name_2',
                        'max_heads': 4,
                        'total': 7,
                        'remaining': 6,
                        }
        self.assertEqual(session.call_xenapi.call_count, 6)
        # It should get_uuid for the vGPU type passed via *enabled_vgpu_types*
        # (the arg for get_uuid should be 'type_ref_2').
        get_uuid_call = [mock.call('VGPU_type.get_uuid', 'type_ref_2')]
        session.call_xenapi.assert_has_calls(get_uuid_call)
        mock_get.assert_called_once()
        self.assertEqual(expect_stats, stats)

    @mock.patch.object(host.HostState, 'update_status')
    @mock.patch.object(host.HostState, '_get_total_vgpu_in_grp',
                       return_value=7)
    def test_get_vgpu_stats_in_group_multiple(self, mock_get, mock_update):
        # Test when enabled multiple vGPU types in the same group.
        # It should only return the first vGPU type's stats.
        enabled_vgpu_types = ['type_name_1', 'type_name_2']
        session = mock.Mock()
        session.call_xenapi.side_effect = [
            ['type_ref_1', 'type_ref_2'],  # GPU_group.get_enabled_VGPU_types
            'type_name_1',  # VGPU_type.get_model_name
            'type_name_2',  # VGPU_type.get_model_name
            'type_uuid_1',  # VGPU_type.get_uuid
            '4',  # VGPU_type.get_max_heads
            '6',  # GPU_group.get_remaining_capacity
        ]
        host_obj = host.HostState(session)

        stats = host_obj._get_vgpu_stats_in_group('grp_ref',
                                                  enabled_vgpu_types)

        expect_stats = {
            'uuid': 'type_uuid_1',
            'type_name': 'type_name_1',
            'max_heads': 4,
            'total': 7,
            'remaining': 6,
        }
        self.assertEqual(session.call_xenapi.call_count, 6)
        # It should call get_uuid for the first vGPU type (the arg for get_uuid
        # should be 'type_ref_1').
        get_uuid_call = [mock.call('VGPU_type.get_uuid', 'type_ref_1')]
        session.call_xenapi.assert_has_calls(get_uuid_call)
        mock_get.assert_called_once()
        self.assertEqual(expect_stats, stats)

    @mock.patch.object(host.HostState, 'update_status')
    @mock.patch.object(host.HostState, '_get_total_vgpu_in_grp',
                       return_value=7)
    def test_get_vgpu_stats_in_group_cfg_not_in_grp(self, mock_get,
                                                    mock_update):
        # Test when the enable_vgpu_types is not a valid
        # type belong to the GPU group. It will return None.
        enabled_vgpu_types = ['bad_type_name']
        session = mock.Mock()
        session.call_xenapi.side_effect = [
            ['type_ref_1', 'type_ref_2'],  # GPU_group.get_enabled_VGPU_types
            'type_name_1',  # VGPU_type.get_model_name
            'type_name_2',  # VGPU_type.get_model_name
        ]
        host_obj = host.HostState(session)

        stats = host_obj._get_vgpu_stats_in_group('grp_ref',
                                                  enabled_vgpu_types)

        expect_stats = None
        self.assertEqual(session.call_xenapi.call_count, 3)
        mock_get.assert_not_called()
        self.assertEqual(expect_stats, stats)

    @mock.patch.object(host.HostState, 'update_status')
    def test_get_total_vgpu_in_grp(self, mock_update):
        session = mock.Mock()
        # The fake PGPU records returned from call_xenapi's string function:
        # "PGPU.get_all_records_where".
        pgpu_records = {
            'pgpu_ref1': {
                'enabled_VGPU_types': ['type_ref1', 'type_ref2'],
                'supported_VGPU_max_capacities': {
                    'type_ref1': '1',
                    'type_ref2': '3',
                }
            },
            'pgpu_ref2': {
                'enabled_VGPU_types': ['type_ref1', 'type_ref2'],
                'supported_VGPU_max_capacities': {
                    'type_ref1': '1',
                    'type_ref2': '3',
                }
            }
        }
        session.call_xenapi.return_value = pgpu_records
        host_obj = host.HostState(session)

        total = host_obj._get_total_vgpu_in_grp('grp_ref', 'type_ref1')

        session.call_xenapi.assert_called_with(
            'PGPU.get_all_records_where', 'field "GPU_group" = "grp_ref"')
        # The total amount of VGPUs is equal to sum of vaiable VGPU of
        # 'type_ref1' in all PGPUs.
        self.assertEqual(total, 2)
