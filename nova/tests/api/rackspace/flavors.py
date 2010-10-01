# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import unittest
import stubout

import nova.api
from nova.api.rackspace import flavors
from nova.tests.api.rackspace import test_helper
from nova.tests.api.test_helper import *

class FlavorsTest(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        test_helper.FakeAuthManager.auth_data = {}
        test_helper.FakeAuthDatabase.data = {}
        test_helper.stub_for_testing(self.stubs)
        test_helper.stub_out_rate_limiting(self.stubs)
        test_helper.stub_out_auth(self.stubs)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get_flavor_list(self):
        req = webob.Request.blank('/v1.0/flavors')
        res = req.get_response(nova.api.API())

    def test_get_flavor_by_id(self):
        pass

if __name__ == '__main__':
    unittest.main()
