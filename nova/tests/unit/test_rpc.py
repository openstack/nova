#    Copyright 2016 IBM Corp.
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

import mock
import oslo_messaging as messaging
from oslo_messaging.rpc import dispatcher
from oslo_serialization import jsonutils
import six

import nova.conf
from nova import context
from nova import rpc
from nova import test

CONF = nova.conf.CONF


class TestRPC(test.NoDBTestCase):

    # We're testing the rpc code so we can't use the RPCFixture.
    STUB_RPC = False

    @mock.patch.object(rpc, 'TRANSPORT')
    @mock.patch.object(rpc, 'NOTIFICATION_TRANSPORT')
    @mock.patch.object(rpc, 'LEGACY_NOTIFIER')
    @mock.patch.object(rpc, 'NOTIFIER')
    @mock.patch.object(rpc, 'get_allowed_exmods')
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'get_notification_transport')
    @mock.patch.object(messaging, 'Notifier')
    def _test_init(self, notification_format, expected_driver_topic_kwargs,
            mock_notif, mock_noti_trans, mock_ser, mock_exmods,
            mock_NOTIFIER, mock_LEGACY_NOTIFIER, mock_NOTIFICATION_TRANSPORT,
            mock_TRANSPORT,
            versioned_notifications_topics=None):

        if not versioned_notifications_topics:
            versioned_notifications_topics = ['versioned_notifications']

        self.flags(
            notification_format=notification_format,
            versioned_notifications_topics=versioned_notifications_topics,
            group='notifications')

        legacy_notifier = mock.Mock()
        notifier = mock.Mock()
        notif_transport = mock.Mock()
        transport = mock.Mock()
        serializer = mock.Mock()

        mock_exmods.return_value = ['foo']
        mock_noti_trans.return_value = notif_transport
        mock_ser.return_value = serializer
        mock_notif.side_effect = [legacy_notifier, notifier]

        with mock.patch.object(rpc, 'create_transport') as create_transport, \
                mock.patch.object(rpc, 'get_transport_url') as get_url:
            create_transport.return_value = transport
            rpc.init(CONF)
            create_transport.assert_called_once_with(get_url.return_value)

        self.assertTrue(mock_exmods.called)
        self.assertIsNotNone(mock_TRANSPORT)
        self.assertIsNotNone(mock_LEGACY_NOTIFIER)
        self.assertIsNotNone(mock_NOTIFIER)
        self.assertEqual(legacy_notifier, rpc.LEGACY_NOTIFIER)
        self.assertEqual(notifier, rpc.NOTIFIER)

        expected_calls = []
        for kwargs in expected_driver_topic_kwargs:
            expected_kwargs = {'serializer': serializer}
            expected_kwargs.update(kwargs)
            expected_calls.append(((notif_transport,), expected_kwargs))

        self.assertEqual(expected_calls, mock_notif.call_args_list,
                         "The calls to messaging.Notifier() did not create "
                         "the legacy and versioned notifiers properly.")

    def test_init_unversioned(self):
        # The expected call to get the legacy notifier will require no new
        # kwargs, and we expect the new notifier will need the noop driver
        expected_driver_topic_kwargs = [{}, {'driver': 'noop'}]
        self._test_init('unversioned', expected_driver_topic_kwargs)

    def test_init_both(self):
        expected_driver_topic_kwargs = [
            {},
            {'topics': ['versioned_notifications']}]
        self._test_init('both', expected_driver_topic_kwargs)

    def test_init_versioned(self):
        expected_driver_topic_kwargs = [
            {'driver': 'noop'},
            {'topics': ['versioned_notifications']}]
        self._test_init('versioned', expected_driver_topic_kwargs)

    def test_init_versioned_with_custom_topics(self):
        expected_driver_topic_kwargs = [
            {'driver': 'noop'},
            {'topics': ['custom_topic1', 'custom_topic2']}]
        versioned_notifications_topics = ['custom_topic1', 'custom_topic2']
        self._test_init('versioned', expected_driver_topic_kwargs,
            versioned_notifications_topics=versioned_notifications_topics)

    @mock.patch.object(rpc, 'NOTIFICATION_TRANSPORT', new=mock.Mock())
    @mock.patch.object(rpc, 'LEGACY_NOTIFIER', new=mock.Mock())
    @mock.patch.object(rpc, 'NOTIFIER', new=mock.Mock())
    def test_cleanup_transport_null(self):
        """Ensure cleanup fails if 'rpc.TRANSPORT' wasn't set."""
        self.assertRaises(AssertionError, rpc.cleanup)

    @mock.patch.object(rpc, 'TRANSPORT', new=mock.Mock())
    @mock.patch.object(rpc, 'LEGACY_NOTIFIER', new=mock.Mock())
    @mock.patch.object(rpc, 'NOTIFIER', new=mock.Mock())
    def test_cleanup_notification_transport_null(self):
        """Ensure cleanup fails if 'rpc.NOTIFICATION_TRANSPORT' wasn't set."""
        self.assertRaises(AssertionError, rpc.cleanup)

    @mock.patch.object(rpc, 'TRANSPORT', new=mock.Mock())
    @mock.patch.object(rpc, 'NOTIFICATION_TRANSPORT', new=mock.Mock())
    @mock.patch.object(rpc, 'NOTIFIER', new=mock.Mock())
    def test_cleanup_legacy_notifier_null(self):
        """Ensure cleanup fails if 'rpc.LEGACY_NOTIFIER' wasn't set."""
        self.assertRaises(AssertionError, rpc.cleanup)

    @mock.patch.object(rpc, 'TRANSPORT', new=mock.Mock())
    @mock.patch.object(rpc, 'NOTIFICATION_TRANSPORT', new=mock.Mock())
    @mock.patch.object(rpc, 'LEGACY_NOTIFIER', new=mock.Mock())
    def test_cleanup_notifier_null(self):
        """Ensure cleanup fails if 'rpc.NOTIFIER' wasn't set."""
        self.assertRaises(AssertionError, rpc.cleanup)

    @mock.patch.object(rpc, 'TRANSPORT')
    @mock.patch.object(rpc, 'NOTIFICATION_TRANSPORT')
    @mock.patch.object(rpc, 'LEGACY_NOTIFIER')
    @mock.patch.object(rpc, 'NOTIFIER')
    def test_cleanup(self, mock_NOTIFIER, mock_LEGACY_NOTIFIER,
            mock_NOTIFICATION_TRANSPORT, mock_TRANSPORT):
        rpc.cleanup()

        mock_TRANSPORT.cleanup.assert_called_once_with()
        mock_NOTIFICATION_TRANSPORT.cleanup.assert_called_once_with()

        self.assertIsNone(rpc.TRANSPORT)
        self.assertIsNone(rpc.NOTIFICATION_TRANSPORT)
        self.assertIsNone(rpc.LEGACY_NOTIFIER)
        self.assertIsNone(rpc.NOTIFIER)

    @mock.patch.object(messaging, 'set_transport_defaults')
    def test_set_defaults(self, mock_set):
        control_exchange = mock.Mock()

        rpc.set_defaults(control_exchange)

        mock_set.assert_called_once_with(control_exchange)

    def test_add_extra_exmods(self):
        extra_exmods = []

        with mock.patch.object(
                rpc, 'EXTRA_EXMODS', extra_exmods) as mock_EXTRA_EXMODS:
            rpc.add_extra_exmods('foo', 'bar')
            self.assertEqual(['foo', 'bar'], mock_EXTRA_EXMODS)

    def test_clear_extra_exmods(self):
        extra_exmods = ['foo', 'bar']

        with mock.patch.object(
                rpc, 'EXTRA_EXMODS', extra_exmods) as mock_EXTRA_EXMODS:
            rpc.clear_extra_exmods()
            self.assertEqual([], mock_EXTRA_EXMODS)

    def test_get_allowed_exmods(self):
        allowed_exmods = ['foo']
        extra_exmods = ['bar']

        with test.nested(
                mock.patch.object(rpc, 'EXTRA_EXMODS', extra_exmods),
                mock.patch.object(rpc, 'ALLOWED_EXMODS', allowed_exmods)
                ) as (mock_EXTRA_EXMODS, mock_ALLOWED_EXMODS):
            exmods = rpc.get_allowed_exmods()

        self.assertEqual(['foo', 'bar'], exmods)

    @mock.patch.object(messaging, 'TransportURL')
    def test_get_transport_url(self, mock_url):
        mock_url.parse.return_value = 'foo'

        url = rpc.get_transport_url(url_str='bar')

        self.assertEqual('foo', url)
        mock_url.parse.assert_called_once_with(rpc.CONF, 'bar')

    @mock.patch.object(messaging, 'TransportURL')
    def test_get_transport_url_null(self, mock_url):
        mock_url.parse.return_value = 'foo'

        url = rpc.get_transport_url()

        self.assertEqual('foo', url)
        mock_url.parse.assert_called_once_with(rpc.CONF, None)

    @mock.patch.object(rpc, 'TRANSPORT')
    @mock.patch.object(rpc, 'profiler', None)
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'RPCClient')
    def test_get_client(self, mock_client, mock_ser, mock_TRANSPORT):
        tgt = mock.Mock()
        ser = mock.Mock()
        mock_client.return_value = 'client'
        mock_ser.return_value = ser

        client = rpc.get_client(tgt, version_cap='1.0', serializer='foo')

        mock_ser.assert_called_once_with('foo')
        mock_client.assert_called_once_with(mock_TRANSPORT,
                                            tgt, version_cap='1.0',
                                            call_monitor_timeout=None,
                                            serializer=ser)
        self.assertEqual('client', client)

    @mock.patch.object(rpc, 'TRANSPORT')
    @mock.patch.object(rpc, 'profiler', None)
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'get_rpc_server')
    def test_get_server(self, mock_get, mock_ser, mock_TRANSPORT):
        ser = mock.Mock()
        tgt = mock.Mock()
        ends = mock.Mock()
        mock_ser.return_value = ser
        mock_get.return_value = 'server'

        server = rpc.get_server(tgt, ends, serializer='foo')

        mock_ser.assert_called_once_with('foo')
        access_policy = dispatcher.DefaultRPCAccessPolicy
        mock_get.assert_called_once_with(mock_TRANSPORT, tgt, ends,
                                         executor='eventlet', serializer=ser,
                                         access_policy=access_policy)
        self.assertEqual('server', server)

    @mock.patch.object(rpc, 'TRANSPORT')
    @mock.patch.object(rpc, 'profiler', mock.Mock())
    @mock.patch.object(rpc, 'ProfilerRequestContextSerializer')
    @mock.patch.object(messaging, 'RPCClient')
    def test_get_client_profiler_enabled(self, mock_client, mock_ser,
            mock_TRANSPORT):
        tgt = mock.Mock()
        ser = mock.Mock()
        mock_client.return_value = 'client'
        mock_ser.return_value = ser

        client = rpc.get_client(tgt, version_cap='1.0', serializer='foo')

        mock_ser.assert_called_once_with('foo')
        mock_client.assert_called_once_with(mock_TRANSPORT,
                                            tgt, version_cap='1.0',
                                            call_monitor_timeout=None,
                                            serializer=ser)
        self.assertEqual('client', client)

    @mock.patch.object(rpc, 'TRANSPORT')
    @mock.patch.object(rpc, 'profiler', mock.Mock())
    @mock.patch.object(rpc, 'profiler', mock.Mock())
    @mock.patch.object(rpc, 'ProfilerRequestContextSerializer')
    @mock.patch.object(messaging, 'get_rpc_server')
    def test_get_server_profiler_enabled(self, mock_get, mock_ser,
            mock_TRANSPORT):
        ser = mock.Mock()
        tgt = mock.Mock()
        ends = mock.Mock()
        mock_ser.return_value = ser
        mock_get.return_value = 'server'

        server = rpc.get_server(tgt, ends, serializer='foo')

        mock_ser.assert_called_once_with('foo')
        access_policy = dispatcher.DefaultRPCAccessPolicy
        mock_get.assert_called_once_with(mock_TRANSPORT, tgt, ends,
                                         executor='eventlet', serializer=ser,
                                         access_policy=access_policy)
        self.assertEqual('server', server)

    @mock.patch.object(rpc, 'LEGACY_NOTIFIER')
    def test_get_notifier(self, mock_LEGACY_NOTIFIER):
        mock_prep = mock.Mock()
        mock_prep.return_value = 'notifier'
        mock_LEGACY_NOTIFIER.prepare = mock_prep

        notifier = rpc.get_notifier('service', publisher_id='foo')

        mock_prep.assert_called_once_with(publisher_id='foo')
        self.assertIsInstance(notifier, rpc.LegacyValidatingNotifier)
        self.assertEqual('notifier', notifier.notifier)

    @mock.patch.object(rpc, 'LEGACY_NOTIFIER')
    def test_get_notifier_null_publisher(self, mock_LEGACY_NOTIFIER):
        mock_prep = mock.Mock()
        mock_prep.return_value = 'notifier'
        mock_LEGACY_NOTIFIER.prepare = mock_prep

        notifier = rpc.get_notifier('service', host='bar')

        mock_prep.assert_called_once_with(publisher_id='service.bar')
        self.assertIsInstance(notifier, rpc.LegacyValidatingNotifier)
        self.assertEqual('notifier', notifier.notifier)

    @mock.patch.object(rpc, 'NOTIFIER')
    def test_get_versioned_notifier(self, mock_NOTIFIER):
        mock_prep = mock.Mock()
        mock_prep.return_value = 'notifier'
        mock_NOTIFIER.prepare = mock_prep

        notifier = rpc.get_versioned_notifier('service.foo')

        mock_prep.assert_called_once_with(publisher_id='service.foo')
        self.assertEqual('notifier', notifier)

    @mock.patch.object(rpc, 'get_allowed_exmods')
    @mock.patch.object(messaging, 'get_rpc_transport')
    def test_create_transport(self, mock_transport, mock_exmods):
        exmods = mock_exmods.return_value
        transport = rpc.create_transport(mock.sentinel.url)
        self.assertEqual(mock_transport.return_value, transport)
        mock_exmods.assert_called_once_with()
        mock_transport.assert_called_once_with(rpc.CONF,
                                               url=mock.sentinel.url,
                                               allowed_remote_exmods=exmods)


