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
import webob

import nova.api
from nova import flags
from nova.api.openstack import flavors
from nova.tests.api.openstack import fakes

FLAGS = flags.FLAGS

class RestrictedAPITest(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.original_permissions = FLAGS.nova_api_permitted_operations

    def tearDown(self):
        self.stubs.UnsetAll()
        FLAGS.nova_api_permitted_operations = self.original_permissions

    def test_permitted(self):
        req = webob.Request.blank('/v1.0/flavors')
        FLAGS.nova_api_permitted_operations = ["server", "backup_schedule", "image", "flavor", "sharedipgroup"]
        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status_int, 200)

    def test_bad_list(self):
        req = webob.Request.blank('/v1.0/flavors')
        FLAGS.nova_api_permitted_operations = ["foo", "bar", "zoo"]
        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status_int, 404)

    def test_default_all_permitted(self):
        req = webob.Request.blank('/v1.0/flavors')
        # empty means all operations available.
        FLAGS.nova_api_permitted_operations = []
        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status_int, 200)

    def test_disallowed(self):
        req = webob.Request.blank('/v1.0/flavors')
        FLAGS.nova_api_permitted_operations = ["server", "backup_schedule", "image", "sharedipgroup"]
        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status_int, 404)

if __name__ == '__main__':
    unittest.main()
