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
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import rpcapi as compute_rpcapi
from nova.conductor.tasks import migrate
from nova import context
from nova import exception
from nova import objects
from nova.scheduler.client import query
from nova.scheduler.client import report
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests.unit.conductor.test_conductor import FakeContext
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance


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

        self.mock_network_api = mock.Mock()

    def _generate_task(self):
        return migrate.MigrationTask(self.context, self.instance, self.flavor,
                                     self.request_spec,
                                     self.clean_shutdown,
                                     compute_rpcapi.ComputeAPI(),
                                     query.SchedulerQueryClient(),
                                     report.SchedulerReportClient(),
                                     host_list=None,
                                     network_api=self.mock_network_api)

    @mock.patch.object(objects.MigrationList, 'get_by_filters')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.Migration.save')
    @mock.patch('nova.objects.Migration.create')
    @mock.patch('nova.objects.Service.get_minimum_version_multi')
    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def _test_execute(self, prep_resize_mock, sel_dest_mock, sig_mock, az_mock,
                      gmv_mock, cm_mock, sm_mock, cn_mock, rc_mock, gbf_mock,
                      requested_destination=False):
        sel_dest_mock.return_value = self.host_lists
        az_mock.return_value = 'myaz'
        gbf_mock.return_value = objects.MigrationList()
        mock_get_resources = \
            self.mock_network_api.get_requested_resource_for_instance
        mock_get_resources.return_value = []

        if requested_destination:
            self.request_spec.requested_destination = objects.Destination(
                host='target_host', node=None)
            self.request_spec.retry = objects.SchedulerRetries.from_dict(
                self.context, self.filter_properties['retry'])
            self.filter_properties.pop('retry')
            self.filter_properties['requested_destination'] = (
                self.request_spec.requested_destination)

        task = self._generate_task()
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

        selection = self.host_lists[0][0]
        with mock.patch.object(scheduler_utils,
                               'fill_provider_mapping') as fill_mock:
            task.execute()
            fill_mock.assert_called_once_with(
                task.context, task.reportclient, task.request_spec, selection)

        self.ensure_network_metadata_mock.assert_called_once_with(
            self.instance)
        self.heal_reqspec_is_bfv_mock.assert_called_once_with(
            self.context, self.request_spec, self.instance)
        sig_mock.assert_called_once_with(self.context, self.request_spec)
        task.query_client.select_destinations.assert_called_once_with(
            self.context, self.request_spec, [self.instance.uuid],
            return_objects=True, return_alternates=True)
        prep_resize_mock.assert_called_once_with(
            self.context, self.instance, self.request_spec.image,
            self.flavor, selection.service_host, task._migration,
            request_spec=self.request_spec,
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

        mock_get_resources.assert_called_once_with(
            self.context, self.instance.uuid)
        self.assertEqual([], self.request_spec.requested_resources)

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
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def test_execute_rollback(self, prep_resize_mock, sel_dest_mock, sig_mock,
                              az_mock, gmv_mock, cm_mock, sm_mock, cn_mock,
                              rc_mock, mock_ra, mock_gbf):
        sel_dest_mock.return_value = self.host_lists
        az_mock.return_value = 'myaz'
        task = self._generate_task()
        gmv_mock.return_value = 23
        mock_gbf.return_value = objects.MigrationList()
        mock_get_resources = \
            self.mock_network_api.get_requested_resource_for_instance
        mock_get_resources.return_value = []

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
                                        task.instance, task._migration)
        mock_get_resources.assert_called_once_with(
            self.context, self.instance.uuid)

    @mock.patch.object(scheduler_utils, 'fill_provider_mapping')
    @mock.patch.object(scheduler_utils, 'claim_resources')
    @mock.patch.object(context.RequestContext, 'elevated')
    def test_execute_reschedule(
            self, mock_elevated, mock_claim, mock_fill_provider_mapping):
        report_client = report.SchedulerReportClient()
        # setup task for re-schedule
        alloc_req = {
            "allocations": {
                uuids.host1: {
                    "resources": {
                        "VCPU": 1,
                        "MEMORY_MB": 1024,
                        "DISK_GB": 100}}}}
        alternate_selection = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(alloc_req),
            allocation_request_version='1.19')
        task = migrate.MigrationTask(
            self.context, self.instance, self.flavor, self.request_spec,
            self.clean_shutdown, compute_rpcapi.ComputeAPI(),
            query.SchedulerQueryClient(), report_client,
            host_list=[alternate_selection], network_api=self.mock_network_api)
        mock_claim.return_value = True

        actual_selection = task._reschedule()

        self.assertIs(alternate_selection, actual_selection)
        mock_claim.assert_called_once_with(
            mock_elevated.return_value, report_client, self.request_spec,
            self.instance.uuid, alloc_req, '1.19')
        mock_fill_provider_mapping.assert_called_once_with(
            self.context, report_client, self.request_spec,
            alternate_selection)

    @mock.patch.object(scheduler_utils, 'fill_provider_mapping')
    @mock.patch.object(scheduler_utils, 'claim_resources')
    @mock.patch.object(context.RequestContext, 'elevated')
    def test_execute_reschedule_claim_fails_no_more_alternate(
            self, mock_elevated, mock_claim, mock_fill_provider_mapping):
        report_client = report.SchedulerReportClient()
        # set up the task for re-schedule
        alloc_req = {
            "allocations": {
                uuids.host1: {
                    "resources": {
                        "VCPU": 1,
                        "MEMORY_MB": 1024,
                        "DISK_GB": 100}}}}
        alternate_selection = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(alloc_req),
            allocation_request_version='1.19')
        task = migrate.MigrationTask(
            self.context, self.instance, self.flavor, self.request_spec,
            self.clean_shutdown, compute_rpcapi.ComputeAPI(),
            query.SchedulerQueryClient(), report_client,
            host_list=[alternate_selection], network_api=self.mock_network_api)
        mock_claim.return_value = False

        self.assertRaises(exception.MaxRetriesExceeded, task._reschedule)

        mock_claim.assert_called_once_with(
            mock_elevated.return_value, report_client, self.request_spec,
            self.instance.uuid, alloc_req, '1.19')
        mock_fill_provider_mapping.assert_not_called()

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_allocation_for_instance')
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_get_host_supporting_request_no_resource_request(
            self, mock_get_service, mock_delete_allocation,
            mock_claim_resources):
        # no resource request so we expect the first host is simply returned
        self.request_spec.requested_resources = []
        task = self._generate_task()
        resources = {
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 100}}

        first = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host1: resources}}),
            allocation_request_version='1.19')
        alternate = objects.Selection(
            service_host="host2",
            nodename="node2",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host2: resources}}),
            allocation_request_version='1.19')
        selection_list = [first, alternate]

        selected, alternates = task._get_host_supporting_request(
            selection_list)

        self.assertEqual(first, selected)
        self.assertEqual([alternate], alternates)
        mock_get_service.assert_not_called()
        # The first host was good and the scheduler made allocation on that
        # host. So we don't expect any resource claim manipulation
        mock_delete_allocation.assert_not_called()
        mock_claim_resources.assert_not_called()

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_allocation_for_instance')
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_get_host_supporting_request_first_host_is_new(
            self, mock_get_service, mock_delete_allocation,
            mock_claim_resources):
        self.request_spec.requested_resources = [
            objects.RequestGroup()
        ]
        task = self._generate_task()
        resources = {
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 100}}

        first = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host1: resources}}),
            allocation_request_version='1.19')
        alternate = objects.Selection(
            service_host="host2",
            nodename="node2",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host2: resources}}),
            allocation_request_version='1.19')
        selection_list = [first, alternate]

        first_service = objects.Service(service_host='host1')
        first_service.version = 39
        mock_get_service.return_value = first_service

        selected, alternates = task._get_host_supporting_request(
            selection_list)

        self.assertEqual(first, selected)
        self.assertEqual([alternate], alternates)
        mock_get_service.assert_called_once_with(
            task.context, 'host1', 'nova-compute')
        # The first host was good and the scheduler made allocation on that
        # host. So we don't expect any resource claim manipulation
        mock_delete_allocation.assert_not_called()
        mock_claim_resources.assert_not_called()

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_allocation_for_instance')
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_get_host_supporting_request_first_host_is_old_no_alternates(
            self, mock_get_service, mock_delete_allocation,
            mock_claim_resources):
        self.request_spec.requested_resources = [
            objects.RequestGroup()
        ]
        task = self._generate_task()
        resources = {
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 100}}

        first = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host1: resources}}),
            allocation_request_version='1.19')
        selection_list = [first]

        first_service = objects.Service(service_host='host1')
        first_service.version = 38
        mock_get_service.return_value = first_service

        self.assertRaises(
            exception.MaxRetriesExceeded, task._get_host_supporting_request,
            selection_list)

        mock_get_service.assert_called_once_with(
            task.context, 'host1', 'nova-compute')
        mock_delete_allocation.assert_called_once_with(
            task.context, self.instance.uuid)
        mock_claim_resources.assert_not_called()

    @mock.patch.object(migrate.LOG, 'debug')
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_allocation_for_instance')
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_get_host_supporting_request_first_host_is_old_second_good(
            self, mock_get_service, mock_delete_allocation,
            mock_claim_resources, mock_debug):

        self.request_spec.requested_resources = [
            objects.RequestGroup()
        ]
        task = self._generate_task()
        resources = {
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 100}}

        first = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host1: resources}}),
            allocation_request_version='1.19')
        second = objects.Selection(
            service_host="host2",
            nodename="node2",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host2: resources}}),
            allocation_request_version='1.19')
        third = objects.Selection(
            service_host="host3",
            nodename="node3",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host3: resources}}),
            allocation_request_version='1.19')
        selection_list = [first, second, third]

        first_service = objects.Service(service_host='host1')
        first_service.version = 38
        second_service = objects.Service(service_host='host2')
        second_service.version = 39
        mock_get_service.side_effect = [first_service, second_service]

        selected, alternates = task._get_host_supporting_request(
            selection_list)

        self.assertEqual(second, selected)
        self.assertEqual([third], alternates)
        mock_get_service.assert_has_calls([
            mock.call(task.context, 'host1', 'nova-compute'),
            mock.call(task.context, 'host2', 'nova-compute'),
        ])
        mock_delete_allocation.assert_called_once_with(
            task.context, self.instance.uuid)
        mock_claim_resources.assert_called_once_with(
            self.context, task.reportclient, task.request_spec,
            self.instance.uuid, {"allocations": {uuids.host2: resources}},
            '1.19')

        mock_debug.assert_called_once_with(
            'Scheduler returned host %(host)s as a possible migration target '
            'but that host is not new enough to support the migration with '
            'resource request %(request)s or the compute RPC is pinned to '
            'less than 5.2. Trying alternate hosts.',
            {'host': 'host1',
             'request': self.request_spec.requested_resources},
            instance=self.instance)

    @mock.patch.object(migrate.LOG, 'debug')
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_allocation_for_instance')
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_get_host_supporting_request_first_host_is_old_second_claim_fails(
            self, mock_get_service, mock_delete_allocation,
            mock_claim_resources, mock_debug):
        self.request_spec.requested_resources = [
            objects.RequestGroup()
        ]
        task = self._generate_task()
        resources = {
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 100}}

        first = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host1: resources}}),
            allocation_request_version='1.19')
        second = objects.Selection(
            service_host="host2",
            nodename="node2",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host2: resources}}),
            allocation_request_version='1.19')
        third = objects.Selection(
            service_host="host3",
            nodename="node3",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host3: resources}}),
            allocation_request_version='1.19')
        fourth = objects.Selection(
            service_host="host4",
            nodename="node4",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host4: resources}}),
            allocation_request_version='1.19')
        selection_list = [first, second, third, fourth]

        first_service = objects.Service(service_host='host1')
        first_service.version = 38
        second_service = objects.Service(service_host='host2')
        second_service.version = 39
        third_service = objects.Service(service_host='host3')
        third_service.version = 39
        mock_get_service.side_effect = [
            first_service, second_service, third_service]
        # not called for the first host but called for the second and third
        # make the second claim fail to force the selection of the third
        mock_claim_resources.side_effect = [False, True]

        selected, alternates = task._get_host_supporting_request(
            selection_list)

        self.assertEqual(third, selected)
        self.assertEqual([fourth], alternates)
        mock_get_service.assert_has_calls([
            mock.call(task.context, 'host1', 'nova-compute'),
            mock.call(task.context, 'host2', 'nova-compute'),
            mock.call(task.context, 'host3', 'nova-compute'),
        ])
        mock_delete_allocation.assert_called_once_with(
            task.context, self.instance.uuid)
        mock_claim_resources.assert_has_calls([
            mock.call(
                self.context, task.reportclient, task.request_spec,
                self.instance.uuid,
                {"allocations": {uuids.host2: resources}}, '1.19'),
            mock.call(
                self.context, task.reportclient, task.request_spec,
                self.instance.uuid,
                {"allocations": {uuids.host3: resources}}, '1.19'),
        ])
        mock_debug.assert_has_calls([
            mock.call(
                'Scheduler returned host %(host)s as a possible migration '
                'target but that host is not new enough to support the '
                'migration with resource request %(request)s or the compute '
                'RPC is pinned to less than 5.2. Trying alternate hosts.',
                {'host': 'host1',
                 'request': self.request_spec.requested_resources},
                instance=self.instance),
            mock.call(
                'Scheduler returned alternate host %(host)s as a possible '
                'migration target but resource claim '
                'failed on that host. Trying another alternate.',
                {'host': 'host2'},
                instance=self.instance),
        ])

    @mock.patch.object(migrate.LOG, 'debug')
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_allocation_for_instance')
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_get_host_supporting_request_both_first_and_second_too_old(
            self, mock_get_service, mock_delete_allocation,
            mock_claim_resources, mock_debug):
        self.request_spec.requested_resources = [
            objects.RequestGroup()
        ]
        task = self._generate_task()
        resources = {
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 100}}

        first = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host1: resources}}),
            allocation_request_version='1.19')
        second = objects.Selection(
            service_host="host2",
            nodename="node2",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host2: resources}}),
            allocation_request_version='1.19')
        third = objects.Selection(
            service_host="host3",
            nodename="node3",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host3: resources}}),
            allocation_request_version='1.19')
        fourth = objects.Selection(
            service_host="host4",
            nodename="node4",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host4: resources}}),
            allocation_request_version='1.19')
        selection_list = [first, second, third, fourth]

        first_service = objects.Service(service_host='host1')
        first_service.version = 38
        second_service = objects.Service(service_host='host2')
        second_service.version = 38
        third_service = objects.Service(service_host='host3')
        third_service.version = 39
        mock_get_service.side_effect = [
            first_service, second_service, third_service]
        # not called for the first and second hosts but called for the third
        mock_claim_resources.side_effect = [True]

        selected, alternates = task._get_host_supporting_request(
            selection_list)

        self.assertEqual(third, selected)
        self.assertEqual([fourth], alternates)
        mock_get_service.assert_has_calls([
            mock.call(task.context, 'host1', 'nova-compute'),
            mock.call(task.context, 'host2', 'nova-compute'),
            mock.call(task.context, 'host3', 'nova-compute'),
        ])
        mock_delete_allocation.assert_called_once_with(
            task.context, self.instance.uuid)
        mock_claim_resources.assert_called_once_with(
            self.context, task.reportclient, task.request_spec,
            self.instance.uuid,
            {"allocations": {uuids.host3: resources}}, '1.19')
        mock_debug.assert_has_calls([
            mock.call(
                'Scheduler returned host %(host)s as a possible migration '
                'target but that host is not new enough to support the '
                'migration with resource request %(request)s or the compute '
                'RPC is pinned to less than 5.2. Trying alternate hosts.',
                {'host': 'host1',
                 'request': self.request_spec.requested_resources},
                instance=self.instance),
            mock.call(
                'Scheduler returned alternate host %(host)s as a possible '
                'migration target but that host is not new enough to support '
                'the migration with resource request %(request)s or the '
                'compute RPC is pinned to less than 5.2. Trying another '
                'alternate.',
                {'host': 'host2',
                 'request': self.request_spec.requested_resources},
                instance=self.instance),
        ])

    @mock.patch.object(migrate.LOG, 'debug')
    @mock.patch('nova.scheduler.utils.fill_provider_mapping')
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_reschedule_old_compute_skipped(
            self, mock_get_service, mock_claim_resources, mock_fill_mapping,
            mock_debug):
        self.request_spec.requested_resources = [
            objects.RequestGroup()
        ]
        task = self._generate_task()
        resources = {
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 100}}

        first = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host1: resources}}),
            allocation_request_version='1.19')
        second = objects.Selection(
            service_host="host2",
            nodename="node2",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host2: resources}}),
            allocation_request_version='1.19')

        first_service = objects.Service(service_host='host1')
        first_service.version = 38
        second_service = objects.Service(service_host='host2')
        second_service.version = 39
        mock_get_service.side_effect = [first_service, second_service]

        # set up task for re-schedule
        task.host_list = [first, second]

        selected = task._reschedule()

        self.assertEqual(second, selected)
        self.assertEqual([], task.host_list)
        mock_get_service.assert_has_calls([
            mock.call(task.context, 'host1', 'nova-compute'),
            mock.call(task.context, 'host2', 'nova-compute'),
        ])
        mock_claim_resources.assert_called_once_with(
            self.context.elevated(), task.reportclient, task.request_spec,
            self.instance.uuid,
            {"allocations": {uuids.host2: resources}}, '1.19')
        mock_fill_mapping.assert_called_once_with(
            task.context, task.reportclient, task.request_spec, second)
        mock_debug.assert_has_calls([
            mock.call(
                'Scheduler returned alternate host %(host)s as a possible '
                'migration target for re-schedule but that host is not '
                'new enough to support the migration with resource '
                'request %(request)s. Trying another alternate.',
                {'host': 'host1',
                 'request': self.request_spec.requested_resources},
                instance=self.instance),
        ])

    @mock.patch.object(migrate.LOG, 'debug')
    @mock.patch('nova.scheduler.utils.fill_provider_mapping')
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    def test_reschedule_old_computes_no_more_alternates(
            self, mock_get_service, mock_claim_resources, mock_fill_mapping,
            mock_debug):
        self.request_spec.requested_resources = [
            objects.RequestGroup()
        ]
        task = self._generate_task()
        resources = {
            "resources": {
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 100}}

        first = objects.Selection(
            service_host="host1",
            nodename="node1",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host1: resources}}),
            allocation_request_version='1.19')
        second = objects.Selection(
            service_host="host2",
            nodename="node2",
            cell_uuid=uuids.cell1,
            allocation_request=jsonutils.dumps(
                {"allocations": {uuids.host2: resources}}),
            allocation_request_version='1.19')

        first_service = objects.Service(service_host='host1')
        first_service.version = 38
        second_service = objects.Service(service_host='host2')
        second_service.version = 38
        mock_get_service.side_effect = [first_service, second_service]

        # set up task for re-schedule
        task.host_list = [first, second]

        self.assertRaises(exception.MaxRetriesExceeded, task._reschedule)

        self.assertEqual([], task.host_list)
        mock_get_service.assert_has_calls([
            mock.call(task.context, 'host1', 'nova-compute'),
            mock.call(task.context, 'host2', 'nova-compute'),
        ])
        mock_claim_resources.assert_not_called()
        mock_fill_mapping.assert_not_called()
        mock_debug.assert_has_calls([
            mock.call(
                'Scheduler returned alternate host %(host)s as a possible '
                'migration target for re-schedule but that host is not '
                'new enough to support the migration with resource '
                'request %(request)s. Trying another alternate.',
                {'host': 'host1',
                 'request': self.request_spec.requested_resources},
                instance=self.instance),
            mock.call(
                'Scheduler returned alternate host %(host)s as a possible '
                'migration target for re-schedule but that host is not '
                'new enough to support the migration with resource '
                'request %(request)s. Trying another alternate.',
                {'host': 'host2',
                 'request': self.request_spec.requested_resources},
                instance=self.instance),
        ])


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
                'get_allocs_for_consumer')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    def test_replace_allocation_with_migration_no_allocs(self, mock_cn,
                                                         mock_ga):
        mock_ga.return_value = {'allocations': {}}
        migration = objects.Migration(uuid=uuids.migration)
        instance = objects.Instance(uuid=uuids.instance,
                                    host='host', node='node')

        result = migrate.replace_allocation_with_migration(
            mock.sentinel.context, instance, migration)
        self.assertEqual((None, None), result)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put_allocations')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocs_for_consumer')
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
