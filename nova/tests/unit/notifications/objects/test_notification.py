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
from unittest import mock

from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_versionedobjects import fixture

from nova import exception
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
            'lazy_field': fields.IntegerField()
        }

        def obj_load_attr(self, attrname):
            if attrname == 'lazy_field':
                self.lazy_field = 42
            else:
                raise exception.ObjectActionError(
                    action='obj_load_attr',
                    reason='attribute %s not lazy-loadable' % attrname)

        def __init__(self, not_important_field):
            super(TestNotificationBase.TestObject, self).__init__()
            # field1 and field_2 simulates that some fields are initialized
            # outside of the object's ctor
            self.not_important_field = not_important_field

    @base.NovaObjectRegistry.register_if(False)
    class TestNotificationPayload(notification.NotificationPayloadBase):
        VERSION = '1.0'

        SCHEMA = {
            'field_1': ('source_field', 'field_1'),
            'field_2': ('source_field', 'field_2'),
            'lazy_field': ('source_field', 'lazy_field')
        }

        fields = {
            'extra_field': fields.StringField(),  # filled by ctor
            # filled by the schema
            'field_1': fields.StringField(nullable=True),
            'field_2': fields.IntegerField(),   # filled by the schema
            'lazy_field': fields.IntegerField()  # filled by the schema
        }

        def __init__(self, extra_field, source_field):
            super(TestNotificationBase.TestNotificationPayload,
                  self).__init__()
            self.extra_field = extra_field
            self.populate_schema(source_field=source_field)

    @base.NovaObjectRegistry.register_if(False)
    class TestNotificationPayloadEmptySchema(
        notification.NotificationPayloadBase):
        VERSION = '1.0'

        fields = {
            'extra_field': fields.StringField(),  # filled by ctor
        }

        def __init__(self, extra_field):
            super(TestNotificationBase.TestNotificationPayloadEmptySchema,
                  self).__init__()
            self.extra_field = extra_field

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
        'uuid': uuids.service,
        'host': 'fake-host',
        'binary': 'nova-compute',
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
            'field_2': 15,
            'lazy_field': 42},
        'nova_object.version': '1.0',
        'nova_object.namespace': 'nova'}

    def setUp(self):
        super(TestNotificationBase, self).setUp()
        with mock.patch(
                'nova.db.main.api.service_update') as mock_db_service_update:
            self.service_obj = objects.Service(context=mock.sentinel.context,
                                               id=self.fake_service['id'])
            self.service_obj.obj_reset_changes(['version'])
            mock_db_service_update.return_value = self.fake_service
            self.service_obj.save()

        self.my_obj = self.TestObject(not_important_field=13)
        self.my_obj.field_1 = 'test1'
        self.my_obj.field_2 = 15

        self.payload = self.TestNotificationPayload(
            extra_field='test string', source_field=self.my_obj)

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
            publisher_id='nova-compute:fake-host')
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
            publisher=notification.NotificationPublisher(
                host='fake-host',
                source='nova-compute'),
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
        payload = self.TestNotificationPayload(
            extra_field='test string', source_field=self.my_obj)
        payload.populated = False

        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=payload)

        mock_context = mock.Mock()
        self.assertRaises(AssertionError, noti.emit, mock_context)
        self.assertFalse(mock_notifier.called)

    def test_lazy_load_source_field(self):
        my_obj = self.TestObject(not_important_field=13)
        my_obj.field_1 = 'test1'
        my_obj.field_2 = 15

        payload = self.TestNotificationPayload(extra_field='test string',
                                               source_field=my_obj)

        self.assertEqual(42, payload.lazy_field)

    def test_uninited_source_field_defaulted_to_none(self):
        my_obj = self.TestObject(not_important_field=13)
        # intentionally not initializing field_1 to simulate an uninited but
        # nullable field
        my_obj.field_2 = 15

        payload = self.TestNotificationPayload(extra_field='test string',
                                               source_field=my_obj)

        self.assertIsNone(payload.field_1)

    def test_uninited_source_field_not_nullable_payload_field_fails(self):
        my_obj = self.TestObject(not_important_field=13)
        # intentionally not initializing field_2 to simulate an uninited no
        # nullable field
        my_obj.field_1 = 'test1'

        self.assertRaises(ValueError, self.TestNotificationPayload,
                          extra_field='test string', source_field=my_obj)

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

    @mock.patch('nova.notifications.objects.base.NotificationBase._emit')
    @mock.patch('nova.rpc.NOTIFIER')
    def test_payload_is_not_generated_if_notifier_is_not_enabled(
            self, mock_notifier, mock_emit):
        mock_notifier.is_enabled.return_value = False

        payload = self.TestNotificationPayload(
            extra_field='test string',
            source_field=self.my_obj)
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=payload)

        mock_context = mock.Mock()

        noti.emit(mock_context)

        self.assertFalse(payload.populated)
        self.assertFalse(mock_emit.called)

    @mock.patch('nova.notifications.objects.base.NotificationBase._emit')
    def test_payload_is_not_generated_if_notification_format_is_unversioned(
            self, mock_emit):
        self.flags(notification_format='unversioned', group='notifications')

        payload = self.TestNotificationPayload(
            extra_field='test string',
            source_field=self.my_obj)
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=payload)

        mock_context = mock.Mock()

        noti.emit(mock_context)

        self.assertFalse(payload.populated)
        self.assertFalse(mock_emit.called)


