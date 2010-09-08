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
import logging

from twisted.internet import defer

from nova import flags
from nova import rpc
from nova import test


FLAGS = flags.FLAGS


class RpcTestCase(test.TrialTestCase):
    """Test cases for rpc"""
    def setUp(self):  # pylint: disable-msg=C0103
        super(RpcTestCase, self).setUp()
        self.conn = rpc.Connection.instance()
        self.receiver = TestReceiver()
        self.consumer = rpc.AdapterConsumer(connection=self.conn,
                                            topic='test',
                                            proxy=self.receiver)

        self.injected.append(self.consumer.attach_to_twisted())

    def test_call_succeed(self):
        """Get a value through rpc call"""
        value = 42
        result = yield rpc.call('test', {"method": "echo",
                                         "args": {"value": value}})
        self.assertEqual(value, result)

    def test_call_exception(self):
        """Test that exception gets passed back properly

        rpc.call returns a RemoteError object.  The value of the
        exception is converted to a string, so we convert it back
        to an int in the test.
        """
        value = 42
        self.assertFailure(rpc.call('test', {"method": "fail",
                                             "args": {"value": value}}),
                           rpc.RemoteError)
        try:
            yield rpc.call('test', {"method": "fail",
                                    "args": {"value": value}})
            self.fail("should have thrown rpc.RemoteError")
        except rpc.RemoteError as exc:
            self.assertEqual(int(exc.value), value)


class TestReceiver(object):
    """Simple Proxy class so the consumer has methods to call

    Uses static methods because we aren't actually storing any state"""

    @staticmethod
    def echo(value):
        """Simply returns whatever value is sent in"""
        logging.debug("Received %s", value)
        return defer.succeed(value)

    @staticmethod
    def fail(value):
        """Raises an exception with the value sent in"""
        raise Exception(value)
