#
# Copyright 2013 - Red Hat, Inc.
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
#

"""
Test the base rpc API.
"""

from nova import baserpc
from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova import test


class BaseAPITestCase(test.TestCase):

    def setUp(self):
        super(BaseAPITestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)
        self.compute = self.start_service('compute')
        self.base_rpcapi = baserpc.BaseAPI(compute_rpcapi.RPC_TOPIC)

    def test_ping(self):
        res = self.base_rpcapi.ping(self.context, 'foo')
        self.assertEqual({'service': 'compute', 'arg': 'foo'}, res)

    def test_get_backdoor_port(self):
        res = self.base_rpcapi.get_backdoor_port(self.context,
                self.compute.host)
        self.assertEqual(self.compute.backdoor_port, res)
