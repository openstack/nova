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

import copy

import mock
from oslo_messaging import exceptions as messaging_exceptions
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
import six

from nova.compute import instance_actions
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor.tasks import cross_cell_migrate
from nova import context as nova_context
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.db import test_db_api
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_compute_node
from nova.tests.unit.objects import test_instance_device_metadata
from nova.tests.unit.objects import test_instance_numa
from nova.tests.unit.objects import test_instance_pci_requests
from nova.tests.unit.objects import test_keypair
from nova.tests.unit.objects import test_migration
from nova.tests.unit.objects import test_pci_device
from nova.tests.unit.objects import test_service
from nova.tests.unit.objects import test_vcpu_model


class ObjectComparatorMixin(test_db_api.ModelsObjectComparatorMixin):
    """Mixin class to aid in comparing two objects."""

    def _compare_objs(self, obj1, obj2, ignored_keys=None):
        # We can always ignore id since it is not deterministic when records
        # are copied over to the target cell database.
        if ignored_keys is None:
            ignored_keys = []
        if 'id' not in ignored_keys:
            ignored_keys.append('id')
        prim1 = obj1.obj_to_primitive()['nova_object.data']
        prim2 = obj2.obj_to_primitive()['nova_object.data']
        if isinstance(obj1, obj_base.ObjectListBase):
            self.assertEqual(len(obj1), len(obj2))
            prim1 = [o['nova_object.data'] for o in prim1['objects']]
            prim2 = [o['nova_object.data'] for o in prim2['objects']]
            self._assertEqualListsOfObjects(
                prim1, prim2, ignored_keys=ignored_keys)
        else:
            self._assertEqualObjects(prim1, prim2, ignored_keys=ignored_keys)


class TargetDBSetupTaskTestCase(test.TestCase, ObjectComparatorMixin):

    def setUp(self):
        super(TargetDBSetupTaskTestCase, self).setUp()
        cells = list(self.cell_mappings.values())
        self.source_cell = cells[0]
        self.target_cell = cells[1]
        # Pass is_admin=True because of the funky DB API
        # _check_instance_exists_in_project check when creating instance tags.
        self.source_context = nova_context.RequestContext(
            user_id='fake-user', project_id='fake-project', is_admin=True)
        self.target_context = self.source_context.elevated()  # copy source
        nova_context.set_target_cell(self.source_context, self.source_cell)
        nova_context.set_target_cell(self.target_context, self.target_cell)

    def _create_instance_data(self):
        """Creates an instance record and associated data like BDMs, VIFs,
        migrations, etc in the source cell and returns the Instance object.

        The idea is to create as many things from the
        Instance.INSTANCE_OPTIONAL_ATTRS list as possible.

        :returns: The created Instance and Migration objects
        """
        # Create the nova-compute services record first.
        fake_service = test_service._fake_service()
        fake_service.pop('version', None)  # version field is immutable
        fake_service.pop('id', None)  # cannot create with an id set
        service = objects.Service(self.source_context, **fake_service)
        service.create()
        # Create the compute node using the service.
        fake_compute_node = copy.copy(test_compute_node.fake_compute_node)
        fake_compute_node['host'] = service.host
        fake_compute_node['hypervisor_hostname'] = service.host
        fake_compute_node['stats'] = {}  # the object requires a dict
        fake_compute_node['service_id'] = service.id
        fake_compute_node.pop('id', None)  # cannot create with an id set
        compute_node = objects.ComputeNode(
            self.source_context, **fake_compute_node)
        compute_node.create()

        # Build an Instance object with basic fields set.
        updates = {
            'metadata': {'foo': 'bar'},
            'system_metadata': {'roles': ['member']},
            'host': compute_node.host,
            'node': compute_node.hypervisor_hostname
        }
        inst = fake_instance.fake_instance_obj(self.source_context, **updates)
        delattr(inst, 'id')  # cannot create an instance with an id set
        # Now we have to dirty all of the fields because fake_instance_obj
        # uses Instance._from_db_object to create the Instance object we have
        # but _from_db_object calls obj_reset_changes() which resets all of
        # the fields that were on the object, including the basic stuff like
        # the 'host' field, which means those fields don't get set in the DB.
        # TODO(mriedem): This should live in fake_instance_obj with a
        # make_creatable kwarg.
        for field in inst.obj_fields:
            if field in inst:
                setattr(inst, field, getattr(inst, field))
        # Make sure at least one expected basic field is dirty on the Instance.
        self.assertIn('host', inst.obj_what_changed())
        # Set the optional fields on the instance before creating it.
        inst.pci_requests = objects.InstancePCIRequests(requests=[
            objects.InstancePCIRequest(
                **test_instance_pci_requests.fake_pci_requests[0])])
        inst.numa_topology = objects.InstanceNUMATopology(
            cells=test_instance_numa.fake_obj_numa_topology.cells)
        inst.trusted_certs = objects.TrustedCerts(ids=[uuids.cert])
        inst.vcpu_model = test_vcpu_model.fake_vcpumodel
        inst.keypairs = objects.KeyPairList(objects=[
            objects.KeyPair(**test_keypair.fake_keypair)])
        inst.device_metadata = (
            test_instance_device_metadata.get_fake_obj_device_metadata(
                self.source_context))
        # FIXME(mriedem): db.instance_create does not handle tags
        inst.obj_reset_changes(['tags'])
        inst.create()

        bdm = {
            'instance_uuid': inst.uuid,
            'source_type': 'volume',
            'destination_type': 'volume',
            'volume_id': uuids.volume_id,
            'volume_size': 1,
            'device_name': '/dev/vda',
        }
        bdm = objects.BlockDeviceMapping(
            self.source_context,
            **fake_block_device.FakeDbBlockDeviceDict(bdm_dict=bdm))
        delattr(bdm, 'id')  # cannot create a bdm with an id set
        bdm.obj_reset_changes(['id'])
        bdm.create()

        vif = objects.VirtualInterface(
            self.source_context, address='de:ad:be:ef:ca:fe', uuid=uuids.port,
            instance_uuid=inst.uuid)
        vif.create()

        info_cache = objects.InstanceInfoCache().new(
            self.source_context, inst.uuid)
        info_cache.network_info = network_model.NetworkInfo([
                network_model.VIF(id=vif.uuid, address=vif.address)])
        info_cache.save(update_cells=False)

        objects.TagList.create(self.source_context, inst.uuid, ['test'])

        try:
            raise test.TestingException('test-fault')
        except test.TestingException as fault:
            compute_utils.add_instance_fault_from_exc(
                self.source_context, inst, fault)

        objects.InstanceAction().action_start(
            self.source_context, inst.uuid, 'resize', want_result=False)
        objects.InstanceActionEvent().event_start(
            self.source_context, inst.uuid, 'migrate_server',
            want_result=False)

        # Create a fake migration for the cross-cell resize operation.
        migration = objects.Migration(
            self.source_context,
            **test_migration.fake_db_migration(
                instance_uuid=inst.uuid, cross_cell_move=True,
                migration_type='resize'))
        delattr(migration, 'id')  # cannot create a migration with an id set
        migration.obj_reset_changes(['id'])
        migration.create()

        # Create an old non-resize migration to make sure it is copied to the
        # target cell database properly.
        old_migration = objects.Migration(
            self.source_context,
            **test_migration.fake_db_migration(
                instance_uuid=inst.uuid, migration_type='live-migration',
                status='completed', uuid=uuids.old_migration))
        delattr(old_migration, 'id')  # cannot create a migration with an id
        old_migration.obj_reset_changes(['id'])
        old_migration.create()

        fake_pci_device = copy.copy(test_pci_device.fake_db_dev)
        fake_pci_device['extra_info'] = {}  # the object requires a dict
        fake_pci_device['compute_node_id'] = compute_node.id
        pci_device = objects.PciDevice.create(
            self.source_context, fake_pci_device)
        pci_device.allocate(inst)  # sets the status and instance_uuid fields
        pci_device.save()

        # Return a fresh copy of the instance from the DB with as many joined
        # fields loaded as possible.
        expected_attrs = copy.copy(instance_obj.INSTANCE_OPTIONAL_ATTRS)
        # Cannot load fault from get_by_uuid.
        expected_attrs.remove('fault')
        inst = objects.Instance.get_by_uuid(
            self.source_context, inst.uuid, expected_attrs=expected_attrs)
        return inst, migration

    def test_execute_and_rollback(self):
        """Happy path test which creates an instance with related records
        in a source cell and then executes TargetDBSetupTask to create those
        same records in a target cell. Runs rollback to make sure the target
        cell instance is deleted.
        """
        source_cell_instance, migration = self._create_instance_data()
        instance_uuid = source_cell_instance.uuid

        task = cross_cell_migrate.TargetDBSetupTask(
            self.source_context, source_cell_instance, migration,
            self.target_context)
        target_cell_instance = task.execute()[0]

        # The instance in the target cell should be hidden.
        self.assertTrue(target_cell_instance.hidden,
                        'Target cell instance should be hidden')
        # Assert that the various records created in _create_instance_data are
        # found in the target cell database. We ignore 'hidden' because the
        # values are explicitly different between source and target DB. The
        # pci_devices and services fields are not set on the target instance
        # during TargetDBSetupTask.execute so we ignore those here and verify
        # them below. tags are also special in that we have to lazy-load them
        # on target_cell_instance so we check those explicitly below as well.
        ignored_keys = ['hidden', 'pci_devices', 'services', 'tags']
        self._compare_objs(source_cell_instance, target_cell_instance,
                           ignored_keys=ignored_keys)

        # Explicitly compare flavor fields to make sure they are created and
        # loaded properly.
        for flavor_field in ('old_', 'new_', ''):
            source_field = getattr(
                source_cell_instance, flavor_field + 'flavor')
            target_field = getattr(
                target_cell_instance, flavor_field + 'flavor')
            # old/new may not be set
            if source_field is None or target_field is None:
                self.assertIsNone(source_field)
                self.assertIsNone(target_field)
            else:
                self._compare_objs(source_field, target_field)

        # Compare PCI requests
        self.assertIsNotNone(target_cell_instance.pci_requests)
        self._compare_objs(source_cell_instance.pci_requests,
                           target_cell_instance.pci_requests)

        # Compare requested instance NUMA topology
        self.assertIsNotNone(target_cell_instance.numa_topology)
        self._compare_objs(source_cell_instance.numa_topology,
                           target_cell_instance.numa_topology)

        # Compare trusted certs
        self.assertIsNotNone(target_cell_instance.trusted_certs)
        self._compare_objs(source_cell_instance.trusted_certs,
                           target_cell_instance.trusted_certs)

        # Compare vcpu_model
        self.assertIsNotNone(target_cell_instance.vcpu_model)
        self._compare_objs(source_cell_instance.vcpu_model,
                           target_cell_instance.vcpu_model)

        # Compare keypairs
        self.assertEqual(1, len(target_cell_instance.keypairs))
        self._compare_objs(source_cell_instance.keypairs,
                           target_cell_instance.keypairs)

        # Compare device_metadata
        self.assertIsNotNone(target_cell_instance.device_metadata)
        self._compare_objs(source_cell_instance.device_metadata,
                           target_cell_instance.device_metadata)

        # Compare BDMs
        target_bdms = target_cell_instance.get_bdms()
        self.assertEqual(1, len(target_bdms))
        self._compare_objs(source_cell_instance.get_bdms(), target_bdms)
        self.assertEqual(source_cell_instance.uuid,
                         target_bdms[0].instance_uuid)

        # Compare VIFs
        source_vifs = objects.VirtualInterfaceList.get_by_instance_uuid(
            self.source_context, instance_uuid)
        target_vifs = objects.VirtualInterfaceList.get_by_instance_uuid(
            self.target_context, instance_uuid)
        self.assertEqual(1, len(target_vifs))
        self._compare_objs(source_vifs, target_vifs)

        # Compare info cache (there should be a single vif in the target)
        self.assertEqual(1, len(target_cell_instance.info_cache.network_info))
        self.assertEqual(target_vifs[0].uuid,
                         target_cell_instance.info_cache.network_info[0]['id'])
        self._compare_objs(source_cell_instance.info_cache,
                           target_cell_instance.info_cache)

        # Compare tags
        self.assertEqual(1, len(target_cell_instance.tags))
        self._compare_objs(source_cell_instance.tags,
                           target_cell_instance.tags)

        # Assert that the fault from the source is not in the target.
        self.assertIsNone(target_cell_instance.fault)

        # Compare instance actions and events
        source_actions = objects.InstanceActionList.get_by_instance_uuid(
            self.source_context, instance_uuid)
        target_actions = objects.InstanceActionList.get_by_instance_uuid(
            self.target_context, instance_uuid)
        self._compare_objs(source_actions, target_actions)

        # The InstanceActionEvent.action_id is per-cell DB so we need to get
        # the events per action and compare them but ignore the action_id.
        source_events = objects.InstanceActionEventList.get_by_action(
            self.source_context, source_actions[0].id)
        target_events = objects.InstanceActionEventList.get_by_action(
            self.target_context, target_actions[0].id)
        self._compare_objs(source_events, target_events,
                           ignored_keys=['action_id'])

        # Compare migrations
        filters = {'instance_uuid': instance_uuid}
        source_migrations = objects.MigrationList.get_by_filters(
            self.source_context, filters)
        target_migrations = objects.MigrationList.get_by_filters(
            self.target_context, filters)
        # There should be two migrations in the target cell.
        self.assertEqual(2, len(target_migrations))
        self._compare_objs(source_migrations, target_migrations)
        # One should be a live-migration type (make sure Migration._from-db_obj
        # did not set the migration_type for us).
        migration_types = [mig.migration_type for mig in target_migrations]
        self.assertIn('resize', migration_types)
        self.assertIn('live-migration', migration_types)

        # pci_devices and services should not have been copied over since they
        # are specific to the compute node in the source cell database
        for field in ('pci_devices', 'services'):
            source_value = getattr(source_cell_instance, field)
            self.assertEqual(
                1, len(source_value),
                'Unexpected number of %s in source cell instance' % field)
            target_value = getattr(target_cell_instance, field)
            self.assertEqual(
                0, len(target_value),
                'Unexpected number of %s in target cell instance' % field)

        # Rollback the task and assert the instance and its related data are
        # gone from the target cell database. Use a modified context to make
        # sure the instance was hard-deleted.
        task.rollback(test.TestingException('error'))
        read_deleted_ctxt = self.target_context.elevated(read_deleted='yes')
        self.assertRaises(exception.InstanceNotFound,
                          objects.Instance.get_by_uuid,
                          read_deleted_ctxt, target_cell_instance.uuid)


