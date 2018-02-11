#    Copyright 2010 OpenStack Foundation
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

import errno
import socket
import tempfile

import fixtures

from nova.db import api as db
from nova import test
from nova.tests.unit import utils as test_utils


class TestUtilsTestCase(test.TestCase):
    def test_get_test_admin_context(self):
        # get_test_admin_context's return value behaves like admin context.
        ctxt = test_utils.get_test_admin_context()

        # TODO(soren): This should verify the full interface context
        # objects expose.
        self.assertTrue(ctxt.is_admin)

    def test_get_test_instance(self):
        # get_test_instance's return value looks like an instance_ref.
        instance_ref = test_utils.get_test_instance()
        ctxt = test_utils.get_test_admin_context()
        db.instance_get(ctxt, instance_ref['id'])

    def test_ipv6_supported(self):
        self.assertIn(test_utils.is_ipv6_supported(), (False, True))

        def fake_open(path):
            raise IOError

        def fake_socket_fail(x, y):
            e = socket.error()
            e.errno = errno.EAFNOSUPPORT
            raise e

        def fake_socket_ok(x, y):
            return tempfile.TemporaryFile()

        with fixtures.MonkeyPatch('socket.socket', fake_socket_fail):
            self.assertFalse(test_utils.is_ipv6_supported())

        with fixtures.MonkeyPatch('socket.socket', fake_socket_ok):
            with fixtures.MonkeyPatch('sys.platform', 'windows'):
                self.assertTrue(test_utils.is_ipv6_supported())

            with fixtures.MonkeyPatch('sys.platform', 'linux2'):
                with fixtures.MonkeyPatch('six.moves.builtins.open',
                                          fake_open):
                    self.assertFalse(test_utils.is_ipv6_supported())
