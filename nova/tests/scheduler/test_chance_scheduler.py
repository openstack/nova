# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import random

from nova import context
from nova import exception
from nova.scheduler import driver
from nova.scheduler import chance
from nova.tests.scheduler import test_scheduler


class ChanceSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Chance Scheduler."""

    driver_cls = chance.ChanceScheduler

    def test_filter_hosts_avoid(self):
        """Test to make sure _filter_hosts() filters original hosts if
        avoid_original_host is True."""

        hosts = ['host1', 'host2', 'host3']
        request_spec = dict(instance_properties=dict(host='host2'))
        filter_properties = {'ignore_hosts': ['host2']}

        filtered = self.driver._filter_hosts(request_spec, hosts,
                filter_properties=filter_properties)
        self.assertEqual(filtered, ['host1', 'host3'])

    def test_filter_hosts_no_avoid(self):
        """Test to make sure _filter_hosts() does not filter original
        hosts if avoid_original_host is False."""

        hosts = ['host1', 'host2', 'host3']
        request_spec = dict(instance_properties=dict(host='host2'))
        filter_properties = {'ignore_hosts': []}

        filtered = self.driver._filter_hosts(request_spec, hosts,
                filter_properties=filter_properties)
        self.assertEqual(filtered, hosts)

    def test_basic_schedule_run_instance(self):
        ctxt = context.RequestContext('fake', 'fake', False)
        ctxt_elevated = 'fake-context-elevated'
        fake_args = (1, 2, 3)
        fake_kwargs = {'fake_kwarg1': 'fake_value1',
                       'fake_kwarg2': 'fake_value2'}
        instance_opts = {'fake_opt1': 'meow'}
        request_spec = {'num_instances': 2,
                        'instance_properties': instance_opts}
        instance1 = {'uuid': 'fake-uuid1'}
        instance2 = {'uuid': 'fake-uuid2'}
        instance1_encoded = {'uuid': 'fake-uuid1', '_is_precooked': False}
        instance2_encoded = {'uuid': 'fake-uuid2', '_is_precooked': False}

        # create_instance_db_entry() usually does this, but we're
        # stubbing it.
        def _add_uuid1(ctxt, request_spec):
            request_spec['instance_properties']['uuid'] = 'fake-uuid1'

        def _add_uuid2(ctxt, request_spec):
            request_spec['instance_properties']['uuid'] = 'fake-uuid2'

        self.mox.StubOutWithMock(ctxt, 'elevated')
        self.mox.StubOutWithMock(self.driver, 'hosts_up')
        self.mox.StubOutWithMock(random, 'random')
        self.mox.StubOutWithMock(self.driver, 'create_instance_db_entry')
        self.mox.StubOutWithMock(driver, 'cast_to_compute_host')
        self.mox.StubOutWithMock(driver, 'encode_instance')

        ctxt.elevated().AndReturn(ctxt_elevated)
        # instance 1
        self.driver.hosts_up(ctxt_elevated, 'compute').AndReturn(
                ['host1', 'host2', 'host3', 'host4'])
        random.random().AndReturn(.5)
        self.driver.create_instance_db_entry(ctxt,
                request_spec).WithSideEffects(_add_uuid1).AndReturn(
                instance1)
        driver.cast_to_compute_host(ctxt, 'host3', 'run_instance',
                instance_uuid=instance1['uuid'], **fake_kwargs)
        driver.encode_instance(instance1).AndReturn(instance1_encoded)
        # instance 2
        ctxt.elevated().AndReturn(ctxt_elevated)
        self.driver.hosts_up(ctxt_elevated, 'compute').AndReturn(
                ['host1', 'host2', 'host3', 'host4'])
        random.random().AndReturn(.2)
        self.driver.create_instance_db_entry(ctxt,
                request_spec).WithSideEffects(_add_uuid2).AndReturn(
                instance2)
        driver.cast_to_compute_host(ctxt, 'host1', 'run_instance',
                instance_uuid=instance2['uuid'], **fake_kwargs)
        driver.encode_instance(instance2).AndReturn(instance2_encoded)

        self.mox.ReplayAll()
        result = self.driver.schedule_run_instance(ctxt, request_spec,
                *fake_args, **fake_kwargs)
        expected = [instance1_encoded, instance2_encoded]
        self.assertEqual(result, expected)

    def test_basic_schedule_run_instance_no_hosts(self):
        ctxt = context.RequestContext('fake', 'fake', False)
        ctxt_elevated = 'fake-context-elevated'
        fake_args = (1, 2, 3)
        fake_kwargs = {'fake_kwarg1': 'fake_value1',
                       'fake_kwarg2': 'fake_value2'}
        instance_opts = 'fake_instance_opts'
        request_spec = {'num_instances': 2,
                        'instance_properties': instance_opts}

        self.mox.StubOutWithMock(ctxt, 'elevated')
        self.mox.StubOutWithMock(self.driver, 'hosts_up')

        # instance 1
        ctxt.elevated().AndReturn(ctxt_elevated)
        self.driver.hosts_up(ctxt_elevated, 'compute').AndReturn([])

        self.mox.ReplayAll()
        self.assertRaises(exception.NoValidHost,
                self.driver.schedule_run_instance, ctxt, request_spec,
                *fake_args, **fake_kwargs)

    def test_basic_schedule_fallback(self):
        ctxt = context.RequestContext('fake', 'fake', False)
        ctxt_elevated = 'fake-context-elevated'
        topic = 'fake_topic'
        method = 'fake_method'
        fake_args = (1, 2, 3)
        fake_kwargs = {'fake_kwarg1': 'fake_value1',
                       'fake_kwarg2': 'fake_value2'}

        self.mox.StubOutWithMock(ctxt, 'elevated')
        self.mox.StubOutWithMock(self.driver, 'hosts_up')
        self.mox.StubOutWithMock(random, 'random')
        self.mox.StubOutWithMock(driver, 'cast_to_host')

        ctxt.elevated().AndReturn(ctxt_elevated)
        self.driver.hosts_up(ctxt_elevated, topic).AndReturn(
                ['host1', 'host2', 'host3', 'host4'])
        random.random().AndReturn(.5)
        driver.cast_to_host(ctxt, topic, 'host3', method, **fake_kwargs)

        self.mox.ReplayAll()
        self.driver.schedule(ctxt, topic, method, *fake_args, **fake_kwargs)

    def test_basic_schedule_fallback_no_hosts(self):
        ctxt = context.RequestContext('fake', 'fake', False)
        ctxt_elevated = 'fake-context-elevated'
        topic = 'fake_topic'
        method = 'fake_method'
        fake_args = (1, 2, 3)
        fake_kwargs = {'fake_kwarg1': 'fake_value1',
                       'fake_kwarg2': 'fake_value2'}

        self.mox.StubOutWithMock(ctxt, 'elevated')
        self.mox.StubOutWithMock(self.driver, 'hosts_up')

        ctxt.elevated().AndReturn(ctxt_elevated)
        self.driver.hosts_up(ctxt_elevated, topic).AndReturn([])

        self.mox.ReplayAll()
        self.assertRaises(exception.NoValidHost,
                self.driver.schedule, ctxt, topic, method,
                *fake_args, **fake_kwargs)
