# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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
Unit Tests for nova.console.rpcapi
"""

from nova.console import rpcapi as console_rpcapi
from nova import context
from nova import flags
from nova.openstack.common import rpc
from nova import test


FLAGS = flags.FLAGS


class ConsoleRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(ConsoleRpcAPITestCase, self).setUp()

    def tearDown(self):
        super(ConsoleRpcAPITestCase, self).tearDown()

    def _test_console_api(self, method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = console_rpcapi.ConsoleAPI()
        expected_msg = rpcapi.make_msg(method, **kwargs)
        expected_msg['version'] = rpcapi.BASE_RPC_API_VERSION

        self.cast_ctxt = None
        self.cast_topic = None
        self.cast_msg = None

        def _fake_cast(_ctxt, _topic, _msg):
            self.cast_ctxt = _ctxt
            self.cast_topic = _topic
            self.cast_msg = _msg

        self.stubs.Set(rpc, 'cast', _fake_cast)

        getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(self.cast_ctxt, ctxt)
        self.assertEqual(self.cast_topic, FLAGS.console_topic)
        self.assertEqual(self.cast_msg, expected_msg)

    def test_add_console(self):
        self._test_console_api('add_console', instance_id='i')

    def test_remove_console(self):
        self._test_console_api('remove_console', console_id='i')
