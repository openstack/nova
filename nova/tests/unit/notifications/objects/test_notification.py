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
import collections

import mock
from oslo_utils import timeutils
from oslo_versionedobjects import fixture

from nova.notifications.objects import base as notification
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova import test
from nova.tests.unit.objects import test_objects


class TestNotificationBase(test.NoDBTestCase):

    @base.NovaObjectRegistry.register_if(False)
    class TestObject(base.NovaObject):
        VERSION = '1.0'
        fields = {
            'field_1': fields.StringField(),
            'field_2': fields.IntegerField(),
            'not_important_field': fields.IntegerField(),
        }

    @base.NovaObjectRegistry.register_if(False)
    class TestNotificationPayload(notification.NotificationPayloadBase):
        VERSION = '1.0'

        SCHEMA = {
            'field_1': ('source_field', 'field_1'),
            'field_2': ('source_field', 'field_2'),
        }

        fields = {
            'extra_field': fields.StringField(),  # filled by ctor
            'field_1': fields.StringField(),  # filled by the schema
            'field_2': fields.IntegerField(),   # filled by the schema
        }

        def populate_schema(self, source_field):
            super(TestNotificationBase.TestNotificationPayload,
                  self).populate_schema(source_field=source_field)

    @base.NovaObjectRegistry.register_if(False)
    class TestNotificationPayloadEmptySchema(
        notification.NotificationPayloadBase):
        VERSION = '1.0'

        fields = {
            'extra_field': fields.StringField(),  # filled by ctor
        }

    @notification.notification_sample('test-update-1.json')
    @notification.notification_sample('test-update-2.json')
    @base.NovaObjectRegistry.register_if(False)
    class TestNotification(notification.NotificationBase):
        VERSION = '1.0'
        fields = {
            'payload': fields.ObjectField('TestNotificationPayload')
        }

    @base.NovaObjectRegistry.register_if(False)
    class TestNotificationEmptySchema(notification.NotificationBase):
        VERSION = '1.0'
        fields = {
            'payload': fields.ObjectField('TestNotificationPayloadEmptySchema')
        }

    fake_service = {
        'created_at': timeutils.utcnow().replace(microsecond=0),
        'updated_at': None,
        'deleted_at': None,
        'deleted': False,
        'id': 123,
        'host': 'fake-host',
        'binary': 'nova-fake',
        'topic': 'fake-service-topic',
        'report_count': 1,
        'forced_down': False,
        'disabled': False,
        'disabled_reason': None,
        'last_seen_up': None,
        'version': 1}

    expected_payload = {
        'nova_object.name': 'TestNotificationPayload',
        'nova_object.data': {
            'extra_field': 'test string',
            'field_1': 'test1',
            'field_2': 42},
        'nova_object.version': '1.0',
        'nova_object.namespace': 'nova'}

    def setUp(self):
        super(TestNotificationBase, self).setUp()
        with mock.patch('nova.db.service_update') as mock_db_service_update:
            self.service_obj = objects.Service(context=mock.sentinel.context,
                                               id=self.fake_service['id'])
            self.service_obj.obj_reset_changes(['version'])
            mock_db_service_update.return_value = self.fake_service
            self.service_obj.save()

        self.my_obj = self.TestObject(field_1='test1',
                                      field_2=42,
                                      not_important_field=13)

        self.payload = self.TestNotificationPayload(
            extra_field='test string')
        self.payload.populate_schema(source_field=self.my_obj)

        self.notification = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE,
                phase=fields.NotificationPhase.START),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=self.payload)

    def _verify_notification(self, mock_notifier, mock_context,
                             expected_event_type,
                             expected_payload):
        mock_notifier.prepare.assert_called_once_with(
            publisher_id='nova-fake:fake-host')
        mock_notify = mock_notifier.prepare.return_value.info
        self.assertTrue(mock_notify.called)
        self.assertEqual(mock_notify.call_args[0][0], mock_context)
        self.assertEqual(mock_notify.call_args[1]['event_type'],
                         expected_event_type)
        actual_payload = mock_notify.call_args[1]['payload']
        self.assertJsonEqual(expected_payload, actual_payload)

    @mock.patch('nova.rpc.LEGACY_NOTIFIER')
    @mock.patch('nova.rpc.NOTIFIER')
    def test_emit_notification(self, mock_notifier, mock_legacy):

        mock_context = mock.Mock()
        mock_context.to_dict.return_value = {}
        self.notification.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='test_object.update.start',
            expected_payload=self.expected_payload)
        self.assertFalse(mock_legacy.called)

    @mock.patch('nova.rpc.NOTIFIER')
    def test_emit_with_host_and_binary_as_publisher(self, mock_notifier):
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher(host='fake-host',
                                                         binary='nova-fake'),
            priority=fields.NotificationPriority.INFO,
            payload=self.payload)

        mock_context = mock.Mock()
        mock_context.to_dict.return_value = {}
        noti.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='test_object.update',
            expected_payload=self.expected_payload)

    @mock.patch('nova.rpc.LEGACY_NOTIFIER')
    @mock.patch('nova.rpc.NOTIFIER')
    def test_emit_event_type_without_phase(self, mock_notifier, mock_legacy):
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=self.payload)

        mock_context = mock.Mock()
        mock_context.to_dict.return_value = {}
        noti.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='test_object.update',
            expected_payload=self.expected_payload)
        self.assertFalse(mock_legacy.called)

    @mock.patch('nova.rpc.NOTIFIER')
    def test_not_possible_to_emit_if_not_populated(self, mock_notifier):
        non_populated_payload = self.TestNotificationPayload(
            extra_field='test string')
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=non_populated_payload)

        mock_context = mock.Mock()
        self.assertRaises(AssertionError, noti.emit, mock_context)
        self.assertFalse(mock_notifier.called)

    @mock.patch('nova.rpc.NOTIFIER')
    def test_empty_schema(self, mock_notifier):
        non_populated_payload = self.TestNotificationPayloadEmptySchema(
            extra_field='test string')
        noti = self.TestNotificationEmptySchema(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=non_populated_payload)

        mock_context = mock.Mock()
        mock_context.to_dict.return_value = {}
        noti.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='test_object.update',
            expected_payload=
            {'nova_object.name': 'TestNotificationPayloadEmptySchema',
             'nova_object.data': {'extra_field': u'test string'},
             'nova_object.version': '1.0',
             'nova_object.namespace': 'nova'})

    def test_sample_decorator(self):
        self.assertEqual(2, len(self.TestNotification.samples))
        self.assertIn('test-update-1.json', self.TestNotification.samples)
        self.assertIn('test-update-2.json', self.TestNotification.samples)