class CrossCellMigrationTaskTestCase(test.NoDBTestCase):

    def setUp(self):
        super(CrossCellMigrationTaskTestCase, self).setUp()
        source_context = nova_context.get_context()
        host_selection = objects.Selection(
            service_host='target.host.com', cell_uuid=uuids.cell_uuid)
        migration = objects.Migration(
            id=1, cross_cell_move=False, source_compute='source.host.com')
        instance = objects.Instance()
        self.task = cross_cell_migrate.CrossCellMigrationTask(
            source_context,
            instance,
            objects.Flavor(),
            mock.sentinel.request_spec,
            migration,
            mock.sentinel.compute_rpcapi,
            host_selection,
            mock.sentinel.alternate_hosts)

    def test_execute_and_rollback(self):
        """Basic test to just hit execute and rollback."""
        # Mock out the things that execute calls
        with test.nested(
            mock.patch.object(self.task.source_migration, 'save'),
            mock.patch.object(self.task, '_perform_external_api_checks'),
            mock.patch.object(self.task, '_setup_target_cell_db'),
            mock.patch.object(self.task, '_prep_resize_at_dest'),
            mock.patch.object(self.task, '_prep_resize_at_source'),
            mock.patch.object(self.task, '_finish_resize_at_dest'),
        ) as (
            mock_migration_save, mock_perform_external_api_checks,
            mock_setup_target_cell_db, mock_prep_resize_at_dest,
            mock_prep_resize_at_source, mock_finish_resize_at_dest,
        ):
            mock_setup_target_cell_db.return_value = (
                mock.sentinel.target_cell_migration,
                mock.sentinel.target_cell_mapping)
            self.task.execute()
        # Assert the calls
        self.assertTrue(self.task.source_migration.cross_cell_move,
                        'Migration.cross_cell_move should be True.')
        mock_migration_save.assert_called_once_with()
        mock_perform_external_api_checks.assert_called_once_with()
        mock_setup_target_cell_db.assert_called_once_with()
        mock_prep_resize_at_dest.assert_called_once_with(
            mock.sentinel.target_cell_migration)
        mock_prep_resize_at_source.assert_called_once_with()
        mock_finish_resize_at_dest.assert_called_once_with(
            mock_prep_resize_at_dest.return_value,
            mock.sentinel.target_cell_mapping,
            mock_prep_resize_at_source.return_value)
        # Now rollback the completed sub-tasks
        self.task.rollback(test.TestingException('error'))

    def test_perform_external_api_checks_ok(self):
        """Tests the happy path scenario where neutron APIs are new enough for
        what we need.
        """
        with mock.patch.object(
                self.task.network_api, 'supports_port_binding_extension',
                return_value=True) as mock_neutron_check:
            self.task._perform_external_api_checks()
        mock_neutron_check.assert_called_once_with(self.task.context)

    def test_perform_external_api_checks_old_neutron(self):
        """Tests the case that neutron API is old."""
        with mock.patch.object(
                self.task.network_api, 'supports_port_binding_extension',
                return_value=False):
            ex = self.assertRaises(exception.MigrationPreCheckError,
                                   self.task._perform_external_api_checks)
            self.assertIn('Required networking service API extension',
                          six.text_type(ex))

    @mock.patch('nova.conductor.tasks.cross_cell_migrate.LOG.exception')
    def test_rollback_idempotent(self, mock_log_exception):
        """Tests that the rollback routine hits all completed tasks even if
        one or more of them fail their own rollback routine.
        """
        # Mock out some completed tasks
        for x in range(3):
            task = mock.Mock()
            # The 2nd task will fail its rollback.
            if x == 1:
                task.rollback.side_effect = test.TestingException('sub-task')
            self.task._completed_tasks[str(x)] = task
        # Run execute but mock _execute to fail somehow.
        error = test.TestingException('main task')
        with mock.patch.object(self.task, '_execute', side_effect=error):
            # The TestingException from the main task should be raised.
            ex = self.assertRaises(test.TestingException, self.task.execute)
            self.assertEqual('main task', six.text_type(ex))
        # And all three sub-task rollbacks should have been called.
        for subtask in self.task._completed_tasks.values():
            subtask.rollback.assert_called_once_with(error)
        # The 2nd task rollback should have raised and been logged.
        mock_log_exception.assert_called_once()
        self.assertEqual('1', mock_log_exception.call_args[0][1])

    @mock.patch('nova.objects.CellMapping.get_by_uuid')
    @mock.patch('nova.context.set_target_cell')
    @mock.patch.object(cross_cell_migrate.TargetDBSetupTask, 'execute')
    def test_setup_target_cell_db(self, mock_target_db_set_task_execute,
                                  mock_set_target_cell, mock_get_cell_mapping):
        """Tests setting up and executing TargetDBSetupTask"""
        mock_target_db_set_task_execute.return_value = (
            mock.sentinel.target_cell_instance,
            mock.sentinel.target_cell_migration)
        result = self.task._setup_target_cell_db()
        mock_target_db_set_task_execute.assert_called_once_with()
        mock_get_cell_mapping.assert_called_once_with(
            self.task.context, self.task.host_selection.cell_uuid)
        # The target_cell_context should be set on the main task but as a copy
        # of the source context.
        self.assertIsNotNone(self.task._target_cell_context)
        self.assertIsNot(self.task._target_cell_context, self.task.context)
        # The target cell context should have been targeted to the target
        # cell mapping.
        mock_set_target_cell.assert_called_once_with(
            self.task._target_cell_context, mock_get_cell_mapping.return_value)
        # The resulting migration record from TargetDBSetupTask should have
        # been returned along with the target cell mapping.
        self.assertIs(result[0], mock.sentinel.target_cell_migration)
        self.assertIs(result[1], mock_get_cell_mapping.return_value)
        # The target_cell_instance should be set on the main task.
        self.assertIsNotNone(self.task._target_cell_instance)
        self.assertIs(self.task._target_cell_instance,
                      mock.sentinel.target_cell_instance)
        # And the completed task should have been recorded for rollbacks.
        self.assertIn('TargetDBSetupTask', self.task._completed_tasks)
        self.assertIsInstance(self.task._completed_tasks['TargetDBSetupTask'],
                              cross_cell_migrate.TargetDBSetupTask)

    @mock.patch.object(cross_cell_migrate.PrepResizeAtDestTask, 'execute')
    @mock.patch('nova.availability_zones.get_host_availability_zone',
                return_value='cell2-az1')
    def test_prep_resize_at_dest(self, mock_get_az, mock_task_execute):
        """Tests setting up and executing PrepResizeAtDestTask"""
        # _setup_target_cell_db set the _target_cell_context and
        # _target_cell_instance variables so fake those out here
        self.task._target_cell_context = mock.sentinel.target_cell_context
        target_inst = objects.Instance(
            vm_state=vm_states.ACTIVE, system_metadata={})
        self.task._target_cell_instance = target_inst
        target_cell_migration = objects.Migration(
            # use unique ids for comparisons
            id=self.task.source_migration.id + 1)
        self.assertNotIn('migration_context', self.task.instance)
        mock_task_execute.return_value = objects.MigrationContext(
            migration_id=target_cell_migration.id)

        with test.nested(
            mock.patch.object(self.task,
                              '_update_migration_from_dest_after_claim'),
            mock.patch.object(self.task.instance, 'save'),
            mock.patch.object(target_inst, 'save')
        ) as (
            _upd_mig, source_inst_save, target_inst_save
        ):
            retval = self.task._prep_resize_at_dest(target_cell_migration)

        self.assertIs(retval, _upd_mig.return_value)
        mock_task_execute.assert_called_once_with()
        mock_get_az.assert_called_once_with(
            self.task.context, self.task.host_selection.service_host)
        self.assertIn('PrepResizeAtDestTask', self.task._completed_tasks)
        self.assertIsInstance(
            self.task._completed_tasks['PrepResizeAtDestTask'],
            cross_cell_migrate.PrepResizeAtDestTask)
        # The new_flavor should be set on the target cell instance along with
        # the AZ and old_vm_state.
        self.assertIs(target_inst.new_flavor, self.task.flavor)
        self.assertEqual(vm_states.ACTIVE,
                         target_inst.system_metadata['old_vm_state'])
        self.assertEqual(mock_get_az.return_value,
                         target_inst.availability_zone)
        # A clone of the MigrationContext returned from execute() should be
        # stored on the source instance with the internal context targeted
        # at the source cell context and the migration_id updated.
        self.assertIsNotNone(self.task.instance.migration_context)
        self.assertEqual(self.task.source_migration.id,
                         self.task.instance.migration_context.migration_id)
        source_inst_save.assert_called_once_with()
        _upd_mig.assert_called_once_with(target_cell_migration)

    @mock.patch('nova.objects.Migration.get_by_uuid')
    def test_update_migration_from_dest_after_claim(self, get_by_uuid):
        """Tests the _update_migration_from_dest_after_claim method."""
        self.task._target_cell_context = mock.sentinel.target_cell_context
        target_cell_migration = objects.Migration(
            uuid=uuids.migration, cross_cell_move=True,
            dest_compute='dest-compute', dest_node='dest-node',
            dest_host='192.168.159.176')
        get_by_uuid.return_value = target_cell_migration.obj_clone()
        with mock.patch.object(self.task.source_migration, 'save') as save:
            retval = self.task._update_migration_from_dest_after_claim(
                target_cell_migration)
        # The returned target cell migration should be the one we pulled from
        # the target cell database.
        self.assertIs(retval, get_by_uuid.return_value)
        get_by_uuid.assert_called_once_with(
            self.task._target_cell_context, target_cell_migration.uuid)
        # The source cell migration on the task should have been updated.
        source_cell_migration = self.task.source_migration
        self.assertEqual('dest-compute', source_cell_migration.dest_compute)
        self.assertEqual('dest-node', source_cell_migration.dest_node)
        self.assertEqual('192.168.159.176', source_cell_migration.dest_host)
        save.assert_called_once_with()

    @mock.patch.object(cross_cell_migrate.PrepResizeAtSourceTask, 'execute')
    def test_prep_resize_at_source(self, mock_task_execute):
        """Tests setting up and executing PrepResizeAtSourceTask"""
        snapshot_id = self.task._prep_resize_at_source()
        self.assertIs(snapshot_id, mock_task_execute.return_value)
        self.assertIn('PrepResizeAtSourceTask', self.task._completed_tasks)
        self.assertIsInstance(
            self.task._completed_tasks['PrepResizeAtSourceTask'],
            cross_cell_migrate.PrepResizeAtSourceTask)

    @mock.patch.object(cross_cell_migrate.FinishResizeAtDestTask, 'execute')
    def test_finish_resize_at_dest(self, mock_task_execute):
        """Tests setting up and executing FinishResizeAtDestTask"""
        target_cell_migration = objects.Migration()
        target_cell_mapping = objects.CellMapping()
        self.task._finish_resize_at_dest(
            target_cell_migration, target_cell_mapping, uuids.snapshot_id)
        mock_task_execute.assert_called_once_with()
        self.assertIn('FinishResizeAtDestTask', self.task._completed_tasks)
        self.assertIsInstance(
            self.task._completed_tasks['FinishResizeAtDestTask'],
            cross_cell_migrate.FinishResizeAtDestTask)


