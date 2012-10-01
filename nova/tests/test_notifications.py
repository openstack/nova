# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack, LLC.
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

"""Tests for common notifcations."""

import copy

from nova.compute import instance_types
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova import flags
from nova.network import api as network_api
from nova import notifications
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier_api
from nova.openstack.common.notifier import test_notifier
from nova import test
from nova.tests import fake_network

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class NotificationsTestCase(test.TestCase):

    def setUp(self):
        super(NotificationsTestCase, self).setUp()

        self.net_info = fake_network.fake_get_instance_nw_info(self.stubs, 1,
                                                        1, spectacular=True)

        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return self.net_info

        self.stubs.Set(network_api.API, 'get_instance_nw_info',
                fake_get_nw_info)
        fake_network.set_stub_network_methods(self.stubs)

        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   notification_driver=[test_notifier.__name__],
                   network_manager='nova.network.manager.FlatManager',
                   notify_on_state_change="vm_and_task_state",
                   host='testhost')

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        test_notifier.NOTIFICATIONS = []

        self.instance = self._wrapped_create()

    def tearDown(self):
        notifier_api._reset_drivers()
        super(NotificationsTestCase, self).tearDown()

    def _wrapped_create(self, params=None):
        inst = {}
        inst['image_ref'] = 1
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        inst['instance_type_id'] = type_id
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst['access_ip_v4'] = '1.2.3.4'
        inst['access_ip_v6'] = 'feed:5eed'
        inst['display_name'] = 'test_instance'
        if params:
            inst.update(params)
        return db.instance_create(self.context, inst)

    def test_notif_disabled(self):

        # test config disable of the notifcations
        self.flags(notify_on_state_change=None)
        self.flags(notify_on_any_change=False)

        old = copy.copy(self.instance)
        self.instance["vm_state"] = vm_states.ACTIVE

        old_vm_state = old['vm_state']
        new_vm_state = self.instance["vm_state"]
        old_task_state = old['task_state']
        new_task_state = self.instance["task_state"]

        notifications.send_update_with_states(self.context, self.instance,
                old_vm_state, new_vm_state, old_task_state, new_task_state,
                verify_states=True)

        notifications.send_update(self.context, old, self.instance)
        self.assertEquals(0, len(test_notifier.NOTIFICATIONS))

    def test_task_notif(self):

        # test config disable of just the task state notifications
        self.flags(notify_on_state_change="vm_state")

        # we should not get a notification on task stgate chagne now
        old = copy.copy(self.instance)
        self.instance["task_state"] = task_states.SPAWNING

        old_vm_state = old['vm_state']
        new_vm_state = self.instance["vm_state"]
        old_task_state = old['task_state']
        new_task_state = self.instance["task_state"]

        notifications.send_update_with_states(self.context, self.instance,
                old_vm_state, new_vm_state, old_task_state, new_task_state,
                verify_states=True)

        self.assertEquals(0, len(test_notifier.NOTIFICATIONS))

        # ok now enable task state notifcations and re-try
        self.flags(notify_on_state_change="vm_and_task_state")

        notifications.send_update(self.context, old, self.instance)
        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))

    def test_send_no_notif(self):

        # test notification on send no initial vm state:
        old_vm_state = self.instance['vm_state']
        new_vm_state = self.instance['vm_state']
        old_task_state = self.instance['task_state']
        new_task_state = self.instance['task_state']

        notifications.send_update_with_states(self.context, self.instance,
                old_vm_state, new_vm_state, old_task_state, new_task_state,
                service="compute", host=None, verify_states=True)

        self.assertEquals(0, len(test_notifier.NOTIFICATIONS))

    def test_send_on_vm_change(self):

        # pretend we just transitioned to ACTIVE:
        params = {"vm_state": vm_states.ACTIVE}
        (old_ref, new_ref) = db.instance_update_and_get_original(self.context,
                self.instance['uuid'], params)
        notifications.send_update(self.context, old_ref, new_ref)

        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))

    def test_send_on_task_change(self):

        # pretend we just transitioned to task SPAWNING:
        params = {"task_state": task_states.SPAWNING}
        (old_ref, new_ref) = db.instance_update_and_get_original(self.context,
                self.instance['uuid'], params)
        print old_ref["task_state"]
        print new_ref["task_state"]
        notifications.send_update(self.context, old_ref, new_ref)

        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))

    def test_no_update_with_states(self):

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                task_states.SPAWNING, verify_states=True)
        self.assertEquals(0, len(test_notifier.NOTIFICATIONS))

    def test_vm_update_with_states(self):

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.ACTIVE, task_states.SPAWNING,
                task_states.SPAWNING, verify_states=True)
        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))
        notif = test_notifier.NOTIFICATIONS[0]
        payload = notif["payload"]
        access_ip_v4 = self.instance["access_ip_v4"]
        access_ip_v6 = self.instance["access_ip_v6"]
        display_name = self.instance["display_name"]

        self.assertEquals(vm_states.BUILDING, payload["old_state"])
        self.assertEquals(vm_states.ACTIVE, payload["state"])
        self.assertEquals(task_states.SPAWNING, payload["old_task_state"])
        self.assertEquals(task_states.SPAWNING, payload["new_task_state"])
        self.assertEquals(payload["access_ip_v4"], access_ip_v4)
        self.assertEquals(payload["access_ip_v6"], access_ip_v6)
        self.assertEquals(payload["display_name"], display_name)

    def test_task_update_with_states(self):
        self.flags(notify_on_state_change="vm_and_task_state")

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, verify_states=True)
        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))
        notif = test_notifier.NOTIFICATIONS[0]
        payload = notif["payload"]
        access_ip_v4 = self.instance["access_ip_v4"]
        access_ip_v6 = self.instance["access_ip_v6"]
        display_name = self.instance["display_name"]

        self.assertEquals(vm_states.BUILDING, payload["old_state"])
        self.assertEquals(vm_states.BUILDING, payload["state"])
        self.assertEquals(task_states.SPAWNING, payload["old_task_state"])
        self.assertEquals(None, payload["new_task_state"])
        self.assertEquals(payload["access_ip_v4"], access_ip_v4)
        self.assertEquals(payload["access_ip_v6"], access_ip_v6)
        self.assertEquals(payload["display_name"], display_name)

    def test_update_no_service_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None)
        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))

        # service name should default to 'compute'
        notif = test_notifier.NOTIFICATIONS[0]
        self.assertEquals('compute.testhost', notif['publisher_id'])

    def test_update_with_service_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, service="testservice")
        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))

        # service name should default to 'compute'
        notif = test_notifier.NOTIFICATIONS[0]
        self.assertEquals('testservice.testhost', notif['publisher_id'])

    def test_update_with_host_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, host="someotherhost")
        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))

        # service name should default to 'compute'
        notif = test_notifier.NOTIFICATIONS[0]
        self.assertEquals('compute.someotherhost', notif['publisher_id'])

    def test_payload_has_fixed_ip_labels(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info, None)
        self.assertTrue("fixed_ips" in info)
        self.assertEquals(info["fixed_ips"][0]["label"], "test1")

    def test_send_access_ip_update(self):
        notifications.send_update(self.context, self.instance, self.instance)
        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))
        notif = test_notifier.NOTIFICATIONS[0]
        payload = notif["payload"]
        access_ip_v4 = self.instance["access_ip_v4"]
        access_ip_v6 = self.instance["access_ip_v6"]

        self.assertEquals(payload["access_ip_v4"], access_ip_v4)
        self.assertEquals(payload["access_ip_v6"], access_ip_v6)

    def test_send_name_update(self):
        notifications.send_update(self.context, self.instance, self.instance)
        self.assertEquals(1, len(test_notifier.NOTIFICATIONS))
        notif = test_notifier.NOTIFICATIONS[0]
        payload = notif["payload"]
        display_name = self.instance["display_name"]

        self.assertEquals(payload["display_name"], display_name)

    def test_send_no_state_change(self):
        called = [False]

        def sending_no_state_change(context, instance, **kwargs):
            called[0] = True
        self.stubs.Set(notifications, '_send_instance_update_notification',
                       sending_no_state_change)
        notifications.send_update(self.context, self.instance, self.instance)
        self.assertTrue(called[0])

    def test_fail_sending_update(self):
        def fail_sending(context, instance, **kwargs):
            raise Exception('failed to notify')
        self.stubs.Set(notifications, '_send_instance_update_notification',
                       fail_sending)

        notifications.send_update(self.context, self.instance, self.instance)
        self.assertEquals(0, len(test_notifier.NOTIFICATIONS))
