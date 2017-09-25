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
import copy

import fixtures
import mock
import oslo_messaging as messaging
from oslo_messaging.rpc import dispatcher
from oslo_serialization import jsonutils

from nova import context
from nova import rpc
from nova import test


# Make a class that resets all of the global variables in nova.rpc
class RPCResetFixture(fixtures.Fixture):
    def _setUp(self):
        self.trans = copy.copy(rpc.TRANSPORT)
        self.noti_trans = copy.copy(rpc.NOTIFICATION_TRANSPORT)
        self.noti = copy.copy(rpc.NOTIFIER)
        self.all_mods = copy.copy(rpc.ALLOWED_EXMODS)
        self.ext_mods = copy.copy(rpc.EXTRA_EXMODS)
        self.conf = copy.copy(rpc.CONF)
        self.addCleanup(self._reset_everything)

    def _reset_everything(self):
        rpc.TRANSPORT = self.trans
        rpc.NOTIFICATION_TRANSPORT = self.noti_trans
        rpc.NOTIFIER = self.noti
        rpc.ALLOWED_EXMODS = self.all_mods
        rpc.EXTRA_EXMODS = self.ext_mods
        rpc.CONF = self.conf


class TestRPC(test.NoDBTestCase):

    # We're testing the rpc code so we can't use the RPCFixture.
    STUB_RPC = False

    def setUp(self):
        super(TestRPC, self).setUp()
        self.useFixture(RPCResetFixture())

    @mock.patch.object(rpc, 'get_allowed_exmods')
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'get_notification_transport')
    @mock.patch.object(messaging, 'Notifier')
    def test_init_unversioned(self, mock_notif, mock_noti_trans,
                              mock_ser, mock_exmods):
        # The expected call to get the legacy notifier will require no new
        # kwargs, and we expect the new notifier will need the noop driver
        expected = [{}, {'driver': 'noop'}]
        self._test_init(mock_notif, mock_noti_trans, mock_ser,
                        mock_exmods, 'unversioned', expected)

    @mock.patch.object(rpc, 'get_allowed_exmods')
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'get_notification_transport')
    @mock.patch.object(messaging, 'Notifier')
    def test_init_both(self, mock_notif, mock_noti_trans,
                       mock_ser, mock_exmods):
        expected = [{}, {'topics': ['versioned_notifications']}]
        self._test_init(mock_notif, mock_noti_trans, mock_ser,
                        mock_exmods, 'both', expected)

    @mock.patch.object(rpc, 'get_allowed_exmods')
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'get_notification_transport')
    @mock.patch.object(messaging, 'Notifier')
    def test_init_versioned(self, mock_notif, mock_noti_trans,
                            mock_ser, mock_exmods):
        expected = [{'driver': 'noop'},
                    {'topics': ['versioned_notifications']}]
        self._test_init(mock_notif, mock_noti_trans, mock_ser,
                        mock_exmods, 'versioned', expected)

    @mock.patch.object(rpc, 'get_allowed_exmods')
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'get_notification_transport')
    @mock.patch.object(messaging, 'Notifier')
    def test_init_versioned_with_custom_topics(self, mock_notif,
                                               mock_noti_trans, mock_ser,
                                               mock_exmods):
        expected = [{'driver': 'noop'},
                    {'topics': ['custom_topic1', 'custom_topic2']}]
        self._test_init(
            mock_notif, mock_noti_trans, mock_ser, mock_exmods, 'versioned',
            expected, versioned_notification_topics=['custom_topic1',
                                                     'custom_topic2'])

    def test_cleanup_transport_null(self):
        rpc.NOTIFICATION_TRANSPORT = mock.Mock()
        rpc.LEGACY_NOTIFIER = mock.Mock()
        rpc.NOTIFIER = mock.Mock()
        self.assertRaises(AssertionError, rpc.cleanup)

    def test_cleanup_notification_transport_null(self):
        rpc.TRANSPORT = mock.Mock()
        rpc.NOTIFIER = mock.Mock()
        self.assertRaises(AssertionError, rpc.cleanup)

    def test_cleanup_legacy_notifier_null(self):
        rpc.TRANSPORT = mock.Mock()
        rpc.NOTIFICATION_TRANSPORT = mock.Mock()
        rpc.NOTIFIER = mock.Mock()

    def test_cleanup_notifier_null(self):
        rpc.TRANSPORT = mock.Mock()
        rpc.LEGACY_NOTIFIER = mock.Mock()
        rpc.NOTIFICATION_TRANSPORT = mock.Mock()
        self.assertRaises(AssertionError, rpc.cleanup)

    def test_cleanup(self):
        rpc.LEGACY_NOTIFIER = mock.Mock()
        rpc.NOTIFIER = mock.Mock()
        rpc.NOTIFICATION_TRANSPORT = mock.Mock()
        rpc.TRANSPORT = mock.Mock()
        trans_cleanup = mock.Mock()
        not_trans_cleanup = mock.Mock()
        rpc.TRANSPORT.cleanup = trans_cleanup
        rpc.NOTIFICATION_TRANSPORT.cleanup = not_trans_cleanup

        rpc.cleanup()

        trans_cleanup.assert_called_once_with()
        not_trans_cleanup.assert_called_once_with()
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
        rpc.EXTRA_EXMODS = []

        rpc.add_extra_exmods('foo', 'bar')

        self.assertEqual(['foo', 'bar'], rpc.EXTRA_EXMODS)

    def test_clear_extra_exmods(self):
        rpc.EXTRA_EXMODS = ['foo', 'bar']

        rpc.clear_extra_exmods()

        self.assertEqual(0, len(rpc.EXTRA_EXMODS))

    def test_get_allowed_exmods(self):
        rpc.ALLOWED_EXMODS = ['foo']
        rpc.EXTRA_EXMODS = ['bar']

        exmods = rpc.get_allowed_exmods()

        self.assertEqual(['foo', 'bar'], exmods)

    @mock.patch.object(messaging, 'TransportURL')
    def test_get_transport_url(self, mock_url):
        conf = mock.Mock()
        rpc.CONF = conf
        mock_url.parse.return_value = 'foo'

        url = rpc.get_transport_url(url_str='bar')

        self.assertEqual('foo', url)
        mock_url.parse.assert_called_once_with(conf, 'bar')

    @mock.patch.object(messaging, 'TransportURL')
    def test_get_transport_url_null(self, mock_url):
        conf = mock.Mock()
        rpc.CONF = conf
        mock_url.parse.return_value = 'foo'

        url = rpc.get_transport_url()

        self.assertEqual('foo', url)
        mock_url.parse.assert_called_once_with(conf, None)

    @mock.patch.object(rpc, 'profiler', None)
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'RPCClient')
    def test_get_client(self, mock_client, mock_ser):
        rpc.TRANSPORT = mock.Mock()
        tgt = mock.Mock()
        ser = mock.Mock()
        mock_client.return_value = 'client'
        mock_ser.return_value = ser

        client = rpc.get_client(tgt, version_cap='1.0', serializer='foo')

        mock_ser.assert_called_once_with('foo')
        mock_client.assert_called_once_with(rpc.TRANSPORT,
                                            tgt, version_cap='1.0',
                                            serializer=ser)
        self.assertEqual('client', client)

    @mock.patch.object(rpc, 'profiler', None)
    @mock.patch.object(rpc, 'RequestContextSerializer')
    @mock.patch.object(messaging, 'get_rpc_server')
    def test_get_server(self, mock_get, mock_ser):
        rpc.TRANSPORT = mock.Mock()
        ser = mock.Mock()
        tgt = mock.Mock()
        ends = mock.Mock()
        mock_ser.return_value = ser
        mock_get.return_value = 'server'

        server = rpc.get_server(tgt, ends, serializer='foo')

        mock_ser.assert_called_once_with('foo')
        access_policy = dispatcher.DefaultRPCAccessPolicy
        mock_get.assert_called_once_with(rpc.TRANSPORT, tgt, ends,
                                         executor='eventlet', serializer=ser,
                                         access_policy=access_policy)
        self.assertEqual('server', server)

    @mock.patch.object(rpc, 'profiler', mock.Mock())
    @mock.patch.object(rpc, 'ProfilerRequestContextSerializer')
    @mock.patch.object(messaging, 'RPCClient')
    def test_get_client_profiler_enabled(self, mock_client, mock_ser):
        rpc.TRANSPORT = mock.Mock()
        tgt = mock.Mock()
        ser = mock.Mock()
        mock_client.return_value = 'client'
        mock_ser.return_value = ser

        client = rpc.get_client(tgt, version_cap='1.0', serializer='foo')

        mock_ser.assert_called_once_with('foo')
        mock_client.assert_called_once_with(rpc.TRANSPORT,
                                            tgt, version_cap='1.0',
                                            serializer=ser)
        self.assertEqual('client', client)

    @mock.patch.object(rpc, 'profiler', mock.Mock())
    @mock.patch.object(rpc, 'ProfilerRequestContextSerializer')
    @mock.patch.object(messaging, 'get_rpc_server')
    def test_get_server_profiler_enabled(self, mock_get, mock_ser):
        rpc.TRANSPORT = mock.Mock()
        ser = mock.Mock()
        tgt = mock.Mock()
        ends = mock.Mock()
        mock_ser.return_value = ser
        mock_get.return_value = 'server'

        server = rpc.get_server(tgt, ends, serializer='foo')

        mock_ser.assert_called_once_with('foo')
        access_policy = dispatcher.DefaultRPCAccessPolicy
        mock_get.assert_called_once_with(rpc.TRANSPORT, tgt, ends,
                                         executor='eventlet', serializer=ser,
                                         access_policy=access_policy)
        self.assertEqual('server', server)

    def test_get_notifier(self):
        rpc.LEGACY_NOTIFIER = mock.Mock()
        mock_prep = mock.Mock()
        mock_prep.return_value = 'notifier'
        rpc.LEGACY_NOTIFIER.prepare = mock_prep

        notifier = rpc.get_notifier('service', publisher_id='foo')

        mock_prep.assert_called_once_with(publisher_id='foo')
        self.assertIsInstance(notifier, rpc.LegacyValidatingNotifier)
        self.assertEqual('notifier', notifier.notifier)

    def test_get_notifier_null_publisher(self):
        rpc.LEGACY_NOTIFIER = mock.Mock()
        mock_prep = mock.Mock()
        mock_prep.return_value = 'notifier'
        rpc.LEGACY_NOTIFIER.prepare = mock_prep

        notifier = rpc.get_notifier('service', host='bar')

        mock_prep.assert_called_once_with(publisher_id='service.bar')
        self.assertIsInstance(notifier, rpc.LegacyValidatingNotifier)
        self.assertEqual('notifier', notifier.notifier)

    def test_get_versioned_notifier(self):
        rpc.NOTIFIER = mock.Mock()
        mock_prep = mock.Mock()
        mock_prep.return_value = 'notifier'
        rpc.NOTIFIER.prepare = mock_prep

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

    def _test_init(self, mock_notif, mock_noti_trans, mock_ser,
                   mock_exmods, notif_format, expected_driver_topic_kwargs,
                   versioned_notification_topics=['versioned_notifications']):
        legacy_notifier = mock.Mock()
        notifier = mock.Mock()
        notif_transport = mock.Mock()
        transport = mock.Mock()
        serializer = mock.Mock()
        conf = mock.Mock()

        conf.transport_url = None
        conf.notifications.notification_format = notif_format
        conf.notifications.versioned_notifications_topics = (
            versioned_notification_topics)
        mock_exmods.return_value = ['foo']
        mock_noti_trans.return_value = notif_transport
        mock_ser.return_value = serializer
        mock_notif.side_effect = [legacy_notifier, notifier]

        @mock.patch.object(rpc, 'CONF', new=conf)
        @mock.patch.object(rpc, 'create_transport')
        @mock.patch.object(rpc, 'get_transport_url')
        def _test(get_url, create_transport):
            create_transport.return_value = transport
            rpc.init(conf)
            create_transport.assert_called_once_with(get_url.return_value)

        _test()

        self.assertTrue(mock_exmods.called)
        self.assertIsNotNone(rpc.TRANSPORT)
        self.assertIsNotNone(rpc.LEGACY_NOTIFIER)
        self.assertIsNotNone(rpc.NOTIFIER)
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


class TestJsonPayloadSerializer(test.NoDBTestCase):
    def test_serialize_entity(self):
        with mock.patch.object(jsonutils, 'to_primitive') as mock_prim:
            rpc.JsonPayloadSerializer.serialize_entity('context', 'entity')

        mock_prim.assert_called_once_with('entity', convert_instances=True)


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
