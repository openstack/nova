# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack, LLC
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
Unit Tests for 'common' functons used through rpc code.
"""

import json
import sys

from nova import context
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova.rpc import amqp as rpc_amqp
from nova.rpc import common as rpc_common
from nova.tests.rpc import common

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


def raise_exception():
    raise Exception("test")


class FakeUserDefinedException(Exception):
    def __init__(self):
        Exception.__init__(self, "Test Message")


class RpcCommonTestCase(test.TestCase):
    def test_serialize_remote_exception(self):
        expected = {
            'class': 'Exception',
            'module': 'exceptions',
            'message': 'test',
        }

        try:
            raise_exception()
        except Exception as exc:
            failure = rpc_common.serialize_remote_exception(sys.exc_info())

        failure = json.loads(failure)
        #assure the traceback was added
        self.assertEqual(expected['class'], failure['class'])
        self.assertEqual(expected['module'], failure['module'])
        self.assertEqual(expected['message'], failure['message'])

    def test_serialize_remote_nova_exception(self):
        def raise_nova_exception():
            raise exception.NovaException("test", code=500)

        expected = {
            'class': 'NovaException',
            'module': 'nova.exception',
            'kwargs': {'code': 500},
            'message': 'test'
        }

        try:
            raise_nova_exception()
        except Exception as exc:
            failure = rpc_common.serialize_remote_exception(sys.exc_info())

        failure = json.loads(failure)
        #assure the traceback was added
        self.assertEqual(expected['class'], failure['class'])
        self.assertEqual(expected['module'], failure['module'])
        self.assertEqual(expected['kwargs'], failure['kwargs'])
        self.assertEqual(expected['message'], failure['message'])

    def test_deserialize_remote_exception(self):
        failure = {
            'class': 'NovaException',
            'module': 'nova.exception',
            'message': 'test message',
            'tb': ['raise NovaException'],
        }
        serialized = json.dumps(failure)

        after_exc = rpc_common.deserialize_remote_exception(serialized)
        self.assertTrue(isinstance(after_exc, exception.NovaException))
        self.assertTrue('test message' in unicode(after_exc))
        #assure the traceback was added
        self.assertTrue('raise NovaException' in unicode(after_exc))

    def test_deserialize_remote_exception_bad_module(self):
        failure = {
            'class': 'popen2',
            'module': 'os',
            'kwargs': {'cmd': '/bin/echo failed'},
            'message': 'foo',
        }
        serialized = json.dumps(failure)

        after_exc = rpc_common.deserialize_remote_exception(serialized)
        self.assertTrue(isinstance(after_exc, rpc_common.RemoteError))

    def test_deserialize_remote_exception_user_defined_exception(self):
        """Ensure a user defined exception can be deserialized."""
        self.flags(allowed_rpc_exception_modules=[self.__class__.__module__])
        failure = {
            'class': 'FakeUserDefinedException',
            'module': self.__class__.__module__,
            'tb': ['raise FakeUserDefinedException'],
        }
        serialized = json.dumps(failure)

        after_exc = rpc_common.deserialize_remote_exception(serialized)
        self.assertTrue(isinstance(after_exc, FakeUserDefinedException))
        #assure the traceback was added
        self.assertTrue('raise FakeUserDefinedException' in unicode(after_exc))

    def test_deserialize_remote_exception_cannot_recreate(self):
        """Ensure a RemoteError is returned on initialization failure.

        If an exception cannot be recreated with it's original class then a
        RemoteError with the exception informations should still be returned.

        """
        self.flags(allowed_rpc_exception_modules=[self.__class__.__module__])
        failure = {
            'class': 'FakeIDontExistException',
            'module': self.__class__.__module__,
            'tb': ['raise FakeIDontExistException'],
        }
        serialized = json.dumps(failure)

        after_exc = rpc_common.deserialize_remote_exception(serialized)
        self.assertTrue(isinstance(after_exc, rpc_common.RemoteError))
        #assure the traceback was added
        self.assertTrue('raise FakeIDontExistException' in unicode(after_exc))
