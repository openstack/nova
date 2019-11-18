# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

import fixtures
import mock
import oslo_messaging as messaging
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import services
from nova.compute import api as compute
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_notifier
from nova.tests.unit.objects import test_objects
from nova.tests.unit.objects import test_service


class ComputeHostAPITestCase(test.TestCase):
    def setUp(self):
        super(ComputeHostAPITestCase, self).setUp()
        self.host_api = compute.HostAPI()
        self.aggregate_api = compute.AggregateAPI()
        self.ctxt = context.get_admin_context()
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)
        self.req = fakes.HTTPRequest.blank('')
        self.controller = services.ServiceController()
        self.useFixture(nova_fixtures.SingleCellSimple())

    def _compare_obj(self, obj, db_obj):
        test_objects.compare_obj(self, obj, db_obj,
                                 allow_missing=test_service.OPTIONAL)

    def _compare_objs(self, obj_list, db_obj_list):
        self.assertEqual(len(obj_list), len(db_obj_list),
                         "The length of two object lists are different.")
        for index, obj in enumerate(obj_list):
            self._compare_obj(obj, db_obj_list[index])

    def test_set_host_enabled(self):
        fake_notifier.NOTIFICATIONS = []

        @mock.patch.object(self.host_api.rpcapi, 'set_host_enabled',
                           return_value='fake-result')
        @mock.patch.object(self.host_api, '_assert_host_exists',
                           return_value='fake_host')
        def _do_test(mock_assert_host_exists, mock_set_host_enabled):
            result = self.host_api.set_host_enabled(self.ctxt, 'fake_host',
                                                    'fake_enabled')
            self.assertEqual('fake-result', result)
            self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
            msg = fake_notifier.NOTIFICATIONS[0]
            self.assertEqual('HostAPI.set_enabled.start', msg.event_type)
            self.assertEqual('api.fake_host', msg.publisher_id)
            self.assertEqual('INFO', msg.priority)
            self.assertEqual('fake_enabled', msg.payload['enabled'])
            self.assertEqual('fake_host', msg.payload['host_name'])
            msg = fake_notifier.NOTIFICATIONS[1]
            self.assertEqual('HostAPI.set_enabled.end', msg.event_type)
            self.assertEqual('api.fake_host', msg.publisher_id)
            self.assertEqual('INFO', msg.priority)
            self.assertEqual('fake_enabled', msg.payload['enabled'])
            self.assertEqual('fake_host', msg.payload['host_name'])

        _do_test()

    def test_host_name_from_assert_hosts_exists(self):
        @mock.patch.object(self.host_api.rpcapi, 'set_host_enabled',
                           return_value='fake-result')
        @mock.patch.object(self.host_api, '_assert_host_exists',
                           return_value='fake_host')
        def _do_test(mock_assert_host_exists, mock_set_host_enabled):
            result = self.host_api.set_host_enabled(self.ctxt, 'fake_host',
                                                    'fake_enabled')
            self.assertEqual('fake-result', result)

        _do_test()

    def test_get_host_uptime(self):
        @mock.patch.object(self.host_api.rpcapi, 'get_host_uptime',
                           return_value='fake-result')
        @mock.patch.object(self.host_api, '_assert_host_exists',
                           return_value='fake_host')
        def _do_test(mock_assert_host_exists, mock_get_host_uptime):
            result = self.host_api.get_host_uptime(self.ctxt, 'fake_host')
            self.assertEqual('fake-result', result)

        _do_test()

    def test_get_host_uptime_service_down(self):
        @mock.patch.object(self.host_api.db, 'service_get_by_compute_host',
                           return_value=dict(test_service.fake_service, id=1))
        @mock.patch.object(self.host_api.servicegroup_api, 'service_is_up',
                           return_value=False)
        def _do_test(mock_service_is_up, mock_service_get_by_compute_host):
            self.assertRaises(exception.ComputeServiceUnavailable,
                              self.host_api.get_host_uptime, self.ctxt,
                              'fake_host')

        _do_test()

    def test_host_power_action(self):
        fake_notifier.NOTIFICATIONS = []

        @mock.patch.object(self.host_api.rpcapi, 'host_power_action',
                           return_value='fake-result')
        @mock.patch.object(self.host_api, '_assert_host_exists',
                           return_value='fake_host')
        def _do_test(mock_assert_host_exists, mock_host_power_action):
            result = self.host_api.host_power_action(self.ctxt, 'fake_host',
                                                     'fake_action')
            self.assertEqual('fake-result', result)
            self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
            msg = fake_notifier.NOTIFICATIONS[0]
            self.assertEqual('HostAPI.power_action.start', msg.event_type)
            self.assertEqual('api.fake_host', msg.publisher_id)
            self.assertEqual('INFO', msg.priority)
            self.assertEqual('fake_action', msg.payload['action'])
            self.assertEqual('fake_host', msg.payload['host_name'])
            msg = fake_notifier.NOTIFICATIONS[1]
            self.assertEqual('HostAPI.power_action.end', msg.event_type)
            self.assertEqual('api.fake_host', msg.publisher_id)
            self.assertEqual('INFO', msg.priority)
            self.assertEqual('fake_action', msg.payload['action'])
            self.assertEqual('fake_host', msg.payload['host_name'])

        _do_test()

    def test_set_host_maintenance(self):
        fake_notifier.NOTIFICATIONS = []

        @mock.patch.object(self.host_api.rpcapi, 'host_maintenance_mode',
                           return_value='fake-result')
        @mock.patch.object(self.host_api, '_assert_host_exists',
                           return_value='fake_host')
        def _do_test(mock_assert_host_exists, mock_host_maintenance_mode):
            result = self.host_api.set_host_maintenance(self.ctxt, 'fake_host',
                                                        'fake_mode')
            self.assertEqual('fake-result', result)
            self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
            msg = fake_notifier.NOTIFICATIONS[0]
            self.assertEqual('HostAPI.set_maintenance.start', msg.event_type)
            self.assertEqual('api.fake_host', msg.publisher_id)
            self.assertEqual('INFO', msg.priority)
            self.assertEqual('fake_host', msg.payload['host_name'])
            self.assertEqual('fake_mode', msg.payload['mode'])
            msg = fake_notifier.NOTIFICATIONS[1]
            self.assertEqual('HostAPI.set_maintenance.end', msg.event_type)
            self.assertEqual('api.fake_host', msg.publisher_id)
            self.assertEqual('INFO', msg.priority)
            self.assertEqual('fake_host', msg.payload['host_name'])
            self.assertEqual('fake_mode', msg.payload['mode'])

        _do_test()

    def test_service_get_all_cells(self):
        cells = objects.CellMappingList.get_all(self.ctxt)
        for cell in cells:
            with context.target_cell(self.ctxt, cell) as cctxt:
                objects.Service(context=cctxt,
                                binary='nova-compute',
                                host='host-%s' % cell.uuid).create()
        services = self.host_api.service_get_all(self.ctxt, all_cells=True)
        self.assertEqual(sorted(['host-%s' % cell.uuid for cell in cells]),
                         sorted([svc.host for svc in services]))

    @mock.patch('nova.context.scatter_gather_cells')
    def test_service_get_all_cells_with_failures(self, mock_sg):
        service = objects.Service(binary='nova-compute',
                                  host='host-%s' % uuids.cell1)
        mock_sg.return_value = {
            uuids.cell1: [service],
            uuids.cell2: context.did_not_respond_sentinel
        }
        services = self.host_api.service_get_all(self.ctxt, all_cells=True)
        # returns the results from cell1 and ignores cell2.
        self.assertEqual(['host-%s' % uuids.cell1],
                         [svc.host for svc in services])

    @mock.patch('nova.objects.CellMappingList.get_all')
    @mock.patch.object(objects.HostMappingList, 'get_by_cell_id')
    @mock.patch('nova.context.scatter_gather_all_cells')
    def test_service_get_all_cells_with_minimal_constructs(self, mock_sg,
                                                           mock_get_hm,
                                                           mock_cm_list):
        service = objects.Service(binary='nova-compute',
                                  host='host-%s' % uuids.cell0)
        cells = [
            objects.CellMapping(uuid=uuids.cell1, id=1),
            objects.CellMapping(uuid=uuids.cell2, id=2),
        ]
        mock_cm_list.return_value = cells
        context.load_cells()
        # create two hms in cell1, which is the down cell in this test.
        hm1 = objects.HostMapping(self.ctxt, host='host1-unavailable',
            cell_mapping=cells[0])
        hm1.create()
        hm2 = objects.HostMapping(self.ctxt, host='host2-unavailable',
            cell_mapping=cells[0])
        hm2.create()
        mock_sg.return_value = {
            cells[0].uuid: [service],
            cells[1].uuid: context.did_not_respond_sentinel,
        }
        mock_get_hm.return_value = [hm1, hm2]
        services = self.host_api.service_get_all(self.ctxt, all_cells=True,
            cell_down_support=True)
        # returns the results from cell0 and minimal construct from cell1.
        self.assertEqual(sorted(['host-%s' % uuids.cell0, 'host1-unavailable',
                         'host2-unavailable']),
                         sorted([svc.host for svc in services]))
        mock_sg.assert_called_once_with(self.ctxt, objects.ServiceList.get_all,
                                        None, set_zones=False)
        mock_get_hm.assert_called_once_with(self.ctxt, cells[1].id)

    def test_service_get_all_no_zones(self):
        services = [dict(test_service.fake_service,
                         id=1, topic='compute', host='host1'),
                    dict(test_service.fake_service,
                         topic='compute', host='host2')]

        @mock.patch.object(self.host_api.db, 'service_get_all')
        def _do_test(mock_service_get_all):
            mock_service_get_all.return_value = services
            # Test no filters
            result = self.host_api.service_get_all(self.ctxt)
            mock_service_get_all.assert_called_once_with(self.ctxt,
                                                         disabled=None)
            self._compare_objs(result, services)

            # Test no filters #2
            mock_service_get_all.reset_mock()
            result = self.host_api.service_get_all(self.ctxt, filters={})
            mock_service_get_all.assert_called_once_with(self.ctxt,
                                                         disabled=None)
            self._compare_objs(result, services)

            # Test w/ filter
            mock_service_get_all.reset_mock()
            result = self.host_api.service_get_all(self.ctxt,
                                                   filters=dict(host='host2'))
            mock_service_get_all.assert_called_once_with(self.ctxt,
                                                         disabled=None)
            self._compare_objs(result, [services[1]])

        _do_test()

    def test_service_get_all(self):
        services = [dict(test_service.fake_service,
                         topic='compute', host='host1'),
                    dict(test_service.fake_service,
                         topic='compute', host='host2')]
        exp_services = []
        for service in services:
            exp_service = {}
            exp_service.update(availability_zone='nova', **service)
            exp_services.append(exp_service)

        @mock.patch.object(self.host_api.db, 'service_get_all')
        def _do_test(mock_service_get_all):
            mock_service_get_all.return_value = services

            # Test no filters
            result = self.host_api.service_get_all(self.ctxt, set_zones=True)
            mock_service_get_all.assert_called_once_with(self.ctxt,
                                                         disabled=None)
            self._compare_objs(result, exp_services)

            # Test no filters #2
            mock_service_get_all.reset_mock()
            result = self.host_api.service_get_all(self.ctxt, filters={},
                                                   set_zones=True)
            mock_service_get_all.assert_called_once_with(self.ctxt,
                                                         disabled=None)
            self._compare_objs(result, exp_services)

            # Test w/ filter
            mock_service_get_all.reset_mock()
            result = self.host_api.service_get_all(self.ctxt,
                                                   filters=dict(host='host2'),
                                                   set_zones=True)
            mock_service_get_all.assert_called_once_with(self.ctxt,
                                                         disabled=None)
            self._compare_objs(result, [exp_services[1]])

            # Test w/ zone filter but no set_zones arg.
            mock_service_get_all.reset_mock()
            filters = {'availability_zone': 'nova'}
            result = self.host_api.service_get_all(self.ctxt,
                                                   filters=filters)
            mock_service_get_all.assert_called_once_with(self.ctxt,
                                                         disabled=None)
            self._compare_objs(result, exp_services)

        _do_test()

    def test_service_get_by_compute_host(self):
        @mock.patch.object(self.host_api.db, 'service_get_by_compute_host',
                           return_value=test_service.fake_service)
        def _do_test(mock_service_get_by_compute_host):
            result = self.host_api.service_get_by_compute_host(self.ctxt,
                                                               'fake-host')
            self.assertEqual(test_service.fake_service['id'], result.id)

        _do_test()

    def test_service_update_by_host_and_binary(self):
        host_name = 'fake-host'
        binary = 'nova-compute'
        params_to_update = dict(disabled=True)
        service_id = 42
        expected_result = dict(test_service.fake_service, id=service_id)

        @mock.patch.object(self.host_api, '_update_compute_provider_status')
        @mock.patch.object(self.host_api.db, 'service_get_by_host_and_binary')
        @mock.patch.object(self.host_api.db, 'service_update')
        def _do_test(mock_service_update, mock_service_get_by_host_and_binary,
                     mock_update_compute_provider_status):
            mock_service_get_by_host_and_binary.return_value = expected_result
            mock_service_update.return_value = expected_result

            result = self.host_api.service_update_by_host_and_binary(
                self.ctxt, host_name, binary, params_to_update)
            self._compare_obj(result, expected_result)
            mock_update_compute_provider_status.assert_called_once_with(
                self.ctxt, test.MatchType(objects.Service))

        _do_test()

    @mock.patch('nova.compute.api.HostAPI._update_compute_provider_status',
                new_callable=mock.NonCallableMock)
    def test_service_update_no_update_provider_status(self, mock_ucps):
        """Tests the scenario that the service is updated but the disabled
        field is not changed, for example the forced_down field is only
        updated. In this case _update_compute_provider_status should not be
        called.
        """
        service = objects.Service(forced_down=True)
        self.assertIn('forced_down', service.obj_what_changed())
        with mock.patch.object(service, 'save') as mock_save:
            retval = self.host_api.service_update(self.ctxt, service)
            self.assertIs(retval, service)
            mock_save.assert_called_once_with()

    @mock.patch('nova.compute.rpcapi.ComputeAPI.set_host_enabled',
                new_callable=mock.NonCallableMock)
    def test_update_compute_provider_status_service_too_old(self, mock_she):
        """Tests the scenario that the service is up but is too old to sync the
        COMPUTE_STATUS_DISABLED trait.
        """
        service = objects.Service(host='fake-host')
        service.version = compute.MIN_COMPUTE_SYNC_COMPUTE_STATUS_DISABLED - 1
        with mock.patch.object(
                self.host_api.servicegroup_api, 'service_is_up',
                return_value=True) as service_is_up:
            self.host_api._update_compute_provider_status(self.ctxt, service)
            service_is_up.assert_called_once_with(service)
        self.assertIn('Compute service on host fake-host is too old to sync '
                      'the COMPUTE_STATUS_DISABLED trait in Placement.',
                      self.stdlog.logger.output)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.set_host_enabled',
                side_effect=messaging.MessagingTimeout)
    def test_update_compute_provider_status_service_rpc_error(self, mock_she):
        """Tests the scenario that the RPC call to the compute service raised
        some exception.
        """
        service = objects.Service(host='fake-host', disabled=True)
        with mock.patch.object(
                self.host_api.servicegroup_api, 'service_is_up',
                return_value=True) as service_is_up:
            self.host_api._update_compute_provider_status(self.ctxt, service)
            service_is_up.assert_called_once_with(service)
        mock_she.assert_called_once_with(self.ctxt, 'fake-host', False)
        log_output = self.stdlog.logger.output
        self.assertIn('An error occurred while updating the '
                      'COMPUTE_STATUS_DISABLED trait on compute node '
                      'resource providers managed by host fake-host.',
                      log_output)
        self.assertIn('MessagingTimeout', log_output)

    @mock.patch.object(objects.InstanceList, 'get_by_host',
                       return_value = ['fake-responses'])
    def test_instance_get_all_by_host(self, mock_get):
        result = self.host_api.instance_get_all_by_host(self.ctxt,
                                                        'fake-host')
        self.assertEqual(['fake-responses'], result)

    def test_task_log_get_all(self):
        @mock.patch.object(self.host_api.db, 'task_log_get_all',
                           return_value='fake-response')
        def _do_test(mock_task_log_get_all):
            result = self.host_api.task_log_get_all(self.ctxt, 'fake-name',
                                                    'fake-begin', 'fake-end',
                                                    host='fake-host',
                                                    state='fake-state')
            self.assertEqual('fake-response', result)

        _do_test()

    @mock.patch.object(objects.CellMappingList, 'get_all',
                       return_value=objects.CellMappingList(objects=[
                           objects.CellMapping(
                               uuid=uuids.cell1_uuid,
                               transport_url='mq://fake1',
                               database_connection='db://fake1'),
                           objects.CellMapping(
                               uuid=uuids.cell2_uuid,
                               transport_url='mq://fake2',
                               database_connection='db://fake2'),
                           objects.CellMapping(
                               uuid=uuids.cell3_uuid,
                               transport_url='mq://fake3',
                               database_connection='db://fake3')]))
    @mock.patch.object(objects.Service, 'get_by_uuid',
                       side_effect=[
                           exception.ServiceNotFound(
                               service_id=uuids.service_uuid),
                           objects.Service(uuid=uuids.service_uuid)])
    def test_service_get_by_id_using_uuid(self, service_get_by_uuid,
                                          cell_mappings_get_all):
        """Tests that we can lookup a service in the HostAPI using a uuid.
        There are two calls to objects.Service.get_by_uuid and the first
        raises ServiceNotFound so that we ensure we keep looping over the
        cells. We'll find the service in the second cell and break the loop
        so that we don't needlessly check in the third cell.
        """

        def _fake_set_target_cell(ctxt, cell_mapping):
            if cell_mapping:
                # These aren't really what would be set for values but let's
                # keep this simple so we can assert something is set when a
                # mapping is provided.
                ctxt.db_connection = cell_mapping.database_connection
                ctxt.mq_connection = cell_mapping.transport_url

        # We have to override the SingleCellSimple fixture.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.set_target_cell', _fake_set_target_cell))
        ctxt = context.get_admin_context()
        self.assertIsNone(ctxt.db_connection)
        self.host_api.service_get_by_id(ctxt, uuids.service_uuid)
        # We should have broken the loop over the cells and set the target cell
        # on the context.
        service_get_by_uuid.assert_has_calls(
            [mock.call(ctxt, uuids.service_uuid)] * 2)
        self.assertEqual('db://fake2', ctxt.db_connection)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_remove_host')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_add_host')
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    @mock.patch.object(objects.HostMapping, 'get_by_host')
    def test_service_delete_compute_in_aggregate(
            self, mock_hm, mock_get_cn, mock_add_host, mock_remove_host):
        compute = objects.Service(self.ctxt,
                                  **{'host': 'fake-compute-host',
                                     'binary': 'nova-compute',
                                     'topic': 'compute',
                                     'report_count': 0})
        compute.create()
        # This is needed because of lazy-loading service.compute_node
        cn = objects.ComputeNode(uuid=uuids.cn, host="fake-compute-host",
                                 hypervisor_hostname="fake-compute-host")
        mock_get_cn.return_value = [cn]
        aggregate = self.aggregate_api.create_aggregate(self.ctxt,
                                                   'aggregate',
                                                   None)
        self.aggregate_api.add_host_to_aggregate(self.ctxt,
                                                 aggregate.id,
                                                 'fake-compute-host')
        mock_add_host.assert_called_once_with(
            mock.ANY, aggregate.uuid, host_name='fake-compute-host')
        self.controller.delete(self.req, compute.id)
        result = self.aggregate_api.get_aggregate(self.ctxt,
                                                  aggregate.id).hosts
        self.assertEqual([], result)
        mock_hm.return_value.destroy.assert_called_once_with()
        mock_remove_host.assert_called_once_with(
            mock.ANY, aggregate.uuid, 'fake-compute-host')

    @mock.patch('nova.db.api.compute_node_statistics')
    def test_compute_node_statistics(self, mock_cns):
        # Note this should only be called twice
        mock_cns.side_effect = [
            {'stat1': 1, 'stat2': 4.0},
            {'stat1': 5, 'stat2': 1.2},
        ]
        compute.CELLS = [objects.CellMapping(uuid=uuids.cell1),
                         objects.CellMapping(
                                 uuid=objects.CellMapping.CELL0_UUID),
                         objects.CellMapping(uuid=uuids.cell2)]
        stats = self.host_api.compute_node_statistics(self.ctxt)
        self.assertEqual({'stat1': 6, 'stat2': 5.2}, stats)

    @mock.patch.object(objects.CellMappingList, 'get_all',
                       return_value=objects.CellMappingList(objects=[
                           objects.CellMapping(
                               uuid=objects.CellMapping.CELL0_UUID,
                               transport_url='mq://cell0',
                               database_connection='db://cell0'),
                           objects.CellMapping(
                               uuid=uuids.cell1_uuid,
                               transport_url='mq://fake1',
                               database_connection='db://fake1'),
                           objects.CellMapping(
                               uuid=uuids.cell2_uuid,
                               transport_url='mq://fake2',
                               database_connection='db://fake2')]))
    @mock.patch.object(objects.ComputeNode, 'get_by_uuid',
                       side_effect=[exception.ComputeHostNotFound(
                                        host=uuids.cn_uuid),
                                    objects.ComputeNode(uuid=uuids.cn_uuid)])
    def test_compute_node_get_using_uuid(self, compute_get_by_uuid,
                                         cell_mappings_get_all):
        """Tests that we can lookup a compute node in the HostAPI using a uuid.
        """
        self.host_api.compute_node_get(self.ctxt, uuids.cn_uuid)
        # cell0 should have been skipped, and the compute node wasn't found
        # in cell1 so we checked cell2 and found it
        self.assertEqual(2, compute_get_by_uuid.call_count)
        compute_get_by_uuid.assert_has_calls(
            [mock.call(self.ctxt, uuids.cn_uuid)] * 2)

    @mock.patch.object(objects.CellMappingList, 'get_all',
                       return_value=objects.CellMappingList(objects=[
                           objects.CellMapping(
                               uuid=objects.CellMapping.CELL0_UUID,
                               transport_url='mq://cell0',
                               database_connection='db://cell0'),
                           objects.CellMapping(
                               uuid=uuids.cell1_uuid,
                               transport_url='mq://fake1',
                               database_connection='db://fake1'),
                           objects.CellMapping(
                               uuid=uuids.cell2_uuid,
                               transport_url='mq://fake2',
                               database_connection='db://fake2')]))
    @mock.patch.object(objects.ComputeNode, 'get_by_uuid',
                       side_effect=exception.ComputeHostNotFound(
                           host=uuids.cn_uuid))
    def test_compute_node_get_not_found(self, compute_get_by_uuid,
                                        cell_mappings_get_all):
        """Tests that we can lookup a compute node in the HostAPI using a uuid
        and will fail with ComputeHostNotFound if we didn't find it in any
        cell.
        """
        self.assertRaises(exception.ComputeHostNotFound,
                          self.host_api.compute_node_get,
                          self.ctxt, uuids.cn_uuid)
        # cell0 should have been skipped, and the compute node wasn't found
        # in cell1 or cell2.
        self.assertEqual(2, compute_get_by_uuid.call_count)
        compute_get_by_uuid.assert_has_calls(
            [mock.call(self.ctxt, uuids.cn_uuid)] * 2)


