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
Unit Tests for remote procedure calls using fake_impl
"""

from nova import log as logging
from nova.rpc import impl_fake
from nova.tests.rpc import common


LOG = logging.getLogger('nova.tests.rpc')


class RpcFakeTestCase(common._BaseRpcTestCase):
    def setUp(self):
        self.rpc = impl_fake
        super(RpcFakeTestCase, self).setUp()

    def tearDown(self):
        super(RpcFakeTestCase, self).tearDown()
