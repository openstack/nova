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

from nova import test
import nova.api
from nova import context
from nova import db
from nova.api.openstack import flavors
from nova.tests.api.openstack import fakes


class FlavorsTest(test.TestCase):
    def setUp(self):
        super(FlavorsTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(FlavorsTest, self).tearDown()

    def test_get_flavor_list(self):
        req = webob.Request.blank('/v1.0/flavors')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)

    def test_get_flavor_by_id(self):
        req = webob.Request.blank('/v1.0/flavors/1')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
