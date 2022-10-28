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

from unittest import mock

import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context
from nova import exception
from nova import objects
from nova.scheduler import filters
from nova.scheduler import host_manager
from nova.scheduler import manager
from nova.scheduler import utils as scheduler_utils
from nova.scheduler import weights
from nova import servicegroup
from nova import test
from nova.tests.unit import fake_server_actions
from nova.tests.unit.scheduler import fakes


fake_numa_limit = objects.NUMATopologyLimits(cpu_allocation_ratio=1.0,
        ram_allocation_ratio=1.0)
fake_limit = {"memory_mb": 1024, "disk_gb": 100, "vcpus": 2,
        "numa_topology": fake_numa_limit}
fake_limit_obj = objects.SchedulerLimits.from_dict(fake_limit)
fake_alloc = {"allocations": [
        {"resource_provider": {"uuid": uuids.compute_node},
         "resources": {"VCPU": 1,
                       "MEMORY_MB": 1024,
                       "DISK_GB": 100}
        }]}
fake_alloc_version = "1.23"
json_alloc = jsonutils.dumps(fake_alloc)
fake_selection = objects.Selection(service_host="fake_host",
        nodename="fake_node", compute_node_uuid=uuids.compute_node,
        cell_uuid=uuids.cell, limits=fake_limit_obj,
        allocation_request=json_alloc,
        allocation_request_version=fake_alloc_version)


