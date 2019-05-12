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

import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova import context as nova_context
from nova.network import model as network_model
from nova.notifications import base as notification_base
from nova.notifications.objects import instance as instance_notification
from nova import objects
from nova import test
from nova.tests.unit import fake_instance


class TestInstanceNotification(test.NoDBTestCase):

    def setUp(self):
        super(TestInstanceNotification, self).setUp()
        self.test_keys = ['memory_mb', 'vcpus', 'root_gb', 'ephemeral_gb',
                          'swap']
        self.flavor_values = {k: 123 for k in self.test_keys}
        instance_values = {k: 456 for k in self.test_keys}
        flavor = objects.Flavor(flavorid='test-flavor', name='test-flavor',
                                disabled=False, projects=[], is_public=True,
                                extra_specs={}, **self.flavor_values)
        info_cache = objects.InstanceInfoCache(
            network_info=network_model.NetworkInfo())
        self.instance = objects.Instance(
            flavor=flavor,
            info_cache=info_cache,
            metadata={},
            uuid=uuids.instance1,
            locked=False,
            auto_disk_config=False,
            system_metadata={},
            **instance_values)
        self.payload = {
            'bandwidth': {},
            'audit_period_ending': timeutils.utcnow(),
            'audit_period_beginning': timeutils.utcnow(),
        }

    @mock.patch('nova.notifications.objects.instance.'
                'InstanceUpdateNotification._emit')
    def test_send_version_instance_update_uses_flavor(self, mock_emit):
        # instance.update notification needs some tags value to avoid lazy-load
        self.instance.tags = objects.TagList()
        # Make sure that the notification payload chooses the values in
        # instance.flavor.$value instead of instance.$value
        mock_context = mock.MagicMock()
        mock_context.project_id = 'fake_project_id'
        mock_context.user_id = 'fake_user_id'
        mock_context.request_id = 'fake_req_id'
        notification_base._send_versioned_instance_update(
            mock_context,
            self.instance,
            self.payload,
            'host',
            'compute')
        payload = mock_emit.call_args_list[0][1]['payload']['nova_object.data']
        flavor_payload = payload['flavor']['nova_object.data']
        data = {k: flavor_payload[k] for k in self.test_keys}
        self.assertEqual(self.flavor_values, data)

    @mock.patch('nova.rpc.NOTIFIER')
    @mock.patch('nova.notifications.objects.instance.'
                'InstanceUpdatePayload.__init__', return_value=None)
    @mock.patch('nova.notifications.objects.instance.'
                'InstanceUpdateNotification.__init__', return_value=None)
    def test_send_versioned_instance_notification_is_not_called_disabled(
            self, mock_notification, mock_payload, mock_notifier):
        mock_notifier.is_enabled.return_value = False

        notification_base._send_versioned_instance_update(
            mock.MagicMock(),
            self.instance,
            self.payload,
            'host',
            'compute')

        self.assertFalse(mock_payload.called)
        self.assertFalse(mock_notification.called)

    @mock.patch('nova.notifications.objects.instance.'
                'InstanceUpdatePayload.__init__', return_value=None)
    @mock.patch('nova.notifications.objects.instance.'
                'InstanceUpdateNotification.__init__', return_value=None)
    def test_send_versioned_instance_notification_is_not_called_unversioned(
            self, mock_notification, mock_payload):
        self.flags(notification_format='unversioned', group='notifications')

        notification_base._send_versioned_instance_update(
            mock.MagicMock(),
            self.instance,
            self.payload,
            'host',
            'compute')

        self.assertFalse(mock_payload.called)
        self.assertFalse(mock_notification.called)

    def test_instance_payload_request_id_periodic_task(self):
        """Tests that creating an InstancePayload from the type of request
        context used during a periodic task will not populate the
        payload request_id field since it is not an end user request.
        """
        ctxt = nova_context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctxt)
        # Set some other fields otherwise populate_schema tries to hit the DB.
        instance.metadata = {}
        instance.system_metadata = {}
        instance.info_cache = objects.InstanceInfoCache(
            network_info=network_model.NetworkInfo([]))
        payload = instance_notification.InstancePayload(ctxt, instance)
        self.assertIsNone(payload.request_id)


class TestBlockDevicePayload(test.NoDBTestCase):
    @mock.patch('nova.objects.instance.Instance.get_bdms')
    def test_payload_contains_volume_bdms_if_requested(self, mock_get_bdms):
        self.flags(bdms_in_notifications='True', group='notifications')
        context = mock.Mock()
        instance = objects.Instance(uuid=uuids.instance_uuid)
        image_bdm = objects.BlockDeviceMapping(
            **{'context': context, 'source_type': 'image',
               'destination_type': 'local',
               'image_id': uuids.image_id,
               'volume_id': None,
               'device_name': '/dev/vda',
               'instance_uuid': instance.uuid})

        volume_bdm = objects.BlockDeviceMapping(
            **{'context': context, 'source_type': 'volume',
               'destination_type': 'volume',
               'volume_id': uuids.volume_id,
               'device_name': '/dev/vdb',
               'instance_uuid': instance.uuid,
               'boot_index': 0,
               'delete_on_termination': True,
               'tag': 'my-tag'})

        mock_get_bdms.return_value = [image_bdm, volume_bdm]

        bdms = instance_notification.BlockDevicePayload.from_instance(
            instance)

        self.assertEqual(1, len(bdms))
        bdm = bdms[0]
        self.assertIsInstance(bdm, instance_notification.BlockDevicePayload)
        self.assertEqual('/dev/vdb', bdm.device_name)
        self.assertEqual(0, bdm.boot_index)
        self.assertTrue(bdm.delete_on_termination)
        self.assertEqual('my-tag', bdm.tag)
        self.assertEqual(uuids.volume_id, bdm.volume_id)

    @mock.patch('nova.objects.instance.Instance.get_bdms',
                return_value=mock.NonCallableMock())
    def test_bdms_are_skipped_by_default(self, mock_get_bdms):
        instance = objects.Instance(uuid=uuids.instance_uuid)
        bmds = instance_notification.BlockDevicePayload.from_instance(
            instance)
        self.assertIsNone(bmds)
