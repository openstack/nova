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
Unit Tests for rpc.dispatcher
"""

from nova import context
from nova.rpc import common as rpc_common
from nova.rpc import dispatcher
from nova import test


class RpcDispatcherTestCase(test.TestCase):
    class API1(object):
        RPC_API_VERSION = '1.0'

        def __init__(self):
            self.test_method_ctxt = None
            self.test_method_arg1 = None

        def test_method(self, ctxt, arg1):
            self.test_method_ctxt = ctxt
            self.test_method_arg1 = arg1

    class API2(object):
        RPC_API_VERSION = '2.1'

        def __init__(self):
            self.test_method_ctxt = None
            self.test_method_arg1 = None

        def test_method(self, ctxt, arg1):
            self.test_method_ctxt = ctxt
            self.test_method_arg1 = arg1

    class API3(object):
        RPC_API_VERSION = '3.5'

        def __init__(self):
            self.test_method_ctxt = None
            self.test_method_arg1 = None

        def test_method(self, ctxt, arg1):
            self.test_method_ctxt = ctxt
            self.test_method_arg1 = arg1

    def setUp(self):
        self.ctxt = context.RequestContext('fake_user', 'fake_project')
        super(RpcDispatcherTestCase, self).setUp()

    def tearDown(self):
        super(RpcDispatcherTestCase, self).tearDown()

    def _test_dispatch(self, version, expectations):
        v2 = self.API2()
        v3 = self.API3()
        disp = dispatcher.RpcDispatcher([v2, v3])

        disp.dispatch(self.ctxt, version, 'test_method', arg1=1)

        self.assertEqual(v2.test_method_ctxt, expectations[0])
        self.assertEqual(v2.test_method_arg1, expectations[1])
        self.assertEqual(v3.test_method_ctxt, expectations[2])
        self.assertEqual(v3.test_method_arg1, expectations[3])

    def test_dispatch(self):
        self._test_dispatch('2.1', (self.ctxt, 1, None, None))
        self._test_dispatch('3.5', (None, None, self.ctxt, 1))

    def test_dispatch_lower_minor_version(self):
        self._test_dispatch('2.0', (self.ctxt, 1, None, None))
        self._test_dispatch('3.1', (None, None, self.ctxt, 1))

    def test_dispatch_higher_minor_version(self):
        self.assertRaises(rpc_common.UnsupportedRpcVersion,
                self._test_dispatch, '2.6', (None, None, None, None))
        self.assertRaises(rpc_common.UnsupportedRpcVersion,
                self._test_dispatch, '3.6', (None, None, None, None))

    def test_dispatch_lower_major_version(self):
        self.assertRaises(rpc_common.UnsupportedRpcVersion,
                self._test_dispatch, '1.0', (None, None, None, None))

    def test_dispatch_higher_major_version(self):
        self.assertRaises(rpc_common.UnsupportedRpcVersion,
                self._test_dispatch, '4.0', (None, None, None, None))

    def test_dispatch_no_version_uses_v1(self):
        v1 = self.API1()
        disp = dispatcher.RpcDispatcher([v1])

        disp.dispatch(self.ctxt, None, 'test_method', arg1=1)

        self.assertEqual(v1.test_method_ctxt, self.ctxt)
        self.assertEqual(v1.test_method_arg1, 1)
