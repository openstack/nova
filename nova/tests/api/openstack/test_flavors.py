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

import json
import stubout
import webob

from nova import test
import nova.api
from nova import context
from nova.api.openstack import flavors
from nova import db
from nova.tests.api.openstack import fakes


def stub_flavor(flavorid, name, memory_mb="256", local_gb="10"):
    return {
        "flavorid": str(flavorid),
        "name": name,
        "memory_mb": memory_mb,
        "local_gb": local_gb,
    }


def return_instance_type_by_flavor_id(context, flavorid):
    return stub_flavor(flavorid, "flavor %s" % (flavorid,))

def return_instance_types(context, num=2):
    instance_types = {}
    for i in xrange(1,num+1):
        name = "flavor %s" % (i,)
        instance_types[name] = stub_flavor(i, name)
    return instance_types


class FlavorsTest(test.TestCase):
    def setUp(self):
        super(FlavorsTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db.api, "instance_type_get_all",
                       return_instance_types)
        self.stubs.Set(nova.db.api, "instance_type_get_by_flavor_id",
                       return_instance_type_by_flavor_id)
        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(FlavorsTest, self).tearDown()

    def test_get_flavor_list(self):
        req = webob.Request.blank('/v1.0/flavors')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavors = json.loads(res.body)["flavors"]
        expected = [
            {
                "id": "1",
                "name": "flavor 1",
            },
            {
                "id": "2",
                "name": "flavor 2",
            },
        ]
        self.assertEqual(flavors, expected)

    def test_get_flavor_list_detail(self):
        req = webob.Request.blank('/v1.0/flavors/detail')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavors = json.loads(res.body)["flavors"]
        expected = [
            {
                "id": "1",
                "name": "flavor 1",
                "ram": "256",
                "disk": "10",
            },
            {
                "id": "2",
                "name": "flavor 2",
                "ram": "256",
                "disk": "10",
            },
        ]
        self.assertEqual(flavors, expected)
        

    def test_get_flavor_by_id(self):
        req = webob.Request.blank('/v1.0/flavors/12')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        flavor = json.loads(res.body)["flavor"]
        expected = {
            "id": "12",
            "name": "flavor 12",
            "ram": "256",
            "disk": "10",
        }
        self.assertEqual(flavor, expected)
