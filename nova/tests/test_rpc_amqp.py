# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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
Tests For RPC AMQP.
"""

from nova import context
from nova import log as logging
from nova import rpc
from nova.rpc import amqp
from nova import test


LOG = logging.getLogger('nova.tests.rpc')


class RpcAMQPTestCase(test.TestCase):
    def setUp(self):
        super(RpcAMQPTestCase, self).setUp()
        self.conn = rpc.create_connection(True)
        self.receiver = TestReceiver()
        self.consumer = rpc.create_consumer(self.conn,
                                            'test',
                                            self.receiver,
                                            False)
        self.consumer.attach_to_eventlet()
        self.context = context.get_admin_context()

    def test_connectionpool_single(self):
        """Test that ConnectionPool recycles a single connection."""
        conn1 = amqp.ConnectionPool.get()
        amqp.ConnectionPool.put(conn1)
        conn2 = amqp.ConnectionPool.get()
        amqp.ConnectionPool.put(conn2)
        self.assertEqual(conn1, conn2)


class TestReceiver(object):
    """Simple Proxy class so the consumer has methods to call.

    Uses static methods because we aren't actually storing any state.

    """

    @staticmethod
    def echo(context, value):
        """Simply returns whatever value is sent in."""
        LOG.debug(_("Received %s"), value)
        return value

    @staticmethod
    def context(context, value):
        """Returns dictionary version of context."""
        LOG.debug(_("Received %s"), context)
        return context.to_dict()

    @staticmethod
    def echo_three_times(context, value):
        context.reply(value)
        context.reply(value + 1)
        context.reply(value + 2)

    @staticmethod
    def echo_three_times_yield(context, value):
        yield value
        yield value + 1
        yield value + 2

    @staticmethod
    def fail(context, value):
        """Raises an exception with the value sent in."""
        raise Exception(value)
