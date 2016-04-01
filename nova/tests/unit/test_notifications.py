# Copyright (c) 2012 OpenStack Foundation
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

"""Tests for common notifications."""

import copy

import mock
from oslo_context import context as o_context
from oslo_context import fixture as o_fixture

from nova.compute import flavors
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import exception
from nova import notifications
from nova import objects
from nova.objects import base as obj_base
from nova import test
from nova.tests.unit import fake_network
from nova.tests.unit import fake_notifier


class NotificationsTestCase(test.TestCase):

    def setUp(self):
        super(NotificationsTestCase, self).setUp()
        self.fixture = self.useFixture(o_fixture.ClearRequestContext())

        self.net_info = fake_network.fake_get_instance_nw_info(self, 1,
                                                               1)

        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return self.net_info

        self.stub_out('nova.network.api.API.get_instance_nw_info',
                fake_get_nw_info)
        fake_network.set_stub_network_methods(self)

        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   network_manager='nova.network.manager.FlatManager',
                   notify_on_state_change="vm_and_task_state",
                   host='testhost')

        self.flags(api_servers=['http://localhost:9292'], group='glance')

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

        self.instance = self._wrapped_create()

        self.decorated_function_called = False

    def _wrapped_create(self, params=None):
        instance_type = flavors.get_flavor_by_name('m1.tiny')
        inst = objects.Instance(image_ref=1,
                                user_id=self.user_id,
                                project_id=self.project_id,
                                instance_type_id=instance_type['id'],
                                root_gb=0,
                                ephemeral_gb=0,
                                access_ip_v4='1.2.3.4',
                                access_ip_v6='feed::5eed',
                                display_name='test_instance',
                                hostname='test_instance_hostname',
                                node='test_instance_node',
                                system_metadata={})
        inst._context = self.context
        if params:
            inst.update(params)
        inst.flavor = instance_type
        inst.create()
        return inst

    def test_send_api_fault_disabled(self):
        self.flags(notify_api_faults=False)
        notifications.send_api_fault("http://example.com/foo", 500, None)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))

    def test_send_api_fault(self):
        self.flags(notify_api_faults=True)
        exception = None
        try:
            # Get a real exception with a call stack.
            raise test.TestingException("junk")
        except test.TestingException as e:
            exception = e

        notifications.send_api_fault("http://example.com/foo", 500, exception)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        n = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(n.priority, 'ERROR')
        self.assertEqual(n.event_type, 'api.fault')
        self.assertEqual(n.payload['url'], 'http://example.com/foo')
        self.assertEqual(n.payload['status'], 500)
        self.assertIsNotNone(n.payload['exception'])

    def test_send_api_fault_fresh_context(self):
        self.flags(notify_api_faults=True)
        exception = None
        try:
            # Get a real exception with a call stack.
            raise test.TestingException("junk")
        except test.TestingException as e:
            exception = e

        ctxt = context.RequestContext(overwrite=True)
        notifications.send_api_fault("http://example.com/foo", 500, exception)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        n = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(n.priority, 'ERROR')
        self.assertEqual(n.event_type, 'api.fault')
        self.assertEqual(n.payload['url'], 'http://example.com/foo')
        self.assertEqual(n.payload['status'], 500)
        self.assertIsNotNone(n.payload['exception'])
        self.assertEqual(ctxt, n.context)

    def test_send_api_fault_fake_context(self):
        self.flags(notify_api_faults=True)
        exception = None
        try:
            # Get a real exception with a call stack.
            raise test.TestingException("junk")
        except test.TestingException as e:
            exception = e

        ctxt = o_context.get_current()
        self.assertIsNotNone(ctxt)
        notifications.send_api_fault("http://example.com/foo", 500, exception)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        n = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(n.priority, 'ERROR')
        self.assertEqual(n.event_type, 'api.fault')
        self.assertEqual(n.payload['url'], 'http://example.com/foo')
        self.assertEqual(n.payload['status'], 500)
        self.assertIsNotNone(n.payload['exception'])
        self.assertIsNotNone(n.context)
        self.assertEqual(ctxt, n.context)

    def test_send_api_fault_admin_context(self):
        self.flags(notify_api_faults=True)
        exception = None
        try:
            # Get a real exception with a call stack.
            raise test.TestingException("junk")
        except test.TestingException as e:
            exception = e

        self.fixture._remove_cached_context()
        self.assertIsNone(o_context.get_current())
        notifications.send_api_fault("http://example.com/foo", 500, exception)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        n = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(n.priority, 'ERROR')
        self.assertEqual(n.event_type, 'api.fault')
        self.assertEqual(n.payload['url'], 'http://example.com/foo')
        self.assertEqual(n.payload['status'], 500)
        self.assertIsNotNone(n.payload['exception'])
        self.assertIsNotNone(n.context)
        self.assertTrue(n.context.is_admin)

    def test_notif_disabled(self):

        # test config disable of the notifications
        self.flags(notify_on_state_change=None)

        old = copy.copy(self.instance)
        self.instance.vm_state = vm_states.ACTIVE

        old_vm_state = old['vm_state']
        new_vm_state = self.instance.vm_state
        old_task_state = old['task_state']
        new_task_state = self.instance.task_state

        notifications.send_update_with_states(self.context, self.instance,
                old_vm_state, new_vm_state, old_task_state, new_task_state,
                verify_states=True)

        notifications.send_update(self.context, old, self.instance)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))

    def test_task_notif(self):

        # test config disable of just the task state notifications
        self.flags(notify_on_state_change="vm_state")

        # we should not get a notification on task stgate chagne now
        old = copy.copy(self.instance)
        self.instance.task_state = task_states.SPAWNING

        old_vm_state = old['vm_state']
        new_vm_state = self.instance.vm_state
        old_task_state = old['task_state']
        new_task_state = self.instance.task_state

        notifications.send_update_with_states(self.context, self.instance,
                old_vm_state, new_vm_state, old_task_state, new_task_state,
                verify_states=True)

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))

        # ok now enable task state notifications and re-try
        self.flags(notify_on_state_change="vm_and_task_state")

        notifications.send_update(self.context, old, self.instance)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

    def test_send_no_notif(self):

        # test notification on send no initial vm state:
        old_vm_state = self.instance.vm_state
        new_vm_state = self.instance.vm_state
        old_task_state = self.instance.task_state
        new_task_state = self.instance.task_state

        notifications.send_update_with_states(self.context, self.instance,
                old_vm_state, new_vm_state, old_task_state, new_task_state,
                service="compute", host=None, verify_states=True)

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))

    def test_send_on_vm_change(self):
        old = obj_base.obj_to_primitive(self.instance)
        old['vm_state'] = None
        # pretend we just transitioned to ACTIVE:
        self.instance.vm_state = vm_states.ACTIVE
        notifications.send_update(self.context, old, self.instance)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        # service name should default to 'compute'
        notif = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('compute.testhost', notif.publisher_id)

    def test_send_on_task_change(self):

        old = obj_base.obj_to_primitive(self.instance)
        old['task_state'] = None
        # pretend we just transitioned to task SPAWNING:
        self.instance.task_state = task_states.SPAWNING
        notifications.send_update(self.context, old, self.instance)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

    def test_no_update_with_states(self):

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                task_states.SPAWNING, verify_states=True)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))

    def test_vm_update_with_states(self):

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.ACTIVE, task_states.SPAWNING,
                task_states.SPAWNING, verify_states=True)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        notif = fake_notifier.NOTIFICATIONS[0]
        payload = notif.payload
        access_ip_v4 = str(self.instance.access_ip_v4)
        access_ip_v6 = str(self.instance.access_ip_v6)
        display_name = self.instance.display_name
        hostname = self.instance.hostname
        node = self.instance.node

        self.assertEqual(vm_states.BUILDING, payload["old_state"])
        self.assertEqual(vm_states.ACTIVE, payload["state"])
        self.assertEqual(task_states.SPAWNING, payload["old_task_state"])
        self.assertEqual(task_states.SPAWNING, payload["new_task_state"])
        self.assertEqual(payload["access_ip_v4"], access_ip_v4)
        self.assertEqual(payload["access_ip_v6"], access_ip_v6)
        self.assertEqual(payload["display_name"], display_name)
        self.assertEqual(payload["hostname"], hostname)
        self.assertEqual(payload["node"], node)

    def test_task_update_with_states(self):
        self.flags(notify_on_state_change="vm_and_task_state")

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, verify_states=True)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        notif = fake_notifier.NOTIFICATIONS[0]
        payload = notif.payload
        access_ip_v4 = str(self.instance.access_ip_v4)
        access_ip_v6 = str(self.instance.access_ip_v6)
        display_name = self.instance.display_name
        hostname = self.instance.hostname

        self.assertEqual(vm_states.BUILDING, payload["old_state"])
        self.assertEqual(vm_states.BUILDING, payload["state"])
        self.assertEqual(task_states.SPAWNING, payload["old_task_state"])
        self.assertIsNone(payload["new_task_state"])
        self.assertEqual(payload["access_ip_v4"], access_ip_v4)
        self.assertEqual(payload["access_ip_v6"], access_ip_v6)
        self.assertEqual(payload["display_name"], display_name)
        self.assertEqual(payload["hostname"], hostname)

    def test_update_no_service_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

        # service name should default to 'compute'
        notif = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('compute.testhost', notif.publisher_id)

    def test_update_with_service_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, service="testservice")
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

        # service name should default to 'compute'
        notif = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('testservice.testhost', notif.publisher_id)

    def test_update_with_host_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, host="someotherhost")
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

        # service name should default to 'compute'
        notif = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('compute.someotherhost', notif.publisher_id)

    def test_payload_has_fixed_ip_labels(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info, None)
        self.assertIn("fixed_ips", info)
        self.assertEqual(info["fixed_ips"][0]["label"], "test1")

    def test_payload_has_vif_mac_address(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info, None)
        self.assertIn("fixed_ips", info)
        self.assertEqual(self.net_info[0]['address'],
                         info["fixed_ips"][0]["vif_mac"])

    def test_payload_has_cell_name_empty(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info, None)
        self.assertIn("cell_name", info)
        self.assertIsNone(self.instance.cell_name)
        self.assertEqual("", info["cell_name"])

    def test_payload_has_cell_name(self):
        self.instance.cell_name = "cell1"
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info, None)
        self.assertIn("cell_name", info)
        self.assertEqual("cell1", info["cell_name"])

    def test_payload_has_progress_empty(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info, None)
        self.assertIn("progress", info)
        self.assertIsNone(self.instance.progress)
        self.assertEqual("", info["progress"])

    def test_payload_has_progress(self):
        self.instance.progress = 50
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info, None)
        self.assertIn("progress", info)
        self.assertEqual(50, info["progress"])

    def test_send_access_ip_update(self):
        notifications.send_update(self.context, self.instance, self.instance)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        notif = fake_notifier.NOTIFICATIONS[0]
        payload = notif.payload
        access_ip_v4 = str(self.instance.access_ip_v4)
        access_ip_v6 = str(self.instance.access_ip_v6)

        self.assertEqual(payload["access_ip_v4"], access_ip_v4)
        self.assertEqual(payload["access_ip_v6"], access_ip_v6)

    def test_send_name_update(self):
        param = {"display_name": "new_display_name"}
        new_name_inst = self._wrapped_create(params=param)
        notifications.send_update(self.context, self.instance, new_name_inst)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        notif = fake_notifier.NOTIFICATIONS[0]
        payload = notif.payload
        old_display_name = self.instance.display_name
        new_display_name = new_name_inst.display_name

        self.assertEqual(payload["old_display_name"], old_display_name)
        self.assertEqual(payload["display_name"], new_display_name)

    def test_send_no_state_change(self):
        called = [False]

        def sending_no_state_change(context, instance, **kwargs):
            called[0] = True
        self.stub_out('nova.notifications._send_instance_update_notification',
                       sending_no_state_change)
        notifications.send_update(self.context, self.instance, self.instance)
        self.assertTrue(called[0])

    def test_fail_sending_update(self):
        def fail_sending(context, instance, **kwargs):
            raise Exception('failed to notify')
        self.stub_out('nova.notifications._send_instance_update_notification',
                       fail_sending)

        notifications.send_update(self.context, self.instance, self.instance)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))

    @mock.patch.object(notifications.LOG, 'exception')
    def test_fail_sending_update_instance_not_found(self, mock_log_exception):
        # Tests that InstanceNotFound is handled as an expected exception and
        # not logged as an error.
        notfound = exception.InstanceNotFound(instance_id=self.instance.uuid)
        with mock.patch.object(notifications,
                               '_send_instance_update_notification',
                               side_effect=notfound):
            notifications.send_update(
                self.context, self.instance, self.instance)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(0, mock_log_exception.call_count)

    @mock.patch.object(notifications.LOG, 'exception')
    def test_fail_send_update_with_states_inst_not_found(self,
                                                         mock_log_exception):
        # Tests that InstanceNotFound is handled as an expected exception and
        # not logged as an error.
        notfound = exception.InstanceNotFound(instance_id=self.instance.uuid)
        with mock.patch.object(notifications,
                               '_send_instance_update_notification',
                               side_effect=notfound):
            notifications.send_update_with_states(
                self.context, self.instance,
                vm_states.BUILDING, vm_states.ERROR,
                task_states.NETWORKING, new_task_state=None)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(0, mock_log_exception.call_count)

    def _decorated_function(self, arg1, arg2):
        self.decorated_function_called = True

    def test_notify_decorator(self):
        func_name = self._decorated_function.__name__

        # Decorated with notify_decorator like monkey_patch
        self._decorated_function = notifications.notify_decorator(
            func_name,
            self._decorated_function)

        ctxt = o_context.RequestContext()

        self._decorated_function(1, ctxt)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        n = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(n.priority, 'INFO')
        self.assertEqual(n.event_type, func_name)
        self.assertEqual(n.context, ctxt)
        self.assertTrue(self.decorated_function_called)


