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
from oslo_utils.fixture import uuidsentinel

from nova.compute import vm_states
from nova import objects
from nova import test
from nova.virt.libvirt import machine_type_utils


class TestMachineTypeUtils(test.NoDBTestCase):

    def _create_test_instance_obj(
        self,
        vm_state=vm_states.STOPPED,
        mtype=None
    ):
        instance = objects.Instance(
            uuid=uuidsentinel.instance, host='fake', node='fake',
            task_state=None, flavor=objects.Flavor(),
            project_id='fake-project', user_id='fake-user',
            vm_state=vm_state, system_metadata={}
        )
        if mtype:
            instance.system_metadata = {
                'image_hw_machine_type': mtype,
            }
        return instance

    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid',
        new=mock.Mock(cell_mapping=mock.sentinel.cell_mapping))
    def test_get_machine_type(self, mock_target_cell, mock_get_instance):
        mock_target_cell.return_value.__enter__.return_value = (
            mock.sentinel.cell_context)
        mock_get_instance.return_value = self._create_test_instance_obj(
            mtype='pc'
        )
        self.assertEqual(
            'pc',
            machine_type_utils.get_machine_type(
                mock.sentinel.context,
                instance_uuid=uuidsentinel.instance
            )
        )
        mock_get_instance.assert_called_once_with(
            mock.sentinel.cell_context,
            uuidsentinel.instance,
            expected_attrs=['system_metadata']
        )

    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid',
        new=mock.Mock(cell_mapping=mock.sentinel.cell_mapping))
    def test_get_machine_type_none_found(
        self, mock_target_cell, mock_get_instance
    ):
        mock_target_cell.return_value.__enter__.return_value = (
            mock.sentinel.cell_context)
        mock_get_instance.return_value = self._create_test_instance_obj()
        self.assertIsNone(
            machine_type_utils.get_machine_type(
                mock.sentinel.context,
                instance_uuid=uuidsentinel.instance
            )
        )
        mock_get_instance.assert_called_once_with(
            mock.sentinel.cell_context,
            uuidsentinel.instance,
            expected_attrs=['system_metadata']
        )
