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

from nova import context
from nova import log as logging
from nova import test
from nova.rpc import impl_kombu
from nova.tests import test_rpc_common


LOG = logging.getLogger('nova.tests.rpc')


class RpcKombuTestCase(test_rpc_common._BaseRpcTestCase):
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
