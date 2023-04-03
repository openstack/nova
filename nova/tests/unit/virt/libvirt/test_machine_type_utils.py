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

from unittest import mock

import ddt
from oslo_utils.fixture import uuidsentinel
from oslo_utils import uuidutils

from nova.compute import vm_states
from nova import context as nova_context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.virt.libvirt import machine_type_utils


@ddt.ddt
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
            vm_state=vm_state, system_metadata={},
            image_ref=uuidsentinel.image_ref
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

    @ddt.data(
        'pc',
        'q35',
        'virt',
        's390-ccw-virtio',
        'pc-i440fx-2.12',
        'pc-q35-2.12',
        'virt-2.12',
        'pc-i440fx-rhel8.2.0',
        'pc-q35-rhel8.2.0')
    def test_check_machine_type_support(self, machine_type):
        # Assert UnsupportedMachineType isn't raised for supported types
        machine_type_utils._check_machine_type_support(
            machine_type)

    @ddt.data(
        'pc-foo',
        'pc-foo-1.2',
        'bar-q35',
        'virt-foo',
        'pc-virt')
    def test_check_machine_type_support_failure(self, machine_type):
        # Assert UnsupportedMachineType is raised for unsupported types
        self.assertRaises(
            exception.UnsupportedMachineType,
            machine_type_utils._check_machine_type_support,
            machine_type
        )

    @ddt.data(
        ('pc-i440fx-2.10', 'pc-i440fx-2.11'),
        ('pc-q35-2.10', 'pc-q35-2.11'))
    def test_check_update_to_existing_type(self, machine_types):
        # Assert that exception.InvalidMachineTypeUpdate is not raised when
        # updating to the same type or between versions of the same type
        original_type, update_type = machine_types
        machine_type_utils._check_update_to_existing_type(
            original_type, update_type)

    @ddt.data(
        ('pc', 'q35'),
        ('q35', 'pc'),
        ('pc-i440fx-2.12', 'pc-q35-2.12'),
        ('pc', 'pc-i440fx-2.12'),
        ('pc-i440fx-2.12', 'pc'),
        ('pc-i440fx-2.12', 'pc-i440fx-2.11'))
    def test_check_update_to_existing_type_failure(self, machine_types):
        # Assert that exception.InvalidMachineTypeUpdate is raised when
        # updating to a different underlying machine type or between versioned
        # and aliased machine types
        existing_type, update_type = machine_types
        self.assertRaises(
            exception.InvalidMachineTypeUpdate,
            machine_type_utils._check_update_to_existing_type,
            existing_type, update_type
        )

    @ddt.data(
        vm_states.STOPPED,
        vm_states.SHELVED,
        vm_states.SHELVED_OFFLOADED)
    def test_check_vm_state(self, vm_state):
        instance = self._create_test_instance_obj(
            vm_state=vm_state
        )
        machine_type_utils._check_vm_state(instance)

    @ddt.data(
        vm_states.ACTIVE,
        vm_states.PAUSED,
        vm_states.ERROR)
    def test_check_vm_state_failure(self, vm_state):
        instance = self._create_test_instance_obj(
            vm_state=vm_state
        )
        self.assertRaises(
            exception.InstanceInvalidState,
            machine_type_utils._check_vm_state,
            instance
        )

    @mock.patch('nova.objects.instance.Instance.save')
    @mock.patch('nova.virt.libvirt.machine_type_utils._check_vm_state')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid',
                new=mock.Mock(cell_mapping=mock.sentinel.cell_mapping))
    def test_update_noop(
        self,
        mock_target_cell,
        mock_get_instance,
        mock_check_vm_state,
        mock_instance_save
    ):
        # Assert that update_machine_type is a noop when the type is already
        # set within the instance, even if forced
        existing_type = 'pc'
        mock_target_cell.return_value.__enter__.return_value = (
            mock.sentinel.cell_context)
        mock_get_instance.return_value = self._create_test_instance_obj(
            mtype=existing_type,
        )

        self.assertEqual(
            (existing_type, existing_type),
            machine_type_utils.update_machine_type(
                mock.sentinel.context,
                instance_uuid=uuidsentinel.instance,
                machine_type=existing_type
            ),
        )
        mock_check_vm_state.assert_not_called()
        mock_instance_save.assert_not_called()

        self.assertEqual(
            (existing_type, existing_type),
            machine_type_utils.update_machine_type(
                mock.sentinel.context,
                instance_uuid=uuidsentinel.instance,
                machine_type=existing_type,
                force=True
            ),
        )
        mock_check_vm_state.assert_not_called()
        mock_instance_save.assert_not_called()

    @ddt.data(
        ('foobar', 'foobar', None),
        ('foobar-1.3', 'foobar-1.3', 'foobar-1.2'),
        ('foobar-1.2', 'foobar-1.2', 'foobar-1.3'),
        ('foobar', 'foobar', 'q35'),
        ('pc', 'pc', 'q35'))
    @mock.patch('nova.objects.instance.Instance.save')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid',
                new=mock.Mock(cell_mapping=mock.sentinel.cell_mapping))
    def test_update_force(
        self,
        types,
        mock_target_cell,
        mock_get_instance,
        mock_instance_save
    ):
        expected_type, update_type, existing_type = types
        mock_target_cell.return_value.__enter__.return_value = (
            mock.sentinel.cell_context)
        instance = self._create_test_instance_obj(
            mtype=existing_type
        )
        mock_get_instance.return_value = instance

        returned_type = machine_type_utils.update_machine_type(
            mock.sentinel.context,
            uuidsentinel.instance,
            machine_type=update_type,
            force=True
        )

        # Assert that the instance machine type was updated and saved
        self.assertEqual((expected_type, existing_type), returned_type)
        self.assertEqual(
            expected_type,
            instance.system_metadata.get('image_hw_machine_type')
        )
        mock_instance_save.assert_called_once()

    @ddt.data(
        ('pc', 'pc', None),
        ('q35', 'q35', None),
        ('pc-1.2', 'pc-1.2', None),
        ('pc-q35-1.2', 'pc-q35-1.2', None),
        ('pc-1.2', 'pc-1.2', 'pc-1.1'),
        ('pc-i440fx-1.2', 'pc-i440fx-1.2', 'pc-i440fx-1.1'),
        ('pc-q35-1.2', 'pc-q35-1.2', 'pc-q35-1.1'),
        ('pc-q35-rhel8.2.0', 'pc-q35-rhel8.2.0', 'pc-q35-rhel8.1.0'))
    @mock.patch('nova.objects.instance.Instance.save')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid',
                new=mock.Mock(cell_mapping=mock.sentinel.cell_mapping))
    def test_update(
        self,
        types,
        mock_target_cell,
        mock_get_instance,
        mock_instance_save
    ):
        expected_type, update_type, existing_type = types
        mock_target_cell.return_value.__enter__.return_value = (
            mock.sentinel.cell_context)
        instance = self._create_test_instance_obj(
            mtype=existing_type
        )
        mock_get_instance.return_value = instance

        returned_type = machine_type_utils.update_machine_type(
            mock.sentinel.context,
            uuidsentinel.instance,
            machine_type=update_type
        )

        # Assert that the instance machine type was updated and saved
        self.assertEqual((expected_type, existing_type), returned_type)
        self.assertEqual(
            expected_type,
            instance.system_metadata.get('image_hw_machine_type')
        )
        mock_instance_save.assert_called_once()


