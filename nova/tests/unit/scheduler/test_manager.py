# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Tests For Scheduler
"""

import mock
import oslo_messaging as messaging
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context
from nova import exception
from nova import objects
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import manager
from nova import test
from nova.tests.unit import fake_server_actions
from nova.tests.unit.scheduler import fakes


class SchedulerManagerInitTestCase(test.NoDBTestCase):
    """Test case for scheduler manager initiation."""
    manager_cls = manager.SchedulerManager

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_default_schedulerdriver(self,
                                                mock_init_agg,
                                                mock_init_inst):
        driver = self.manager_cls().driver
        self.assertIsInstance(driver, filter_scheduler.FilterScheduler)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_nonexist_schedulerdriver(self,
                                           mock_init_agg,
                                           mock_init_inst):
        self.flags(driver='nonexist_scheduler', group='scheduler')
        # The entry point has to be defined in setup.cfg and nova-scheduler has
        # to be deployed again before using a custom value.
        self.assertRaises(RuntimeError, self.manager_cls)


class SchedulerManagerTestCase(test.NoDBTestCase):
    """Test case for scheduler manager."""

    manager_cls = manager.SchedulerManager

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(SchedulerManagerTestCase, self).setUp()
        self.manager = self.manager_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.fake_args = (1, 2, 3)
        self.fake_kwargs = {'cat': 'meow', 'dog': 'woof'}
        fake_server_actions.stub_out_action_events(self)

    @mock.patch('nova.scheduler.request_filter.process_reqspec')
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination(self, mock_get_ac, mock_rfrs, mock_process):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        fake_version = "9.42"
        mock_p_sums = mock.Mock()
        fake_alloc_reqs = fakes.get_fake_alloc_reqs()
        place_res = (fake_alloc_reqs, mock_p_sums, fake_version)
        mock_get_ac.return_value = place_res
        mock_rfrs.return_value.cpu_pinning_requested = False
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fake_alloc_reqs[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(self.context, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid])
            mock_process.assert_called_once_with(self.context, fake_spec)
            select_destinations.assert_called_once_with(
                self.context, fake_spec,
                [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                mock_p_sums, fake_version, False)
            mock_get_ac.assert_called_once_with(
                self.context, mock_rfrs.return_value)

            # Now call select_destinations() with True values for the params
            # introduced in RPC version 4.5
            select_destinations.reset_mock()
            self.manager.select_destinations(None, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid],
                    return_objects=True, return_alternates=True)
            select_destinations.assert_called_once_with(None, fake_spec,
                [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                mock_p_sums, fake_version, True)

    @mock.patch('nova.scheduler.request_filter.process_reqspec')
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination_return_objects(self, mock_get_ac,
            mock_rfrs, mock_process):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        fake_version = "9.42"
        mock_p_sums = mock.Mock()
        fake_alloc_reqs = fakes.get_fake_alloc_reqs()
        place_res = (fake_alloc_reqs, mock_p_sums, fake_version)
        mock_get_ac.return_value = place_res
        mock_rfrs.return_value.cpu_pinning_requested = False
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fake_alloc_reqs[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            sel_obj = objects.Selection(service_host="fake_host",
                    nodename="fake_node", compute_node_uuid=uuids.compute_node,
                    cell_uuid=uuids.cell, limits=None)
            select_destinations.return_value = [[sel_obj]]
            # Pass True; should get the Selection object back.
            dests = self.manager.select_destinations(None, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid],
                    return_objects=True, return_alternates=True)
            sel_host = dests[0][0]
            self.assertIsInstance(sel_host, objects.Selection)
            mock_process.assert_called_once_with(None, fake_spec)
            # Since both return_objects and return_alternates are True, the
            # driver should have been called with True for return_alternates.
            select_destinations.assert_called_once_with(None, fake_spec,
                    [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                    mock_p_sums, fake_version, True)

            # Now pass False for return objects, but keep return_alternates as
            # True. Verify that the manager converted the Selection object back
            # to a dict.
            select_destinations.reset_mock()
            dests = self.manager.select_destinations(None, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid],
                    return_objects=False, return_alternates=True)
            sel_host = dests[0]
            self.assertIsInstance(sel_host, dict)
            # Even though return_alternates was passed as True, since
            # return_objects was False, the driver should have been called with
            # return_alternates as False.
            select_destinations.assert_called_once_with(None, fake_spec,
                    [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                    mock_p_sums, fake_version, False)

    @mock.patch('nova.scheduler.request_filter.process_reqspec')
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def _test_select_destination(self, get_allocation_candidates_response,
                                 mock_get_ac, mock_rfrs, mock_process):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        place_res = get_allocation_candidates_response
        mock_get_ac.return_value = place_res
        mock_rfrs.return_value.cpu_pinning_requested = False
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.assertRaises(messaging.rpc.dispatcher.ExpectedException,
                    self.manager.select_destinations, self.context,
                    spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid])
            select_destinations.assert_not_called()
            mock_process.assert_called_once_with(self.context, fake_spec)
            mock_get_ac.assert_called_once_with(
                self.context, mock_rfrs.return_value)

    def test_select_destination_old_placement(self):
        """Tests that we will raise NoValidhost when the scheduler
        report client's get_allocation_candidates() returns None, None as it
        would if placement service hasn't been upgraded before scheduler.
        """
        place_res = (None, None, None)
        self._test_select_destination(place_res)

    def test_select_destination_placement_connect_fails(self):
        """Tests that we will raise NoValidHost when the scheduler
        report client's get_allocation_candidates() returns None, which it
        would if the connection to Placement failed and the safe_connect
        decorator returns None.
        """
        place_res = None
        self._test_select_destination(place_res)

    def test_select_destination_no_candidates(self):
        """Tests that we will raise NoValidHost when the scheduler
        report client's get_allocation_candidates() returns [], {} which it
        would if placement service hasn't yet had compute nodes populate
        inventory.
        """
        place_res = ([], {}, None)
        self._test_select_destination(place_res)

    @mock.patch('nova.scheduler.request_filter.process_reqspec')
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination_is_rebuild(self, mock_get_ac, mock_rfrs,
                                           mock_process):
        fake_spec = objects.RequestSpec(
            scheduler_hints={'_nova_check_type': ['rebuild']})
        fake_spec.instance_uuid = uuids.instance
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(self.context, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid])
            select_destinations.assert_called_once_with(
                self.context, fake_spec,
                [fake_spec.instance_uuid], None, None, None, False)
            mock_get_ac.assert_not_called()
            mock_process.assert_not_called()

    @mock.patch('nova.scheduler.request_filter.process_reqspec')
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination_with_4_3_client(
            self, mock_get_ac, mock_rfrs, mock_process,
            cpu_pinning_requested=False):
        fake_spec = objects.RequestSpec()
        mock_p_sums = mock.Mock()
        fake_alloc_reqs = fakes.get_fake_alloc_reqs()
        place_res = (fake_alloc_reqs, mock_p_sums, "42.0")
        mock_get_ac.return_value = place_res
        mock_rfrs.return_value.cpu_pinning_requested = cpu_pinning_requested
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fake_alloc_reqs[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(self.context, spec_obj=fake_spec)
            mock_process.assert_called_once_with(self.context, fake_spec)
            select_destinations.assert_called_once_with(self.context,
                fake_spec, None, expected_alloc_reqs_by_rp_uuid,
                mock_p_sums, "42.0", False)
            mock_rfrs.assert_called_once_with(
                self.context, fake_spec, mock.ANY,
                enable_pinning_translate=True)
            mock_get_ac.assert_called_once_with(
                self.context, mock_rfrs.return_value)

    @mock.patch('nova.scheduler.manager.LOG.debug')
    @mock.patch('nova.scheduler.request_filter.process_reqspec')
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination_with_pcpu_fallback(
            self, mock_get_ac, mock_rfrs, mock_process, mock_log):
        """Check that we make a second request to placement if we've got a PCPU
        request.
        """
        self.flags(disable_fallback_pcpu_query=False, group='workarounds')

        # mock the result from placement. In reality, the two calls we expect
        # would return two different results, but we don't care about that. All
        # we want to check is that it _was_ called twice
        fake_spec = objects.RequestSpec()
        mock_p_sums = mock.Mock()
        fake_alloc_reqs = fakes.get_fake_alloc_reqs()
        place_res = (fake_alloc_reqs, mock_p_sums, "42.0")
        mock_get_ac.return_value = place_res

        pcpu_rreq = mock.Mock()
        pcpu_rreq.cpu_pinning_requested = True
        vcpu_rreq = mock.Mock()
        mock_rfrs.side_effect = [pcpu_rreq, vcpu_rreq]

        # as above, the two allocation requests against each compute node would
        # be different in reality, and not all compute nodes might have two
        # allocation requests, but that doesn't matter for this simple test
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fake_alloc_reqs[x], fake_alloc_reqs[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }

        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(self.context, spec_obj=fake_spec)
            select_destinations.assert_called_once_with(self.context,
                fake_spec, None, expected_alloc_reqs_by_rp_uuid,
                mock_p_sums, "42.0", False)

        mock_process.assert_called_once_with(self.context, fake_spec)
        mock_log.assert_called_with(
            'Requesting fallback allocation candidates with VCPU instead of '
            'PCPU')
        mock_rfrs.assert_has_calls([
            mock.call(self.context, fake_spec, mock.ANY,
                      enable_pinning_translate=True),
            mock.call(self.context, fake_spec, mock.ANY,
                      enable_pinning_translate=False),
        ])
        mock_get_ac.assert_has_calls([
            mock.call(self.context, pcpu_rreq),
            mock.call(self.context, vcpu_rreq),
        ])

    def test_select_destination_with_pcpu_fallback_disabled(self):
        """Check that we do not make a second request to placement if we've
        been told not to, even though we've got a PCPU instance.
        """
        self.flags(disable_fallback_pcpu_query=True, group='workarounds')

        self.test_select_destination_with_4_3_client(
            cpu_pinning_requested=True)

    # TODO(sbauza): Remove that test once the API v4 is removed
    @mock.patch('nova.scheduler.request_filter.process_reqspec')
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    def test_select_destination_with_old_client(self, from_primitives,
            mock_get_ac, mock_rfrs, mock_process):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        from_primitives.return_value = fake_spec
        mock_p_sums = mock.Mock()
        fake_alloc_reqs = fakes.get_fake_alloc_reqs()
        place_res = (fake_alloc_reqs, mock_p_sums, "42.0")
        mock_get_ac.return_value = place_res
        mock_rfrs.return_value.cpu_pinning_requested = False
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fake_alloc_reqs[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(
                self.context, request_spec='fake_spec',
                filter_properties='fake_props',
                instance_uuids=[fake_spec.instance_uuid])
            mock_process.assert_called_once_with(self.context, fake_spec)
            select_destinations.assert_called_once_with(
                self.context, fake_spec,
                [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                mock_p_sums, "42.0", False)
            mock_get_ac.assert_called_once_with(
                self.context, mock_rfrs.return_value)

    def test_update_aggregates(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'update_aggregates'
                ) as update_aggregates:
            self.manager.update_aggregates(None, aggregates='agg')
            update_aggregates.assert_called_once_with('agg')

    def test_delete_aggregate(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'delete_aggregate'
                ) as delete_aggregate:
            self.manager.delete_aggregate(None, aggregate='agg')
            delete_aggregate.assert_called_once_with('agg')

    def test_update_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'update_instance_info') as mock_update:
            self.manager.update_instance_info(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_info)
            mock_update.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.host_name,
                                                mock.sentinel.instance_info)

    def test_delete_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'delete_instance_info') as mock_delete:
            self.manager.delete_instance_info(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_uuid)
            mock_delete.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.host_name,
                                                mock.sentinel.instance_uuid)

    def test_sync_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'sync_instance_info') as mock_sync:
            self.manager.sync_instance_info(mock.sentinel.context,
                                            mock.sentinel.host_name,
                                            mock.sentinel.instance_uuids)
            mock_sync.assert_called_once_with(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_uuids)

    def test_reset(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'refresh_cells_caches') as mock_refresh:
            self.manager.reset()
            mock_refresh.assert_called_once_with()

    @mock.patch('nova.objects.host_mapping.discover_hosts')
    def test_discover_hosts(self, mock_discover):
        cm1 = objects.CellMapping(name='cell1')
        cm2 = objects.CellMapping(name='cell2')
        mock_discover.return_value = [objects.HostMapping(host='a',
                                                          cell_mapping=cm1),
                                      objects.HostMapping(host='b',
                                                          cell_mapping=cm2)]
        self.manager._discover_hosts_in_cells(mock.sentinel.context)

    @mock.patch('nova.scheduler.manager.LOG.debug')
    @mock.patch('nova.scheduler.manager.LOG.warning')
    @mock.patch('nova.objects.host_mapping.discover_hosts')
    def test_discover_hosts_duplicate_host_mapping(self, mock_discover,
                                                   mock_log_warning,
                                                   mock_log_debug):
        # This tests the scenario of multiple schedulers running discover_hosts
        # at the same time.
        mock_discover.side_effect = exception.HostMappingExists(name='a')
        self.manager._discover_hosts_in_cells(mock.sentinel.context)
        msg = ("This periodic task should only be enabled on a single "
               "scheduler to prevent collisions between multiple "
               "schedulers: Host 'a' mapping already exists")
        mock_log_warning.assert_called_once_with(msg)
        mock_log_debug.assert_not_called()
        # Second collision should log at debug, not warning.
        mock_log_warning.reset_mock()
        self.manager._discover_hosts_in_cells(mock.sentinel.context)
        mock_log_warning.assert_not_called()
        mock_log_debug.assert_called_once_with(msg)
