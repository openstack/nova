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
from nova.tests.unit.scheduler import test_scheduler
from nova.tests import uuidsentinel as uuids


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

    @mock.patch('random.choice')
    def test_select_destinations(self, mock_random_choice):
        all_hosts = ['host1', 'host2', 'host3', 'host4']

        def _return_hosts(*args, **kwargs):
            return all_hosts

        mock_random_choice.side_effect = ['host3', 'host2']
        self.stub_out('nova.scheduler.chance.ChanceScheduler.hosts_up',
                      _return_hosts)

        spec_obj = objects.RequestSpec(num_instances=2, ignore_hosts=None)
        dests = self.driver.select_destinations(self.context, spec_obj,
                [uuids.instance1, uuids.instance2], {},
                mock.sentinel.p_sums)

        self.assertEqual(2, len(dests))
        (host, node) = (dests[0].host, dests[0].nodename)
        self.assertEqual('host3', host)
        self.assertIsNone(node)
        (host, node) = (dests[1].host, dests[1].nodename)
        self.assertEqual('host2', host)
        self.assertIsNone(node)

        calls = [mock.call(all_hosts), mock.call(all_hosts)]
        self.assertEqual(calls, mock_random_choice.call_args_list)

    def test_select_destinations_no_valid_host(self):

        def _return_hosts(*args, **kwargs):
            return ['host1', 'host2']

        def _return_no_host(*args, **kwargs):
            return []

        self.stub_out('nova.scheduler.chance.ChanceScheduler.hosts_up',
                      _return_hosts)
        self.stub_out('nova.scheduler.chance.ChanceScheduler._filter_hosts',
                      _return_no_host)

        spec_obj = objects.RequestSpec(num_instances=1)
        spec_obj.instance_uuid = uuids.instance
        self.assertRaises(exception.NoValidHost,
                          self.driver.select_destinations, self.context,
                          spec_obj, [spec_obj.instance_uuid], {},
                          mock.sentinel.p_sums)
