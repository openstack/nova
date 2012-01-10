# Copyright 2011 OpenStack LLC.
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

from nova import test
from nova.scheduler import chance


class ChanceSchedulerTestCase(test.TestCase):
    """Test case for Chance Scheduler."""

    def test_filter_hosts_avoid(self):
        """Test to make sure _filter_hosts() filters original hosts if
        avoid_original_host is True."""

        sched = chance.ChanceScheduler()

        hosts = ['host1', 'host2', 'host3']
        request_spec = dict(instance_properties=dict(host='host2'),
                            avoid_original_host=True)

        filtered = sched._filter_hosts(request_spec, hosts)
        self.assertEqual(filtered, ['host1', 'host3'])

    def test_filter_hosts_no_avoid(self):
        """Test to make sure _filter_hosts() does not filter original
        hosts if avoid_original_host is False."""

        sched = chance.ChanceScheduler()

        hosts = ['host1', 'host2', 'host3']
        request_spec = dict(instance_properties=dict(host='host2'),
                            avoid_original_host=False)

        filtered = sched._filter_hosts(request_spec, hosts)
        self.assertEqual(filtered, hosts)
