# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 University of Southern California
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
import unittest
import webob

from nova import flags
from nova.api import openstack
from nova.tests.api.openstack import fakes
import nova.wsgi


def return_flavor_extra_specs(context, flavor_id):
    return stub_flavor_extra_specs()


def stub_flavor_extra_specs():
    specs = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5"}
    return specs


class FlavorsExtraSpecsTest(unittest.TestCase):
    
    def setUp(self):
        super(FlavorsExtraSpecsTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_auth(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(FlavorsExtraSpecsTest, self).tearDown()


    def test_index(self):
        self.stubs.Set(nova.db.api, 'instance_type_extra_specs_get',
                       return_flavor_extra_specs)
        req = webob.Request.blank('/v1.1/flavors/1/extra')
        req.environ['api.version'] = '1.1'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        res_dict = json.loads(res.body)
        self.assertEqual('application/json', res.headers['Content-Type'])
        self.assertEqual('value1', res_dict['metadata']['key1'])
        
        
        