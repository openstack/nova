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

import mox

from nova.compute import rpcapi as compute_rpcapi
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.scheduler import chance
from nova.scheduler import driver
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
        instance_opts = {'fake_opt1': 'meow', 'launch_index': -1}
        instance1 = {'uuid': 'fake-uuid1'}
        instance2 = {'uuid': 'fake-uuid2'}
        request_spec = {'instance_uuids': ['fake-uuid1', 'fake-uuid2'],
                        'instance_properties': instance_opts}
        instance1_encoded = {'uuid': 'fake-uuid1', '_is_precooked': False}
        instance2_encoded = {'uuid': 'fake-uuid2', '_is_precooked': False}
        reservations = ['resv1', 'resv2']

        def inc_launch_index(*args):
            request_spec['instance_properties']['launch_index'] = (
                request_spec['instance_properties']['launch_index'] + 1)

        self.mox.StubOutWithMock(ctxt, 'elevated')
        self.mox.StubOutWithMock(self.driver, 'hosts_up')
        self.mox.StubOutWithMock(random, 'random')
        self.mox.StubOutWithMock(driver, 'instance_update_db')
        self.mox.StubOutWithMock(compute_rpcapi.ComputeAPI, 'run_instance')

        ctxt.elevated().AndReturn(ctxt_elevated)
        # instance 1
        self.driver.hosts_up(ctxt_elevated, 'compute').AndReturn(
                ['host1', 'host2', 'host3', 'host4'])
        random.random().AndReturn(.5)
        driver.instance_update_db(ctxt, instance1['uuid']).WithSideEffects(
                inc_launch_index).AndReturn(instance1)
        compute_rpcapi.ComputeAPI.run_instance(ctxt, host='host3',
                instance=instance1, requested_networks=None,
                injected_files=None, admin_password=None, is_first_time=None,
                request_spec=request_spec, filter_properties={})

        # instance 2
        ctxt.elevated().AndReturn(ctxt_elevated)
        self.driver.hosts_up(ctxt_elevated, 'compute').AndReturn(
                ['host1', 'host2', 'host3', 'host4'])
        random.random().AndReturn(.2)
        driver.instance_update_db(ctxt, instance2['uuid']).WithSideEffects(
                inc_launch_index).AndReturn(instance2)
        compute_rpcapi.ComputeAPI.run_instance(ctxt, host='host1',
                instance=instance2, requested_networks=None,
                injected_files=None, admin_password=None, is_first_time=None,
                request_spec=request_spec, filter_properties={})

        self.mox.ReplayAll()
        self.driver.schedule_run_instance(ctxt, request_spec,
                None, None, None, None, {})

    def test_basic_schedule_run_instance_no_hosts(self):
        ctxt = context.RequestContext('fake', 'fake', False)
        ctxt_elevated = 'fake-context-elevated'
        fake_args = (1, 2, 3)
        uuid = 'fake-uuid1'
        instance_opts = {'fake_opt1': 'meow', 'launch_index': -1}
        request_spec = {'instance_uuids': [uuid],
                        'instance_properties': instance_opts}

        self.mox.StubOutWithMock(ctxt, 'elevated')
        self.mox.StubOutWithMock(self.driver, 'hosts_up')
        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        # instance 1
        ctxt.elevated().AndReturn(ctxt_elevated)
        self.driver.hosts_up(ctxt_elevated, 'compute').AndReturn([])
        compute_utils.add_instance_fault_from_exc(ctxt,
                uuid, mox.IsA(exception.NoValidHost), mox.IgnoreArg())
        db.instance_update_and_get_original(ctxt, uuid,
                {'vm_state': vm_states.ERROR,
                 'task_state': None}).AndReturn(({}, {}))

        self.mox.ReplayAll()
        self.driver.schedule_run_instance(
                ctxt, request_spec, None, None, None, None, {})

    def test_schedule_prep_resize_doesnt_update_host(self):
        fake_context = context.RequestContext('user', 'project',
                is_admin=True)

        def _return_host(*args, **kwargs):
            return 'host2'

        self.stubs.Set(self.driver, '_schedule', _return_host)

        info = {'called': 0}

        def _fake_instance_update_db(*args, **kwargs):
            # This should not be called
            info['called'] = 1

        self.stubs.Set(driver, 'instance_update_db',
                _fake_instance_update_db)

        instance = {'uuid': 'fake-uuid', 'host': 'host1'}

        self.driver.schedule_prep_resize(fake_context, {}, {}, {},
                instance, {}, None)
        self.assertEqual(info['called'], 0)
