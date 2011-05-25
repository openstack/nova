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
Unit Tests for remote procedure calls using queue
"""

from nova import context
from nova import flags
from nova import log as logging
from nova import rpc
from nova import test


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.rpc')


class RpcTestCase(test.TestCase):
    """Test cases for rpc"""
    def setUp(self):
        super(RpcTestCase, self).setUp()
        self.conn = rpc.Connection.instance(True)
        self.receiver = TestReceiver()
        self.consumer = rpc.TopicAdapterConsumer(connection=self.conn,
                                            topic='test',
                                            proxy=self.receiver)
        self.consumer.attach_to_eventlet()
        self.context = context.get_admin_context()

    def test_call_succeed(self):
        """Get a value through rpc call"""
        value = 42
        result = rpc.call(self.context, 'test', {"method": "echo",
                                                 "args": {"value": value}})
        self.assertEqual(value, result)

    def test_multicall_succeed_three_times(self):
        """Get a value through rpc call"""
        value = 42
        result = rpc.multicall(self.context,
                              'test',
                              {"method": "echo_three_times",
                               "args": {"value": value}})

        for x in result:
            self.assertEqual(value, x)

    def test_context_passed(self):
        """Makes sure a context is passed through rpc call"""
        value = 42
        result = rpc.call(self.context,
                          'test', {"method": "context",
                                   "args": {"value": value}})
        self.assertEqual(self.context.to_dict(), result)

    def test_call_exception(self):
        """Test that exception gets passed back properly

        rpc.call returns a RemoteError object.  The value of the
        exception is converted to a string, so we convert it back
        to an int in the test.
        """
        value = 42
        self.assertRaises(rpc.RemoteError,
                          rpc.call,
                          self.context,
                          'test',
                          {"method": "fail",
                           "args": {"value": value}})
        try:
            rpc.call(self.context,
                     'test',
                     {"method": "fail",
                      "args": {"value": value}})
            self.fail("should have thrown rpc.RemoteError")
        except rpc.RemoteError as exc:
            self.assertEqual(int(exc.value), value)

    def test_nested_calls(self):
        """Test that we can do an rpc.call inside another call"""
        class Nested(object):
            @staticmethod
            def echo(context, queue, value):
                """Calls echo in the passed queue"""
                LOG.debug(_("Nested received %(queue)s, %(value)s")
                        % locals())
                ret = rpc.call(context,
                               queue,
                               {"method": "echo",
                                "args": {"value": value}})
                LOG.debug(_("Nested return %s"), ret)
                return value

        nested = Nested()
        conn = rpc.Connection.instance(True)
        consumer = rpc.TopicAdapterConsumer(connection=conn,
                                       topic='nested',
                                       proxy=nested)
        consumer.attach_to_eventlet()
        value = 42
        result = rpc.call(self.context,
                          'nested', {"method": "echo",
                                     "args": {"queue": "test",
                                              "value": value}})
        self.assertEqual(value, result)


class TestReceiver(object):
    """Simple Proxy class so the consumer has methods to call

    Uses static methods because we aren't actually storing any state"""

    @staticmethod
    def echo(context, value):
        """Simply returns whatever value is sent in"""
        LOG.debug(_("Received %s"), value)
        return value

    @staticmethod
    def context(context, value):
        """Returns dictionary version of context"""
        LOG.debug(_("Received %s"), context)
        return context.to_dict()

    @staticmethod
    def echo_three_times(context, value):
        context.reply(value)
        context.reply(value)
        context.reply(value)

    @staticmethod
    def fail(context, value):
        """Raises an exception with the value sent in"""
        raise Exception(value)