class TestMachineTypeUtilsListUnset(test.NoDBTestCase):

    USES_DB_SELF = True
    NUMBER_OF_CELLS = 2

    def setUp(self):
        super().setUp()
        self.useFixture(nova_fixtures.Database(database='api'))
        self.context = nova_context.get_admin_context()

    @staticmethod
    def _create_node_in_cell(ctxt, cell, hypervisor_type, nodename):
        with nova_context.target_cell(ctxt, cell) as cctxt:
            cn = objects.ComputeNode(
                context=cctxt,
                hypervisor_type=hypervisor_type,
                hypervisor_hostname=nodename,
                # The rest of these values are fakes.
                host=uuidsentinel.host,
                vcpus=4,
                memory_mb=8 * 1024,
                local_gb=40,
                vcpus_used=2,
                memory_mb_used=2 * 1024,
                local_gb_used=10,
                hypervisor_version=1,
                cpu_info='{"arch": "x86_64"}')
            cn.create()
            return cn

    @staticmethod
    def _create_instance_in_cell(
        ctxt,
        cell,
        node,
        is_deleted=False,
        hw_machine_type=None
    ):
        with nova_context.target_cell(ctxt, cell) as cctxt:
            inst = objects.Instance(
                context=cctxt,
                host=node.host,
                node=node.hypervisor_hostname,
                compute_id=node.id,
                uuid=uuidutils.generate_uuid())
            inst.create()

            if hw_machine_type:
                inst.system_metadata = {
                    'image_hw_machine_type': hw_machine_type
                }

            if is_deleted:
                inst.destroy()

            return inst

    def _setup_instances(self):
        # Setup the required cells
        self._setup_cells()

        # Track and return the created instances so the tests can assert
        instances = {}

        # Create a node in each cell
        node1_cell1 = self._create_node_in_cell(
            self.context,
            self.cell_mappings['cell1'],
            'kvm',
            uuidsentinel.node_cell1_uuid
        )
        node2_cell2 = self._create_node_in_cell(
            self.context,
            self.cell_mappings['cell2'],
            'kvm',
            uuidsentinel.node_cell2_uuid
        )

        # Create some instances with and without machine types defined in cell1
        instances['cell1_without_mtype'] = self._create_instance_in_cell(
            self.context,
            self.cell_mappings['cell1'],
            node1_cell1
        )
        instances['cell1_with_mtype'] = self._create_instance_in_cell(
            self.context,
            self.cell_mappings['cell1'],
            node1_cell1,
            hw_machine_type='pc'
        )
        instances['cell1_with_mtype_deleted'] = self._create_instance_in_cell(
            self.context,
            self.cell_mappings['cell1'],
            node1_cell1,
            hw_machine_type='pc',
            is_deleted=True
        )

        # Repeat for cell2
        instances['cell2_without_mtype'] = self._create_instance_in_cell(
            self.context,
            self.cell_mappings['cell2'],
            node2_cell2
        )
        instances['cell2_with_mtype'] = self._create_instance_in_cell(
            self.context,
            self.cell_mappings['cell2'],
            node2_cell2,
            hw_machine_type='pc'
        )
        instances['cell2_with_mtype_deleted'] = self._create_instance_in_cell(
            self.context,
            self.cell_mappings['cell2'],
            node2_cell2,
            hw_machine_type='pc',
            is_deleted=True
        )
        return instances

    def test_fresh_install_no_cell_mappings(self):
        self.assertEqual(
            [],
            machine_type_utils.get_instances_without_type(self.context)
        )

    def test_fresh_install_no_computes(self):
        self._setup_cells()
        self.assertEqual(
            [],
            machine_type_utils.get_instances_without_type(self.context)
        )

    def test_get_from_specific_cell(self):
        instances = self._setup_instances()
        # Assert that we only see the uuid for instance cell1_without_mtype
        instance_list = machine_type_utils.get_instances_without_type(
            self.context,
            cell_uuid=self.cell_mappings['cell1'].uuid
        )
        self.assertEqual(
            instances['cell1_without_mtype'].uuid,
            instance_list[0].uuid
        )

    def test_get_multi_cell(self):
        instances = self._setup_instances()
        # Assert that we see both undeleted _without_mtype instances
        instance_list = machine_type_utils.get_instances_without_type(
            self.context,
        )
        instance_uuids = [i.uuid for i in instance_list]
        self.assertIn(
            instances['cell1_without_mtype'].uuid,
            instance_uuids
        )
        self.assertIn(
            instances['cell2_without_mtype'].uuid,
            instance_uuids
        )
