# Copyright 2011 OpenStack Foundation
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
Tests For Filter Scheduler.
"""

import mock

from nova import exception
from nova import objects
from nova.scheduler import client
from nova.scheduler.client import report
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import utils as scheduler_utils
from nova.scheduler import weights
from nova import test  # noqa
from nova.tests.unit.scheduler import test_scheduler
from nova.tests import uuidsentinel as uuids


class FilterSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Filter Scheduler."""

    driver_cls = filter_scheduler.FilterScheduler

    @mock.patch('nova.scheduler.client.SchedulerClient')
    def setUp(self, mock_client):
        pc_client = mock.Mock(spec=report.SchedulerReportClient)
        sched_client = mock.Mock(spec=client.SchedulerClient)
        sched_client.reportclient = pc_client
        mock_client.return_value = sched_client
        self.placement_client = pc_client
        super(FilterSchedulerTestCase, self).setUp()

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_claim_resources')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def test_schedule_placement_bad_comms(self, mock_get_hosts,
            mock_get_all_states, mock_claim):
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
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None)

        host_state = mock.Mock(spec=host_manager.HostState,
            host=mock.sentinel.host, uuid=uuids.cn1)
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.return_value = all_host_states

        instance_uuids = None
        ctx = mock.Mock()
        selected_hosts = self.driver._schedule(ctx, spec_obj,
            instance_uuids, None, mock.sentinel.provider_summaries)

        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called_once_with(spec_obj, all_host_states, 0)

        self.assertEqual(len(selected_hosts), 1)
        self.assertEqual([host_state], selected_hosts)

        # Ensure that we have consumed the resources on the chosen host states
        host_state.consume_from_request.assert_called_once_with(spec_obj)

        # And ensure we never called _claim_resources()
        self.assertFalse(mock_claim.called)

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_claim_resources')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def test_schedule_old_conductor(self, mock_get_hosts,
            mock_get_all_states, mock_claim):
        """Old conductor can call scheduler without the instance_uuids
        parameter. When this happens, we need to ensure we do not attempt to
        claim resources in the placement API since obviously we need instance
        UUIDs to perform those claims.
        """
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None)

        host_state = mock.Mock(spec=host_manager.HostState,
            host=mock.sentinel.host, uuid=uuids.cn1)
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.return_value = all_host_states

        instance_uuids = None
        ctx = mock.Mock()
        selected_hosts = self.driver._schedule(ctx, spec_obj,
            instance_uuids, mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries)

        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called_once_with(spec_obj, all_host_states, 0)

        self.assertEqual(len(selected_hosts), 1)
        self.assertEqual([host_state], selected_hosts)

        # Ensure that we have consumed the resources on the chosen host states
        host_state.consume_from_request.assert_called_once_with(spec_obj)

        # And ensure we never called _claim_resources()
        self.assertFalse(mock_claim.called)

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_claim_resources')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def _test_schedule_successful_claim(self, mock_get_hosts,
            mock_get_all_states, mock_claim, num_instances=1):
        spec_obj = objects.RequestSpec(
            num_instances=num_instances,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None)

        host_state = mock.Mock(spec=host_manager.HostState,
            host=mock.sentinel.host, uuid=uuids.cn1)
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.return_value = all_host_states
        mock_claim.return_value = True

        instance_uuids = [uuids.instance]
        alloc_reqs_by_rp_uuid = {
            uuids.cn1: [mock.sentinel.alloc_req],
        }
        ctx = mock.Mock()
        selected_hosts = self.driver._schedule(ctx, spec_obj,
            instance_uuids, alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries)

        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called_once_with(spec_obj, all_host_states, 0)
        mock_claim.assert_called_once_with(ctx.elevated.return_value, spec_obj,
            uuids.instance, [mock.sentinel.alloc_req])

        self.assertEqual(len(selected_hosts), 1)
        self.assertEqual([host_state], selected_hosts)

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

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_cleanup_allocations')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_claim_resources')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def test_schedule_unsuccessful_claim(self, mock_get_hosts,
            mock_get_all_states, mock_claim, mock_cleanup):
        """Tests that we return an empty list if we are unable to successfully
        claim resources for the instance
        """
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None)

        host_state = mock.Mock(spec=host_manager.HostState,
            host=mock.sentinel.host, uuid=uuids.cn1)
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.return_value = all_host_states
        mock_claim.return_value = False

        instance_uuids = [uuids.instance]
        alloc_reqs_by_rp_uuid = {
            uuids.cn1: [mock.sentinel.alloc_req],
        }
        ctx = mock.Mock()
        selected_hosts = self.driver._schedule(ctx, spec_obj,
            instance_uuids, alloc_reqs_by_rp_uuid,
            mock.sentinel.provider_summaries)

        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called_once_with(spec_obj, all_host_states, 0)
        mock_claim.assert_called_once_with(ctx.elevated.return_value, spec_obj,
            uuids.instance, [mock.sentinel.alloc_req])

        self.assertEqual([], selected_hosts)

        mock_cleanup.assert_called_once_with([])

        # Ensure that we have consumed the resources on the chosen host states
        self.assertFalse(host_state.consume_from_request.called)

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_cleanup_allocations')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_claim_resources')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def test_schedule_not_all_instance_clean_claimed(self, mock_get_hosts,
            mock_get_all_states, mock_claim, mock_cleanup):
        """Tests that we clean up previously-allocated instances if not all
        instances could be scheduled
        """
        spec_obj = objects.RequestSpec(
            num_instances=2,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None)

        host_state = mock.Mock(spec=host_manager.HostState,
            host=mock.sentinel.host, uuid=uuids.cn1)
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.side_effect = [
            all_host_states,  # first return all the hosts (only one)
            [],  # then act as if no more hosts were found that meet criteria
        ]
        mock_claim.return_value = True

        instance_uuids = [uuids.instance1, uuids.instance2]
        alloc_reqs_by_rp_uuid = {
            uuids.cn1: [mock.sentinel.alloc_req],
        }
        ctx = mock.Mock()
        self.driver._schedule(ctx, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries)

        # Ensure we cleaned up the first successfully-claimed instance
        mock_cleanup.assert_called_once_with([uuids.instance1])

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_claim_resources')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def test_schedule_instance_group(self, mock_get_hosts,
            mock_get_all_states, mock_claim):
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
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=ig)

        hs1 = mock.Mock(spec=host_manager.HostState, host='host1',
            uuid=uuids.cn1)
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2',
            uuid=uuids.cn2)
        all_host_states = [hs1, hs2]
        mock_get_all_states.return_value = all_host_states
        mock_claim.return_value = True

        alloc_reqs_by_rp_uuid = {
            uuids.cn1: [mock.sentinel.alloc_req_cn1],
            uuids.cn2: [mock.sentinel.alloc_req_cn2],
        }

        # Simulate host 1 and host 2 being randomly returned first by
        # _get_sorted_hosts() in the two iterations for each instance in
        # num_instances
        mock_get_hosts.side_effect = ([hs2, hs1], [hs1, hs2])
        instance_uuids = [
            getattr(uuids, 'instance%d' % x) for x in range(num_instances)
        ]
        ctx = mock.Mock()
        self.driver._schedule(ctx, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries)

        # Check that we called _claim_resources() for both the first and second
        # host state
        claim_calls = [
            mock.call(ctx.elevated.return_value, spec_obj,
                uuids.instance0, [mock.sentinel.alloc_req_cn2]),
            mock.call(ctx.elevated.return_value, spec_obj,
                uuids.instance1, [mock.sentinel.alloc_req_cn1]),
        ]
        mock_claim.assert_has_calls(claim_calls)

        # Check that _get_sorted_hosts() is called twice and that the
        # second time, we pass it the hosts that were returned from
        # _get_sorted_hosts() the first time
        sorted_host_calls = [
            mock.call(spec_obj, all_host_states, 0),
            mock.call(spec_obj, [hs2, hs1], 1),
        ]
        mock_get_hosts.assert_has_calls(sorted_host_calls)

        # The instance group object should have both host1 and host2 in its
        # instance group hosts list and there should not be any "changes" to
        # save in the instance group object
        self.assertEqual(['host2', 'host1'], ig.hosts)
        self.assertEqual({}, ig.obj_get_changes())

    @mock.patch('nova.scheduler.filter_scheduler.LOG.debug')
    @mock.patch('random.choice', side_effect=lambda x: x[1])
    @mock.patch('nova.scheduler.host_manager.HostManager.get_weighed_hosts')
    @mock.patch('nova.scheduler.host_manager.HostManager.get_filtered_hosts')
    def test_get_sorted_hosts(self, mock_filt, mock_weighed, mock_rand, debug):
        """Tests the call that returns a sorted list of hosts by calling the
        host manager's filtering and weighing routines
        """
        self.flags(host_subset_size=2, group='filter_scheduler')
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1')
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2')
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

        results = self.driver._get_sorted_hosts(mock.sentinel.spec,
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
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1')
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2')
        all_host_states = [hs1, hs2]

        mock_weighed.return_value = [
            weights.WeighedHost(hs1, 1.0), weights.WeighedHost(hs2, 1.0),
        ]

        results = self.driver._get_sorted_hosts(mock.sentinel.spec,
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
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1')
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2')
        all_host_states = [hs1, hs2]

        mock_weighed.return_value = [
            weights.WeighedHost(hs1, 1.0), weights.WeighedHost(hs2, 1.0),
        ]

        results = self.driver._get_sorted_hosts(mock.sentinel.spec,
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

    def test_cleanup_allocations(self):
        instance_uuids = []
        # Check we don't do anything if there's no instance UUIDs to cleanup
        # allocations for
        pc = self.placement_client

        self.driver._cleanup_allocations(instance_uuids)
        self.assertFalse(pc.delete_allocation_for_instance.called)

        instance_uuids = [uuids.instance1, uuids.instance2]
        self.driver._cleanup_allocations(instance_uuids)

        exp_calls = [mock.call(uuids.instance1), mock.call(uuids.instance2)]
        pc.delete_allocation_for_instance.assert_has_calls(exp_calls)

    def test_claim_resources(self):
        """Tests that when _schedule() calls _claim_resources(), that we
        appropriately call the placement client to claim resources for the
        instance.
        """
        ctx = mock.Mock(user_id=uuids.user_id)
        spec_obj = objects.RequestSpec(project_id=uuids.project_id)
        instance_uuid = uuids.instance
        alloc_reqs = [mock.sentinel.alloc_req]

        res = self.driver._claim_resources(ctx, spec_obj, instance_uuid,
            alloc_reqs)

        pc = self.placement_client
        pc.claim_resources.return_value = True
        pc.claim_resources.assert_called_once_with(uuids.instance,
            mock.sentinel.alloc_req, uuids.project_id, uuids.user_id)
        self.assertTrue(res)

    @mock.patch('nova.scheduler.utils.request_is_rebuild')
    def test_claim_resouces_for_policy_check(self, mock_policy):
        mock_policy.return_value = True
        res = self.driver._claim_resources(None, mock.sentinel.spec_obj,
                                           mock.sentinel.instance_uuid,
                                           [])
        self.assertTrue(res)
        mock_policy.assert_called_once_with(mock.sentinel.spec_obj)
        self.assertFalse(self.placement_client.claim_resources.called)

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

        host_state = host_manager.HostState('host', 'node', uuids.cell)
        host_state.limits['vcpu'] = 5
        scheduler_utils.populate_filter_properties(filter_properties,
                host_state)

        self.assertEqual(['host', 'node'],
                         filter_properties['retry']['hosts'][0])

        self.assertEqual({'vcpu': 5}, host_state.limits)

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_schedule')
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
                                  vcpus=1),
            project_id=uuids.project_id,
            num_instances=1)

        mock_schedule.return_value = [mock.sentinel.hs1]

        dests = self.driver.select_destinations(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums)

        mock_schedule.assert_called_once_with(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums)

        self.assertEqual([mock.sentinel.hs1], dests)

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_schedule')
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
                                  vcpus=1),
            project_id=uuids.project_id,
            num_instances=2)

        mock_schedule.return_value = [mock.sentinel.hs1]

        dests = self.driver.select_destinations(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums)

        mock_schedule.assert_called_once_with(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums)

        self.assertEqual([mock.sentinel.hs1], dests)

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_schedule')
    def test_select_destinations_fewer_num_instances(self, mock_schedule):
        """Tests that the select_destinations() method properly handles
        resetting host state objects and raising NoValidHost when the
        _schedule() method returns no host matches.
        """
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            num_instances=2)

        host_state = mock.Mock(spec=host_manager.HostState)
        mock_schedule.return_value = [host_state]

        self.assertRaises(exception.NoValidHost,
            self.driver.select_destinations, self.context, spec_obj,
            [mock.sentinel.instance_uuid1, mock.sentinel.instance_uuid2],
            mock.sentinel.alloc_reqs_by_rp_uuid, mock.sentinel.p_sums)

        # Verify that the host state object has been marked as not updated so
        # it's picked up in the next pull from the DB for compute node objects
        self.assertIsNone(host_state.updated)

    @mock.patch.object(filter_scheduler.FilterScheduler, '_schedule')
    def test_select_destinations_notifications(self, mock_schedule):
        mock_schedule.return_value = [mock.Mock()]

        with mock.patch.object(self.driver.notifier, 'info') as mock_info:
            expected = {'num_instances': 1,
                        'instance_properties': {'uuid': uuids.instance},
                        'instance_type': {},
                        'image': {}}
            spec_obj = objects.RequestSpec(num_instances=1,
                                           instance_uuid=uuids.instance)

            self.driver.select_destinations(self.context, spec_obj,
                    [uuids.instance], {}, None)

            expected = [
                mock.call(self.context, 'scheduler.select_destinations.start',
                 dict(request_spec=expected)),
                mock.call(self.context, 'scheduler.select_destinations.end',
                 dict(request_spec=expected))]
            self.assertEqual(expected, mock_info.call_args_list)

    def test_get_all_host_states_provider_summaries_is_none(self):
        """Tests that HostManager.get_host_states_by_uuids is called with
        compute_uuids being None when the incoming provider_summaries is None.
        """
        with mock.patch.object(self.driver.host_manager,
                               'get_host_states_by_uuids') as get_host_states:
            self.driver._get_all_host_states(
                mock.sentinel.ctxt, mock.sentinel.spec_obj, None)
        # Make sure get_host_states_by_uuids was called with
        # compute_uuids being None.
        get_host_states.assert_called_once_with(
            mock.sentinel.ctxt, None, mock.sentinel.spec_obj)

    def test_get_all_host_states_provider_summaries_is_empty(self):
        """Tests that HostManager.get_host_states_by_uuids is called with
        compute_uuids being [] when the incoming provider_summaries is {}.
        """
        with mock.patch.object(self.driver.host_manager,
                               'get_host_states_by_uuids') as get_host_states:
            self.driver._get_all_host_states(
                mock.sentinel.ctxt, mock.sentinel.spec_obj, {})
        # Make sure get_host_states_by_uuids was called with
        # compute_uuids being [].
        get_host_states.assert_called_once_with(
            mock.sentinel.ctxt, [], mock.sentinel.spec_obj)