class PrepResizeAtDestTaskTestCase(test.NoDBTestCase):

    def setUp(self):
        super(PrepResizeAtDestTaskTestCase, self).setUp()
        host_selection = objects.Selection(
            service_host='fake-host', nodename='fake-host',
            limits=objects.SchedulerLimits())
        self.task = cross_cell_migrate.PrepResizeAtDestTask(
            nova_context.get_context(),
            objects.Instance(uuid=uuids.instance),
            objects.Flavor(),
            objects.Migration(),
            objects.RequestSpec(),
            compute_rpcapi=mock.Mock(),
            host_selection=host_selection,
            network_api=mock.Mock(),
            volume_api=mock.Mock())

    def test_create_port_bindings(self):
        """Happy path test for creating port bindings"""
        with mock.patch.object(
                self.task.network_api, 'bind_ports_to_host') as mock_bind:
            self.task._create_port_bindings()
        self.assertIs(self.task._bindings_by_port_id, mock_bind.return_value)
        mock_bind.assert_called_once_with(
            self.task.context, self.task.instance,
            self.task.host_selection.service_host)

    def test_create_port_bindings_port_binding_failed(self):
        """Tests that bind_ports_to_host raises PortBindingFailed which
        results in a MigrationPreCheckError.
        """
        with mock.patch.object(
                self.task.network_api, 'bind_ports_to_host',
                side_effect=exception.PortBindingFailed(
                    port_id=uuids.port_id)) as mock_bind:
            self.assertRaises(exception.MigrationPreCheckError,
                              self.task._create_port_bindings)
        self.assertEqual({}, self.task._bindings_by_port_id)
        mock_bind.assert_called_once_with(
            self.task.context, self.task.instance,
            self.task.host_selection.service_host)

    @mock.patch('nova.objects.BlockDeviceMapping.save')
    def test_create_volume_attachments(self, mock_bdm_save):
        """Happy path test for creating volume attachments"""
        # Two BDMs: one as a local image and one as an attached data volume;
        # only the volume BDM should be processed and returned.
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(
                source_type='image', destination_type='local'),
            objects.BlockDeviceMapping(
                source_type='volume', destination_type='volume',
                volume_id=uuids.volume_id,
                instance_uuid=self.task.instance.uuid)])
        with test.nested(
            mock.patch.object(
                self.task.instance, 'get_bdms', return_value=bdms),
            mock.patch.object(
                self.task.volume_api, 'attachment_create',
                return_value={'id': uuids.attachment_id}),
        ) as (
            mock_get_bdms, mock_attachment_create
        ):
            volume_bdms = self.task._create_volume_attachments()

        mock_attachment_create.assert_called_once_with(
            self.task.context, uuids.volume_id, self.task.instance.uuid)
        # The created attachment ID should be saved for rollbacks.
        self.assertEqual(1, len(self.task._created_volume_attachment_ids))
        self.assertEqual(
            uuids.attachment_id, self.task._created_volume_attachment_ids[0])
        # Only the volume BDM should have been processed and returned.
        self.assertEqual(1, len(volume_bdms))
        self.assertIs(bdms[1], volume_bdms[0])
        # The volume BDM attachment_id should have been updated.
        self.assertEqual(uuids.attachment_id, volume_bdms[0].attachment_id)

    def test_execute(self):
        """Happy path for executing the task"""

        def fake_create_port_bindings():
            self.task._bindings_by_port_id = mock.sentinel.bindings

        with test.nested(
            mock.patch.object(self.task, '_create_port_bindings',
                              side_effect=fake_create_port_bindings),
            mock.patch.object(self.task, '_create_volume_attachments'),
            mock.patch.object(
                self.task.compute_rpcapi, 'prep_snapshot_based_resize_at_dest')
        ) as (
            _create_port_bindings, _create_volume_attachments,
            prep_snapshot_based_resize_at_dest
        ):
            # Execute the task. The return value should be the MigrationContext
            # returned from prep_snapshot_based_resize_at_dest.
            self.assertEqual(
                prep_snapshot_based_resize_at_dest.return_value,
                self.task.execute())

        _create_port_bindings.assert_called_once_with()
        _create_volume_attachments.assert_called_once_with()
        prep_snapshot_based_resize_at_dest.assert_called_once_with(
            self.task.context, self.task.instance, self.task.flavor,
            self.task.host_selection.nodename, self.task.target_migration,
            self.task.host_selection.limits, self.task.request_spec,
            self.task.host_selection.service_host)

    def test_execute_messaging_timeout(self):
        """Tests the case that prep_snapshot_based_resize_at_dest raises
        MessagingTimeout which results in a MigrationPreCheckError.
        """
        with test.nested(
            mock.patch.object(self.task, '_create_port_bindings'),
            mock.patch.object(self.task, '_create_volume_attachments'),
            mock.patch.object(
                self.task.compute_rpcapi, 'prep_snapshot_based_resize_at_dest',
                side_effect=messaging_exceptions.MessagingTimeout)
        ) as (
            _create_port_bindings, _create_volume_attachments,
            prep_snapshot_based_resize_at_dest
        ):
            ex = self.assertRaises(
                exception.MigrationPreCheckError, self.task.execute)
            self.assertIn(
                'RPC timeout while checking if we can cross-cell migrate to '
                'host: fake-host', six.text_type(ex))

        _create_port_bindings.assert_called_once_with()
        _create_volume_attachments.assert_called_once_with()
        prep_snapshot_based_resize_at_dest.assert_called_once_with(
            self.task.context, self.task.instance, self.task.flavor,
            self.task.host_selection.nodename, self.task.target_migration,
            self.task.host_selection.limits, self.task.request_spec,
            self.task.host_selection.service_host)

    @mock.patch('nova.conductor.tasks.cross_cell_migrate.LOG.exception')
    def test_rollback(self, mock_log_exception):
        """Tests rollback to make sure it idempotently handles cleaning up
        port bindings and volume attachments even if one in the set fails for
        each.
        """
        # Make sure we have two port bindings and two volume attachments
        # because we are going to make the first of each fail and we want to
        # make sure we still try to delete the other.
        self.task._bindings_by_port_id = {
            uuids.port_id1: mock.sentinel.binding1,
            uuids.port_id2: mock.sentinel.binding2
        }
        self.task._created_volume_attachment_ids = [
            uuids.attachment_id1, uuids.attachment_id2
        ]
        with test.nested(
            mock.patch.object(
                self.task.network_api, 'delete_port_binding',
                # First call fails, second is OK.
                side_effect=(exception.PortBindingDeletionFailed, None)),
            mock.patch.object(
                self.task.volume_api, 'attachment_delete',
                # First call fails, second is OK.
                side_effect=(exception.CinderConnectionFailed, None)),
        ) as (
            delete_port_binding, attachment_delete
        ):
            self.task.rollback(test.TestingException('error'))
        # Should have called both delete methods twice in any order.
        host = self.task.host_selection.service_host
        delete_port_binding.assert_has_calls([
            mock.call(self.task.context, port_id, host)
            for port_id in self.task._bindings_by_port_id],
            any_order=True)
        attachment_delete.assert_has_calls([
            mock.call(self.task.context, attachment_id)
            for attachment_id in self.task._created_volume_attachment_ids],
            any_order=True)
        # Should have logged both exceptions.
        self.assertEqual(2, mock_log_exception.call_count)


