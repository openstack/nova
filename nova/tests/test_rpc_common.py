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
Unit Tests for remote procedure calls shared between all implementations
"""

from nova import context
from nova import log as logging
from nova.rpc.common import RemoteError
from nova import test


LOG = logging.getLogger('nova.tests.rpc')


class _BaseRpcTestCase(test.TestCase):
    def setUp(self):
        super(_BaseRpcTestCase, self).setUp()
        self.conn = self.rpc.create_connection(True)
        self.receiver = TestReceiver()
        self.conn.create_consumer('test', self.receiver, False)
        self.conn.consume_in_thread()
        self.context = context.get_admin_context()

    def tearDown(self):
        self.conn.close()
        super(_BaseRpcTestCase, self).tearDown()

    def test_call_succeed(self):
        value = 42
        result = self.rpc.call(self.context, 'test', {"method": "echo",
                                                 "args": {"value": value}})
        self.assertEqual(value, result)

    def test_call_succeed_despite_multiple_returns(self):
        value = 42
        result = self.rpc.call(self.context, 'test',
                {"method": "echo_three_times",
                 "args": {"value": value}})
        self.assertEqual(value + 2, result)

    def test_call_succeed_despite_multiple_returns_yield(self):
        value = 42
        result = self.rpc.call(self.context, 'test',
                          {"method": "echo_three_times_yield",
                           "args": {"value": value}})
        self.assertEqual(value + 2, result)

    def test_multicall_succeed_once(self):
        value = 42
        result = self.rpc.multicall(self.context,
                              'test',
                              {"method": "echo",
                               "args": {"value": value}})
        for i, x in enumerate(result):
            if i > 0:
                self.fail('should only receive one response')
            self.assertEqual(value + i, x)

    def test_multicall_succeed_three_times(self):
        value = 42
        result = self.rpc.multicall(self.context,
                              'test',
                              {"method": "echo_three_times",
                               "args": {"value": value}})
        for i, x in enumerate(result):
            self.assertEqual(value + i, x)

    def test_multicall_succeed_three_times_yield(self):
        value = 42
        result = self.rpc.multicall(self.context,
                              'test',
                              {"method": "echo_three_times_yield",
                               "args": {"value": value}})
        for i, x in enumerate(result):
            self.assertEqual(value + i, x)

    def test_context_passed(self):
        """Makes sure a context is passed through rpc call."""
        value = 42
        result = self.rpc.call(self.context,
                          'test', {"method": "context",
                                   "args": {"value": value}})
        self.assertEqual(self.context.to_dict(), result)

    def test_call_exception(self):
        """Test that exception gets passed back properly.

        rpc.call returns a RemoteError object.  The value of the
        exception is converted to a string, so we convert it back
        to an int in the test.

        """
        value = 42
        self.assertRaises(RemoteError,
                          self.rpc.call,
                          self.context,
                          'test',
                          {"method": "fail",
                           "args": {"value": value}})
        try:
            self.rpc.call(self.context,
                     'test',
                     {"method": "fail",
                      "args": {"value": value}})
            self.fail("should have thrown RemoteError")
        except RemoteError as exc:
            self.assertEqual(int(exc.value), value)

    def test_nested_calls(self):
        """Test that we can do an rpc.call inside another call."""
        class Nested(object):
            @staticmethod
            def echo(context, queue, value):
                """Calls echo in the passed queue"""
                LOG.debug(_("Nested received %(queue)s, %(value)s")
                        % locals())
                # TODO: so, it will replay the context and use the same REQID?
                # that's bizarre.
                ret = self.rpc.call(context,
                               queue,
                               {"method": "echo",
                                "args": {"value": value}})
                LOG.debug(_("Nested return %s"), ret)
                return value

        nested = Nested()
        conn = self.rpc.create_connection(True)
        conn.create_consumer('nested', nested, False)
        conn.consume_in_thread()
        value = 42
        result = self.rpc.call(self.context,
                          'nested', {"method": "echo",
                                     "args": {"queue": "test",
                                              "value": value}})
        conn.close()
        self.assertEqual(value, result)


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