notification_object_data = {
    'AuditPeriodPayload': '1.0-28345f72ca9d805eeb61b2c2385805dd',
    'BandwidthPayload': '1.0-49278639296f9939ff2c8947b2078a82',
    'EventType': '1.3-6ef678bfe9a4ebfd669c96d2d2c124a5',
    'ExceptionNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ExceptionPayload': '1.0-4516ae282a55fe2fd5c754967ee6248b',
    'FlavorPayload': '1.0-8ad962ab0bafc7270f474c7dda0b7c20',
    'InstanceActionNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionPayload': '1.0-aa6a322cf1a3a19d090259fee65d1094',
    'InstancePayload': '1.0-878bbc5a7a20bdeac7c6570f438a53aa',
    'InstanceStateUpdatePayload': '1.0-a934d04e1b314318e42e8062647edd11',
    'InstanceUpdateNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceUpdatePayload': '1.0-c69e17e00400455bfe602e5573a61f0b',
    'IpPayload': '1.0-26b40117c41ed95a61ae104f0fcb5fdc',
    'NotificationPublisher': '1.0-bbbc1402fb0e443a3eb227cc52b61545',
    'ServiceStatusNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ServiceStatusPayload': '1.0-a5e7b4fd6cc5581be45b31ff1f3a3f7f',
}


class TestNotificationObjectVersions(test.NoDBTestCase):
    def setUp(self):
        super(test.NoDBTestCase, self).setUp()
        base.NovaObjectRegistry.register_notification_objects()

    def test_versions(self):
        checker = fixture.ObjectVersionChecker(
            test_objects.get_nova_objects())
        notification_object_data.update(test_objects.object_data)
        expected, actual = checker.test_hashes(notification_object_data)
        self.assertEqual(expected, actual,
                         'Some notification objects have changed; please make '
                         'sure the versions have been bumped, and then update '
                         'their hashes here.')

    def test_notification_payload_version_depends_on_the_schema(self):
        @base.NovaObjectRegistry.register_if(False)
        class TestNotificationPayload(notification.NotificationPayloadBase):
            VERSION = '1.0'

            SCHEMA = {
                'field_1': ('source_field', 'field_1'),
                'field_2': ('source_field', 'field_2'),
            }

            fields = {
                'extra_field': fields.StringField(),  # filled by ctor
                'field_1': fields.StringField(),  # filled by the schema
                'field_2': fields.IntegerField(),   # filled by the schema
            }

        checker = fixture.ObjectVersionChecker(
            {'TestNotificationPayload': (TestNotificationPayload,)})

        old_hash = checker.get_hashes(extra_data_func=get_extra_data)
        TestNotificationPayload.SCHEMA['field_3'] = ('source_field',
                                                     'field_3')
        new_hash = checker.get_hashes(extra_data_func=get_extra_data)

        self.assertNotEqual(old_hash, new_hash)


def get_extra_data(obj_class):
    extra_data = tuple()

    # Get the SCHEMA items to add to the fingerprint
    # if we are looking at a notification
    if issubclass(obj_class, notification.NotificationPayloadBase):
        schema_data = collections.OrderedDict(
            sorted(obj_class.SCHEMA.items()))

        extra_data += (schema_data,)

    return extra_data
