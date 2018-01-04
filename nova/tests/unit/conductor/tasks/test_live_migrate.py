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
import oslo_messaging as messaging
import six

from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import vm_states
from nova.conductor.tasks import live_migrate
from nova import exception
from nova import objects
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import servicegroup
from nova import test
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids
from nova import utils


fake_selection1 = objects.Selection(service_host="host1", nodename="node1",
        cell_uuid=uuids.cell)
fake_selection2 = objects.Selection(service_host="host2", nodename="node2",
        cell_uuid=uuids.cell)


class LiveMigrationTaskTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LiveMigrationTaskTestCase, self).setUp()
        self.context = "context"
        self.instance_host = "host"
        self.instance_uuid = uuids.instance
        self.instance_image = "image_ref"
        db_instance = fake_instance.fake_db_instance(
                host=self.instance_host,
                uuid=self.instance_uuid,
                power_state=power_state.RUNNING,
                vm_state = vm_states.ACTIVE,
                memory_mb=512,
                image_ref=self.instance_image)
        self.instance = objects.Instance._from_db_object(
                self.context, objects.Instance(), db_instance)
        self.instance.system_metadata = {'image_hw_disk_bus': 'scsi'}
        self.destination = "destination"
        self.block_migration = "bm"
        self.disk_over_commit = "doc"
        self.migration = objects.Migration()
        self.fake_spec = objects.RequestSpec()
        self._generate_task()

    def _generate_task(self):
        self.task = live_migrate.LiveMigrationTask(self.context,
            self.instance, self.destination, self.block_migration,
            self.disk_over_commit, self.migration, compute_rpcapi.ComputeAPI(),
            servicegroup.API(), scheduler_client.SchedulerClient(),
            self.fake_spec)

    def test_execute_with_destination(self, new_mode=True):
        dest_node = objects.ComputeNode(hypervisor_hostname='dest_node')
        with test.nested(
            mock.patch.object(self.task, '_check_host_is_up'),
            mock.patch.object(self.task, '_check_requested_destination',
                              return_value=(mock.sentinel.source_node,
                                            dest_node)),
            mock.patch.object(scheduler_utils,
                              'claim_resources_on_destination'),
            mock.patch.object(self.migration, 'save'),
            mock.patch.object(self.task.compute_rpcapi, 'live_migration'),
            mock.patch('nova.conductor.tasks.migrate.'
                       'replace_allocation_with_migration'),
            mock.patch('nova.conductor.tasks.live_migrate.'
                       'should_do_migration_allocation')
        ) as (mock_check_up, mock_check_dest, mock_claim, mock_save, mock_mig,
              m_alloc, mock_sda):
            mock_mig.return_value = "bob"
            m_alloc.return_value = (mock.MagicMock(), mock.sentinel.allocs)
            mock_sda.return_value = new_mode

            self.assertEqual("bob", self.task.execute())
            mock_check_up.assert_called_once_with(self.instance_host)
            mock_check_dest.assert_called_once_with()
            if new_mode:
                allocs = mock.sentinel.allocs
            else:
                allocs = None
            mock_claim.assert_called_once_with(
                self.context, self.task.scheduler_client.reportclient,
                self.instance, mock.sentinel.source_node, dest_node,
                source_node_allocations=allocs)
            mock_mig.assert_called_once_with(
                self.context,
                host=self.instance_host,
                instance=self.instance,
                dest=self.destination,
                block_migration=self.block_migration,
                migration=self.migration,
                migrate_data=None)
            self.assertTrue(mock_save.called)
            # make sure the source/dest fields were set on the migration object
            self.assertEqual(self.instance.node, self.migration.source_node)
            self.assertEqual(dest_node.hypervisor_hostname,
                             self.migration.dest_node)
            self.assertEqual(self.task.destination,
                             self.migration.dest_compute)
            if new_mode:
                m_alloc.assert_called_once_with(self.context,
                                                self.instance,
                                                self.migration)
            else:
                m_alloc.assert_not_called()

    def test_execute_with_destination_old_school(self):
        self.test_execute_with_destination(new_mode=False)

    def test_execute_without_destination(self):
        self.destination = None
        self._generate_task()
        self.assertIsNone(self.task.destination)

        with test.nested(
            mock.patch.object(self.task, '_check_host_is_up'),
            mock.patch.object(self.task, '_find_destination'),
            mock.patch.object(self.task.compute_rpcapi, 'live_migration'),
            mock.patch.object(self.migration, 'save'),
            mock.patch('nova.conductor.tasks.migrate.'
                       'replace_allocation_with_migration'),
            mock.patch('nova.conductor.tasks.live_migrate.'
                       'should_do_migration_allocation'),
        ) as (mock_check, mock_find, mock_mig, mock_save, mock_alloc,
              mock_sda):
            mock_find.return_value = ("found_host", "found_node")
            mock_mig.return_value = "bob"
            mock_alloc.return_value = (mock.MagicMock(), mock.MagicMock())
            mock_sda.return_value = True

            self.assertEqual("bob", self.task.execute())
            mock_check.assert_called_once_with(self.instance_host)
            mock_find.assert_called_once_with()
            mock_mig.assert_called_once_with(self.context,
                host=self.instance_host,
                instance=self.instance,
                dest="found_host",
                block_migration=self.block_migration,
                migration=self.migration,
                migrate_data=None)
            self.assertTrue(mock_save.called)
            self.assertEqual('found_host', self.migration.dest_compute)
            self.assertEqual('found_node', self.migration.dest_node)
            self.assertEqual(self.instance.node, self.migration.source_node)
            self.assertTrue(mock_alloc.called)

    def test_check_instance_is_active_passes_when_paused(self):
        self.task.instance['power_state'] = power_state.PAUSED
        self.task._check_instance_is_active()

    def test_check_instance_is_active_fails_when_shutdown(self):
        self.task.instance['power_state'] = power_state.SHUTDOWN
        self.assertRaises(exception.InstanceInvalidState,
                          self.task._check_instance_is_active)

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    @mock.patch.object(servicegroup.API, 'service_is_up')
    def test_check_instance_host_is_up(self, mock_is_up, mock_get):
        mock_get.return_value = "service"
        mock_is_up.return_value = True

        self.task._check_host_is_up("host")
        mock_get.assert_called_once_with(self.context, "host")
        mock_is_up.assert_called_once_with("service")

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    @mock.patch.object(servicegroup.API, 'service_is_up')
    def test_check_instance_host_is_up_fails_if_not_up(self, mock_is_up,
                                                       mock_get):
        mock_get.return_value = "service"
        mock_is_up.return_value = False

        self.assertRaises(exception.ComputeServiceUnavailable,
                self.task._check_host_is_up, "host")
        mock_get.assert_called_once_with(self.context, "host")
        mock_is_up.assert_called_once_with("service")

    @mock.patch.object(objects.Service, 'get_by_compute_host',
                       side_effect=exception.ComputeHostNotFound(host='host'))
    def test_check_instance_host_is_up_fails_if_not_found(self, mock):
        self.assertRaises(exception.ComputeHostNotFound,
            self.task._check_host_is_up, "host")

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    @mock.patch.object(live_migrate.LiveMigrationTask, '_get_compute_info')
    @mock.patch.object(servicegroup.API, 'service_is_up')
    @mock.patch.object(compute_rpcapi.ComputeAPI,
                       'check_can_live_migrate_destination')
    def test_check_requested_destination(self, mock_check, mock_is_up,
                                         mock_get_info, mock_get_host):
        mock_get_host.return_value = "service"
        mock_is_up.return_value = True
        hypervisor_details = objects.ComputeNode(
            hypervisor_type="a",
            hypervisor_version=6.1,
            free_ram_mb=513,
            memory_mb=512,
            ram_allocation_ratio=1.0)
        mock_get_info.return_value = hypervisor_details
        mock_check.return_value = "migrate_data"

        self.assertEqual((hypervisor_details, hypervisor_details),
                         self.task._check_requested_destination())
        self.assertEqual("migrate_data", self.task.migrate_data)
        mock_get_host.assert_called_once_with(self.context, self.destination)
        mock_is_up.assert_called_once_with("service")
        self.assertEqual([mock.call(self.destination),
                          mock.call(self.instance_host),
                          mock.call(self.destination)],
                         mock_get_info.call_args_list)
        mock_check.assert_called_once_with(self.context, self.instance,
            self.destination, self.block_migration, self.disk_over_commit)

    def test_check_requested_destination_fails_with_same_dest(self):
        self.task.destination = "same"
        self.task.source = "same"
        self.assertRaises(exception.UnableToMigrateToSelf,
                          self.task._check_requested_destination)

    @mock.patch.object(objects.Service, 'get_by_compute_host',
                       side_effect=exception.ComputeHostNotFound(host='host'))
    def test_check_requested_destination_fails_when_destination_is_up(self,
                                                                      mock):
        self.assertRaises(exception.ComputeHostNotFound,
                          self.task._check_requested_destination)

    @mock.patch.object(live_migrate.LiveMigrationTask, '_check_host_is_up')
    @mock.patch.object(objects.ComputeNode,
                       'get_first_node_by_host_for_old_compat')
    def test_check_requested_destination_fails_with_not_enough_memory(
        self, mock_get_first, mock_is_up):
        mock_get_first.return_value = (
            objects.ComputeNode(free_ram_mb=513,
                                memory_mb=1024,
                                ram_allocation_ratio=0.9,))

        # free_ram is bigger than instance.ram (512) but the allocation
        # ratio reduces the total available RAM to 410MB
        # (1024 * 0.9 - (1024 - 513))
        self.assertRaises(exception.MigrationPreCheckError,
                          self.task._check_requested_destination)
        mock_is_up.assert_called_once_with(self.destination)
        mock_get_first.assert_called_once_with(self.context, self.destination)

    @mock.patch.object(live_migrate.LiveMigrationTask, '_check_host_is_up')
    @mock.patch.object(live_migrate.LiveMigrationTask,
                       '_check_destination_has_enough_memory')
    @mock.patch.object(live_migrate.LiveMigrationTask, '_get_compute_info')
    def test_check_requested_destination_fails_with_hypervisor_diff(
        self, mock_get_info, mock_check, mock_is_up):
        mock_get_info.side_effect = [
            objects.ComputeNode(hypervisor_type='b'),
            objects.ComputeNode(hypervisor_type='a')]

        self.assertRaises(exception.InvalidHypervisorType,
                          self.task._check_requested_destination)
        mock_is_up.assert_called_once_with(self.destination)
        mock_check.assert_called_once_with()
        self.assertEqual([mock.call(self.instance_host),
                          mock.call(self.destination)],
                         mock_get_info.call_args_list)

    @mock.patch.object(live_migrate.LiveMigrationTask, '_check_host_is_up')
    @mock.patch.object(live_migrate.LiveMigrationTask,
                       '_check_destination_has_enough_memory')
    @mock.patch.object(live_migrate.LiveMigrationTask, '_get_compute_info')
    def test_check_requested_destination_fails_with_hypervisor_too_old(
        self, mock_get_info, mock_check, mock_is_up):
        host1 = {'hypervisor_type': 'a', 'hypervisor_version': 7}
        host2 = {'hypervisor_type': 'a', 'hypervisor_version': 6}
        mock_get_info.side_effect = [objects.ComputeNode(**host1),
                                     objects.ComputeNode(**host2)]

        self.assertRaises(exception.DestinationHypervisorTooOld,
                          self.task._check_requested_destination)
        mock_is_up.assert_called_once_with(self.destination)
        mock_check.assert_called_once_with()
        self.assertEqual([mock.call(self.instance_host),
                          mock.call(self.destination)],
                         mock_get_info.call_args_list)

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    @mock.patch.object(live_migrate.LiveMigrationTask, '_get_compute_info')
    @mock.patch.object(servicegroup.API, 'service_is_up')
    @mock.patch.object(compute_rpcapi.ComputeAPI,
                       'check_can_live_migrate_destination')
    @mock.patch.object(objects.HostMapping, 'get_by_host',
                       return_value=objects.HostMapping(
                           cell_mapping=objects.CellMapping(
                               uuid=uuids.different)))
    def test_check_requested_destination_fails_different_cells(
            self, mock_get_host_mapping, mock_check, mock_is_up,
            mock_get_info, mock_get_host):
        mock_get_host.return_value = "service"
        mock_is_up.return_value = True
        hypervisor_details = objects.ComputeNode(
            hypervisor_type="a",
            hypervisor_version=6.1,
            free_ram_mb=513,
            memory_mb=512,
            ram_allocation_ratio=1.0)
        mock_get_info.return_value = hypervisor_details
        mock_check.return_value = "migrate_data"

        ex = self.assertRaises(exception.MigrationPreCheckError,
                               self.task._check_requested_destination)
        self.assertIn('across cells', six.text_type(ex))

    def test_find_destination_works(self):
        self.mox.StubOutWithMock(utils, 'get_image_from_system_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(objects.RequestSpec,
                                 'reset_forced_destinations')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        utils.get_image_from_system_metadata(
            self.instance.system_metadata).AndReturn("image")
        scheduler_utils.setup_instance_group(
            self.context, self.fake_spec)
        self.fake_spec.reset_forced_destinations()
        self.task.scheduler_client.select_destinations(
                self.context, self.fake_spec, [self.instance.uuid],
                return_objects=True, return_alternates=False).AndReturn(
                [[fake_selection1]])
        self.task._check_compatible_with_source_hypervisor("host1")
        self.task._call_livem_checks_on_host("host1")

        self.mox.ReplayAll()
        self.assertEqual(("host1", "node1"), self.task._find_destination())

        # Make sure the request_spec was updated to include the cell
        # mapping.
        self.assertIsNotNone(self.fake_spec.requested_destination.cell)
        # Make sure the spec was updated to include the project_id.
        self.assertEqual(self.fake_spec.project_id, self.instance.project_id)

    def test_find_destination_works_with_no_request_spec(self):
        task = live_migrate.LiveMigrationTask(
            self.context, self.instance, self.destination,
            self.block_migration, self.disk_over_commit, self.migration,
            compute_rpcapi.ComputeAPI(), servicegroup.API(),
            scheduler_client.SchedulerClient(), request_spec=None)
        another_spec = objects.RequestSpec()
        self.instance.flavor = objects.Flavor()
        self.instance.numa_topology = None
        self.instance.pci_requests = None

        @mock.patch.object(task, '_call_livem_checks_on_host')
        @mock.patch.object(task, '_check_compatible_with_source_hypervisor')
        @mock.patch.object(task.scheduler_client, 'select_destinations')
        @mock.patch.object(objects.RequestSpec, 'from_components')
        @mock.patch.object(scheduler_utils, 'setup_instance_group')
        @mock.patch.object(utils, 'get_image_from_system_metadata')
        def do_test(get_image, setup_ig, from_components, select_dest,
                    check_compat, call_livem_checks):
            get_image.return_value = "image"
            from_components.return_value = another_spec
            select_dest.return_value = [[fake_selection1]]

            self.assertEqual(("host1", "node1"), task._find_destination())

            get_image.assert_called_once_with(self.instance.system_metadata)
            setup_ig.assert_called_once_with(self.context, another_spec)
            select_dest.assert_called_once_with(self.context, another_spec,
                    [self.instance.uuid], return_objects=True,
                    return_alternates=False)
            # Make sure the request_spec was updated to include the cell
            # mapping.
            self.assertIsNotNone(another_spec.requested_destination.cell)
            check_compat.assert_called_once_with("host1")
            call_livem_checks.assert_called_once_with("host1")
        do_test()

    def test_find_destination_no_image_works(self):
        self.instance['image_ref'] = ''

        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        scheduler_utils.setup_instance_group(self.context, self.fake_spec)
        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndReturn([[fake_selection1]])
        self.task._check_compatible_with_source_hypervisor("host1")
        self.task._call_livem_checks_on_host("host1")

        self.mox.ReplayAll()
        self.assertEqual(("host1", "node1"), self.task._find_destination())

    def _test_find_destination_retry_hypervisor_raises(self, error):
        self.mox.StubOutWithMock(utils, 'get_image_from_system_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        utils.get_image_from_system_metadata(
            self.instance.system_metadata).AndReturn("image")
        scheduler_utils.setup_instance_group(self.context, self.fake_spec)
        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndReturn([[fake_selection1]])
        self.task._check_compatible_with_source_hypervisor("host1")\
                .AndRaise(error)

        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndReturn([[fake_selection2]])
        self.task._check_compatible_with_source_hypervisor("host2")
        self.task._call_livem_checks_on_host("host2")

        self.mox.ReplayAll()
        with mock.patch.object(self.task,
                               '_remove_host_allocations') as remove_allocs:
            self.assertEqual(("host2", "node2"), self.task._find_destination())
        # Should have removed allocations for the first host.
        remove_allocs.assert_called_once_with('host1', 'node1')

    def test_find_destination_retry_with_old_hypervisor(self):
        self._test_find_destination_retry_hypervisor_raises(
                exception.DestinationHypervisorTooOld)

    def test_find_destination_retry_with_invalid_hypervisor_type(self):
        self._test_find_destination_retry_hypervisor_raises(
                exception.InvalidHypervisorType)

    def test_find_destination_retry_with_invalid_livem_checks(self):
        self.flags(migrate_max_retries=1)
        self.mox.StubOutWithMock(utils, 'get_image_from_system_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        utils.get_image_from_system_metadata(
            self.instance.system_metadata).AndReturn("image")
        scheduler_utils.setup_instance_group(self.context, self.fake_spec)
        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndReturn([[fake_selection1]])
        self.task._check_compatible_with_source_hypervisor("host1")
        self.task._call_livem_checks_on_host("host1")\
                .AndRaise(exception.Invalid)

        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndReturn([[fake_selection2]])
        self.task._check_compatible_with_source_hypervisor("host2")
        self.task._call_livem_checks_on_host("host2")

        self.mox.ReplayAll()
        with mock.patch.object(self.task,
                               '_remove_host_allocations') as remove_allocs:
            self.assertEqual(("host2", "node2"), self.task._find_destination())
        # Should have removed allocations for the first host.
        remove_allocs.assert_called_once_with('host1', 'node1')

    def test_find_destination_retry_with_failed_migration_pre_checks(self):
        self.flags(migrate_max_retries=1)
        self.mox.StubOutWithMock(utils, 'get_image_from_system_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        utils.get_image_from_system_metadata(
            self.instance.system_metadata).AndReturn("image")
        scheduler_utils.setup_instance_group(self.context, self.fake_spec)
        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndReturn([[fake_selection1]])
        self.task._check_compatible_with_source_hypervisor("host1")
        self.task._call_livem_checks_on_host("host1")\
                .AndRaise(exception.MigrationPreCheckError("reason"))

        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndReturn([[fake_selection2]])
        self.task._check_compatible_with_source_hypervisor("host2")
        self.task._call_livem_checks_on_host("host2")

        self.mox.ReplayAll()
        with mock.patch.object(self.task,
                               '_remove_host_allocations') as remove_allocs:
            self.assertEqual(("host2", "node2"), self.task._find_destination())
        # Should have removed allocations for the first host.
        remove_allocs.assert_called_once_with('host1', 'node1')

    def test_find_destination_retry_exceeds_max(self):
        self.flags(migrate_max_retries=0)
        self.mox.StubOutWithMock(utils, 'get_image_from_system_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')

        utils.get_image_from_system_metadata(
            self.instance.system_metadata).AndReturn("image")
        scheduler_utils.setup_instance_group(self.context, self.fake_spec)
        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndReturn([[fake_selection1]])
        self.task._check_compatible_with_source_hypervisor("host1")\
                .AndRaise(exception.DestinationHypervisorTooOld)

        self.mox.ReplayAll()
        with test.nested(
            mock.patch.object(self.task.migration, 'save'),
            mock.patch.object(self.task, '_remove_host_allocations')
        ) as (
            save_mock, remove_allocs
        ):
            self.assertRaises(exception.MaxRetriesExceeded,
                              self.task._find_destination)
            self.assertEqual('failed', self.task.migration.status)
            save_mock.assert_called_once_with()
            # Should have removed allocations for the first host.
            remove_allocs.assert_called_once_with('host1', 'node1')

    def test_find_destination_when_runs_out_of_hosts(self):
        self.mox.StubOutWithMock(utils, 'get_image_from_system_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        utils.get_image_from_system_metadata(
            self.instance.system_metadata).AndReturn("image")
        scheduler_utils.setup_instance_group(self.context, self.fake_spec)
        self.task.scheduler_client.select_destinations(self.context,
                self.fake_spec, [self.instance.uuid], return_objects=True,
                return_alternates=False).AndRaise(
                exception.NoValidHost(reason=""))

        self.mox.ReplayAll()
        self.assertRaises(exception.NoValidHost, self.task._find_destination)

    @mock.patch("nova.utils.get_image_from_system_metadata")
    @mock.patch("nova.scheduler.utils.build_request_spec")
    @mock.patch("nova.scheduler.utils.setup_instance_group")
    @mock.patch("nova.objects.RequestSpec.from_primitives")
    def test_find_destination_with_remoteError(self,
        m_from_primitives, m_setup_instance_group,
        m_build_request_spec, m_get_image_from_system_metadata):
        m_get_image_from_system_metadata.return_value = {'properties': {}}
        m_build_request_spec.return_value = {}
        fake_spec = objects.RequestSpec()
        m_from_primitives.return_value = fake_spec
        with mock.patch.object(self.task.scheduler_client,
            'select_destinations') as m_select_destinations:
            error = messaging.RemoteError()
            m_select_destinations.side_effect = error
            self.assertRaises(exception.MigrationSchedulerRPCError,
                              self.task._find_destination)

    def test_call_livem_checks_on_host(self):
        with mock.patch.object(self.task.compute_rpcapi,
            'check_can_live_migrate_destination',
            side_effect=messaging.MessagingTimeout):
            self.assertRaises(exception.MigrationPreCheckError,
                self.task._call_livem_checks_on_host, {})

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
                       side_effect=exception.InstanceMappingNotFound(
                           uuid=uuids.instance))
    def test_get_source_cell_mapping_not_found(self, mock_get):
        """Negative test where InstanceMappingNotFound is raised and converted
        to MigrationPreCheckError.
        """
        self.assertRaises(exception.MigrationPreCheckError,
                          self.task._get_source_cell_mapping)
        mock_get.assert_called_once_with(
            self.task.context, self.task.instance.uuid)

    @mock.patch.object(objects.HostMapping, 'get_by_host',
                       side_effect=exception.HostMappingNotFound(
                           name='destination'))
    def test_get_destination_cell_mapping_not_found(self, mock_get):
        """Negative test where HostMappingNotFound is raised and converted
        to MigrationPreCheckError.
        """
        self.assertRaises(exception.MigrationPreCheckError,
                          self.task._get_destination_cell_mapping)
        mock_get.assert_called_once_with(
            self.task.context, self.task.destination)

    @mock.patch.object(objects.ComputeNode, 'get_by_host_and_nodename',
                       side_effect=exception.ComputeHostNotFound(host='host'))
    def test_remove_host_allocations_compute_host_not_found(self, get_cn):
        """Tests that failing to find a ComputeNode will not blow up
        the _remove_host_allocations method.
        """
        with mock.patch.object(
                self.task.scheduler_client.reportclient,
                'remove_provider_from_instance_allocation') as remove_provider:
            self.task._remove_host_allocations('host', 'node')
        remove_provider.assert_not_called()