class TestJsonPayloadSerializer(test.NoDBTestCase):
    def test_serialize_entity(self):
        serializer = rpc.JsonPayloadSerializer()
        with mock.patch.object(jsonutils, 'to_primitive') as mock_prim:
            serializer.serialize_entity('context', 'entity')

        mock_prim.assert_called_once_with('entity', convert_instances=True,
                                          fallback=serializer.fallback)

    def test_fallback(self):
        # Convert RequestContext, should get a dict.
        primitive = rpc.JsonPayloadSerializer.fallback(context.get_context())
        self.assertIsInstance(primitive, dict)
        # Convert anything else, should get a string.
        primitive = rpc.JsonPayloadSerializer.fallback(mock.sentinel.entity)
        self.assertIsInstance(primitive, six.text_type)


class TestRequestContextSerializer(test.NoDBTestCase):
    def setUp(self):
        super(TestRequestContextSerializer, self).setUp()
        self.mock_base = mock.Mock()
        self.ser = rpc.RequestContextSerializer(self.mock_base)
        self.ser_null = rpc.RequestContextSerializer(None)

    def test_serialize_entity(self):
        self.mock_base.serialize_entity.return_value = 'foo'

        ser_ent = self.ser.serialize_entity('context', 'entity')

        self.mock_base.serialize_entity.assert_called_once_with('context',
                                                                'entity')
        self.assertEqual('foo', ser_ent)

    def test_serialize_entity_null_base(self):
        ser_ent = self.ser_null.serialize_entity('context', 'entity')

        self.assertEqual('entity', ser_ent)

    def test_deserialize_entity(self):
        self.mock_base.deserialize_entity.return_value = 'foo'

        deser_ent = self.ser.deserialize_entity('context', 'entity')

        self.mock_base.deserialize_entity.assert_called_once_with('context',
                                                                  'entity')
        self.assertEqual('foo', deser_ent)

    def test_deserialize_entity_null_base(self):
        deser_ent = self.ser_null.deserialize_entity('context', 'entity')

        self.assertEqual('entity', deser_ent)

    def test_serialize_context(self):
        context = mock.Mock()

        self.ser.serialize_context(context)

        context.to_dict.assert_called_once_with()

    @mock.patch.object(context, 'RequestContext')
    def test_deserialize_context(self, mock_req):
        self.ser.deserialize_context('context')

        mock_req.from_dict.assert_called_once_with('context')


