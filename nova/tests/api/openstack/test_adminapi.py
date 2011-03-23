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


import stubout
import webob
from paste import urlmap

from nova import flags
from nova import test
from nova.api import openstack
from nova.api.openstack import auth
from nova.tests.api.openstack import fakes

FLAGS = flags.FLAGS


class AdminAPITest(test.TestCase):

    def setUp(self):
        super(AdminAPITest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.allow_admin = FLAGS.allow_admin_api

    def tearDown(self):
        self.stubs.UnsetAll()
        FLAGS.allow_admin_api = self.allow_admin
        super(AdminAPITest, self).tearDown()

    def test_admin_enabled(self):
        FLAGS.allow_admin_api = True
        # We should still be able to access public operations.
        req = webob.Request.blank('/v1.0/flavors')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        # TODO: Confirm admin operations are available.

    def test_admin_disabled(self):
        FLAGS.allow_admin_api = False
        # We should still be able to access public operations.
        req = webob.Request.blank('/v1.0/flavors')
        res = req.get_response(fakes.wsgi_app())
        # TODO: Confirm admin operations are unavailable.
        self.assertEqual(res.status_int, 200)