notification_object_data = {
    'AggregateCacheNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'AggregateCachePayload': '1.0-d0e40be596ea3a230af0f79c242b9d90',
    'AggregateNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'AggregatePayload': '1.1-75c586f283a7e28b9c0b44a7297304bf',
    'AuditPeriodPayload': '1.0-b79111d626d565760b48338ec46c3d1b',
    'BlockDevicePayload': '1.0-771249c2e54ccd127c90cf3071af6b1e',
    'CellMappingPayload': '2.0-ce38914d7cd30cf05de94e15af978d70',
    'ComputeTaskNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ComputeTaskPayload': '1.0-59a9b78b6199470a83c8d07bffd13f5e',
    'DestinationPayload': '1.0-d8faf610201bf5f460892243f6632a37',
    'EventType': '1.21-6a5f57fafe478f354f66b81b4cb537ea',
    'ExceptionNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ExceptionPayload': '1.1-34f006107693b8c9eaf4b104157d21b4',
    'FlavorNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'FlavorPayload': '1.4-029909d2dab5c08b5b854f2d42fe1abe',
    'ImageMetaPayload': '1.0-17c1a13daccbac0482b7d7bdb15af150',
    # NOTE(efried): ImageMetaPropsPayload is built dynamically from
    # ImageMetaProps, so when you see a fail here for that reason, you must
    # *also* bump the version of ImageMetaPropsPayload. See its docstring for
    # more information.
    'ImageMetaPropsPayload': '1.14-af9efd17cd034596be792fa25f24e83d',
    'InstanceActionNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionPayload': '1.8-b948818df6ec562e4eb4b23e515e451b',
    'InstanceActionRebuildNotification':
        '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionRebuildPayload': '1.9-3c1ac23f70c03665797f792ace3d9176',
    'InstanceActionRescueNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionRescuePayload': '1.3-329dda4c0a516c0fedc68aa02ccf3e88',
    'InstanceActionResizePrepNotification':
        '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionResizePrepPayload': '1.3-8969438a48c496569c2add19b170dca1',
    'InstanceActionVolumeNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionVolumePayload': '1.6-b5fd2b23dbafe33b72cdbbb7b937bf18',
    'InstanceActionVolumeSwapNotification':
    '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionVolumeSwapPayload': '1.8-9d8edd0a3556a69f0bfe17ab2641ca19',
    'InstanceCreateNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceCreatePayload': '1.12-bd007423bfdb634448ec589b28f7cd39',
    'InstancePayload': '1.8-0bfe0b258ae4cf6ff68463c9e75adb80',
    'InstanceActionSnapshotNotification':
        '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionSnapshotPayload': '1.9-75809b8ef913f7d2e262c5c804213ac8',
    'InstanceExistsNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceExistsPayload': '2.0-5eb1efc3d1b03d87be82062219adaf6d',
    'InstanceNUMACellPayload': '1.2-93c3cadf4f6ee427664c00039d0a1fed',
    'InstanceNUMATopologyPayload': '1.0-c7885d5da4c66525f20e7d637a7267c4',
    'InstancePCIRequestPayload': '1.1-ee482d38f6c84bb77bba3f4c8708231c',
    'InstancePCIRequestsPayload': '1.0-29cb0fa1ba6756423a9606437c3f247f',
    'InstanceStateUpdatePayload': '1.0-9d136730749479042d47f2a08c2c2e69',
    'InstanceUpdateNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceUpdatePayload': '2.0-f6edbd2b53373f120debf5570ec14676',
    'IpPayload': '1.0-a9f0b3f1ef17ab12378096816faa4e55',
    'KeypairNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'KeypairPayload': '1.0-84f5e6da739af31ea10b89858c67b512',
    'LibvirtErrorNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'LibvirtErrorPayload': '1.0-fb5666286ebb9b1627be2290b9520f8f',
    'MetricPayload': '1.0-6a932f141c9ae2f50fc9d79c548338aa',
    'MetricsNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'MetricsPayload': '1.0-a087851790cd7e76883bdc64a146917a',
    'NotificationPublisher': '2.2-b6ad48126247e10b46b6b0240e52e614',
    'RequestSpecPayload': '1.1-9530d710bf7eaa101a93f6745fbe7aea',
    'SchedulerRetriesPayload': '1.0-6e7e6204e638c0a070412f0e765c320c',
    'SelectDestinationsNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ServerGroupNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ServerGroupPayload': '1.1-f866cf95bf64bfa799193807e66a6a1e',
    'ServiceStatusNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ServiceStatusPayload': '1.1-64c5f80b3865832b936898f11dcddad0',
    'VirtCPUTopologyPayload': '1.0-24fa607e20f48c829953edad6b0b5cc8',
    'VolumeUsageNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'VolumeUsagePayload': '1.0-a12c300f0ddbc7488685c9d9ed36d9e8',
}


class TestNotificationObjectVersions(test.NoDBTestCase):
    def setUp(self):
        super(TestNotificationObjectVersions, self).setUp()
        base.NovaObjectRegistry.register_notification_objects()

    def test_versions(self):
        checker = fixture.ObjectVersionChecker(
            test_objects.get_nova_objects())
        notification_object_data.update(test_objects.object_data)
        expected, actual = checker.test_hashes(notification_object_data,
                                               extra_data_func=get_extra_data)
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
        schema_data = sorted(obj_class.SCHEMA.items())

        extra_data += (schema_data,)

    return extra_data