class TestProfilerRequestContextSerializer(test.NoDBTestCase):
    def setUp(self):
        super(TestProfilerRequestContextSerializer, self).setUp()
        self.ser = rpc.ProfilerRequestContextSerializer(mock.Mock())

    @mock.patch('nova.rpc.profiler')
    def test_serialize_context(self, mock_profiler):
        prof = mock_profiler.get.return_value
        prof.hmac_key = 'swordfish'
        prof.get_base_id.return_value = 'baseid'
        prof.get_id.return_value = 'parentid'

        context = mock.Mock()
        context.to_dict.return_value = {'project_id': 'test'}

        self.assertEqual({'project_id': 'test',
                          'trace_info': {
                              'hmac_key': 'swordfish',
                              'base_id': 'baseid',
                              'parent_id': 'parentid'}},
                          self.ser.serialize_context(context))

    @mock.patch('nova.rpc.profiler')
    def test_deserialize_context(self, mock_profiler):
        serialized = {'project_id': 'test',
                      'trace_info': {
                          'hmac_key': 'swordfish',
                          'base_id': 'baseid',
                          'parent_id': 'parentid'}}

        context = self.ser.deserialize_context(serialized)

        self.assertEqual('test', context.project_id)
        mock_profiler.init.assert_called_once_with(
            hmac_key='swordfish', base_id='baseid', parent_id='parentid')