class PrepResizeAtSourceTaskTestCase(test.NoDBTestCase):

    def setUp(self):
        super(PrepResizeAtSourceTaskTestCase, self).setUp()
        self.task = cross_cell_migrate.PrepResizeAtSourceTask(
            nova_context.get_context(),
            objects.Instance(
                uuid=uuids.instance,
                vm_state=vm_states.ACTIVE,
                display_name='fake-server',
                system_metadata={},
                host='source.host.com'),
            objects.Migration(),
            objects.RequestSpec(),
            compute_rpcapi=mock.Mock(),
            image_api=mock.Mock())

    @mock.patch('nova.compute.utils.create_image')
    @mock.patch('nova.objects.Instance.save')
    def test_execute_volume_backed(self, instance_save, create_image):
        """Tests execution with a volume-backed server so no snapshot image
        is created.
        """
        self.task.request_spec.is_bfv = True
        # No image should be created so no image is returned.
        self.assertIsNone(self.task.execute())
        self.assertIsNone(self.task._image_id)
        create_image.assert_not_called()
        self.task.compute_rpcapi.prep_snapshot_based_resize_at_source.\
            assert_called_once_with(
                self.task.context, self.task.instance, self.task.migration,
                snapshot_id=None)
        # The instance should have been updated.
        instance_save.assert_called_once_with(
            expected_task_state=task_states.RESIZE_PREP)
        self.assertEqual(
            task_states.RESIZE_MIGRATING, self.task.instance.task_state)
        self.assertEqual(self.task.instance.vm_state,
                         self.task.instance.system_metadata['old_vm_state'])

    @mock.patch('nova.compute.utils.create_image',
                return_value={'id': uuids.snapshot_id})
    @mock.patch('nova.objects.Instance.save')
    def test_execute_image_backed(self, instance_save, create_image):
        """Tests execution with an image-backed server so a snapshot image
        is created.
        """
        self.task.request_spec.is_bfv = False
        self.task.instance.image_ref = uuids.old_image_ref
        # An image should be created so an image ID is returned.
        self.assertEqual(uuids.snapshot_id, self.task.execute())
        self.assertEqual(uuids.snapshot_id, self.task._image_id)
        create_image.assert_called_once_with(
            self.task.context, self.task.instance, 'fake-server-resize-temp',
            'snapshot', self.task.image_api)
        self.task.compute_rpcapi.prep_snapshot_based_resize_at_source.\
            assert_called_once_with(
                self.task.context, self.task.instance, self.task.migration,
                snapshot_id=uuids.snapshot_id)
        # The instance should have been updated.
        instance_save.assert_called_once_with(
            expected_task_state=task_states.RESIZE_PREP)
        self.assertEqual(
            task_states.RESIZE_MIGRATING, self.task.instance.task_state)
        self.assertEqual(self.task.instance.vm_state,
                         self.task.instance.system_metadata['old_vm_state'])

    @mock.patch('nova.compute.utils.delete_image')
    def test_rollback(self, delete_image):
        """Tests rollback when there is an image and when there is not."""
        # First test when there is no image_id so we do not try to delete it.
        self.task.rollback(test.TestingException('error'))
        delete_image.assert_not_called()
        # Now set an image and we should try to delete it.
        self.task._image_id = uuids.image_id
        self.task.rollback(test.TestingException('error'))
        delete_image.assert_called_once_with(
            self.task.context, self.task.instance, self.task.image_api,
            self.task._image_id)


