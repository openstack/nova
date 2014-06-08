# Copyright 2014 IBM Corp.
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

import mock
import webob

from nova.api.openstack.compute.contrib import os_tenant_networks as networks
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes


class NetworksTest(test.NoDBTestCase):

    def setUp(self):
        super(NetworksTest, self).setUp()
        self.controller = networks.NetworkController()

    @mock.patch('nova.network.api.API.delete',
                side_effect=exception.NetworkInUse(network_id=1))
    def test_network_delete_in_use(self, mock_delete):
        req = fakes.HTTPRequest.blank('/v2/1234/os-tenant-networks/1')

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.delete, req, 1)
