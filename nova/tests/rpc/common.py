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

import time

import eventlet
from eventlet import greenthread
import nose

from nova import context
from nova import exception
from nova import flags
from nova import log as logging
from nova.rpc import amqp as rpc_amqp
from nova.rpc import common as rpc_common
from nova.rpc import dispatcher as rpc_dispatcher
from nova import test


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class BaseRpcTestCase(test.TestCase):
    def setUp(self, supports_timeouts=True, topic='test',
              topic_nested='nested'):
        super(BaseRpcTestCase, self).setUp()
        self.topic = topic or self.topic
        self.topic_nested = topic_nested or self.topic_nested
        self.supports_timeouts = supports_timeouts
        self.context = context.get_admin_context()

        if self.rpc:
            receiver = TestReceiver()
            self.conn = self._create_consumer(receiver, self.topic)

    def tearDown(self):
        if self.rpc:
            self.conn.close()
        super(BaseRpcTestCase, self).tearDown()

    def _create_consumer(self, proxy, topic, fanout=False):
        dispatcher = rpc_dispatcher.RpcDispatcher([proxy])
        conn = self.rpc.create_connection(FLAGS, True)
        conn.create_consumer(topic, dispatcher, fanout)
        conn.consume_in_thread()
        return conn

    def test_call_succeed(self):
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        value = 42
        result = self.rpc.call(FLAGS, self.context, self.topic,
                               {"method": "echo", "args": {"value": value}})
        self.assertEqual(value, result)

    def test_call_succeed_despite_multiple_returns_yield(self):
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        value = 42
        result = self.rpc.call(FLAGS, self.context, self.topic,
                          {"method": "echo_three_times_yield",
                           "args": {"value": value}})
        self.assertEqual(value + 2, result)

    def test_multicall_succeed_once(self):
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        value = 42
        result = self.rpc.multicall(FLAGS, self.context,
                              self.topic,
                              {"method": "echo",
                               "args": {"value": value}})
        for i, x in enumerate(result):
            if i > 0:
                self.fail('should only receive one response')
            self.assertEqual(value + i, x)

    def test_multicall_three_nones(self):
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        value = 42
        result = self.rpc.multicall(FLAGS, self.context,
                              self.topic,
                              {"method": "multicall_three_nones",
                               "args": {"value": value}})
        for i, x in enumerate(result):
            self.assertEqual(x, None)
        # i should have been 0, 1, and finally 2:
        self.assertEqual(i, 2)

    def test_multicall_succeed_three_times_yield(self):
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        value = 42
        result = self.rpc.multicall(FLAGS, self.context,
                              self.topic,
                              {"method": "echo_three_times_yield",
                               "args": {"value": value}})
        for i, x in enumerate(result):
            self.assertEqual(value + i, x)

    def test_context_passed(self):
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        """Makes sure a context is passed through rpc call."""
        value = 42
        result = self.rpc.call(FLAGS, self.context,
                          self.topic, {"method": "context",
                                   "args": {"value": value}})
        self.assertEqual(self.context.to_dict(), result)

    def _test_cast(self, fanout=False):
        """Test casts by pushing items through a channeled queue."""

        # Not a true global, but capitalized so
        # it is clear it is leaking scope into Nested()
        QUEUE = eventlet.queue.Queue()

        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        # We use the nested topic so we don't need QUEUE to be a proper
        # global, and do not keep state outside this test.
        class Nested(object):
            @staticmethod
            def put_queue(context, value):
                LOG.debug("Got value in put_queue: %s", value)
                QUEUE.put(value)

        nested = Nested()
        conn = self._create_consumer(nested, self.topic_nested, fanout)
        value = 42

        method = (self.rpc.cast, self.rpc.fanout_cast)[fanout]
        method(FLAGS, self.context,
               self.topic_nested,
               {"method": "put_queue",
                "args": {"value": value}})

        try:
            # If it does not succeed in 2 seconds, give up and assume
            # failure.
            result = QUEUE.get(True, 2)
        except Exception:
            self.assertEqual(value, None)

        conn.close()
        self.assertEqual(value, result)

    def test_cast_success(self):
        self._test_cast(False)

    def test_fanout_success(self):
        self._test_cast(True)

    def test_nested_calls(self):
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        """Test that we can do an rpc.call inside another call."""
        class Nested(object):
            @staticmethod
            def echo(context, queue, value):
                """Calls echo in the passed queue."""
                LOG.debug(_("Nested received %(queue)s, %(value)s")
                        % locals())
                # TODO(comstud):
                # so, it will replay the context and use the same REQID?
                # that's bizarre.
                ret = self.rpc.call(FLAGS, context,
                               queue,
                               {"method": "echo",
                                "args": {"value": value}})
                LOG.debug(_("Nested return %s"), ret)
                return value

        nested = Nested()
        conn = self._create_consumer(nested, self.topic_nested)

        value = 42
        result = self.rpc.call(FLAGS, self.context,
                               self.topic_nested,
                               {"method": "echo",
                                "args": {"queue": "test", "value": value}})
        conn.close()
        self.assertEqual(value, result)

    def test_call_timeout(self):
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        """Make sure rpc.call will time out."""
        if not self.supports_timeouts:
            raise nose.SkipTest(_("RPC backend does not support timeouts"))

        value = 42
        self.assertRaises(rpc_common.Timeout,
                          self.rpc.call,
                          FLAGS, self.context,
                          self.topic,
                          {"method": "block",
                           "args": {"value": value}}, timeout=1)
        try:
            self.rpc.call(FLAGS, self.context,
                     self.topic,
                     {"method": "block",
                      "args": {"value": value}},
                     timeout=1)
            self.fail("should have thrown Timeout")
        except rpc_common.Timeout as exc:
            pass


class BaseRpcAMQPTestCase(BaseRpcTestCase):
    """Base test class for all AMQP-based RPC tests."""
    def test_proxycallback_handles_exceptions(self):
        """Make sure exceptions unpacking messages don't cause hangs."""
        if not self.rpc:
            raise nose.SkipTest('rpc driver not available.')

        orig_unpack = rpc_amqp.unpack_context

        info = {'unpacked': False}

        def fake_unpack_context(*args, **kwargs):
            info['unpacked'] = True
            raise test.TestingException('moo')

        self.stubs.Set(rpc_amqp, 'unpack_context', fake_unpack_context)

        value = 41
        self.rpc.cast(FLAGS, self.context, self.topic,
                      {"method": "echo", "args": {"value": value}})

        # Wait for the cast to complete.
        for x in xrange(50):
            if info['unpacked']:
                break
            greenthread.sleep(0.1)
        else:
            self.fail("Timeout waiting for message to be consumed")

        # Now see if we get a response even though we raised an
        # exception for the cast above.
        self.stubs.Set(rpc_amqp, 'unpack_context', orig_unpack)

        value = 42
        result = self.rpc.call(FLAGS, self.context, self.topic,
                {"method": "echo",
                 "args": {"value": value}})
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
    def multicall_three_nones(context, value):
        yield None
        yield None
        yield None

    @staticmethod
    def echo_three_times_yield(context, value):
        yield value
        yield value + 1
        yield value + 2

    @staticmethod
    def fail(context, value):
        """Raises an exception with the value sent in."""
        raise NotImplementedError(value)

    @staticmethod
    def fail_converted(context, value):
        """Raises an exception with the value sent in."""
        raise exception.ConvertedException(explanation=value)

    @staticmethod
    def block(context, value):
        time.sleep(2)