class FinishResizeAtDestTaskTestCase(test.TestCase):
    """Tests for FinishResizeAtDestTask which rely on a database"""

    def _create_instance(self, ctxt, create_instance_mapping=False, **updates):
        """Create a fake instance with the given cell-targeted context

        :param ctxt: Cell-targeted RequestContext
        :param create_instance_mapping: If True, create an InstanceMapping
            for the instance pointed at the cell in which the ctxt is targeted,
            otherwise no InstanceMapping is created.
        :param updates: Additional fields to set on the Instance object.
        :returns: Instance object that was created.
        """
        inst = fake_instance.fake_instance_obj(ctxt, **updates)
        delattr(inst, 'id')  # make it creatable
        # Now we have to dirty all of the fields because fake_instance_obj
        # uses Instance._from_db_object to create the Instance object we have
        # but _from_db_object calls obj_reset_changes() which resets all of
        # the fields that were on the object, including the basic stuff like
        # the 'host' field, which means those fields don't get set in the DB.
        # TODO(mriedem): This should live in fake_instance_obj
        for field in inst.obj_fields:
            if field in inst:
                setattr(inst, field, getattr(inst, field))
        # FIXME(mriedem): db.instance_create does not handle tags
        inst.obj_reset_changes(['tags'])
        inst.create()

        if create_instance_mapping:
            # Find the cell mapping from the context.
            self.assertIsNotNone(ctxt.cell_uuid,
                                 'ctxt must be targeted to a cell.')
            for cell in self.cell_mappings.values():
                if cell.uuid == ctxt.cell_uuid:
                    break
            else:
                raise Exception('Unable to find CellMapping with UUID %s' %
                                ctxt.cell_uuid)

            mapping = objects.InstanceMapping(
                ctxt, instance_uuid=inst.uuid,
                project_id=inst.project_id, cell_mapping=cell)
            mapping.create()

        return inst

    def setUp(self):
        super(FinishResizeAtDestTaskTestCase, self).setUp()
        cells = list(self.cell_mappings.values())
        source_cell = cells[0]
        target_cell = cells[1]
        self.source_context = nova_context.RequestContext(
            user_id='fake-user', project_id='fake-project', is_admin=True)
        self.target_context = self.source_context.elevated()  # copy source
        nova_context.set_target_cell(self.source_context, source_cell)
        nova_context.set_target_cell(self.target_context, target_cell)

        # Create the source cell instance.
        source_instance = self._create_instance(
            self.source_context, create_instance_mapping=True,
            hidden=False)
        # Create the instance action record in the source cell which is needed
        # by the EventReporter.
        objects.InstanceAction.action_start(
            self.source_context, source_instance.uuid,
            instance_actions.RESIZE, want_result=False)
        # Create the target cell instance which would normally be a clone of
        # the source cell instance but the only thing these tests care about
        # is that the UUID matches. The target cell instance is also hidden.
        target_instance = self._create_instance(
            self.target_context, hidden=True, uuid=source_instance.uuid)
        target_migration = objects.Migration(dest_compute='target.host.com')
        self.task = cross_cell_migrate.FinishResizeAtDestTask(
            self.target_context, target_instance, target_migration,
            source_instance, compute_rpcapi=mock.Mock(),
            target_cell_mapping=target_cell, snapshot_id=uuids.snapshot_id,
            request_spec=objects.RequestSpec())

    def test_execute(self):
        """Tests the happy path scenario for the task execution."""
        with test.nested(
            mock.patch.object(
                self.task.compute_rpcapi,
                'finish_snapshot_based_resize_at_dest'),
            mock.patch.object(self.task.instance, 'refresh')
        ) as (
            finish_resize, refresh
        ):
            self.task.execute()
        # _finish_snapshot_based_resize_at_dest will set the instance
        # task_state to resize_migrated, save the change, and call the
        # finish_snapshot_based_resize_at_dest method.
        target_instance = self.task.instance
        self.assertEqual(task_states.RESIZE_MIGRATED,
                         self.task.instance.task_state)
        finish_resize.assert_called_once_with(
            self.task.context, target_instance, self.task.migration,
            self.task.snapshot_id, self.task.request_spec)
        refresh.assert_called_once_with()
        # _update_instance_mapping will swap the hidden fields and update
        # the instance mapping to point at the target cell.
        self.assertFalse(target_instance.hidden,
                         'Target cell instance should not be hidden')
        source_instance = self.task.source_cell_instance
        source_instance.refresh()
        self.assertTrue(source_instance.hidden,
                        'Source cell instance should be hidden')
        mapping = objects.InstanceMapping.get_by_instance_uuid(
            self.task.context, target_instance.uuid)
        self.assertEqual(self.target_context.cell_uuid,
                         mapping.cell_mapping.uuid)

    @mock.patch('nova.objects.InstanceMapping.save')
    def test_finish_snapshot_based_resize_at_dest_fails(self, mock_im_save):
        """Tests when the finish_snapshot_based_resize_at_dest compute method
        raises an error.
        """
        with test.nested(
            mock.patch.object(self.task.compute_rpcapi,
                              'finish_snapshot_based_resize_at_dest',
                              side_effect=test.TestingException('oops')),
            mock.patch.object(self.task, '_copy_latest_fault'),
        ) as (
            finish_resize, copy_fault
        ):
            self.assertRaises(test.TestingException,
                              self.task._finish_snapshot_based_resize_at_dest)
        # The source cell instance should be in error state.
        source_instance = self.task.source_cell_instance
        source_instance.refresh()
        self.assertEqual(vm_states.ERROR, source_instance.vm_state)
        self.assertIsNone(source_instance.task_state)
        # And the latest fault and instance action event should have been
        # copied from the target cell DB to the source cell DB.
        copy_fault.assert_called_once_with(self.source_context)
        # Assert the event was recorded in the source cell DB.
        event_name = 'compute_finish_snapshot_based_resize_at_dest'
        action = objects.InstanceAction.get_by_request_id(
            source_instance._context, source_instance.uuid,
            source_instance._context.request_id)
        self.assertIsNotNone(action, 'InstanceAction not found.')
        events = objects.InstanceActionEventList.get_by_action(
            source_instance._context, action.id)
        self.assertEqual(1, len(events), events)
        self.assertEqual(event_name, events[0].event)
        self.assertEqual('Error', events[0].result)
        self.assertIn('_finish_snapshot_based_resize_at_dest',
                      events[0].traceback)
        self.assertEqual(self.task.migration.dest_compute, events[0].host)
        # Assert the instance mapping was never updated.
        mock_im_save.assert_not_called()

    def test_copy_latest_fault(self):
        """Tests _copy_latest_fault working as expected"""
        # Inject a fault in the target cell database.
        try:
            raise test.TestingException('test-fault')
        except test.TestingException as fault:
            compute_utils.add_instance_fault_from_exc(
                self.target_context, self.task.instance, fault)
        self.task._copy_latest_fault(self.source_context)
        # Now make sure that fault shows up in the source cell DB (it will
        # get lazy-loaded here).
        fault = self.task.source_cell_instance.fault
        self.assertIsNotNone(fault, 'Fault not copied to source cell DB')
        # And it's the fault we expect.
        self.assertEqual('TestingException', fault.message)

    @mock.patch('nova.conductor.tasks.cross_cell_migrate.LOG.exception')
    def test_copy_latest_fault_error(self, mock_log):
        """Tests that _copy_latest_fault errors are swallowed"""
        with mock.patch('nova.objects.InstanceFault.get_latest_for_instance',
                        side_effect=test.TestingException):
            self.task._copy_latest_fault(self.source_context)
        # The source cell should not have a fault.
        self.assertIsNone(self.task.source_cell_instance.fault)
        # The error should have been logged.
        mock_log.assert_called_once()
        self.assertIn('Failed to copy instance fault from target cell DB',
                      mock_log.call_args[0][0])


class UtilityTestCase(test.NoDBTestCase):
    """Tests utility methods in the cross_cell_migrate module."""

    @mock.patch('nova.objects.HostMapping.get_by_host',
                return_value=objects.HostMapping(
                    cell_mapping=objects.CellMapping(uuid=uuids.cell)))
    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_get_inst_and_cell_map_from_source(self, mock_get_inst,
                                               mock_get_by_host):
        target_cell_context = nova_context.get_admin_context()
        # Stub out Instance.get_by_uuid to make sure a copy of the context is
        # targeted at the source cell mapping.

        def stub_get_by_uuid(ctxt, *args, **kwargs):
            self.assertIsNot(ctxt, target_cell_context)
            self.assertEqual(uuids.cell, ctxt.cell_uuid)
            return mock.sentinel.instance
        mock_get_inst.side_effect = stub_get_by_uuid
        inst, cell_mapping = (
            cross_cell_migrate.get_inst_and_cell_map_from_source(
                target_cell_context, 'source-host', uuids.instance))
        self.assertIs(inst, mock.sentinel.instance)
        self.assertIs(cell_mapping, mock_get_by_host.return_value.cell_mapping)
        mock_get_by_host.assert_called_once_with(
            target_cell_context, 'source-host')
        mock_get_inst.assert_called_once_with(
            test.MatchType(nova_context.RequestContext), uuids.instance,
            expected_attrs=['flavor', 'info_cache', 'system_metadata'])


