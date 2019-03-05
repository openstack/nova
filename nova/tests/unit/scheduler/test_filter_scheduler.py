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
from oslo_serialization import jsonutils

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

    @mock.patch('nova.scheduler.utils.claim_resources')
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
            instance_group=None, instance_uuid=uuids.instance)
        # Reset the RequestSpec changes so they don't interfere with the
        # assertion at the end of the test.
        spec_obj.obj_reset_changes(recursive=True)

        host_state = mock.Mock(spec=host_manager.HostState, host="fake_host",
                uuid=uuids.cn1, cell_uuid=uuids.cell, nodename="fake_node",
                limits={})
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
        selected_hosts = self.driver._schedule(ctx, spec_obj, instance_uuids,
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
        group = objects.InstanceGroup(hosts=[])
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=group)

        host_state = mock.Mock(spec=host_manager.HostState,
                host="fake_host", nodename="fake_node", uuid=uuids.cn1,
                limits={}, cell_uuid=uuids.cell, instances={})
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
                host="fake_host", nodename="fake_node", uuid=uuids.cn1,
                cell_uuid=uuids.cell1, limits={})
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.return_value = all_host_states
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
        selected_hosts = self.driver._schedule(ctx, spec_obj, instance_uuids,
                alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries)

        sel_obj = objects.Selection.from_host_state(host_state,
                allocation_request=fake_alloc)
        expected_selection = [[sel_obj]]
        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called()
        mock_claim.assert_called_once_with(ctx.elevated.return_value,
                self.placement_client, spec_obj, uuids.instance,
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

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_cleanup_allocations')
    @mock.patch('nova.scheduler.utils.claim_resources')
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
            host=mock.sentinel.host, uuid=uuids.cn1, cell_uuid=uuids.cell1)
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.return_value = all_host_states
        mock_claim.return_value = False

        instance_uuids = [uuids.instance]
        alloc_reqs_by_rp_uuid = {
            uuids.cn1: [{"allocations": mock.sentinel.alloc_req}],
        }
        ctx = mock.Mock()
        fake_version = "1.99"
        self.assertRaises(exception.NoValidHost, self.driver._schedule, ctx,
                spec_obj, instance_uuids, alloc_reqs_by_rp_uuid,
                mock.sentinel.provider_summaries,
                allocation_request_version=fake_version)

        mock_get_all_states.assert_called_once_with(
            ctx.elevated.return_value, spec_obj,
            mock.sentinel.provider_summaries)
        mock_get_hosts.assert_called_once_with(spec_obj, all_host_states, 0)
        mock_claim.assert_called_once_with(ctx.elevated.return_value,
                self.placement_client, spec_obj, uuids.instance,
                alloc_reqs_by_rp_uuid[uuids.cn1][0],
            allocation_request_version=fake_version)

        mock_cleanup.assert_not_called()
        # Ensure that we have consumed the resources on the chosen host states
        self.assertFalse(host_state.consume_from_request.called)

    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_cleanup_allocations')
    @mock.patch('nova.scheduler.utils.claim_resources')
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
                host="fake_host", nodename="fake_node", uuid=uuids.cn1,
                cell_uuid=uuids.cell1, limits={}, updated='fake')
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.side_effect = [
            all_host_states,  # first instance: return all the hosts (only one)
            [],  # second: act as if no more hosts that meet criteria
            all_host_states,  # the final call when creating alternates
        ]
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
        self.assertRaises(exception.NoValidHost, self.driver._schedule, ctx,
                spec_obj, instance_uuids, alloc_reqs_by_rp_uuid,
                mock.sentinel.provider_summaries)

        # Ensure we cleaned up the first successfully-claimed instance
        mock_cleanup.assert_called_once_with(ctx, [uuids.instance1])

    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def test_selection_alloc_requests_for_alts(self, mock_get_hosts,
            mock_get_all_states, mock_claim):
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None)

        host_state0 = mock.Mock(spec=host_manager.HostState,
                host="fake_host0", nodename="fake_node0", uuid=uuids.cn0,
                cell_uuid=uuids.cell, limits={})
        host_state1 = mock.Mock(spec=host_manager.HostState,
                host="fake_host1", nodename="fake_node1", uuid=uuids.cn1,
                cell_uuid=uuids.cell, limits={})
        host_state2 = mock.Mock(spec=host_manager.HostState,
                host="fake_host2", nodename="fake_node2", uuid=uuids.cn2,
                cell_uuid=uuids.cell, limits={})
        all_host_states = [host_state0, host_state1, host_state2]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.return_value = all_host_states
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
        selected_hosts = self.driver._schedule(ctx, spec_obj, instance_uuids,
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
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def test_selection_alloc_requests_no_alts(self, mock_get_hosts,
            mock_get_all_states, mock_claim):
        spec_obj = objects.RequestSpec(
            num_instances=1,
            flavor=objects.Flavor(memory_mb=512,
                                  root_gb=512,
                                  ephemeral_gb=0,
                                  swap=0,
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None)

        host_state0 = mock.Mock(spec=host_manager.HostState,
                host="fake_host0", nodename="fake_node0", uuid=uuids.cn0,
                cell_uuid=uuids.cell, limits={})
        host_state1 = mock.Mock(spec=host_manager.HostState,
                host="fake_host1", nodename="fake_node1", uuid=uuids.cn1,
                cell_uuid=uuids.cell, limits={})
        host_state2 = mock.Mock(spec=host_manager.HostState,
                host="fake_host2", nodename="fake_node2", uuid=uuids.cn2,
                cell_uuid=uuids.cell, limits={})
        all_host_states = [host_state0, host_state1, host_state2]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.return_value = all_host_states
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
        selected_hosts = self.driver._schedule(ctx, spec_obj, instance_uuids,
                alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries,
                return_alternates=False)

        sel0 = objects.Selection.from_host_state(host_state0,
                allocation_request=fake_alloc0)
        expected_selection = [[sel0]]
        self.assertEqual(expected_selection, selected_hosts)

    @mock.patch('nova.scheduler.utils.claim_resources')
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
            instance_group=ig, instance_uuid=uuids.instance0)
        # Reset the RequestSpec changes so they don't interfere with the
        # assertion at the end of the test.
        spec_obj.obj_reset_changes(recursive=True)

        hs1 = mock.Mock(spec=host_manager.HostState, host='host1',
                nodename="node1", limits={}, uuid=uuids.cn1,
                cell_uuid=uuids.cell1, instances={})
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2',
                nodename="node2", limits={}, uuid=uuids.cn2,
                cell_uuid=uuids.cell2, instances={})
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

        def fake_get_sorted_hosts(_spec_obj, host_states, index):
            # Keep track of which instances are passed to the filters.
            visited_instances.add(_spec_obj.instance_uuid)
            if index % 2:
                return [hs1, hs2]
            return [hs2, hs1]
        mock_get_hosts.side_effect = fake_get_sorted_hosts
        instance_uuids = [
            getattr(uuids, 'instance%d' % x) for x in range(num_instances)
        ]
        ctx = mock.Mock()
        self.driver._schedule(ctx, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, mock.sentinel.provider_summaries)

        # Check that we called claim_resources() for both the first and second
        # host state
        claim_calls = [
            mock.call(ctx.elevated.return_value, self.placement_client,
                    spec_obj, uuids.instance0,
                    alloc_reqs_by_rp_uuid[uuids.cn2][0],
                    allocation_request_version=None),
            mock.call(ctx.elevated.return_value, self.placement_client,
                    spec_obj, uuids.instance1,
                    alloc_reqs_by_rp_uuid[uuids.cn1][0],
                    allocation_request_version=None),
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
        # Assert that we updated HostState.instances for each host.
        self.assertIn(uuids.instance0, hs2.instances)
        self.assertIn(uuids.instance1, hs1.instances)
        # Make sure that the RequestSpec.instance_uuid is not dirty.
        self.assertEqual(sorted(instance_uuids), sorted(visited_instances))
        self.assertEqual(0, len(spec_obj.obj_what_changed()),
                         spec_obj.obj_what_changed())

    @mock.patch('nova.scheduler.filter_scheduler.LOG.debug')
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
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1',
                cell_uuid=uuids.cell1)
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2',
                cell_uuid=uuids.cell2)
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
        hs1 = mock.Mock(spec=host_manager.HostState, host='host1',
                cell_uuid=uuids.cell1)
        hs2 = mock.Mock(spec=host_manager.HostState, host='host2',
                cell_uuid=uuids.cell2)
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

        results = self.driver._get_sorted_hosts(mock.sentinel.spec,
            all_host_states, mock.sentinel.index)

        mock_filt.assert_called_once_with(all_host_states, mock.sentinel.spec,
            mock.sentinel.index)

        mock_weighed.assert_called_once_with(mock_filt.return_value,
            mock.sentinel.spec)

        # We override random.shuffle() to reverse the list, thus the
        # head of the list should become [host#2, host#1]
        # (as the host_subset_size is 1) and the tail should stay the same.
        self.assertEqual([hs2, hs1, hs3, hs4], results)

    def test_cleanup_allocations(self):
        instance_uuids = []
        # Check we don't do anything if there's no instance UUIDs to cleanup
        # allocations for
        pc = self.placement_client

        self.driver._cleanup_allocations(self.context, instance_uuids)
        self.assertFalse(pc.delete_allocation_for_instance.called)

        instance_uuids = [uuids.instance1, uuids.instance2]
        self.driver._cleanup_allocations(self.context, instance_uuids)

        exp_calls = [mock.call(self.context, uuids.instance1),
                     mock.call(self.context, uuids.instance2)]
        pc.delete_allocation_for_instance.assert_has_calls(exp_calls)

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

        mock_schedule.return_value = [[fake_selection]]
        dests = self.driver.select_destinations(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums, mock.sentinel.ar_version)

        mock_schedule.assert_called_once_with(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums, mock.sentinel.ar_version, False)
        self.assertEqual([[fake_selection]], dests)

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

        mock_schedule.return_value = [[fake_selection]]
        dests = self.driver.select_destinations(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums, mock.sentinel.ar_version)

        mock_schedule.assert_called_once_with(self.context, spec_obj,
            [mock.sentinel.instance_uuid], mock.sentinel.alloc_reqs_by_rp_uuid,
            mock.sentinel.p_sums, mock.sentinel.ar_version, False)
        self.assertEqual([[fake_selection]], dests)

    @mock.patch('nova.scheduler.utils.claim_resources', return_value=True)
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_all_host_states')
    @mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                '_get_sorted_hosts')
    def test_schedule_fewer_num_instances(self, mock_get_hosts,
            mock_get_all_states, mock_claim):
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
                                  vcpus=1),
            project_id=uuids.project_id,
            instance_group=None)

        host_state = mock.Mock(spec=host_manager.HostState, host="fake_host",
                uuid=uuids.cn1, cell_uuid=uuids.cell, nodename="fake_node",
                limits={}, updated="Not None")
        all_host_states = [host_state]
        mock_get_all_states.return_value = all_host_states
        mock_get_hosts.side_effect = [all_host_states, []]

        instance_uuids = [uuids.inst1, uuids.inst2]
        fake_allocs_by_rp = {uuids.cn1: [{}]}

        self.assertRaises(exception.NoValidHost, self.driver._schedule,
                self.context, spec_obj, instance_uuids, fake_allocs_by_rp,
                mock.sentinel.p_sums)
        self.assertIsNone(host_state.updated)

    @mock.patch("nova.scheduler.host_manager.HostState.consume_from_request")
    @mock.patch('nova.scheduler.utils.claim_resources')
    @mock.patch("nova.scheduler.filter_scheduler.FilterScheduler."
                "_get_sorted_hosts")
    @mock.patch("nova.scheduler.filter_scheduler.FilterScheduler."
                "_get_all_host_states")
    def _test_alternates_returned(self, mock_get_all_hosts, mock_sorted,
            mock_claim, mock_consume, num_instances=2, num_alternates=2):
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
        mock_sorted.return_value = all_host_states
        mock_claim.return_value = True
        total_returned = num_alternates + 1
        self.flags(max_attempts=total_returned, group="scheduler")
        instance_uuids = [getattr(uuids, "inst%s" % num)
                for num in range(num_instances)]

        spec_obj = objects.RequestSpec(
                num_instances=num_instances,
                flavor=objects.Flavor(memory_mb=512,
                                      root_gb=512,
                                      ephemeral_gb=0,
                                      swap=0,
                                      vcpus=1),
                project_id=uuids.project_id,
                instance_group=None)

        dests = self.driver._schedule(self.context, spec_obj,
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
    @mock.patch("nova.scheduler.filter_scheduler.FilterScheduler."
                "_get_sorted_hosts")
    @mock.patch("nova.scheduler.filter_scheduler.FilterScheduler."
                "_get_all_host_states")
    def test_alternates_same_cell(self, mock_get_all_hosts, mock_sorted,
            mock_claim, mock_consume):
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
        mock_sorted.side_effect = [all_host_states,
                                   list(reversed(all_host_states)),
                                   all_host_states]
        mock_claim.return_value = True
        total_returned = 3
        self.flags(max_attempts=total_returned, group="scheduler")
        instance_uuids = [uuids.inst1, uuids.inst2]
        num_instances = len(instance_uuids)

        spec_obj = objects.RequestSpec(
                num_instances=num_instances,
                flavor=objects.Flavor(memory_mb=512,
                                      root_gb=512,
                                      ephemeral_gb=0,
                                      swap=0,
                                      vcpus=1),
                project_id=uuids.project_id,
                instance_group=None)

        dests = self.driver._schedule(self.context, spec_obj,
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
    @mock.patch("nova.scheduler.filter_scheduler.FilterScheduler."
                "_get_sorted_hosts")
    @mock.patch("nova.scheduler.filter_scheduler.FilterScheduler."
                "_get_all_host_states")
    def _test_not_enough_alternates(self, mock_get_all_hosts, mock_sorted,
            mock_claim, mock_consume, num_hosts, max_attempts):
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
        mock_sorted.return_value = all_host_states
        mock_claim.return_value = True
        # Set the total returned to more than the number of available hosts
        self.flags(max_attempts=max_attempts, group="scheduler")
        instance_uuids = [uuids.inst1, uuids.inst2]
        num_instances = len(instance_uuids)

        spec_obj = objects.RequestSpec(
                num_instances=num_instances,
                flavor=objects.Flavor(memory_mb=512,
                                      root_gb=512,
                                      ephemeral_gb=0,
                                      swap=0,
                                      vcpus=1),
                project_id=uuids.project_id,
                instance_group=None)

        dests = self.driver._schedule(self.context, spec_obj,
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

    @mock.patch.object(filter_scheduler.FilterScheduler, '_schedule')
    def test_select_destinations_notifications(self, mock_schedule):
        mock_schedule.return_value = ([[mock.Mock()]], [[mock.Mock()]])

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
