# Copyright (C) 2011 Midokura KK
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
from nova import compute
from nova.tests.api.openstack import fakes
from nova.api.openstack.contrib.virtual_interfaces import \
    ServerVirtualInterfaceController


def compute_api_get(self, context, server_id):
    return {'virtual_interfaces': [
                {'uuid': '00000000-0000-0000-0000-00000000000000000',
                 'address': '00-00-00-00-00-00'},
                {'uuid': '11111111-1111-1111-1111-11111111111111111',
                 'address': '11-11-11-11-11-11'}]}


class ServerVirtualInterfaceTest(test.TestCase):

    def setUp(self):
        super(ServerVirtualInterfaceTest, self).setUp()
        self.controller = ServerVirtualInterfaceController()
        self.stubs.Set(compute.api.API, "get", compute_api_get)

    def tearDown(self):
        super(ServerVirtualInterfaceTest, self).tearDown()

    def test_get_virtual_interfaces_list(self):
        req = webob.Request.blank('/v1.1/123/servers/1/os-virtual-interfaces')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        response = {'virtual_interfaces': [
                        {'id': '00000000-0000-0000-0000-00000000000000000',
                         'mac_address': '00-00-00-00-00-00'},
                        {'id': '11111111-1111-1111-1111-11111111111111111',
                         'mac_address': '11-11-11-11-11-11'}]}
        self.assertEqual(res_dict, response)
