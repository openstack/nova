# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Unit Tests for remote procedure calls using kombu
"""

from nova import log as logging
from nova import test
from nova.rpc import impl_kombu
from nova.tests.rpc import common


LOG = logging.getLogger('nova.tests.rpc')


class MyException(Exception):
    pass


def _raise_exc_stub(stubs, times, obj, method, exc_msg):
    info = {'called': 0}
    orig_method = getattr(obj, method)

    def _raise_stub(*args, **kwargs):
        info['called'] += 1
        if info['called'] <= times:
            raise MyException(exc_msg)
        orig_method(*args, **kwargs)
    stubs.Set(obj, method, _raise_stub)
    return info


class RpcKombuTestCase(common._BaseRpcTestCase):
    def setUp(self):
        self.rpc = impl_kombu
        super(RpcKombuTestCase, self).setUp()

    def tearDown(self):
        super(RpcKombuTestCase, self).tearDown()

    def test_reusing_connection(self):
        """Test that reusing a connection returns same one."""
        conn_context = self.rpc.create_connection(new=False)
        conn1 = conn_context.connection
        conn_context.close()
        conn_context = self.rpc.create_connection(new=False)
        conn2 = conn_context.connection
        conn_context.close()
        self.assertEqual(conn1, conn2)

    def test_topic_send_receive(self):
        """Test sending to a topic exchange/queue"""

        conn = self.rpc.create_connection()
        message = 'topic test message'

        self.received_message = None

        def _callback(message):
            self.received_message = message

        conn.declare_topic_consumer('a_topic', _callback)
        conn.topic_send('a_topic', message)
        conn.consume(limit=1)
        conn.close()

        self.assertEqual(self.received_message, message)

    def test_direct_send_receive(self):
        """Test sending to a direct exchange/queue"""
        conn = self.rpc.create_connection()
        message = 'direct test message'

        self.received_message = None

        def _callback(message):
            self.received_message = message

        conn.declare_direct_consumer('a_direct', _callback)
        conn.direct_send('a_direct', message)
        conn.consume(limit=1)
        conn.close()

        self.assertEqual(self.received_message, message)

    @test.skip_test("kombu memory transport seems buggy with fanout queues "
            "as this test passes when you use rabbit (fake_rabbit=False)")
    def test_fanout_send_receive(self):
        """Test sending to a fanout exchange and consuming from 2 queues"""

        conn = self.rpc.create_connection()
        conn2 = self.rpc.create_connection()
        message = 'fanout test message'

        self.received_message = None

        def _callback(message):
            self.received_message = message

        conn.declare_fanout_consumer('a_fanout', _callback)
        conn2.declare_fanout_consumer('a_fanout', _callback)
        conn.fanout_send('a_fanout', message)

        conn.consume(limit=1)
        conn.close()
        self.assertEqual(self.received_message, message)

        self.received_message = None
        conn2.consume(limit=1)
        conn2.close()
        self.assertEqual(self.received_message, message)

    def test_declare_consumer_errors_will_reconnect(self):
        # Test that any exception with 'timeout' in it causes a
        # reconnection
        info = _raise_exc_stub(self.stubs, 2, self.rpc.DirectConsumer,
                '__init__', 'foo timeout foo')

        conn = self.rpc.Connection()
        result = conn.declare_consumer(self.rpc.DirectConsumer,
                'test_topic', None)

        self.assertEqual(info['called'], 3)
        self.assertTrue(isinstance(result, self.rpc.DirectConsumer))

        # Test that any exception in transport.connection_errors causes
        # a reconnection
        self.stubs.UnsetAll()

        info = _raise_exc_stub(self.stubs, 1, self.rpc.DirectConsumer,
                '__init__', 'meow')

        conn = self.rpc.Connection()
        conn.connection_errors = (MyException, )

        result = conn.declare_consumer(self.rpc.DirectConsumer,
                'test_topic', None)

        self.assertEqual(info['called'], 2)
        self.assertTrue(isinstance(result, self.rpc.DirectConsumer))

    def test_publishing_errors_will_reconnect(self):
        # Test that any exception with 'timeout' in it causes a
        # reconnection when declaring the publisher class and when
        # calling send()
        info = _raise_exc_stub(self.stubs, 2, self.rpc.DirectPublisher,
                '__init__', 'foo timeout foo')

        conn = self.rpc.Connection()
        conn.publisher_send(self.rpc.DirectPublisher, 'test_topic', 'msg')

        self.assertEqual(info['called'], 3)
        self.stubs.UnsetAll()

        info = _raise_exc_stub(self.stubs, 2, self.rpc.DirectPublisher,
                'send', 'foo timeout foo')

        conn = self.rpc.Connection()
        conn.publisher_send(self.rpc.DirectPublisher, 'test_topic', 'msg')

        self.assertEqual(info['called'], 3)

        # Test that any exception in transport.connection_errors causes
        # a reconnection when declaring the publisher class and when
        # calling send()
        self.stubs.UnsetAll()

        info = _raise_exc_stub(self.stubs, 1, self.rpc.DirectPublisher,
                '__init__', 'meow')

        conn = self.rpc.Connection()
        conn.connection_errors = (MyException, )

        conn.publisher_send(self.rpc.DirectPublisher, 'test_topic', 'msg')

        self.assertEqual(info['called'], 2)
        self.stubs.UnsetAll()

        info = _raise_exc_stub(self.stubs, 1, self.rpc.DirectPublisher,
                'send', 'meow')

        conn = self.rpc.Connection()
        conn.connection_errors = (MyException, )

        conn.publisher_send(self.rpc.DirectPublisher, 'test_topic', 'msg')

        self.assertEqual(info['called'], 2)

    def test_iterconsume_errors_will_reconnect(self):
        conn = self.rpc.Connection()
        message = 'reconnect test message'

        self.received_message = None

        def _callback(message):
            self.received_message = message

        conn.declare_direct_consumer('a_direct', _callback)
        conn.direct_send('a_direct', message)

        info = _raise_exc_stub(self.stubs, 1, conn.connection,
                'drain_events', 'foo timeout foo')
        conn.consume(limit=1)
        conn.close()

        self.assertEqual(self.received_message, message)
        # Only called once, because our stub goes away during reconnection
        self.assertEqual(info['called'], 1)
