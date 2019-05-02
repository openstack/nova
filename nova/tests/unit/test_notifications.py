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
import datetime

import mock
from oslo_config import cfg
from oslo_context import fixture as o_fixture
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import exception
from nova.notifications import base as notifications
from nova import objects
from nova.objects import base as obj_base
from nova import test
from nova.tests.unit import fake_network
from nova.tests.unit import fake_notifier


CONF = cfg.CONF


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

        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        self.flags(host='testhost')
        self.flags(notify_on_state_change="vm_and_task_state",
                   group='notifications')

        self.flags(api_servers=['http://localhost:9292'], group='glance')

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

        self.fake_time = datetime.datetime(2017, 2, 2, 16, 45, 0)
        timeutils.set_time_override(self.fake_time)

        self.instance = self._wrapped_create()

        self.decorated_function_called = False

    def _wrapped_create(self, params=None):
        instance_type = objects.Flavor.get_by_name(self.context, 'm1.tiny')
        inst = objects.Instance(image_ref=uuids.image_ref,
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

    def test_notif_disabled(self):

        # test config disable of the notifications
        self.flags(notify_on_state_change=None, group='notifications')

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
        self.assertEqual(0, len(fake_notifier.VERSIONED_NOTIFICATIONS))

    def test_task_notif(self):

        # test config disable of just the task state notifications
        self.flags(notify_on_state_change="vm_state", group='notifications')

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
        self.assertEqual(0, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        # ok now enable task state notifications and re-try
        self.flags(notify_on_state_change="vm_and_task_state",
                   group='notifications')

        notifications.send_update(self.context, old, self.instance)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        self.assertEqual(
                'instance.update',
                fake_notifier.VERSIONED_NOTIFICATIONS[0]['event_type'])

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
        self.assertEqual(0, len(fake_notifier.VERSIONED_NOTIFICATIONS))

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

        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self.assertEqual(
                'nova-compute:testhost',
                fake_notifier.VERSIONED_NOTIFICATIONS[0]['publisher_id'])
        self.assertEqual(
                'instance.update',
                fake_notifier.VERSIONED_NOTIFICATIONS[0]['event_type'])

    def test_send_on_task_change(self):

        old = obj_base.obj_to_primitive(self.instance)
        old['task_state'] = None
        # pretend we just transitioned to task SPAWNING:
        self.instance.task_state = task_states.SPAWNING
        notifications.send_update(self.context, old, self.instance)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self.assertEqual(
                'instance.update',
                fake_notifier.VERSIONED_NOTIFICATIONS[0]['event_type'])

    def test_no_update_with_states(self):

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                task_states.SPAWNING, verify_states=True)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(0, len(fake_notifier.VERSIONED_NOTIFICATIONS))

    def get_fake_bandwidth(self):
        usage = objects.BandwidthUsage(context=self.context)
        usage.create(
                self.instance.uuid,
                mac='DE:AD:BE:EF:00:01',
                bw_in=1,
                bw_out=2,
                last_ctr_in=0,
                last_ctr_out=0,
                start_period='2012-10-29T13:42:11Z')
        return usage

    @mock.patch.object(objects.BandwidthUsageList, 'get_by_uuids')
    def test_vm_update_with_states(self, mock_bandwidth_list):
        mock_bandwidth_list.return_value = [self.get_fake_bandwidth()]
        fake_net_info = fake_network.fake_get_instance_nw_info(self, 1, 1)
        self.instance.info_cache.network_info = fake_net_info

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.ACTIVE, task_states.SPAWNING,
                task_states.SPAWNING, verify_states=True)

        self._verify_notification()

    def _verify_notification(self, expected_state=vm_states.ACTIVE,
                             expected_new_task_state=task_states.SPAWNING):
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self.assertEqual(
                'instance.update',
                fake_notifier.VERSIONED_NOTIFICATIONS[0]['event_type'])
        access_ip_v4 = str(self.instance.access_ip_v4)
        access_ip_v6 = str(self.instance.access_ip_v6)
        display_name = self.instance.display_name
        hostname = self.instance.hostname
        node = self.instance.node
        payload = fake_notifier.NOTIFICATIONS[0].payload
        self.assertEqual(vm_states.BUILDING, payload["old_state"])
        self.assertEqual(expected_state, payload["state"])
        self.assertEqual(task_states.SPAWNING, payload["old_task_state"])
        self.assertEqual(expected_new_task_state, payload["new_task_state"])
        self.assertEqual(payload["access_ip_v4"], access_ip_v4)
        self.assertEqual(payload["access_ip_v6"], access_ip_v6)
        self.assertEqual(payload["display_name"], display_name)
        self.assertEqual(payload["hostname"], hostname)
        self.assertEqual(payload["node"], node)
        self.assertEqual("2017-02-01T00:00:00.000000",
                         payload["audit_period_beginning"])
        self.assertEqual("2017-02-02T16:45:00.000000",
                         payload["audit_period_ending"])

        payload = fake_notifier.VERSIONED_NOTIFICATIONS[0][
            'payload']['nova_object.data']
        state_update = payload['state_update']['nova_object.data']
        self.assertEqual(vm_states.BUILDING, state_update['old_state'])
        self.assertEqual(expected_state, state_update["state"])
        self.assertEqual(task_states.SPAWNING, state_update["old_task_state"])
        self.assertEqual(expected_new_task_state,
                         state_update["new_task_state"])
        self.assertEqual(payload["display_name"], display_name)
        self.assertEqual(payload["host_name"], hostname)
        self.assertEqual(payload["node"], node)
        flavor = payload['flavor']['nova_object.data']
        self.assertEqual(flavor['flavorid'], '1')
        self.assertEqual(payload['image_uuid'], uuids.image_ref)

        net_info = self.instance.info_cache.network_info
        vif = net_info[0]
        ip_addresses = payload['ip_addresses']

        self.assertEqual(len(ip_addresses), 2)
        for actual_ip, expected_ip in zip(ip_addresses, vif.fixed_ips()):
            actual_ip = actual_ip['nova_object.data']
            self.assertEqual(actual_ip['label'], vif['network']['label'])
            self.assertEqual(actual_ip['mac'], vif['address'].lower())
            self.assertEqual(actual_ip['port_uuid'], vif['id'])
            self.assertEqual(actual_ip['device_name'], vif['devname'])
            self.assertEqual(actual_ip['version'], expected_ip['version'])
            self.assertEqual(actual_ip['address'], expected_ip['address'])

        bandwidth = payload['bandwidth']
        self.assertEqual(len(bandwidth), 1)
        bandwidth = bandwidth[0]['nova_object.data']
        self.assertEqual(bandwidth['in_bytes'], 1)
        self.assertEqual(bandwidth['out_bytes'], 2)
        self.assertEqual(bandwidth['network_name'], 'test1')

    @mock.patch.object(objects.BandwidthUsageList, 'get_by_uuids')
    def test_task_update_with_states(self, mock_bandwidth_list):
        self.flags(notify_on_state_change="vm_and_task_state",
                   group='notifications')
        mock_bandwidth_list.return_value = [self.get_fake_bandwidth()]
        fake_net_info = fake_network.fake_get_instance_nw_info(self, 1, 1)
        self.instance.info_cache.network_info = fake_net_info

        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, verify_states=True)
        self._verify_notification(expected_state=vm_states.BUILDING,
                                  expected_new_task_state=None)

    def test_update_no_service_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        # service name should default to 'compute'
        notif = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('compute.testhost', notif.publisher_id)

        # in the versioned notification it defaults to nova-compute
        notif = fake_notifier.VERSIONED_NOTIFICATIONS[0]
        self.assertEqual('nova-compute:testhost', notif['publisher_id'])

    def test_update_with_service_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, service="nova-compute")
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        # service name should default to 'compute'
        notif = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('nova-compute.testhost', notif.publisher_id)

        notif = fake_notifier.VERSIONED_NOTIFICATIONS[0]
        self.assertEqual('nova-compute:testhost', notif['publisher_id'])

    def test_update_with_host_name(self):
        notifications.send_update_with_states(self.context, self.instance,
                vm_states.BUILDING, vm_states.BUILDING, task_states.SPAWNING,
                None, host="someotherhost")
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        # service name should default to 'compute'
        notif = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('compute.someotherhost', notif.publisher_id)

        notif = fake_notifier.VERSIONED_NOTIFICATIONS[0]
        self.assertEqual('nova-compute:someotherhost', notif['publisher_id'])

    def test_payload_has_fixed_ip_labels(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info)
        self.assertIn("fixed_ips", info)
        self.assertEqual(info["fixed_ips"][0]["label"], "test1")

    def test_payload_has_vif_mac_address(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info)
        self.assertIn("fixed_ips", info)
        self.assertEqual(self.net_info[0]['address'],
                         info["fixed_ips"][0]["vif_mac"])

    def test_payload_has_cell_name_empty(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info)
        self.assertIn("cell_name", info)
        self.assertIsNone(self.instance.cell_name)
        self.assertEqual("", info["cell_name"])

    def test_payload_has_cell_name(self):
        self.instance.cell_name = "cell1"
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info)
        self.assertIn("cell_name", info)
        self.assertEqual("cell1", info["cell_name"])

    def test_payload_has_progress_empty(self):
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info)
        self.assertIn("progress", info)
        self.assertIsNone(self.instance.progress)
        self.assertEqual("", info["progress"])

    def test_payload_has_progress(self):
        self.instance.progress = 50
        info = notifications.info_from_instance(self.context, self.instance,
                                                  self.net_info)
        self.assertIn("progress", info)
        self.assertEqual(50, info["progress"])

    def test_payload_has_flavor_attributes(self):
        # Zero these to make sure they are not used
        self.instance.vcpus = self.instance.memory_mb = 0
        self.instance.root_gb = self.instance.ephemeral_gb = 0

        # Set flavor values and make sure _these_ are present in the output
        self.instance.flavor.vcpus = 10
        self.instance.flavor.root_gb = 20
        self.instance.flavor.memory_mb = 30
        self.instance.flavor.ephemeral_gb = 40
        info = notifications.info_from_instance(self.context, self.instance,
                                                self.net_info)
        self.assertEqual(10, info['vcpus'])
        self.assertEqual(20, info['root_gb'])
        self.assertEqual(30, info['memory_mb'])
        self.assertEqual(40, info['ephemeral_gb'])
        self.assertEqual(60, info['disk_gb'])

    def test_payload_has_timestamp_fields(self):
        time = datetime.datetime(2017, 2, 2, 16, 45, 0)
        # do not define deleted_at to test that missing value is handled
        # properly
        self.instance.terminated_at = time
        self.instance.launched_at = time

        info = notifications.info_from_instance(self.context, self.instance,
                                                self.net_info)

        self.assertEqual('2017-02-02T16:45:00.000000', info['terminated_at'])
        self.assertEqual('2017-02-02T16:45:00.000000', info['launched_at'])
        self.assertEqual('', info['deleted_at'])

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
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        old_display_name = self.instance.display_name
        new_display_name = new_name_inst.display_name

        for payload in [
            fake_notifier.NOTIFICATIONS[0].payload,
            fake_notifier.VERSIONED_NOTIFICATIONS[0][
                'payload']['nova_object.data']]:

            self.assertEqual(payload["old_display_name"], old_display_name)
            self.assertEqual(payload["display_name"], new_display_name)

    def test_send_versioned_tags_update(self):
        objects.TagList.create(self.context,
                               self.instance.uuid, [u'tag1', u'tag2'])
        notifications.send_update(self.context, self.instance, self.instance)
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        self.assertEqual([u'tag1', u'tag2'],
                         fake_notifier.VERSIONED_NOTIFICATIONS[0]
                         ['payload']['nova_object.data']['tags'])

    def test_send_versioned_action_initiator_update(self):
        notifications.send_update(self.context, self.instance, self.instance)
        action_initiator_user = self.context.user_id
        action_initiator_project = self.context.project_id
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        self.assertEqual(action_initiator_user,
                         fake_notifier.VERSIONED_NOTIFICATIONS[0]
                         ['payload']['nova_object.data']
                         ['action_initiator_user'])
        self.assertEqual(action_initiator_project,
                         fake_notifier.VERSIONED_NOTIFICATIONS[0]
                         ['payload']['nova_object.data']
                         ['action_initiator_project'])

    def test_send_no_state_change(self):
        called = [False]

        def sending_no_state_change(context, instance, **kwargs):
            called[0] = True
        self.stub_out('nova.notifications.base.'
                      'send_instance_update_notification',
                       sending_no_state_change)
        notifications.send_update(self.context, self.instance, self.instance)
        self.assertTrue(called[0])

    def test_fail_sending_update(self):
        def fail_sending(context, instance, **kwargs):
            raise Exception('failed to notify')
        self.stub_out('nova.notifications.base.'
                      'send_instance_update_notification',
                       fail_sending)

        notifications.send_update(self.context, self.instance, self.instance)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))

    @mock.patch.object(notifications.LOG, 'exception')
    def test_fail_sending_update_instance_not_found(self, mock_log_exception):
        # Tests that InstanceNotFound is handled as an expected exception and
        # not logged as an error.
        notfound = exception.InstanceNotFound(instance_id=self.instance.uuid)
        with mock.patch.object(notifications,
                               'send_instance_update_notification',
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
                               'send_instance_update_notification',
                               side_effect=notfound):
            notifications.send_update_with_states(
                self.context, self.instance,
                vm_states.BUILDING, vm_states.ERROR,
                task_states.NETWORKING, new_task_state=None)
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(0, mock_log_exception.call_count)

    def _decorated_function(self, arg1, arg2):
        self.decorated_function_called = True


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