class NotificationsFormatTestCase(test.NoDBTestCase):

    def test_state_computation(self):
        instance = {'vm_state': mock.sentinel.vm_state,
                    'task_state': mock.sentinel.task_state}
        states = notifications._compute_states_payload(instance)
        self.assertEqual(mock.sentinel.vm_state, states['state'])
        self.assertEqual(mock.sentinel.vm_state, states['old_state'])
        self.assertEqual(mock.sentinel.task_state, states['old_task_state'])
        self.assertEqual(mock.sentinel.task_state, states['new_task_state'])

        states = notifications._compute_states_payload(
            instance,
            old_vm_state=mock.sentinel.old_vm_state,
        )
        self.assertEqual(mock.sentinel.vm_state, states['state'])
        self.assertEqual(mock.sentinel.old_vm_state, states['old_state'])
        self.assertEqual(mock.sentinel.task_state, states['old_task_state'])
        self.assertEqual(mock.sentinel.task_state, states['new_task_state'])

        states = notifications._compute_states_payload(
            instance,
            old_vm_state=mock.sentinel.old_vm_state,
            old_task_state=mock.sentinel.old_task_state,
            new_vm_state=mock.sentinel.new_vm_state,
            new_task_state=mock.sentinel.new_task_state,
        )

        self.assertEqual(mock.sentinel.new_vm_state, states['state'])
        self.assertEqual(mock.sentinel.old_vm_state, states['old_state'])
        self.assertEqual(mock.sentinel.old_task_state,
                         states['old_task_state'])
        self.assertEqual(mock.sentinel.new_task_state,
                         states['new_task_state'])
