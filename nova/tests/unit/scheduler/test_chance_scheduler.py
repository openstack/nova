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

import random

from mox3 import mox

from nova import context
from nova import exception
from nova.scheduler import chance
from nova.tests.unit.scheduler import test_scheduler


class ChanceSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Chance Scheduler."""

    driver_cls = chance.ChanceScheduler

    def test_filter_hosts_avoid(self):
        """Test to make sure _filter_hosts() filters original hosts if
        avoid_original_host is True.
        """

        hosts = ['host1', 'host2', 'host3']
        request_spec = dict(instance_properties=dict(host='host2'))
        filter_properties = {'ignore_hosts': ['host2']}

        filtered = self.driver._filter_hosts(request_spec, hosts,
                filter_properties=filter_properties)
        self.assertEqual(filtered, ['host1', 'host3'])

    def test_filter_hosts_no_avoid(self):
        """Test to make sure _filter_hosts() does not filter original
        hosts if avoid_original_host is False.
        """

        hosts = ['host1', 'host2', 'host3']
        request_spec = dict(instance_properties=dict(host='host2'))
        filter_properties = {'ignore_hosts': []}

        filtered = self.driver._filter_hosts(request_spec, hosts,
                filter_properties=filter_properties)
        self.assertEqual(filtered, hosts)

    def test_select_destinations(self):
        ctxt = context.RequestContext('fake', 'fake', False)
        ctxt_elevated = 'fake-context-elevated'
        request_spec = {'num_instances': 2}

        self.mox.StubOutWithMock(ctxt, 'elevated')
        self.mox.StubOutWithMock(self.driver, 'hosts_up')
        self.mox.StubOutWithMock(random, 'choice')

        hosts_full = ['host1', 'host2', 'host3', 'host4']

        ctxt.elevated().AndReturn(ctxt_elevated)
        self.driver.hosts_up(ctxt_elevated, 'compute').AndReturn(hosts_full)
        random.choice(hosts_full).AndReturn('host3')

        ctxt.elevated().AndReturn(ctxt_elevated)
        self.driver.hosts_up(ctxt_elevated, 'compute').AndReturn(hosts_full)
        random.choice(hosts_full).AndReturn('host2')

        self.mox.ReplayAll()
        dests = self.driver.select_destinations(ctxt, request_spec, {})
        self.assertEqual(2, len(dests))
        (host, node) = (dests[0]['host'], dests[0]['nodename'])
        self.assertEqual('host3', host)
        self.assertIsNone(node)
        (host, node) = (dests[1]['host'], dests[1]['nodename'])
        self.assertEqual('host2', host)
        self.assertIsNone(node)

    def test_select_destinations_no_valid_host(self):

        def _return_no_host(*args, **kwargs):
            return []

        self.mox.StubOutWithMock(self.driver, 'hosts_up')
        self.driver.hosts_up(mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn([1, 2])
        self.stubs.Set(self.driver, '_filter_hosts', _return_no_host)
        self.mox.ReplayAll()

        request_spec = {'num_instances': 1}
        self.assertRaises(exception.NoValidHost,
                          self.driver.select_destinations, self.context,
                          request_spec, {})