class SchedulerManagerTestCase(test.NoDBTestCase):
    """Test case for scheduler manager."""

    manager_cls = manager.SchedulerManager

    @mock.patch.object(
        host_manager.HostManager, '_init_instance_info', new=mock.Mock())
    @mock.patch.object(
        host_manager.HostManager, '_init_aggregates', new=mock.Mock())
    def setUp(self):
        super().setUp()
        self.manager = self.manager_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.servicegroup_api = servicegroup.API()
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
        with mock.patch.object(
            self.manager, '_select_destinations',
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
        with mock.patch.object(
            self.manager, '_select_destinations',
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
            # method should have been called with True for return_alternates.
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
            # return_objects was False, the method should have been called with
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
        with mock.patch.object(
            self.manager, '_select_destinations',
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
        with mock.patch.object(
            self.manager, '_select_destinations',
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
        with mock.patch.object(
            self.manager, '_select_destinations',
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

        with mock.patch.object(
            self.manager, '_select_destinations',
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
        with mock.patch.object(
            self.manager, '_select_destinations',
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

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def test_schedule_placement_bad_comms(
        self, mock_get_hosts, mock_get_all_states, mock_claim,
    ):
        """If there was a problem communicating with the Placement service,
        alloc_reqs_by_rp_uuid will be None and we need to avoid trying to claim
        in the Placement API.
        """
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            instance_group=None, instance_uuid=uuids.instance)
        # Reset the RequestSpec changes so they don't interfere with the
        # assertion at the end of the test.
        spec_obj.obj_reset_changes(recursive=True)

        host_state = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host",
            uuid=uuids.cn1,
            cell_uuid=uuids.cell,
            nodename="fake_node",
            limits={},
            aggregates=[],
            allocation_candidates=[],
        )
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states

        visited_instances = set([])

        def fake_get_sorted_hosts(_spec_obj, host_states, index):
            # Keep track of which instances are passed to the filters.
            visited_instances.add(_spec_obj.instance_uuid)
            return all_host_states

        mock_get_hosts.side_effect = fake_get_sorted_hosts

        instance_uuids = [uuids.instance]
        ctx = mock.Mock()
        selected_hosts = self.manager._schedule(ctx, spec_obj, instance_uuids,
                None, mock.sentinel.provider_summaries)

        expected_hosts = [[objects.Selection.from_host_state(host_state)]]
        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called_once_with(spec_obj, all_host_states, 0)

        self.assertEqual(len(selected_hosts), 1)
        self.assertEqual(expected_hosts, selected_hosts)

        # Ensure that we have consumed the resources on the chosen host states
        host_state.consume_from_request.assert_called_once_with(spec_obj)

        # And ensure we never called claim_resources()
        self.assertFalse(mock_claim.called)

        # Make sure that the RequestSpec.instance_uuid is not dirty.
        self.assertEqual(sorted(instance_uuids), sorted(visited_instances))
        self.assertEqual(0, len(spec_obj.obj_what_changed()),
                         spec_obj.obj_what_changed())

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def test_schedule_old_conductor(
        self, mock_get_hosts, mock_get_all_states, mock_claim,
    ):
        """Old conductor can call scheduler without the instance_uuids
        parameter. When this happens, we need to ensure we do not attempt to
        claim resources in the placement API since obviously we need instance
        UUIDs to perform those claims.
        """
        group = objects.InstanceGroup(hosts=[])
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            instance_group=group,
            requested_resources=[],
        )

        host_state = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host",
            nodename="fake_node",
            uuid=uuids.cn1,
            limits={},
            cell_uuid=uuids.cell,
            instances={},
            aggregates=[],
            allocation_candidates=[],
        )
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.side_effect = lambda spec_obj, hosts, num: list(hosts)

        instance_uuids = None
        ctx = mock.Mock()
        selected_hosts = self.manager._schedule(ctx, spec_obj,
            instance_uuids, None, mock.sentinel.provider_summaries)

        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called_once_with(spec_obj, all_host_states, 0)

        self.assertEqual(len(selected_hosts), 1)
        expected_host = objects.Selection.from_host_state(host_state)
        self.assertEqual([[expected_host]], selected_hosts)

        # Ensure that we have consumed the resources on the chosen host states
        host_state.consume_from_request.assert_called_once_with(spec_obj)

        # And ensure we never called claim_resources()
        self.assertFalse(mock_claim.called)
        # And that the host is added to the server group but there are no
        # instances tracked in the host_state.
        self.assertIn(host_state.host, group.hosts)
        self.assertEqual(0, len(host_state.instances))

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def _test_schedule_successful_claim(
        self, mock_get_hosts, mock_get_all_states, mock_claim, num_instances=1,
    ):
        spec_obj = objects.RequestSpec(
            num_instances=num_instances,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            instance_group=None,
            requested_resources=[],
        )

        host_state = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host",
            nodename="fake_node",
            uuid=uuids.cn1,
            cell_uuid=uuids.cell1,
            limits={},
            aggregates=[],
            allocation_candidates=[],
        )
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        # simulate that every host passes the filtering
        mock_get_hosts.side_effect = lambda spec_obj, hosts, num: list(hosts)
        mock_claim.return_value = True

        instance_uuids = [uuids.instance]
        fake_alloc = {"allocations": [
                {"resource_provider": {"uuid": uuids.cn1},
                 "resources": {"VCPU": 1,
                               "MEMORY_MB": 1024,
                               "DISK_GB": 100}
                }]}
        alloc_reqs_by_rp_uuid = {uuids.cn1: [fake_alloc]}
        ctx = mock.Mock()
        selected_hosts = self.manager._schedule(ctx, spec_obj, instance_uuids,
                alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries)

        sel_obj = objects.Selection.from_host_state(host_state,
                allocation_request=fake_alloc)
        expected_selection = [[sel_obj]]
        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called()
        mock_claim.assert_called_once_with(ctx.elevated.return_value,
                self.manager.placement_client, spec_obj, uuids.instance,
                alloc_reqs_by_rp_uuid[uuids.cn1][0],
                allocation_request_version=None)

        self.assertEqual(len(selected_hosts), 1)
        self.assertEqual(expected_selection, selected_hosts)

        # Ensure that we have consumed the resources on the chosen host states
        host_state.consume_from_request.assert_called_once_with(spec_obj)

    def test_schedule_successful_claim(self):
        self._test_schedule_successful_claim()

    def test_schedule_old_reqspec_and_move_operation(self):
        """This test is for verifying that in case of a move operation with an
        original RequestSpec created for 3 concurrent instances, we only verify
        the instance that is moved.
        """
        self._test_schedule_successful_claim(num_instances=3)

    @mock.patch('nova.scheduler.manager.SchedulerManager._cleanup_allocations')
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def test_schedule_unsuccessful_claim(
        self, mock_get_hosts, mock_get_all_states, mock_claim, mock_cleanup,
    ):
        """Tests that we return an empty list if we are unable to successfully
        claim resources for the instance
        """
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            instance_group=None)

        host_state = mock.Mock(
            spec=host_manager.HostState,
            host=mock.sentinel.host,
            uuid=uuids.cn1,
            cell_uuid=uuids.cell1,
            allocations_candidates=[],
        )
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.side_effect = lambda spec_obj, hosts, num: list(hosts)
        mock_claim.return_value = False

        instance_uuids = [uuids.instance]
        alloc_reqs_by_rp_uuid = {
            uuids.cn1: [{"allocations": mock.sentinel.alloc_req}],
        }
        ctx = mock.Mock()
        fake_version = "1.99"
        self.assertRaises(exception.NoValidHost, self.manager._schedule, ctx,
                spec_obj, instance_uuids, alloc_reqs_by_rp_uuid,
                mock.sentinel.provider_summaries,
                allocation_request_version=fake_version)

        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called_once_with(spec_obj, mock.ANY, 0)
        mock_claim.assert_called_once_with(ctx.elevated.return_value,
                self.manager.placement_client, spec_obj, uuids.instance,
                alloc_reqs_by_rp_uuid[uuids.cn1][0],
            allocation_request_version=fake_version)

        mock_cleanup.assert_not_called()
        # Ensure that we have consumed the resources on the chosen host states
        self.assertFalse(host_state.consume_from_request.called)

    @mock.patch('nova.scheduler.manager.SchedulerManager._cleanup_allocations')
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def test_schedule_not_all_instance_clean_claimed(
        self, mock_get_hosts, mock_get_all_states, mock_claim, mock_cleanup,
    ):
        """Tests that we clean up previously-allocated instances if not all
        instances could be scheduled
        """
        spec_obj = objects.RequestSpec(
            num_instances=2,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            instance_group=None,
            requested_resources=[],
        )

        host_state = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host",
            nodename="fake_node",
            uuid=uuids.cn1,
            cell_uuid=uuids.cell1,
            limits={},
            updated="fake",
            allocation_candidates=[],
        )
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states

        calls = []

        def fake_get_sorted_hosts(spec_obj, hosts, num):
            c = len(calls)
            calls.append(1)
            # first instance: return all the hosts (only one)
            if c == 0:
                return hosts
            # second: act as if no more hosts that meet criteria
            elif c == 1:
                return []
            # the final call when creating alternates
            elif c == 2:
                return hosts
            else:
                raise StopIteration()

        mock_get_hosts.side_effect = fake_get_sorted_hosts
        mock_claim.return_value = True

        instance_uuids = [uuids.instance1, uuids.instance2]
        fake_alloc = {"allocations": [
                {"resource_provider": {"uuid": uuids.cn1},
                 "resources": {"VCPU": 1,
                               "MEMORY_MB": 1024,
                               "DISK_GB": 100}
                }]}
        alloc_reqs_by_rp_uuid = {uuids.cn1: [fake_alloc]}
        ctx = mock.Mock()
        self.assertRaises(exception.NoValidHost, self.manager._schedule, ctx,
                spec_obj, instance_uuids, alloc_reqs_by_rp_uuid,
                mock.sentinel.provider_summaries)

        # Ensure we cleaned up the first successfully-claimed instance
        mock_cleanup.assert_called_once_with(ctx, [uuids.instance1])

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def test_selection_alloc_requests_for_alts(
        self, mock_get_hosts, mock_get_all_states, mock_claim,
    ):
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None,
            requested_resources=[],
        )

        host_state0 = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host0",
            nodename="fake_node0",
            uuid=uuids.cn0,
            cell_uuid=uuids.cell,
            limits={},
            aggregates=[],
            allocation_candidates=[],
        )
        host_state1 = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host1",
            nodename="fake_node1",
            uuid=uuids.cn1,
            cell_uuid=uuids.cell,
            limits={},
            aggregates=[],
            allocation_candidates=[],
        )
        host_state2 = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host2",
            nodename="fake_node2",
            uuid=uuids.cn2,
            cell_uuid=uuids.cell,
            limits={},
            aggregates=[],
            allocation_candidates=[],
        )
        all_host_states = [host_state0, host_state1, host_state2]
        mock_get_all_states.return_value = all_host_states
        # simulate that every host passes the filtering
        mock_get_hosts.side_effect = lambda spec_obj, hosts, num: list(hosts)
        mock_claim.return_value = True

        instance_uuids = [uuids.instance0]
        fake_alloc0 = {"allocations": [
                {"resource_provider": {"uuid": uuids.cn0},
                 "resources": {"VCPU": 1,
                               "MEMORY_MB": 1024,
                               "DISK_GB": 100}
                }]}
        fake_alloc1 = {"allocations": [
                {"resource_provider": {"uuid": uuids.cn1},
                 "resources": {"VCPU": 1,
                               "MEMORY_MB": 1024,
                               "DISK_GB": 100}
                }]}
        fake_alloc2 = {"allocations": [
                {"resource_provider": {"uuid": uuids.cn2},
                 "resources": {"VCPU": 1,
                               "MEMORY_MB": 1024,
                               "DISK_GB": 100}
                }]}
        alloc_reqs_by_rp_uuid = {uuids.cn0: [fake_alloc0],
                uuids.cn1: [fake_alloc1], uuids.cn2: [fake_alloc2]}
        ctx = mock.Mock()
        selected_hosts = self.manager._schedule(ctx, spec_obj, instance_uuids,
                alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries,
                return_alternates=True)

        sel0 = objects.Selection.from_host_state(host_state0,
                allocation_request=fake_alloc0)
        sel1 = objects.Selection.from_host_state(host_state1,
                allocation_request=fake_alloc1)
        sel2 = objects.Selection.from_host_state(host_state2,
                allocation_request=fake_alloc2)
        expected_selection = [[sel0, sel1, sel2]]
        self.assertEqual(expected_selection, selected_hosts)

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def test_selection_alloc_requests_no_alts(
        self, mock_get_hosts, mock_get_all_states, mock_claim,
    ):
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None,
            requested_resources=[],
        )

        host_state0 = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host0",
            nodename="fake_node0",
            uuid=uuids.cn0,
            cell_uuid=uuids.cell,
            limits={},
            aggregates=[],
            allocation_candidates=[],
        )
        host_state1 = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host1",
            nodename="fake_node1",
            uuid=uuids.cn1,
            cell_uuid=uuids.cell,
            limits={},
            aggregates=[],
            allocation_candidates=[],
        )
        host_state2 = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host2",
            nodename="fake_node2",
            uuid=uuids.cn2,
            cell_uuid=uuids.cell,
            limits={},
            aggregates=[],
            allocation_candidates=[],
        )
        all_host_states = [host_state0, host_state1, host_state2]
        mock_get_all_states.return_value = all_host_states
        # simulate that every host passes the filtering
        mock_get_hosts.side_effect = lambda spec_obj, hosts, num: list(hosts)
        mock_claim.return_value = True

        instance_uuids = [uuids.instance0]
        fake_alloc0 = {"allocations": [
                {"resource_provider": {"uuid": uuids.cn0},
                 "resources": {"VCPU": 1,
                               "MEMORY_MB": 1024,
                               "DISK_GB": 100}
                }]}
        fake_alloc1 = {"allocations": [
                {"resource_provider": {"uuid": uuids.cn1},
                 "resources": {"VCPU": 1,
                               "MEMORY_MB": 1024,
                               "DISK_GB": 100}
                }]}
        fake_alloc2 = {"allocations": [
                {"resource_provider": {"uuid": uuids.cn2},
                 "resources": {"VCPU": 1,
                               "MEMORY_MB": 1024,
                               "DISK_GB": 100}
                }]}
        alloc_reqs_by_rp_uuid = {uuids.cn0: [fake_alloc0],
                uuids.cn1: [fake_alloc1], uuids.cn2: [fake_alloc2]}
        ctx = mock.Mock()
        selected_hosts = self.manager._schedule(ctx, spec_obj, instance_uuids,
                alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries,
                return_alternates=False)

        sel0 = objects.Selection.from_host_state(host_state0,
                allocation_request=fake_alloc0)
        expected_selection = [[sel0]]
        self.assertEqual(expected_selection, selected_hosts)

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def test_schedule_instance_group(
        self, mock_get_hosts, mock_get_all_states, mock_claim,
    ):
        """Test that since the request spec object contains an instance group
        object, that upon choosing a host in the primary schedule loop,
        that we update the request spec's instance group information
        """
        num_instances = 2
        ig = objects.InstanceGroup(hosts=[])
        spec_obj = objects.RequestSpec(
            num_instances=num_instances,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            instance_group=ig,
            instance_uuid=uuids.instance0,
            requested_resources=[],
        )
        # Reset the RequestSpec changes so they don't interfere with the
        # assertion at the end of the test.
        spec_obj.obj_reset_changes(recursive=True)

        hs1 = mock.Mock(
            spec=host_manager.HostState,
            host="host1",
            nodename="node1",
            limits={},
            uuid=uuids.cn1,
            cell_uuid=uuids.cell1,
            instances={},
            aggregates=[],
            allocation_candidates=[],
        )
        hs2 = mock.Mock(
            spec=host_manager.HostState,
            host="host2",
            nodename="node2",
            limits={},
            uuid=uuids.cn2,
            cell_uuid=uuids.cell2,
            instances={},
            aggregates=[],
            allocation_candidates=[],
        )
        all_host_states = [hs1, hs2]
        mock_get_all_states.return_value = all_host_states
        mock_claim.return_value = True

        alloc_reqs_by_rp_uuid = {
            uuids.cn1: [{"allocations": "fake_cn1_alloc"}],
            uuids.cn2: [{"allocations": "fake_cn2_alloc"}],
        }

        # Simulate host 1 and host 2 being randomly returned first by
        # _get_sorted_hosts() in the two iterations for each instance in
        # num_instances
        visited_instances = set([])
        get_sorted_hosts_called_with_host_states = []

        def fake_get_sorted_hosts(_spec_obj, host_states, index):
            # Keep track of which instances are passed to the filters.
            visited_instances.add(_spec_obj.instance_uuid)
            if index % 2:
                s = list(host_states)
                get_sorted_hosts_called_with_host_states.append(s)
                return s
            s = list(host_states)
            get_sorted_hosts_called_with_host_states.append(s)
            return reversed(s)
        mock_get_hosts.side_effect = fake_get_sorted_hosts
        instance_uuids = [
            getattr(uuids, 'instance%d' % x) for x in range(num_instances)
        ]
        ctx = mock.Mock()
        self.manager._schedule(ctx, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries)

        # Check that we called claim_resources() for both the first and second
        # host state
        claim_calls = [
            mock.call(ctx.elevated.return_value, self.manager.placement_client,
                    spec_obj, uuids.instance0,
                    alloc_reqs_by_rp_uuid[uuids.cn2][0],
                    allocation_request_version=None),
            mock.call(ctx.elevated.return_value, self.manager.placement_client,
                    spec_obj, uuids.instance1,
                    alloc_reqs_by_rp_uuid[uuids.cn1][0],
                    allocation_request_version=None),
        ]
        mock_claim.assert_has_calls(claim_calls)

        # Check that _get_sorted_hosts() is called twice and that the
        # second time, we pass it the hosts that were returned from
        # _get_sorted_hosts() the first time
        sorted_host_calls = [
            mock.call(spec_obj, mock.ANY, 0),
            mock.call(spec_obj, mock.ANY, 1),
        ]
        mock_get_hosts.assert_has_calls(sorted_host_calls)
        self.assertEqual(
            all_host_states, get_sorted_hosts_called_with_host_states[0])
        self.assertEqual(
            [hs1], get_sorted_hosts_called_with_host_states[1])

        # The instance group object should have both host1 and host2 in its
        # instance group hosts list and there should not be any "changes" to
        # save in the instance group object
        self.assertEqual(['host2', 'host1'], ig.hosts)
        self.assertEqual({}, ig.obj_get_changes())
        # Assert that we updated HostState.instances for each host.
        self.assertIn(uuids.instance0, hs2.instances)
        self.assertIn(uuids.instance1, hs1.instances)
        # Make sure that the RequestSpec.instance_uuid is not dirty.
        self.assertEqual(sorted(instance_uuids), sorted(visited_instances))
        self.assertEqual(0, len(spec_obj.obj_what_changed()),
                         spec_obj.obj_what_changed())

    @mock.patch('nova.scheduler.manager.LOG.debug')
    @mock.patch('random.choice', side_effect=lambda x: x[1])
    @mock.patch('nova.scheduler.host_manager.HostManager.get_weighed_hosts')
    @mock.patch('nova.scheduler.host_manager.HostManager.get_filtered_hosts')
    def test_get_sorted_hosts(self, mock_filt, mock_weighed, mock_rand, debug):
        """Tests the call that returns a sorted list of hosts by calling the
        host manager's filtering and weighing routines
        """
        self.flags(host_subset_size=2, group='filter_scheduler')
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1',
                cell_uuid=uuids.cell1)
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2',
                cell_uuid=uuids.cell2)
        all_host_states = [hs1, hs2]

        mock_weighed.return_value = [
            weights.WeighedHost(hs1, 1.0), weights.WeighedHost(hs2, 1.0),
        ]

        # Make sure that when logging the weighed hosts we are logging them
        # with the WeighedHost wrapper class rather than the HostState objects.
        def fake_debug(message, *args, **kwargs):
            if message.startswith('Weighed'):
                self.assertEqual(1, len(args))
                for weighed_host in args[0]['hosts']:
                    self.assertIsInstance(weighed_host, weights.WeighedHost)
        debug.side_effect = fake_debug

        results = self.manager._get_sorted_hosts(mock.sentinel.spec,
            all_host_states, mock.sentinel.index)
        debug.assert_called()

        mock_filt.assert_called_once_with(all_host_states, mock.sentinel.spec,
            mock.sentinel.index)

        mock_weighed.assert_called_once_with(mock_filt.return_value,
            mock.sentinel.spec)

        # We override random.choice() to pick the **second** element of the
        # returned weighed hosts list, which is the host state #2. This tests
        # the code path that combines the randomly-chosen host with the
        # remaining list of weighed host state objects
        self.assertEqual([hs2, hs1], results)

    @mock.patch('random.choice', side_effect=lambda x: x[0])
    @mock.patch('nova.scheduler.host_manager.HostManager.get_weighed_hosts')
    @mock.patch('nova.scheduler.host_manager.HostManager.get_filtered_hosts')
    def test_get_sorted_hosts_subset_less_than_num_weighed(self, mock_filt,
            mock_weighed, mock_rand):
        """Tests that when we have >1 weighed hosts but a host subset size of
        1, that we always pick the first host in the weighed host
        """
        self.flags(host_subset_size=1, group='filter_scheduler')
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1',
                cell_uuid=uuids.cell1)
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2',
                cell_uuid=uuids.cell2)
        all_host_states = [hs1, hs2]

        mock_weighed.return_value = [
            weights.WeighedHost(hs1, 1.0), weights.WeighedHost(hs2, 1.0),
        ]

        results = self.manager._get_sorted_hosts(mock.sentinel.spec,
            all_host_states, mock.sentinel.index)

        mock_filt.assert_called_once_with(all_host_states, mock.sentinel.spec,
            mock.sentinel.index)

        mock_weighed.assert_called_once_with(mock_filt.return_value,
            mock.sentinel.spec)

        # We should be randomly selecting only from a list of one host state
        mock_rand.assert_called_once_with([hs1])
        self.assertEqual([hs1, hs2], results)

    @mock.patch('random.choice', side_effect=lambda x: x[0])
    @mock.patch('nova.scheduler.host_manager.HostManager.get_weighed_hosts')
    @mock.patch('nova.scheduler.host_manager.HostManager.get_filtered_hosts')
    def test_get_sorted_hosts_subset_greater_than_num_weighed(self, mock_filt,
            mock_weighed, mock_rand):
        """Hosts should still be chosen if host subset size is larger than
        number of weighed hosts.
        """
        self.flags(host_subset_size=20, group='filter_scheduler')
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1',
                cell_uuid=uuids.cell1)
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2',
                cell_uuid=uuids.cell2)
        all_host_states = [hs1, hs2]

        mock_weighed.return_value = [
            weights.WeighedHost(hs1, 1.0), weights.WeighedHost(hs2, 1.0),
        ]

        results = self.manager._get_sorted_hosts(mock.sentinel.spec,
            all_host_states, mock.sentinel.index)

        mock_filt.assert_called_once_with(all_host_states, mock.sentinel.spec,
            mock.sentinel.index)

        mock_weighed.assert_called_once_with(mock_filt.return_value,
            mock.sentinel.spec)

        # We overrode random.choice() to return the first element in the list,
        # so even though we had a host_subset_size greater than the number of
        # weighed hosts (2), we just random.choice() on the entire set of
        # weighed hosts and thus return [hs1, hs2]
        self.assertEqual([hs1, hs2], results)

    @mock.patch('random.shuffle', side_effect=lambda x: x.reverse())
    @mock.patch('nova.scheduler.host_manager.HostManager.get_weighed_hosts')
    @mock.patch('nova.scheduler.host_manager.HostManager.get_filtered_hosts')
    def test_get_sorted_hosts_shuffle_top_equal(self, mock_filt, mock_weighed,
                                                mock_shuffle):
        """Tests that top best weighed hosts are shuffled when enabled.
        """
        self.flags(host_subset_size=1, group='filter_scheduler')
        self.flags(shuffle_best_same_weighed_hosts=True,
                   group='filter_scheduler')
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1')
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2')
        hs3 = mock.Mock(spec=host_manager.HostState, host='host3')
        hs4 = mock.Mock(spec=host_manager.HostState, host='host4')
        all_host_states = [hs1, hs2, hs3, hs4]

        mock_weighed.return_value = [
            weights.WeighedHost(hs1, 1.0),
            weights.WeighedHost(hs2, 1.0),
            weights.WeighedHost(hs3, 0.5),
            weights.WeighedHost(hs4, 0.5),
        ]

        results = self.manager._get_sorted_hosts(mock.sentinel.spec,
            all_host_states, mock.sentinel.index)

        mock_filt.assert_called_once_with(all_host_states, mock.sentinel.spec,
            mock.sentinel.index)

        mock_weighed.assert_called_once_with(mock_filt.return_value,
            mock.sentinel.spec)

        # We override random.shuffle() to reverse the list, thus the
        # head of the list should become [host#2, host#1]
        # (as the host_subset_size is 1) and the tail should stay the same.
        self.assertEqual([hs2, hs1, hs3, hs4], results)

    @mock.patch(
        'nova.scheduler.client.report.SchedulerReportClient'
        '.delete_allocation_for_instance')
    def test_cleanup_allocations(self, mock_delete_alloc):
        # Check we don't do anything if there's no instance UUIDs to cleanup
        # allocations for

        instance_uuids = []
        self.manager._cleanup_allocations(self.context, instance_uuids)
        mock_delete_alloc.assert_not_called()

        instance_uuids = [uuids.instance1, uuids.instance2]
        self.manager._cleanup_allocations(self.context, instance_uuids)
        mock_delete_alloc.assert_has_calls([
            mock.call(self.context, uuids.instance1, force=True),
            mock.call(self.context, uuids.instance2, force=True),
        ])

    def test_add_retry_host(self):
        retry = dict(num_attempts=1, hosts=[])
        filter_properties = dict(retry=retry)
        host = "fakehost"
        node = "fakenode"

        scheduler_utils._add_retry_host(filter_properties, host, node)

        hosts = filter_properties['retry']['hosts']
        self.assertEqual(1, len(hosts))
        self.assertEqual([host, node], hosts[0])

    def test_post_select_populate(self):
        # Test addition of certain filter props after a node is selected.
        retry = {'hosts': [], 'num_attempts': 1}
        filter_properties = {'retry': retry}

        selection = objects.Selection(service_host="host", nodename="node",
                cell_uuid=uuids.cell)
        scheduler_utils.populate_filter_properties(filter_properties,
                selection)
        self.assertEqual(['host', 'node'],
                         filter_properties['retry']['hosts'][0])

    @mock.patch('nova.scheduler.manager.SchedulerManager._schedule')
    def test_select_destinations_match_num_instances(self, mock_schedule):
        """Tests that the select_destinations() method returns the list of
        hosts from the _schedule() method when the number of returned hosts
        equals the number of instance UUIDs passed in.
        """
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            num_instances=1,
            image=None,
            numa_topology=None,
            pci_requests=None,
            instance_uuid=uuids.instance_id)

        mock_schedule.return_value = [[fake_selection]]
        dests = self.manager._select_destinations(
            self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums, mock.sentinel.ar_version)

        mock_schedule.assert_called_once_with(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums, mock.sentinel.ar_version, False)
        self.assertEqual([[fake_selection]], dests)

    @mock.patch('nova.scheduler.manager.SchedulerManager._schedule')
    def test_select_destinations_for_move_ops(self, mock_schedule):
        """Tests that the select_destinations() method verifies the number of
        hosts returned from the _schedule() method against the number of
        instance UUIDs passed as a parameter and not against the RequestSpec
        num_instances field since the latter could be wrong in case of a move
        operation.
        """
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            num_instances=2,
            image=None,
            numa_topology=None,
            pci_requests=None,
            instance_uuid=uuids.instance_id)

        mock_schedule.return_value = [[fake_selection]]
        dests = self.manager._select_destinations(
            self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums, mock.sentinel.ar_version)

        mock_schedule.assert_called_once_with(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums, mock.sentinel.ar_version, False)
        self.assertEqual([[fake_selection]], dests)

    @mock.patch('nova.scheduler.utils.claim_resources', return_value=True)
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    def test_schedule_fewer_num_instances(
        self, mock_get_hosts, mock_get_all_states, mock_claim,
    ):
        """Tests that the _schedule() method properly handles
        resetting host state objects and raising NoValidHost when there are not
        enough hosts available.
        """
        spec_obj = objects.RequestSpec(
            num_instances=2,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1,
                                  disabled=False,
                                  is_public=True,
                                  name="small_flavor"),
            project_id=uuids.project_id,
            instance_uuid=uuids.instance_id,
            instance_group=None,
            requested_resources=[],
        )

        host_state = mock.Mock(
            spec=host_manager.HostState,
            host="fake_host",
            uuid=uuids.cn1,
            cell_uuid=uuids.cell,
            nodename="fake_node",
            limits={},
            updated="Not None",
            allocation_candidates=[],
        )
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states

        calls = []

        def fake_get_sorted_hosts(spec_obj, hosts, num):
            c = len(calls)
            calls.append(1)
            if c == 0:
                return list(hosts)
            elif c == 1:
                return []
            else:
                raise StopIteration

        mock_get_hosts.side_effect = fake_get_sorted_hosts

        instance_uuids = [uuids.inst1, uuids.inst2]
        fake_allocs_by_rp = {uuids.cn1: [{}]}

        self.assertRaises(exception.NoValidHost, self.manager._schedule,
                self.context, spec_obj, instance_uuids, fake_allocs_by_rp,
                mock.sentinel.p_sums)
        self.assertIsNone(host_state.updated)

    @mock.patch("nova.scheduler.host_manager.HostState.consume_from_request")
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    def _test_alternates_returned(
        self, mock_get_all_hosts, mock_sorted, mock_claim, mock_consume,
        num_instances=2, num_alternates=2,
    ):
        all_host_states = []
        alloc_reqs = {}
        for num in range(10):
            host_name = "host%s" % num
            hs = host_manager.HostState(host_name, "node%s" % num,
                    uuids.cell)
            hs.uuid = getattr(uuids, host_name)
            all_host_states.append(hs)
            alloc_reqs[hs.uuid] = [{}]

        mock_get_all_hosts.return_value = all_host_states
        mock_sorted.side_effect = lambda spec_obj, hosts, num: list(hosts)
        mock_claim.return_value = True
        total_returned = num_alternates + 1
        self.flags(max_attempts=total_returned, group="scheduler")
        instance_uuids = [getattr(uuids, "inst%s" % num)
                for num in range(num_instances)]

        spec_obj = objects.RequestSpec(
            num_instances=num_instances,
            flavor=objects.Flavor(
                memory_mb=512, root_gb=512, ephemeral_gb=0, swap=0, vcpus=1
            ),
            project_id=uuids.project_id,
            instance_group=None,
            requested_resources=[],
        )

        dests = self.manager._schedule(self.context, spec_obj,
                instance_uuids, alloc_reqs, None, return_alternates=True)
        self.assertEqual(num_instances, len(dests))
        # Filtering and weighing hosts should be called num_instances + 1 times
        # unless we're not getting alternates, and then just num_instances
        self.assertEqual(num_instances + 1
                         if num_alternates > 0 and num_instances > 1
                         else num_instances,
                         mock_sorted.call_count,
                         'Unexpected number of calls to filter hosts for %s '
                         'instances.' % num_instances)
        selected_hosts = [dest[0] for dest in dests]
        for dest in dests:
            self.assertEqual(total_returned, len(dest))
            # Verify that there are no duplicates among a destination
            self.assertEqual(len(dest), len(set(dest)))
            # Verify that none of the selected hosts appear in the alternates.
            for alt in dest[1:]:
                self.assertNotIn(alt, selected_hosts)

    def test_alternates_returned(self):
        self._test_alternates_returned(num_instances=1, num_alternates=1)
        self._test_alternates_returned(num_instances=3, num_alternates=0)
        self._test_alternates_returned(num_instances=1, num_alternates=4)
        self._test_alternates_returned(num_instances=2, num_alternates=3)
        self._test_alternates_returned(num_instances=8, num_alternates=8)

    @mock.patch("nova.scheduler.host_manager.HostState.consume_from_request")
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    def test_alternates_same_cell(
        self, mock_get_all_hosts, mock_sorted, mock_claim, mock_consume,
    ):
        """Tests getting alternates plus claims where the hosts are spread
        across two cells.
        """
        all_host_states = []
        alloc_reqs = {}
        for num in range(10):
            host_name = "host%s" % num
            cell_uuid = uuids.cell1 if num % 2 else uuids.cell2
            hs = host_manager.HostState(host_name, "node%s" % num,
                    cell_uuid)
            hs.uuid = getattr(uuids, host_name)
            all_host_states.append(hs)
            alloc_reqs[hs.uuid] = [{}]

        mock_get_all_hosts.return_value = all_host_states

        # There are two instances so _get_sorted_hosts is called once per
        # instance and then once again before picking alternates.
        calls = []

        def fake_get_sorted_hosts(spec_obj, hosts, num):
            c = len(calls)
            calls.append(1)
            if c == 0:
                return list(hosts)
            elif c == 1:
                return list(reversed(all_host_states))
            elif c == 2:
                return list(hosts)
            else:
                raise StopIteration()

        mock_sorted.side_effect = fake_get_sorted_hosts
        mock_claim.return_value = True
        total_returned = 3
        self.flags(max_attempts=total_returned, group="scheduler")
        instance_uuids = [uuids.inst1, uuids.inst2]
        num_instances = len(instance_uuids)

        spec_obj = objects.RequestSpec(
            num_instances=num_instances,
            flavor=objects.Flavor(
                memory_mb=512, root_gb=512, ephemeral_gb=0, swap=0, vcpus=1
            ),
            project_id=uuids.project_id,
            instance_group=None,
            requested_resources=[],
        )

        dests = self.manager._schedule(self.context, spec_obj,
                instance_uuids, alloc_reqs, None, return_alternates=True)
        # There should be max_attempts hosts per instance (1 selected, 2 alts)
        self.assertEqual(total_returned, len(dests[0]))
        self.assertEqual(total_returned, len(dests[1]))
        # Verify that the two selected hosts are not in the same cell.
        self.assertNotEqual(dests[0][0].cell_uuid, dests[1][0].cell_uuid)
        for dest in dests:
            selected_host = dest[0]
            selected_cell_uuid = selected_host.cell_uuid
            for alternate in dest[1:]:
                self.assertEqual(alternate.cell_uuid, selected_cell_uuid)

    @mock.patch("nova.scheduler.host_manager.HostState.consume_from_request")
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_sorted_hosts')
    @mock.patch('nova.scheduler.manager.SchedulerManager._get_all_host_states')
    def _test_not_enough_alternates(
        self, mock_get_all_hosts, mock_sorted, mock_claim, mock_consume,
        num_hosts, max_attempts,
    ):
        all_host_states = []
        alloc_reqs = {}
        for num in range(num_hosts):
            host_name = "host%s" % num
            hs = host_manager.HostState(host_name, "node%s" % num,
                    uuids.cell)
            hs.uuid = getattr(uuids, host_name)
            all_host_states.append(hs)
            alloc_reqs[hs.uuid] = [{}]

        mock_get_all_hosts.return_value = all_host_states
        mock_sorted.side_effect = lambda spec_obj, hosts, num: list(hosts)
        mock_claim.return_value = True
        # Set the total returned to more than the number of available hosts
        self.flags(max_attempts=max_attempts, group="scheduler")
        instance_uuids = [uuids.inst1, uuids.inst2]
        num_instances = len(instance_uuids)

        spec_obj = objects.RequestSpec(
            num_instances=num_instances,
            flavor=objects.Flavor(
                memory_mb=512, root_gb=512, ephemeral_gb=0, swap=0, vcpus=1
            ),
            project_id=uuids.project_id,
            instance_group=None,
            requested_resources=[],
        )

        dests = self.manager._schedule(self.context, spec_obj,
                instance_uuids, alloc_reqs, None, return_alternates=True)
        self.assertEqual(num_instances, len(dests))
        selected_hosts = [dest[0] for dest in dests]
        # The number returned for each destination should be the less of the
        # number of available host and the max_attempts setting.
        expected_number = min(num_hosts, max_attempts)
        for dest in dests:
            self.assertEqual(expected_number, len(dest))
            # Verify that there are no duplicates among a destination
            self.assertEqual(len(dest), len(set(dest)))
            # Verify that none of the selected hosts appear in the alternates.
            for alt in dest[1:]:
                self.assertNotIn(alt, selected_hosts)

    def test_not_enough_alternates(self):
        self._test_not_enough_alternates(num_hosts=100, max_attempts=5)
        self._test_not_enough_alternates(num_hosts=5, max_attempts=5)
        self._test_not_enough_alternates(num_hosts=3, max_attempts=5)
        self._test_not_enough_alternates(num_hosts=20, max_attempts=5)

    @mock.patch('nova.compute.utils.notify_about_scheduler_action')
    @mock.patch.object(manager.SchedulerManager, '_schedule')
    def test_select_destinations_notifications(
        self, mock_schedule, mock_notify,
    ):
        mock_schedule.return_value = ([[mock.Mock()]], [[mock.Mock()]])

        with mock.patch.object(self.manager.notifier, 'info') as mock_info:
            flavor = objects.Flavor(memory_mb=512,
                                    root_gb=512,
                                    ephemeral_gb=0,
                                    swap=0,
                                    vcpus=1,
                                    disabled=False,
                                    is_public=True,
                                    name="small_flavor")
            expected = {'num_instances': 1,
                        'instance_properties': {
                            'uuid': uuids.instance,
                            'ephemeral_gb': 0,
                            'memory_mb': 512,
                            'vcpus': 1,
                            'root_gb': 512},
                        'instance_type': flavor,
                        'image': {}}
            spec_obj = objects.RequestSpec(num_instances=1,
                                           flavor=flavor,
                                           instance_uuid=uuids.instance)

            self.manager._select_destinations(
                self.context, spec_obj, [uuids.instance], {}, None)

            expected = [
                mock.call(self.context, 'scheduler.select_destinations.start',
                 dict(request_spec=expected)),
                mock.call(self.context, 'scheduler.select_destinations.end',
                 dict(request_spec=expected))]
            self.assertEqual(expected, mock_info.call_args_list)

            mock_notify.assert_has_calls([
                mock.call(
                    context=self.context, request_spec=spec_obj,
                    action='select_destinations', phase='start',
                ),
                mock.call(
                    context=self.context, request_spec=spec_obj,
                    action='select_destinations', phase='end',
                ),
            ])

    def test_get_all_host_states_provider_summaries_is_none(self):
        """Tests that HostManager.get_host_states_by_uuids is called with
        compute_uuids being None when the incoming provider_summaries is None.
        """
        with mock.patch.object(self.manager.host_manager,
                               'get_host_states_by_uuids') as get_host_states:
            self.manager._get_all_host_states(
                mock.sentinel.ctxt, mock.sentinel.spec_obj, None)
        # Make sure get_host_states_by_uuids was called with
        # compute_uuids being None.
        get_host_states.assert_called_once_with(
            mock.sentinel.ctxt, None, mock.sentinel.spec_obj)

    def test_get_all_host_states_provider_summaries_is_empty(self):
        """Tests that HostManager.get_host_states_by_uuids is called with
        compute_uuids being [] when the incoming provider_summaries is {}.
        """
        with mock.patch.object(self.manager.host_manager,
                               'get_host_states_by_uuids') as get_host_states:
            self.manager._get_all_host_states(
                mock.sentinel.ctxt, mock.sentinel.spec_obj, {})
        # Make sure get_host_states_by_uuids was called with
        # compute_uuids being [].
        get_host_states.assert_called_once_with(
            mock.sentinel.ctxt, [], mock.sentinel.spec_obj)

    def test_update_aggregates(self):
        with mock.patch.object(
            self.manager.host_manager, 'update_aggregates',
        ) as update_aggregates:
            self.manager.update_aggregates(None, aggregates='agg')
            update_aggregates.assert_called_once_with('agg')

    def test_delete_aggregate(self):
        with mock.patch.object(
            self.manager.host_manager, 'delete_aggregate',
        ) as delete_aggregate:
            self.manager.delete_aggregate(None, aggregate='agg')
            delete_aggregate.assert_called_once_with('agg')

    def test_update_instance_info(self):
        with mock.patch.object(
            self.manager.host_manager, 'update_instance_info',
        ) as mock_update:
            self.manager.update_instance_info(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_info)
            mock_update.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.host_name,
                                                mock.sentinel.instance_info)

    def test_delete_instance_info(self):
        with mock.patch.object(
            self.manager.host_manager, 'delete_instance_info',
        ) as mock_delete:
            self.manager.delete_instance_info(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_uuid)
            mock_delete.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.host_name,
                                                mock.sentinel.instance_uuid)

    def test_sync_instance_info(self):
        with mock.patch.object(
            self.manager.host_manager, 'sync_instance_info',
        ) as mock_sync:
            self.manager.sync_instance_info(mock.sentinel.context,
                                            mock.sentinel.host_name,
                                            mock.sentinel.instance_uuids)
            mock_sync.assert_called_once_with(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_uuids)

    def test_reset(self):
        with mock.patch.object(
            self.manager.host_manager, 'refresh_cells_caches',
        ) as mock_refresh:
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


