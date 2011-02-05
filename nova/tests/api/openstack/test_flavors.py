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
from nova import context
from nova import db
from nova.api.openstack import flavors
from nova.tests.api.openstack import fakes


class FlavorsTest(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get_flavor_list(self):
        req = webob.Request.blank('/v1.0/flavors')
        res = req.get_response(fakes.wsgi_app())

    def test_create_list_delete_favor(self):
        # create a new flavor
        starting_flavors = db.instance_type_get_all(self.context)
        new_instance_type = dict(name="os1.big", memory_mb=512,
                                  vcpus=1, local_gb=120, flavorid=25)
        new_flavor = db.instance_type_create(self.context, new_instance_type)
        self.assertEqual(new_flavor["name"], new_instance_type["name"])
        # retrieve the newly created flavor
        retrieved_new_flavor = db.instance_type_get_by_name(
                                                    self.context,
                                                    new_instance_type["name"])
        # self.assertEqual(len(tuple(retrieved_new_flavor)),1)
        self.assertEqual(retrieved_new_flavor["memory_mb"],
                            new_instance_type["memory_mb"])
        flavors = db.instance_type_get_all(self.context)
        self.assertNotEqual(starting_flavors, flavors)
        # delete the newly created flavor
        delete_query = db.instance_type_destroy(self.context,
                                                new_instance_type["name"])
        deleted_flavor = db.instance_type_get_by_name(self.context,
                                                    new_instance_type["name"])
        self.assertEqual(deleted_flavor["deleted"], 1)


if __name__ == '__main__':
    unittest.main()