class ConfirmResizeTaskTestCase(test.NoDBTestCase):

    def setUp(self):
        super(ConfirmResizeTaskTestCase, self).setUp()
        context = nova_context.get_admin_context()
        compute_rpcapi = mock.Mock()
        self.task = cross_cell_migrate.ConfirmResizeTask(
            context,
            objects.Instance(context, uuid=uuids.instance,
                             host='target-host', vm_state=vm_states.RESIZED,
                             system_metadata={
                                 'old_vm_state': vm_states.ACTIVE}),
            objects.Migration(context, uuid=uuids.migration,
                              dest_compute='target-host',
                              source_compute='source-host',
                              status='confirming'),
            mock.sentinel.legacy_notifier,
            compute_rpcapi)

    @mock.patch('nova.conductor.tasks.cross_cell_migrate.'
                'get_inst_and_cell_map_from_source')
    def test_execute(self, mock_get_instance):
        source_cell_instance = objects.Instance(
            mock.MagicMock(), uuid=uuids.instance)
        source_cell_instance.destroy = mock.Mock()
        mock_get_instance.return_value = (
            source_cell_instance, objects.CellMapping())
        with test.nested(
            mock.patch.object(self.task, '_send_resize_confirm_notification'),
            mock.patch.object(self.task, '_cleanup_source_host'),
            mock.patch.object(self.task, '_finish_confirm_in_target_cell')
        ) as (
            _send_resize_confirm_notification, _cleanup_source_host,
            _finish_confirm_in_target_cell
        ):
            self.task.execute()
        mock_get_instance.assert_called_once_with(
            self.task.context, self.task.migration.source_compute,
            self.task.instance.uuid)
        self.assertEqual(2, _send_resize_confirm_notification.call_count)
        _send_resize_confirm_notification.assert_has_calls([
            mock.call(source_cell_instance, fields.NotificationPhase.START),
            mock.call(self.task.instance, fields.NotificationPhase.END)])
        _cleanup_source_host.assert_called_once_with(source_cell_instance)
        source_cell_instance.destroy.assert_called_once_with(
            hard_delete=True)
        _finish_confirm_in_target_cell.assert_called_once_with()

    @mock.patch('nova.conductor.tasks.cross_cell_migrate.'
                'get_inst_and_cell_map_from_source',
                side_effect=exception.InstanceNotFound(
                    instance_id=uuids.instance))
    @mock.patch('nova.objects.Migration.save')
    @mock.patch('nova.objects.RequestSpec.get_by_instance_uuid')
    @mock.patch('nova.scheduler.utils.set_vm_state_and_notify')
    def test_rollback(self, mock_set_state_notify, mock_get_reqspec,
                      mock_mig_save, mock_get_instance):
        self.assertRaises(exception.InstanceNotFound, self.task.execute)
        mock_get_instance.assert_called_once_with(
            self.task.context, self.task.migration.source_compute,
            self.task.instance.uuid)
        self.assertEqual('error', self.task.migration.status)
        mock_mig_save.assert_called_once_with()
        mock_get_reqspec.assert_called_once_with(
            self.task.context, self.task.instance.uuid)
        mock_set_state_notify.assert_called_once_with(
            self.task.context, self.task.instance.uuid, 'compute_task',
            'migrate_server',
            {'vm_state': vm_states.ERROR, 'task_state': None},
            mock_get_instance.side_effect,
            mock_get_reqspec.return_value)

    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def test_send_resize_confirm_notification(self, mock_versioned_notify,
                                              mock_legacy_notify):
        self.flags(host='fake-conductor-host')
        instance = self.task.instance
        self.task._send_resize_confirm_notification(instance, 'fake-phase')
        mock_legacy_notify.assert_called_once_with(
            self.task.legacy_notifier, instance._context, instance,
            'resize.confirm.fake-phase')
        mock_versioned_notify.assert_called_once_with(
            instance._context, instance, 'fake-conductor-host',
            action=fields.NotificationAction.RESIZE_CONFIRM,
            phase='fake-phase')

    @mock.patch('nova.objects.InstanceAction.action_start')
    @mock.patch('nova.objects.Migration.get_by_uuid')
    @mock.patch('nova.objects.InstanceActionEvent')  # stub EventReporter calls
    def test_cleanup_source_host(
            self, mock_action_event, mock_get_mig, mock_action_start):
        instance = objects.Instance(nova_context.get_admin_context(),
                                    uuid=uuids.instance,
                                    flavor=objects.Flavor())
        self.task._cleanup_source_host(instance)
        self.assertIs(instance.old_flavor, instance.flavor)
        mock_action_start.assert_called_once_with(
            instance._context, instance.uuid, instance_actions.CONFIRM_RESIZE,
            want_result=False)
        mock_get_mig.assert_called_once_with(
            instance._context, self.task.migration.uuid)
        self.task.compute_rpcapi.confirm_snapshot_based_resize_at_source.\
            assert_called_once_with(instance._context, instance,
                                    mock_get_mig.return_value)
        mock_action_event.event_start.assert_called_once_with(
            self.task.context, uuids.instance,
            'compute_confirm_snapshot_based_resize_at_source',
            want_result=False, host=mock_get_mig.return_value.source_compute)
        mock_action_event.event_finish_with_failure.assert_called_once_with(
            self.task.context, uuids.instance,
            'compute_confirm_snapshot_based_resize_at_source',
            exc_val=None, exc_tb=None, want_result=False)

    @mock.patch('nova.objects.Migration.save')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.objects.Instance.drop_migration_context')
    def test_finish_confirm_in_target_cell(self, mock_drop_ctx, mock_inst_save,
                                           mock_mig_save):
        with mock.patch.object(
                self.task, '_set_vm_and_task_state') as mock_set_state:
            self.task._finish_confirm_in_target_cell()
        self.assertEqual('confirmed', self.task.migration.status)
        mock_mig_save.assert_called_once_with()
        self.assertNotIn('old_vm_state', self.task.instance.system_metadata)
        self.assertIsNone(self.task.instance.old_flavor)
        self.assertIsNone(self.task.instance.new_flavor)
        mock_set_state.assert_called_once_with()
        mock_drop_ctx.assert_called_once_with()
        mock_inst_save.assert_called_once_with(expected_task_state=[
            None, task_states.DELETING, task_states.SOFT_DELETING])

    def test_set_vm_and_task_state_shutdown(self):
        self.task.instance.power_state = power_state.SHUTDOWN
        self.task._set_vm_and_task_state()
        self.assertEqual(vm_states.STOPPED, self.task.instance.vm_state)
        self.assertIsNone(self.task.instance.task_state)

    def test_set_vm_and_task_state_active(self):
        self.task.instance.power_state = power_state.RUNNING
        self.task._set_vm_and_task_state()
        self.assertEqual(vm_states.ACTIVE, self.task.instance.vm_state)
        self.assertIsNone(self.task.instance.task_state)