class SchedulerManagerAllocationCandidateTestCase(test.NoDBTestCase):

    class ACRecorderFilter(filters.BaseHostFilter):
        """A filter that records what allocation candidates it saw on each host
        """

        def __init__(self):
            super().__init__()
            self.seen_candidates = []

        def host_passes(self, host_state, filter_properties):
            # record what candidate the filter saw for each host
            self.seen_candidates.append(list(host_state.allocation_candidates))
            return True

    class DropFirstFilter(filters.BaseHostFilter):
        """A filter that removes one candidate and keeps the rest on each
        host
        """

        def host_passes(self, host_state, filter_properties):
            host_state.allocation_candidates.pop(0)
            return bool(host_state.allocation_candidates)

    @mock.patch.object(
        host_manager.HostManager, '_init_instance_info', new=mock.Mock())
    @mock.patch.object(
        host_manager.HostManager, '_init_aggregates', new=mock.Mock())
    def setUp(self):
        super().setUp()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.manager = manager.SchedulerManager()
        self.manager.host_manager.weighers = []
        self.request_spec = objects.RequestSpec(
            ignore_hosts=[],
            force_hosts=[],
            force_nodes=[],
            requested_resources=[],
        )

    @mock.patch("nova.objects.selection.Selection.from_host_state")
    @mock.patch(
        "nova.scheduler.manager.SchedulerManager._consume_selected_host",
    )
    @mock.patch(
        "nova.scheduler.utils.claim_resources",
        new=mock.Mock(return_value=True),
    )
    @mock.patch("nova.scheduler.manager.SchedulerManager._get_all_host_states")
    def test_filters_see_allocation_candidates_for_each_host(
        self,
        mock_get_all_host_states,
        mock_consume,
        mock_selection_from_host_state,
    ):
        # have a single filter configured where we can assert that the filter
        # see the allocation_candidates of each host
        filter = self.ACRecorderFilter()
        self.manager.host_manager.enabled_filters = [filter]

        instance_uuids = [uuids.inst1]

        alloc_reqs_by_rp_uuid = {}
        # have two hosts with different candidates
        host1 = host_manager.HostState("host1", "node1", uuids.cell1)
        host1.uuid = uuids.host1
        alloc_reqs_by_rp_uuid[uuids.host1] = [
            mock.sentinel.host1_a_c_1,
            mock.sentinel.host1_a_c_2,
        ]
        host2 = host_manager.HostState("host2", "node2", uuids.cell1)
        host2.uuid = uuids.host2
        alloc_reqs_by_rp_uuid[uuids.host2] = [
            mock.sentinel.host2_a_c_1,
        ]
        mock_get_all_host_states.return_value = iter([host1, host2])

        self.manager._schedule(
            self.context,
            self.request_spec,
            instance_uuids,
            alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries,
            mock.sentinel.allocation_request_version,
        )

        # we expect that our filter seen the allocation candidate list of
        # each host respectively
        self.assertEqual(
            [
                alloc_reqs_by_rp_uuid[uuids.host1],
                alloc_reqs_by_rp_uuid[uuids.host2],
            ],
            filter.seen_candidates,
        )

    @mock.patch(
        "nova.scheduler.manager.SchedulerManager._consume_selected_host",
    )
    @mock.patch(
        "nova.scheduler.utils.claim_resources",
        new=mock.Mock(return_value=True),
    )
    @mock.patch("nova.scheduler.manager.SchedulerManager._get_all_host_states")
    def test_scheduler_selects_filtered_a_c_from_hosts_state(
        self,
        mock_get_all_host_states,
        mock_consume,
    ):
        """Assert that if a filter removes an allocation candidate from a host
        then even if that host is selected the removed allocation candidate
        is not used by the scheduler.
        """

        self.manager.host_manager.enabled_filters = [self.DropFirstFilter()]

        instance_uuids = [uuids.inst1]
        alloc_reqs_by_rp_uuid = {}
        # have a host with two candidates
        host1 = host_manager.HostState("host1", "node1", uuids.cell1)
        host1.uuid = uuids.host1
        alloc_reqs_by_rp_uuid[uuids.host1] = [
            "host1-candidate1",
            "host1-candidate2",
        ]
        mock_get_all_host_states.return_value = iter([host1])

        result = self.manager._schedule(
            self.context,
            self.request_spec,
            instance_uuids,
            alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries,
            'fake-alloc-req-version',
        )
        # we have requested one instance to be scheduled so expect on set
        # of selections
        self.assertEqual(1, len(result))
        selections = result[0]
        # we did not ask for alternatives so a single selection is expected
        self.assertEqual(1, len(selections))
        selection = selections[0]
        # we expect that candidate2 is used as candidate1 is dropped by
        # the filter
        self.assertEqual(
            "host1-candidate2",
            jsonutils.loads(selection.allocation_request)
        )

    @mock.patch("nova.objects.selection.Selection.from_host_state")
    @mock.patch(
        "nova.scheduler.manager.SchedulerManager._consume_selected_host",
    )
    @mock.patch(
        "nova.scheduler.utils.claim_resources",
        new=mock.Mock(return_value=True),
    )
    @mock.patch("nova.scheduler.manager.SchedulerManager._get_all_host_states")
    def test_consecutive_filter_sees_filtered_a_c_list(
        self,
        mock_get_all_host_states,
        mock_consume,
        mock_selection_from_host_state,
    ):
        # create two filters
        # 1) DropFirstFilter runs first and drops the first candidate from each
        #    host
        # 2) ACRecorderFilter runs next and records what candidates it saw
        recorder_filter = self.ACRecorderFilter()
        self.manager.host_manager.enabled_filters = [
            self.DropFirstFilter(),
            recorder_filter,
        ]

        instance_uuids = [uuids.inst1]
        alloc_reqs_by_rp_uuid = {}
        # have a host with two candidates
        host1 = host_manager.HostState("host1", "node1", uuids.cell1)
        host1.uuid = uuids.host1
        alloc_reqs_by_rp_uuid[uuids.host1] = [
            "host1-candidate1",
            "host1-candidate2",
        ]
        mock_get_all_host_states.return_value = iter([host1])

        self.manager._schedule(
            self.context,
            self.request_spec,
            instance_uuids,
            alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries,
            'fake-alloc-req-version',
        )

        # we expect that the second filter saw one host with one candidate and
        # as candidate1 was already filtered out by the run of the first filter
        self.assertEqual(
            [["host1-candidate2"]],
            recorder_filter.seen_candidates
        )

    @mock.patch(
        "nova.scheduler.manager.SchedulerManager._consume_selected_host",
    )
    @mock.patch(
        "nova.scheduler.utils.claim_resources",
        new=mock.Mock(return_value=True),
    )
    @mock.patch("nova.scheduler.manager.SchedulerManager._get_all_host_states")
    def test_filters_removes_all_a_c_host_is_not_selected(
        self,
        mock_get_all_host_states,
        mock_consume,
    ):
        # use the filter that always drops the first candidate on each host
        self.manager.host_manager.enabled_filters = [self.DropFirstFilter()]

        instance_uuids = [uuids.inst1]
        alloc_reqs_by_rp_uuid = {}
        # have two hosts
        # first with a single candidate
        host1 = host_manager.HostState("host1", "node1", uuids.cell1)
        host1.uuid = uuids.host1
        alloc_reqs_by_rp_uuid[uuids.host1] = [
            "host1-candidate1",
        ]
        # second with two candidates
        host2 = host_manager.HostState("host2", "node2", uuids.cell1)
        host2.uuid = uuids.host2
        alloc_reqs_by_rp_uuid[uuids.host2] = [
            "host2-candidate1",
            "host2-candidate2",
        ]
        mock_get_all_host_states.return_value = iter([host1, host2])

        result = self.manager._schedule(
            self.context,
            self.request_spec,
            instance_uuids,
            alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries,
            'fake-alloc-req-version',
        )
        # we expect that the first host is not selected as the filter
        # removed every candidate from the host
        # also we expect that on the second host only candidate2 could have
        # been selected
        # we asked for one instance, so we expect one set of selections
        self.assertEqual(1, len(result))
        selections = result[0]
        # we did not ask for alternatives so a single selection is expected
        self.assertEqual(1, len(selections))
        selection = selections[0]
        # we expect that candidate2 is used as candidate1 is dropped by
        # the filter
        self.assertEqual(uuids.host2, selection.compute_node_uuid)
        self.assertEqual(
            "host2-candidate2",
            jsonutils.loads(selection.allocation_request)
        )

    @mock.patch(
        "nova.scheduler.manager.SchedulerManager._consume_selected_host",
    )
    @mock.patch(
        "nova.scheduler.utils.claim_resources",
        new=mock.Mock(return_value=True),
    )
    @mock.patch("nova.scheduler.manager.SchedulerManager._get_all_host_states")
    def test_consume_selected_host_sees_updated_request_spec(
        self,
        mock_get_all_host_states,
        mock_consume,
    ):
        # simulate that nothing is filtered out, by not having any filters
        self.manager.host_manager.enabled_filters = []

        # set up the request spec with a request group to be updated
        # by the selected candidate
        self.request_spec.requested_resources = [
            objects.RequestGroup(
                requester_id=uuids.group_req1, provider_uuids=[]
            )
        ]

        instance_uuids = [uuids.inst1]
        alloc_reqs_by_rp_uuid = {}
        # have single host with a single candidate
        # first with a single candidate
        host1 = host_manager.HostState("host1", "node1", uuids.cell1)
        host1.uuid = uuids.host1
        # simulate that placement fulfilled the above RequestGroup from
        # a certain child RP of the host.
        alloc_reqs_by_rp_uuid[uuids.host1] = [
            {
                "mappings": {
                    "": [uuids.host1],
                    uuids.group_req1: [uuids.host1_child_rp],
                }
            }
        ]
        mock_get_all_host_states.return_value = iter([host1])

        # make asserts on the request_spec passed to consume
        def assert_request_spec_updated_with_selected_candidate(
            selected_host, spec_obj, instance_uuid=None
        ):
            # we expect that the scheduler updated the request_spec based
            # the selected candidate before called consume
            self.assertEqual(
                [uuids.host1_child_rp],
                spec_obj.requested_resources[0].provider_uuids,
            )

        mock_consume.side_effect = (
            assert_request_spec_updated_with_selected_candidate)

        self.manager._schedule(
            self.context,
            self.request_spec,
            instance_uuids,
            alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries,
            'fake-alloc-req-version',
        )

        mock_consume.assert_called_once()

    @mock.patch(
        "nova.scheduler.manager.SchedulerManager._consume_selected_host",
    )
    @mock.patch(
        "nova.scheduler.utils.claim_resources",
        return_value=True,
    )
    @mock.patch("nova.scheduler.manager.SchedulerManager._get_all_host_states")
    def test_get_alternate_hosts_returns_main_selection_with_claimed_a_c(
        self,
        mock_get_all_host_states,
        mock_claim,
        mock_consume,
    ):
        """Assert that the first (a.k.a main) selection returned for an
        instance always maps to the allocation candidate, that was claimed by
        the scheduler in placement.
        """
        # use the filter that always drops the first candidate on each host
        self.manager.host_manager.enabled_filters = [self.DropFirstFilter()]

        instance_uuids = [uuids.inst1]
        alloc_reqs_by_rp_uuid = {}
        # have one host with 3 candidates each fulfilling a request group
        # from different child RP
        host1 = host_manager.HostState("host1", "node1", uuids.cell1)
        host1.uuid = uuids.host1
        alloc_reqs_by_rp_uuid[uuids.host1] = [
            {
                "mappings": {
                    # This is odd but the un-name request group uses "" as the
                    # name of the group.
                    "": [uuids.host1],
                    uuids.group_req1: [getattr(uuids, f"host1_child{i}")],
                }
            } for i in [1, 2, 3]
        ]
        mock_get_all_host_states.return_value = iter([host1])

        result = self.manager._schedule(
            self.context,
            self.request_spec,
            instance_uuids,
            alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries,
            'fake-alloc-req-version',
            return_alternates=True,
        )

        # we scheduled one instance
        self.assertEqual(1, len(result))
        selections = result[0]
        # we did not ask for alternatives
        self.assertEqual(1, len(selections))
        selection = selections[0]
        self.assertEqual(uuids.host1, selection.compute_node_uuid)
        # we expect that host1_child2 candidate is selected as the
        # DropFirstFilter will drop host1_child1
        expected_a_c = {
            "mappings": {
                "": [uuids.host1],
                uuids.group_req1: [uuids.host1_child2],
            }
        }
        self.assertEqual(
            expected_a_c,
            jsonutils.loads(selection.allocation_request),
        )
        # and we expect that the same candidate was claimed in placement
        mock_claim.assert_called_once_with(
            mock.ANY,
            self.manager.placement_client,
            self.request_spec,
            uuids.inst1,
            expected_a_c,
            allocation_request_version="fake-alloc-req-version",
        )

    @mock.patch(
        "nova.scheduler.manager.SchedulerManager._consume_selected_host",
    )
    @mock.patch(
        "nova.scheduler.utils.claim_resources",
        return_value=True,
    )
    @mock.patch("nova.scheduler.manager.SchedulerManager._get_all_host_states")
    def test_get_alternate_hosts_returns_alts_with_filtered_a_c(
        self,
        mock_get_all_host_states,
        mock_claim,
        mock_consume,
    ):
        """Assert that alternate generation also works based on filtered
        candidates.
        """

        class RPFilter(filters.BaseHostFilter):
            """A filter that only allows candidates with specific RPs"""

            def __init__(self, allowed_rp_uuids):
                self.allowed_rp_uuids = allowed_rp_uuids

            def host_passes(self, host_state, filter_properties):
                host_state.allocation_candidates = [
                    a_c
                    for a_c in host_state.allocation_candidates
                    if a_c["mappings"][uuids.group_req1][0]
                    in self.allowed_rp_uuids
                ]
                return True

        instance_uuids = [uuids.inst1]
        alloc_reqs_by_rp_uuid = {}
        # have 3 hosts each with 2 allocation candidates fulfilling a request
        # group from a different child RP
        hosts = []
        for i in [1, 2, 3]:
            host = host_manager.HostState(f"host{i}", f"node{i}", uuids.cell1)
            host.uuid = getattr(uuids, f"host{i}")
            alloc_reqs_by_rp_uuid[host.uuid] = [
                {
                    "mappings": {
                        "": [host.uuid],
                        uuids.group_req1: [
                            getattr(uuids, f"host{i}_child{j}")
                        ],
                    }
                }
                for j in [1, 2]
            ]
            hosts.append(host)
        mock_get_all_host_states.return_value = iter(hosts)

        # configure a filter that only "likes" host1_child2 and host3_child2
        # RPs. This means host2 is totally out and host1 and host3 only have
        # one viable candidate
        self.manager.host_manager.enabled_filters = [
            RPFilter(allowed_rp_uuids=[uuids.host1_child2, uuids.host3_child2])
        ]

        result = self.manager._schedule(
            self.context,
            self.request_spec,
            instance_uuids,
            alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries,
            'fake-alloc-req-version',
            return_alternates=True,
        )
        # we scheduled one instance
        self.assertEqual(1, len(result))
        selections = result[0]
        # we expect a main selection and a single alternative
        # (host1, and host3) on both selection we expect child2 as selected
        # candidate
        self.assertEqual(2, len(selections))
        main_selection = selections[0]
        self.assertEqual(uuids.host1, main_selection.compute_node_uuid)
        self.assertEqual(
            [uuids.host1_child2],
            jsonutils.loads(main_selection.allocation_request)["mappings"][
                uuids.group_req1
            ],
        )

        alt_selection = selections[1]
        self.assertEqual(uuids.host3, alt_selection.compute_node_uuid)
        self.assertEqual(
            [uuids.host3_child2],
            jsonutils.loads(alt_selection.allocation_request)["mappings"][
                uuids.group_req1
            ],
        )