class TestClientRouter(test.NoDBTestCase):
    @mock.patch('oslo_messaging.RPCClient')
    def test_by_instance(self, mock_rpcclient):
        default_client = mock.Mock()
        cell_client = mock.Mock()
        mock_rpcclient.return_value = cell_client
        ctxt = mock.Mock()
        ctxt.mq_connection = mock.sentinel.transport

        router = rpc.ClientRouter(default_client)
        client = router.client(ctxt)

        # verify a client was created by ClientRouter
        mock_rpcclient.assert_called_once_with(
                mock.sentinel.transport, default_client.target,
                version_cap=default_client.version_cap,
                call_monitor_timeout=default_client.call_monitor_timeout,
                serializer=default_client.serializer)
        # verify cell client was returned
        self.assertEqual(cell_client, client)

    @mock.patch('oslo_messaging.RPCClient')
    def test_by_instance_untargeted(self, mock_rpcclient):
        default_client = mock.Mock()
        cell_client = mock.Mock()
        mock_rpcclient.return_value = cell_client
        ctxt = mock.Mock()
        ctxt.mq_connection = None

        router = rpc.ClientRouter(default_client)
        client = router.client(ctxt)

        self.assertEqual(router.default_client, client)
        self.assertFalse(mock_rpcclient.called)


class TestIsNotificationsEnabledDecorator(test.NoDBTestCase):

    def setUp(self):
        super(TestIsNotificationsEnabledDecorator, self).setUp()
        self.f = mock.Mock()
        self.f.__name__ = 'f'
        self.decorated = rpc.if_notifications_enabled(self.f)

    def test_call_func_if_needed(self):
        self.decorated()
        self.f.assert_called_once_with()

    @mock.patch('nova.rpc.NOTIFIER.is_enabled', return_value=False)
    def test_not_call_func_if_notifier_disabled(self, mock_is_enabled):
        self.decorated()
        self.assertEqual(0, len(self.f.mock_calls))

    def test_not_call_func_if_only_unversioned_notifications_requested(self):
        self.flags(notification_format='unversioned', group='notifications')
        self.decorated()
        self.assertEqual(0, len(self.f.mock_calls))
