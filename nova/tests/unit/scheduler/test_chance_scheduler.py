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
Tests For Chance Scheduler.
"""
import mock

from nova import exception
from nova import objects
from nova.scheduler import chance
from nova.scheduler import host_manager
from nova.tests.unit.scheduler import test_scheduler
from nova.tests import uuidsentinel as uuids


def _generate_fake_hosts(num):
    hosts = []
    for i in range(num):
        fake_host_state = host_manager.HostState("host%s" % i, "fake_node",
                uuids.cell)
        fake_host_state.uuid = getattr(uuids, "host%s" % i)
        fake_host_state.limits = {}
        hosts.append(fake_host_state)
    return hosts


class ChanceSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Chance Scheduler."""

    driver_cls = chance.ChanceScheduler

    def test_filter_hosts_avoid(self):
        """Test to make sure _filter_hosts() filters original hosts if
        avoid_original_host is True.
        """

        hosts = ['host1', 'host2', 'host3']
        spec_obj = objects.RequestSpec(ignore_hosts=['host2'])

        filtered = self.driver._filter_hosts(hosts, spec_obj=spec_obj)
        self.assertEqual(filtered, ['host1', 'host3'])

    def test_filter_hosts_no_avoid(self):
        """Test to make sure _filter_hosts() does not filter original
        hosts if avoid_original_host is False.
        """

        hosts = ['host1', 'host2', 'host3']
        spec_obj = objects.RequestSpec(ignore_hosts=[])

        filtered = self.driver._filter_hosts(hosts, spec_obj=spec_obj)
        self.assertEqual(filtered, hosts)

    @mock.patch("nova.scheduler.chance.ChanceScheduler.hosts_up")
    def test_select_destinations(self, mock_hosts_up):
        mock_hosts_up.return_value = _generate_fake_hosts(4)
        spec_obj = objects.RequestSpec(num_instances=2, ignore_hosts=None)
        dests = self.driver.select_destinations(self.context, spec_obj,
                [uuids.instance1, uuids.instance2], {},
                mock.sentinel.provider_summaries)

        self.assertEqual(2, len(dests))
        # Test that different hosts were returned
        self.assertIsNot(dests[0], dests[1])

    @mock.patch("nova.scheduler.chance.ChanceScheduler._filter_hosts")
    @mock.patch("nova.scheduler.chance.ChanceScheduler.hosts_up")
    def test_select_destinations_no_valid_host(self, mock_hosts_up,
            mock_filter):
        mock_hosts_up.return_value = _generate_fake_hosts(4)
        mock_filter.return_value = []

        spec_obj = objects.RequestSpec(num_instances=1)
        spec_obj.instance_uuid = uuids.instance
        self.assertRaises(exception.NoValidHost,
                          self.driver.select_destinations, self.context,
                          spec_obj, [spec_obj.instance_uuid], {},
                          mock.sentinel.provider_summaries)

    @mock.patch("nova.scheduler.chance.ChanceScheduler.hosts_up")
    def test_schedule_success_single_instance(self, mock_hosts_up):
        hosts = _generate_fake_hosts(20)
        mock_hosts_up.return_value = hosts
        spec_obj = objects.RequestSpec(num_instances=1, ignore_hosts=None)
        spec_obj.instance_uuid = uuids.instance
        # Set the max_attempts to 2
        attempts = 2
        expected = attempts
        self.flags(max_attempts=attempts, group="scheduler")
        selected_hosts = self.driver._schedule(self.context, "compute",
                spec_obj, [spec_obj.instance_uuid], return_alternates=True)
        self.assertEqual(1, len(selected_hosts))
        for host_list in selected_hosts:
            self.assertEqual(expected, len(host_list))

        # Now set max_attempts to a number larger than the available hosts. It
        # should return a host_list containing only as many hosts as there are
        # to choose from.
        attempts = len(hosts) + 1
        expected = len(hosts)
        self.flags(max_attempts=attempts, group="scheduler")
        selected_hosts = self.driver._schedule(self.context, "compute",
                spec_obj, [spec_obj.instance_uuid], return_alternates=True)
        self.assertEqual(1, len(selected_hosts))
        for host_list in selected_hosts:
            self.assertEqual(expected, len(host_list))

        # Now verify that if we pass False for return_alternates, that we only
        # get one host in the host_list.
        attempts = 5
        expected = 1
        self.flags(max_attempts=attempts, group="scheduler")
        selected_hosts = self.driver._schedule(self.context, "compute",
                spec_obj, [spec_obj.instance_uuid], return_alternates=False)
        self.assertEqual(1, len(selected_hosts))
        for host_list in selected_hosts:
            self.assertEqual(expected, len(host_list))

    @mock.patch("nova.scheduler.chance.ChanceScheduler.hosts_up")
    def test_schedule_success_multiple_instances(self, mock_hosts_up):
        hosts = _generate_fake_hosts(20)
        mock_hosts_up.return_value = hosts
        num_instances = 4
        spec_obj = objects.RequestSpec(num_instances=num_instances,
                ignore_hosts=None)
        instance_uuids = [getattr(uuids, "inst%s" % i)
                for i in range(num_instances)]
        spec_obj.instance_uuid = instance_uuids[0]
        # Set the max_attempts to 2
        attempts = 2
        self.flags(max_attempts=attempts, group="scheduler")
        selected_hosts = self.driver._schedule(self.context, "compute",
                spec_obj, instance_uuids, return_alternates=True)
        self.assertEqual(num_instances, len(selected_hosts))
        for host_list in selected_hosts:
            self.assertEqual(attempts, len(host_list))
        # Verify that none of the selected hosts appear as alternates
        # Set the max_attempts to 5 to get 4 alternates per instance
        attempts = 4
        self.flags(max_attempts=attempts, group="scheduler")
        result = self.driver._schedule(self.context, "compute", spec_obj,
                instance_uuids)
        selected = [host_list[0] for host_list in result]
        for host_list in result:
            for sel in selected:
                self.assertNotIn(sel, host_list[1:])