class RevertResizeTaskTestCase(test.NoDBTestCase, ObjectComparatorMixin):

    def setUp(self):
        super(RevertResizeTaskTestCase, self).setUp()
        target_cell_context = nova_context.get_admin_context()
        target_cell_context.cell_uuid = uuids.target_cell
        instance = fake_instance.fake_instance_obj(
            target_cell_context, **{
                'vm_state': vm_states.RESIZED,
                'task_state': task_states.RESIZE_REVERTING,
                'expected_attrs': ['system_metadata', 'flavor']
            })
        migration = objects.Migration(
            target_cell_context, uuid=uuids.migration, status='reverting',
            source_compute='source-host', dest_compute='dest-host')
        legacy_notifier = mock.MagicMock()
        compute_rpcapi = mock.MagicMock()
        self.task = cross_cell_migrate.RevertResizeTask(
            target_cell_context, instance, migration, legacy_notifier,
            compute_rpcapi)

    def _generate_source_cell_instance(self):
        source_cell_context = nova_context.get_admin_context()
        source_cell_context.cell_uuid = uuids.source_cell
        source_cell_instance = self.task.instance.obj_clone()
        source_cell_instance._context = source_cell_context
        return source_cell_instance

    @mock.patch('nova.conductor.tasks.cross_cell_migrate.'
                'get_inst_and_cell_map_from_source')
    @mock.patch('nova.objects.InstanceActionEvent')  # Stub EventReport calls.
    def test_execute(self, mock_action_event, mock_get_instance):
        """Happy path test for the execute method."""
        # Setup mocks.
        source_cell_instance = self._generate_source_cell_instance()
        source_cell_context = source_cell_instance._context
        source_cell_mapping = objects.CellMapping(source_cell_context,
                                                  uuid=uuids.source_cell)
        mock_get_instance.return_value = (source_cell_instance,
                                          source_cell_mapping)

        def stub_update_instance_in_source_cell(*args, **kwargs):
            # Ensure _update_instance_mapping is not called before
            # _update_instance_in_source_cell.
            _update_instance_mapping.assert_not_called()
            return mock.sentinel.source_cell_migration

        with test.nested(
            mock.patch.object(self.task, '_send_resize_revert_notification'),
            mock.patch.object(self.task, '_update_instance_in_source_cell',
                              side_effect=stub_update_instance_in_source_cell),
            mock.patch.object(self.task, '_update_instance_mapping'),
            mock.patch.object(self.task.instance, 'destroy'),
            mock.patch.object(source_cell_instance, 'refresh'),
        ) as (
            _send_resize_revert_notification, _update_instance_in_source_cell,
            _update_instance_mapping, mock_inst_destroy, mock_inst_refresh,
        ):
            # Run the code.
            self.task.execute()
        # Should have sent a start and end notification.
        self.assertEqual(2, _send_resize_revert_notification.call_count,
                         _send_resize_revert_notification.calls)
        _send_resize_revert_notification.assert_has_calls([
            mock.call(self.task.instance, fields.NotificationPhase.START),
            mock.call(source_cell_instance, fields.NotificationPhase.END),
        ])
        mock_get_instance.assert_called_once_with(
            self.task.context, self.task.migration.source_compute,
            self.task.instance.uuid)
        _update_instance_in_source_cell.assert_called_once_with(
            source_cell_instance)
        _update_instance_mapping.assert_called_once_with(
            source_cell_instance, source_cell_mapping)
        # _source_cell_instance and _source_cell_migration should have been
        # set for rollbacks
        self.assertIs(self.task._source_cell_instance, source_cell_instance)
        self.assertIs(self.task._source_cell_migration,
                      mock.sentinel.source_cell_migration)
        # Cleanup at dest host.
        self.task.compute_rpcapi.revert_snapshot_based_resize_at_dest.\
            assert_called_once_with(self.task.context, self.task.instance,
                                    self.task.migration)
        # EventReporter should have been used.
        event_name = 'compute_revert_snapshot_based_resize_at_dest'
        mock_action_event.event_start.assert_called_once_with(
            source_cell_context, source_cell_instance.uuid, event_name,
            want_result=False, host=self.task.migration.dest_compute)
        mock_action_event.event_finish_with_failure.assert_called_once_with(
            source_cell_context, source_cell_instance.uuid, event_name,
            exc_val=None, exc_tb=None, want_result=False)
        mock_action_event.event_finish.assert_called_once_with(
            source_cell_context, source_cell_instance.uuid,
            'conductor_revert_snapshot_based_resize', want_result=False)
        # Destroy the instance in the target cell.
        mock_inst_destroy.assert_called_once_with(hard_delete=True)
        # Cleanup at source host.
        self.task.compute_rpcapi.\
            finish_revert_snapshot_based_resize_at_source.\
            assert_called_once_with(
                source_cell_context, source_cell_instance,
                mock.sentinel.source_cell_migration)
        # Refresh the source cell instance so we have the latest data.
        mock_inst_refresh.assert_called_once_with()

    @mock.patch('nova.conductor.tasks.cross_cell_migrate.RevertResizeTask.'
                '_execute')
    @mock.patch('nova.objects.RequestSpec.get_by_instance_uuid')
    @mock.patch('nova.scheduler.utils.set_vm_state_and_notify')
    def test_rollback_target_cell(
            self, mock_set_state_notify, mock_get_reqspec, mock_execute):
        """Tests the case that we did not update the instance mapping
        so we set the target cell migration to error status.
        """
        error = test.TestingException('zoinks!')
        mock_execute.side_effect = error
        with mock.patch.object(self.task.migration, 'save') as mock_save:
            self.assertRaises(test.TestingException, self.task.execute)
        self.assertEqual('error', self.task.migration.status)
        mock_save.assert_called_once_with()
        mock_get_reqspec.assert_called_once_with(
            self.task.context, self.task.instance.uuid)
        mock_set_state_notify.assert_called_once_with(
            self.task.instance._context, self.task.instance.uuid,
            'compute_task', 'migrate_server',
            {'vm_state': vm_states.ERROR, 'task_state': None}, error,
            mock_get_reqspec.return_value)
        self.assertIn('The instance is mapped to the target cell',
                      self.stdlog.logger.output)

    @mock.patch('nova.conductor.tasks.cross_cell_migrate.RevertResizeTask.'
                '_execute')
    @mock.patch('nova.objects.RequestSpec.get_by_instance_uuid')
    @mock.patch('nova.scheduler.utils.set_vm_state_and_notify')
    def test_rollback_source_cell(
            self, mock_set_state_notify, mock_get_reqspec, mock_execute):
        """Tests the case that we did update the instance mapping
        so we set the source cell migration to error status.
        """
        source_cell_instance = self._generate_source_cell_instance()
        source_cell_context = source_cell_instance._context
        self.task._source_cell_instance = source_cell_instance
        self.task._source_cell_migration = objects.Migration(
            source_cell_context, status='reverting', dest_compute='dest-host')
        error = test.TestingException('jinkies!')
        mock_execute.side_effect = error
        with mock.patch.object(self.task._source_cell_migration,
                               'save') as mock_save:
            self.assertRaises(test.TestingException, self.task.execute)
        self.assertEqual('error', self.task._source_cell_migration.status)
        mock_save.assert_called_once_with()
        mock_get_reqspec.assert_called_once_with(
            self.task.context, self.task.instance.uuid)
        mock_set_state_notify.assert_called_once_with(
            source_cell_context, source_cell_instance.uuid,
            'compute_task', 'migrate_server',
            {'vm_state': vm_states.ERROR, 'task_state': None}, error,
            mock_get_reqspec.return_value)
        self.assertIn('The instance is mapped to the source cell',
                      self.stdlog.logger.output)

    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
    def test_send_resize_revert_notification(self, mock_notify_action,
                                             mock_notify_usage):
        self.flags(host='fake-conductor-host')
        instance = self.task.instance
        self.task._send_resize_revert_notification(instance, 'foo')
        # Assert the legacy notification was sent.
        mock_notify_usage.assert_called_once_with(
            self.task.legacy_notifier, instance._context, instance,
            'resize.revert.foo')
        # Assert the versioned notification was sent.
        mock_notify_action.assert_called_once_with(
            instance._context, instance, 'fake-conductor-host',
            action=fields.NotificationAction.RESIZE_REVERT, phase='foo')

    def test_update_instance_in_source_cell(self):
        # Setup mocks.
        source_cell_instance = self._generate_source_cell_instance()
        source_cell_instance.task_state = None
        self.task.instance.system_metadata = {'old_vm_state': vm_states.ACTIVE}
        with test.nested(
            mock.patch.object(source_cell_instance, 'save'),
            mock.patch.object(self.task, '_update_bdms_in_source_cell'),
            mock.patch.object(self.task,
                              '_update_instance_actions_in_source_cell'),
            mock.patch.object(self.task, '_update_migration_in_source_cell')
        ) as (
            mock_inst_save, _update_bdms_in_source_cell,
            _update_instance_actions_in_source_cell,
            _update_migration_in_source_cell
        ):
            # Run the code.
            source_cell_migration = self.task._update_instance_in_source_cell(
                source_cell_instance)
        # The returned object should be the updated migration object from the
        # source cell database.
        self.assertIs(source_cell_migration,
                      _update_migration_in_source_cell.return_value)
        # Fields on the source cell instance should have been updated.
        self.assertEqual(vm_states.ACTIVE,
                         source_cell_instance.system_metadata['old_vm_state'])
        self.assertIs(source_cell_instance.old_flavor,
                      source_cell_instance.flavor)
        self.assertEqual(task_states.RESIZE_REVERTING,
                         source_cell_instance.task_state)
        mock_inst_save.assert_called_once_with()
        _update_bdms_in_source_cell.assert_called_once_with(
            source_cell_instance._context)
        _update_instance_actions_in_source_cell.assert_called_once_with(
            source_cell_instance._context)
        _update_migration_in_source_cell.assert_called_once_with(
            source_cell_instance._context)

    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.conductor.tasks.cross_cell_migrate.'
                'clone_creatable_object')
    def test_update_bdms_in_source_cell(self, mock_clone, mock_get_bdms):
        """Test updating BDMs from the target cell to the source cell."""
        source_cell_context = nova_context.get_admin_context()
        source_cell_context.cell_uuid = uuids.source_cell
        # Setup fake bdms.
        bdm1 = objects.BlockDeviceMapping(
            source_cell_context, uuid=uuids.bdm1, volume_id='vol1',
            attachment_id=uuids.attach1)
        bdm2 = objects.BlockDeviceMapping(
            source_cell_context, uuid=uuids.bdm2, volume_id='vol2',
            attachment_id=uuids.attach2)
        source_bdms = objects.BlockDeviceMappingList(objects=[bdm1, bdm2])
        # With the target BDMs bdm1 from the source is gone and bdm3 is new
        # to simulate bdm1 being detached and bdm3 being attached while the
        # instance was in VERIFY_RESIZE status.
        bdm3 = objects.BlockDeviceMapping(
            self.task.context, uuid=uuids.bdm3, volume_id='vol3',
            attachment_id=uuids.attach1)
        target_bdms = objects.BlockDeviceMappingList(objects=[bdm2, bdm3])

        def stub_get_bdms(ctxt, *args, **kwargs):
            if ctxt.cell_uuid == uuids.source_cell:
                return source_bdms
            return target_bdms
        mock_get_bdms.side_effect = stub_get_bdms

        def stub_mock_clone(ctxt, obj, *args, **kwargs):
            # We want to make assertions on our mocks so do not create a copy.
            return obj
        mock_clone.side_effect = stub_mock_clone

        with test.nested(
            mock.patch.object(self.task.volume_api, 'attachment_create',
                              return_value={'id': uuids.attachment_id}),
            mock.patch.object(self.task.volume_api, 'attachment_delete'),
            mock.patch.object(bdm3, 'create'),
            mock.patch.object(bdm1, 'destroy')
        ) as (
            mock_attachment_create, mock_attachment_delete,
            mock_bdm_create, mock_bdm_destroy
        ):
            self.task._update_bdms_in_source_cell(source_cell_context)
        # Should have gotten BDMs from the source and target cell (order does
        # not matter).
        self.assertEqual(2, mock_get_bdms.call_count, mock_get_bdms.calls)
        mock_get_bdms.assert_has_calls([
            mock.call(source_cell_context, self.task.instance.uuid),
            mock.call(self.task.context, self.task.instance.uuid)],
            any_order=True)
        # Since bdm3 was new in the target cell an attachment should have been
        # created for it in the source cell.
        mock_attachment_create.assert_called_once_with(
            source_cell_context, bdm3.volume_id, self.task.instance.uuid)
        self.assertEqual(uuids.attachment_id, bdm3.attachment_id)
        # And bdm3 should have been created in the source cell.
        mock_bdm_create.assert_called_once_with()
        # Since bdm1 was not in the target cell it should be destroyed in the
        # source cell since we can assume it was detached from the target host
        # in the target cell while the instance was in VERIFY_RESIZE status.
        mock_attachment_delete.assert_called_once_with(
            bdm1._context, bdm1.attachment_id)
        mock_bdm_destroy.assert_called_once_with()

    @mock.patch('nova.objects.BlockDeviceMapping.destroy')
    def test_delete_orphan_source_cell_bdms_attach_delete_fails(self, destroy):
        """Tests attachment_delete failing but not being fatal."""
        source_cell_context = nova_context.get_admin_context()
        bdm1 = objects.BlockDeviceMapping(
            source_cell_context, volume_id='vol1', attachment_id=uuids.attach1)
        bdm2 = objects.BlockDeviceMapping(
            source_cell_context, volume_id='vol2', attachment_id=uuids.attach2)
        source_cell_bdms = objects.BlockDeviceMappingList(objects=[bdm1, bdm2])
        with mock.patch.object(self.task.volume_api,
                               'attachment_delete') as attachment_delete:
            # First call to attachment_delete fails, second is OK.
            attachment_delete.side_effect = [
                test.TestingException('cinder is down'), None]
            self.task._delete_orphan_source_cell_bdms(source_cell_bdms)
        attachment_delete.assert_has_calls([
            mock.call(bdm1._context, bdm1.attachment_id),
            mock.call(bdm2._context, bdm2.attachment_id)])
        self.assertEqual(2, destroy.call_count, destroy.mock_calls)
        self.assertIn('cinder is down', self.stdlog.logger.output)

    @mock.patch('nova.objects.InstanceAction.get_by_request_id')
    @mock.patch('nova.objects.InstanceActionEventList.get_by_action')
    @mock.patch('nova.objects.InstanceAction.create')
    @mock.patch('nova.objects.InstanceActionEvent.create')
    def test_update_instance_actions_in_source_cell(
            self, mock_event_create, mock_action_create, mock_get_events,
            mock_get_action):
        """Tests copying instance actions from the target to source cell."""
        source_cell_context = nova_context.get_admin_context()
        source_cell_context.cell_uuid = uuids.source_cell
        # Setup a fake action and fake event.
        action = objects.InstanceAction(
            id=1, action=instance_actions.REVERT_RESIZE,
            instance_uuid=self.task.instance.uuid,
            request_id=self.task.context.request_id)
        mock_get_action.return_value = action
        event = objects.InstanceActionEvent(
            id=2, action_id=action.id,
            event='conductor_revert_snapshot_based_resize')
        mock_get_events.return_value = objects.InstanceActionEventList(
            objects=[event])
        # Run the code.
        self.task._update_instance_actions_in_source_cell(source_cell_context)
        # Should have created a clone of the action and event.
        mock_get_action.assert_called_once_with(
            self.task.context, self.task.instance.uuid,
            self.task.context.request_id)
        mock_get_events.assert_called_once_with(self.task.context, action.id)
        mock_action_create.assert_called_once_with()
        mock_event_create.assert_called_once_with(
            action.instance_uuid, action.request_id)

    def test_update_source_obj_from_target_cell(self):
        # Create a fake source object to be updated.
        t1 = timeutils.utcnow()
        source_obj = objects.Migration(id=1, created_at=t1, updated_at=t1,
                                       uuid=uuids.migration,
                                       status='post-migrating')
        t2 = timeutils.utcnow()
        target_obj = objects.Migration(id=2, created_at=t2, updated_at=t2,
                                       uuid=uuids.migration,
                                       status='reverting',
                                       # Add a field that is not in source_obj.
                                       migration_type='resize')
        # Run the copy code.
        self.task._update_source_obj_from_target_cell(source_obj, target_obj)
        # First make sure that id, created_at and updated_at are not changed.
        ignored_keys = ['id', 'created_at', 'updated_at']
        for field in ignored_keys:
            self.assertNotEqual(getattr(source_obj, field),
                                getattr(target_obj, field))
        # Now make sure the rest of the fields are the same.
        self._compare_objs(source_obj, target_obj, ignored_keys=ignored_keys)

    def test_update_source_obj_from_target_cell_nested_object(self):
        """Tests that calling _update_source_obj_from_target_cell with an
        object that has nested object fields will raise ObjectActionError.
        """
        source = objects.Instance(flavor=objects.Flavor(flavorid='a'))
        target = objects.Instance(flavor=objects.Flavor(flavorid='b'))
        ex = self.assertRaises(exception.ObjectActionError,
                               self.task._update_source_obj_from_target_cell,
                               source, target)
        self.assertIn('nested objects are not supported', six.text_type(ex))

    @mock.patch('nova.objects.Migration.get_by_uuid')
    def test_update_migration_in_source_cell(self, mock_get_migration):
        """Tests updating the migration record in the source cell from the
        target cell.
        """
        source_cell_context = nova_context.get_admin_context()
        with mock.patch.object(
                self.task,
                '_update_source_obj_from_target_cell') as mock_update_obj:
            source_cell_migration = \
                self.task._update_migration_in_source_cell(source_cell_context)
        mock_get_migration.assert_called_once_with(source_cell_context,
                                                   self.task.migration.uuid)
        mock_update_obj.assert_called_once_with(source_cell_migration,
                                                self.task.migration)
        self.assertIs(source_cell_migration, mock_get_migration.return_value)
        source_cell_migration.save.assert_called_once_with()

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_update_instance_mapping(self, get_inst_map):
        """Tests updating the instance mapping from the target to source cell.
        """
        source_cell_instance = self._generate_source_cell_instance()
        source_cell_context = source_cell_instance._context
        source_cell_mapping = objects.CellMapping(source_cell_context,
                                                  uuid=uuids.source_cell)
        inst_map = objects.InstanceMapping(
            cell_mapping=objects.CellMapping(uuids.target_cell))
        get_inst_map.return_value = inst_map
        with test.nested(
            mock.patch.object(source_cell_instance, 'save'),
            mock.patch.object(self.task.instance, 'save'),
            mock.patch.object(inst_map, 'save')
        ) as (
            source_inst_save, target_inst_save, inst_map_save
        ):
            self.task._update_instance_mapping(source_cell_instance,
                                               source_cell_mapping)
        get_inst_map.assert_called_once_with(self.task.context,
                                             self.task.instance.uuid)
        # The source cell instance should not be hidden.
        self.assertFalse(source_cell_instance.hidden)
        source_inst_save.assert_called_once_with()
        # The instance mapping should point at the source cell.
        self.assertIs(source_cell_mapping, inst_map.cell_mapping)
        inst_map_save.assert_called_once_with()
        # The target cell instance should be hidden.
        self.assertTrue(self.task.instance.hidden)
        target_inst_save.assert_called_once_with()