class ComputeAggregateAPITestCase(test.TestCase):
    def setUp(self):
        super(ComputeAggregateAPITestCase, self).setUp()
        self.aggregate_api = compute.AggregateAPI()
        self.ctxt = context.get_admin_context()
        # NOTE(jaypipes): We just mock out the HostNapping and Service object
        # lookups in order to bypass the code that does cell lookup stuff,
        # which isn't germane to these tests
        self.useFixture(
            fixtures.MockPatch('nova.objects.HostMapping.get_by_host'))
        self.useFixture(
            fixtures.MockPatch('nova.context.set_target_cell'))
        mock_service_get_by_compute_host = (
            self.useFixture(
                fixtures.MockPatch(
                    'nova.objects.Service.get_by_compute_host')).mock)
        mock_service_get_by_compute_host.return_value = (
            objects.Service(host='fake-host'))

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_add_host')
    @mock.patch.object(compute.LOG, 'warning')
    def test_aggregate_add_host_placement_missing_provider(
            self, mock_log, mock_pc_add_host):
        hostname = 'fake-host'
        err = exception.ResourceProviderNotFound(name_or_uuid=hostname)
        mock_pc_add_host.side_effect = err
        aggregate = self.aggregate_api.create_aggregate(
            self.ctxt, 'aggregate', None)
        self.aggregate_api.add_host_to_aggregate(
            self.ctxt, aggregate.id, hostname)
        # Nothing should blow up in Rocky, but we should get a warning
        msg = ("Failed to associate %s with a placement "
               "aggregate: %s. This may be corrected after running "
               "nova-manage placement sync_aggregates.")
        mock_log.assert_called_with(msg, hostname, err)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_add_host')
    def test_aggregate_add_host_bad_placement(self, mock_pc_add_host):
        hostname = 'fake-host'
        mock_pc_add_host.side_effect = exception.PlacementAPIConnectFailure
        aggregate = self.aggregate_api.create_aggregate(
            self.ctxt, 'aggregate', None)
        agg_uuid = aggregate.uuid
        self.assertRaises(exception.PlacementAPIConnectFailure,
                          self.aggregate_api.add_host_to_aggregate,
                          self.ctxt, aggregate.id, hostname)
        mock_pc_add_host.assert_called_once_with(
            self.ctxt, agg_uuid, host_name=hostname)

    @mock.patch('nova.objects.Aggregate.delete_host')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_remove_host')
    def test_aggregate_remove_host_bad_placement(
            self, mock_pc_remove_host, mock_agg_obj_delete_host):
        hostname = 'fake-host'
        mock_pc_remove_host.side_effect = exception.PlacementAPIConnectFailure
        aggregate = self.aggregate_api.create_aggregate(
            self.ctxt, 'aggregate', None)
        agg_uuid = aggregate.uuid
        self.assertRaises(exception.PlacementAPIConnectFailure,
                          self.aggregate_api.remove_host_from_aggregate,
                          self.ctxt, aggregate.id, hostname)
        mock_pc_remove_host.assert_called_once_with(
            self.ctxt, agg_uuid, hostname)
        # Make sure mock_agg_obj_delete_host wasn't called since placement
        # should be tried first and failed with a server failure.
        mock_agg_obj_delete_host.assert_not_called()

    @mock.patch('nova.objects.Aggregate.delete_host')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_remove_host')
    @mock.patch.object(compute.LOG, 'warning')
    def test_aggregate_remove_host_placement_missing_provider(
            self, mock_log, mock_pc_remove_host, mock_agg_obj_delete_host):
        hostname = 'fake-host'
        err = exception.ResourceProviderNotFound(name_or_uuid=hostname)
        mock_pc_remove_host.side_effect = err
        aggregate = self.aggregate_api.create_aggregate(
            self.ctxt, 'aggregate', None)
        self.aggregate_api.remove_host_from_aggregate(
            self.ctxt, aggregate.id, hostname)
        # Nothing should blow up in Rocky, but we should get a warning
        msg = ("Failed to remove association of %s with a placement "
               "aggregate: %s.")
        mock_log.assert_called_with(msg, hostname, err)
        # In this case Aggregate.delete_host is still called because the
        # ResourceProviderNotFound error is just logged.
        mock_agg_obj_delete_host.assert_called_once_with(hostname)
