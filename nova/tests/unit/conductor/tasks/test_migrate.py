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

from nova.compute import rpcapi as compute_rpcapi
from nova.conductor.tasks import migrate
from nova import context
from nova import exception
from nova import objects
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests.unit.conductor.test_conductor import FakeContext
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids


class MigrationTaskTestCase(test.NoDBTestCase):
    def setUp(self):
        super(MigrationTaskTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = FakeContext(self.user_id, self.project_id)
        self.flavor = fake_flavor.fake_flavor_obj(self.context)
        self.flavor.extra_specs = {'extra_specs': 'fake'}
        inst = fake_instance.fake_db_instance(image_ref='image_ref',
                                              instance_type=self.flavor)
        inst_object = objects.Instance(
            flavor=self.flavor,
            numa_topology=None,
            pci_requests=None,
            system_metadata={'image_hw_disk_bus': 'scsi'})
        self.instance = objects.Instance._from_db_object(
            self.context, inst_object, inst, [])
        self.request_spec = objects.RequestSpec(image=objects.ImageMeta())
        self.host_lists = [[objects.Selection(service_host="host1",
                nodename="node1", cell_uuid=uuids.cell1)]]
        self.filter_properties = {'limits': {}, 'retry': {'num_attempts': 1,
                                  'hosts': [['host1', 'node1']]}}
        self.reservations = []
        self.clean_shutdown = True

        _p = mock.patch('nova.compute.utils.heal_reqspec_is_bfv')
        self.heal_reqspec_is_bfv_mock = _p.start()
        self.addCleanup(_p.stop)

        _p = mock.patch('nova.objects.RequestSpec.ensure_network_metadata')
        self.ensure_network_metadata_mock = _p.start()
        self.addCleanup(_p.stop)

    def _generate_task(self):
        return migrate.MigrationTask(self.context, self.instance, self.flavor,
                                     self.request_spec,
                                     self.clean_shutdown,
                                     compute_rpcapi.ComputeAPI(),
                                     scheduler_client.SchedulerClient(),
                                     host_list=None)

    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def test_execute_legacy_no_pre_create_migration(self, prep_resize_mock,
                                                    sel_dest_mock, sig_mock,
                                                    az_mock, gmv_mock):
        sel_dest_mock.return_value = self.host_lists
        az_mock.return_value = 'myaz'
        task = self._generate_task()
        legacy_request_spec = self.request_spec.to_legacy_request_spec_dict()
        gmv_mock.return_value = 22
        task.execute()

        sig_mock.assert_called_once_with(self.context, self.request_spec)
        task.scheduler_client.select_destinations.assert_called_once_with(
            self.context, self.request_spec, [self.instance.uuid],
            return_objects=True, return_alternates=True)
        selection = self.host_lists[0][0]
        prep_resize_mock.assert_called_once_with(
            self.context, self.instance, legacy_request_spec['image'],
            self.flavor, selection.service_host, None,
            request_spec=legacy_request_spec,
            filter_properties=self.filter_properties, node=selection.nodename,
            clean_shutdown=self.clean_shutdown, host_list=[])
        az_mock.assert_called_once_with(self.context, 'host1')
        self.assertIsNone(task._migration)

    @mock.patch.object(objects.MigrationList, 'get_by_filters')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.Migration.save')
    @mock.patch('nova.objects.Migration.create')
    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def _test_execute(self, prep_resize_mock, sel_dest_mock, sig_mock, az_mock,
                      gmv_mock, cm_mock, sm_mock, cn_mock, rc_mock, gbf_mock,
                      requested_destination=False):
        sel_dest_mock.return_value = self.host_lists
        az_mock.return_value = 'myaz'
        gbf_mock.return_value = objects.MigrationList()

        if requested_destination:
            self.request_spec.requested_destination = objects.Destination(
                host='target_host', node=None)
            self.request_spec.retry = objects.SchedulerRetries.from_dict(
                self.context, self.filter_properties['retry'])
            self.filter_properties.pop('retry')
            self.filter_properties['requested_destination'] = (
                self.request_spec.requested_destination)

        task = self._generate_task()
        legacy_request_spec = self.request_spec.to_legacy_request_spec_dict()
        gmv_mock.return_value = 23

        # We just need this hook point to set a uuid on the
        # migration before we use it for teardown
        def set_migration_uuid(*a, **k):
            task._migration.uuid = uuids.migration
            return mock.MagicMock()

        # NOTE(danms): It's odd to do this on cn_mock, but it's just because
        # of when we need to have it set in the flow and where we have an easy
        # place to find it via self.migration.
        cn_mock.side_effect = set_migration_uuid

        task.execute()

        self.ensure_network_metadata_mock.assert_called_once_with(
            self.instance)
        self.heal_reqspec_is_bfv_mock.assert_called_once_with(
            self.context, self.request_spec, self.instance)
        sig_mock.assert_called_once_with(self.context, self.request_spec)
        task.scheduler_client.select_destinations.assert_called_once_with(
            self.context, self.request_spec, [self.instance.uuid],
            return_objects=True, return_alternates=True)
        selection = self.host_lists[0][0]
        prep_resize_mock.assert_called_once_with(
            self.context, self.instance, legacy_request_spec['image'],
            self.flavor, selection.service_host, task._migration,
            request_spec=legacy_request_spec,
            filter_properties=self.filter_properties, node=selection.nodename,
            clean_shutdown=self.clean_shutdown, host_list=[])
        az_mock.assert_called_once_with(self.context, 'host1')
        self.assertIsNotNone(task._migration)

        old_flavor = self.instance.flavor
        new_flavor = self.flavor
        self.assertEqual(old_flavor.id, task._migration.old_instance_type_id)
        self.assertEqual(new_flavor.id, task._migration.new_instance_type_id)
        self.assertEqual('pre-migrating', task._migration.status)
        self.assertEqual(self.instance.uuid, task._migration.instance_uuid)
        self.assertEqual(self.instance.host, task._migration.source_compute)
        self.assertEqual(self.instance.node, task._migration.source_node)
        if old_flavor.id != new_flavor.id:
            self.assertEqual('resize', task._migration.migration_type)
        else:
            self.assertEqual('migration', task._migration.migration_type)

        task._migration.create.assert_called_once_with()

        if requested_destination:
            self.assertIsNone(self.request_spec.retry)
            self.assertIn('cell', self.request_spec.requested_destination)
            self.assertIsNotNone(self.request_spec.requested_destination.cell)

    def test_execute(self):
        self._test_execute()

    def test_execute_with_destination(self):
        self._test_execute(requested_destination=True)

    def test_execute_resize(self):
        self.flavor = self.flavor.obj_clone()
        self.flavor.id = 3
        self._test_execute()

    @mock.patch.object(objects.MigrationList, 'get_by_filters')
    @mock.patch('nova.conductor.tasks.migrate.revert_allocation_for_migration')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.Migration.save')
    @mock.patch('nova.objects.Migration.create')
    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def test_execute_rollback(self, prep_resize_mock, sel_dest_mock, sig_mock,
                              az_mock, gmv_mock, cm_mock, sm_mock, cn_mock,
                              rc_mock, mock_ra, mock_gbf):
        sel_dest_mock.return_value = self.host_lists
        az_mock.return_value = 'myaz'
        task = self._generate_task()
        gmv_mock.return_value = 23
        mock_gbf.return_value = objects.MigrationList()

        # We just need this hook point to set a uuid on the
        # migration before we use it for teardown
        def set_migration_uuid(*a, **k):
            task._migration.uuid = uuids.migration
            return mock.MagicMock()

        # NOTE(danms): It's odd to do this on cn_mock, but it's just because
        # of when we need to have it set in the flow and where we have an easy
        # place to find it via self.migration.
        cn_mock.side_effect = set_migration_uuid

        prep_resize_mock.side_effect = test.TestingException
        task._held_allocations = mock.sentinel.allocs
        self.assertRaises(test.TestingException, task.execute)
        self.assertIsNotNone(task._migration)
        task._migration.create.assert_called_once_with()
        task._migration.save.assert_called_once_with()
        self.assertEqual('error', task._migration.status)
        mock_ra.assert_called_once_with(task.context, task._source_cn,
                                        task.instance, task._migration,
                                        task._held_allocations)


class MigrationTaskAllocationUtils(test.NoDBTestCase):
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    def test_replace_allocation_with_migration_no_host(self, mock_cn):
        mock_cn.side_effect = exception.ComputeHostNotFound(host='host')
        migration = objects.Migration()
        instance = objects.Instance(host='host', node='node')

        self.assertRaises(exception.ComputeHostNotFound,
                          migrate.replace_allocation_with_migration,
                          mock.sentinel.context,
                          instance, migration)
        mock_cn.assert_called_once_with(mock.sentinel.context,
                                        instance.host, instance.node)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocations_for_consumer_by_provider')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    def test_replace_allocation_with_migration_no_allocs(self, mock_cn,
                                                         mock_ga):
        mock_ga.return_value = None
        migration = objects.Migration(uuid=uuids.migration)
        instance = objects.Instance(uuid=uuids.instance,
                                    host='host', node='node')

        result = migrate.replace_allocation_with_migration(
            mock.sentinel.context, instance, migration)
        self.assertEqual((None, None), result)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put_allocations')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocations_for_consumer_by_provider')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    def test_replace_allocation_with_migration_allocs_fail(self, mock_cn,
                                                           mock_ga, mock_pa):
        ctxt = context.get_admin_context()
        migration = objects.Migration(uuid=uuids.migration)
        instance = objects.Instance(uuid=uuids.instance,
                                    user_id='fake', project_id='fake',
                                    host='host', node='node')
        mock_pa.return_value = False

        self.assertRaises(exception.NoValidHost,
                          migrate.replace_allocation_with_migration,
                          ctxt,
                          instance, migration)
