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
from nova.api.openstack.compute.plugins.v3 import tenant_networks \
     as networks_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


class TenantNetworksTestV21(test.NoDBTestCase):
    ctrlr = networks_v21.TenantNetworkController

    def setUp(self):
        super(TenantNetworksTestV21, self).setUp()
        self.controller = self.ctrlr()
        self.flags(enable_network_quota=True)

    @mock.patch('nova.network.api.API.delete',
                side_effect=exception.NetworkInUse(network_id=1))
    def test_network_delete_in_use(self, mock_delete):
        req = fakes.HTTPRequest.blank('/v2/1234/os-tenant-networks/1')

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.delete, req, 1)

    @mock.patch('nova.quota.QUOTAS.reserve')
    @mock.patch('nova.quota.QUOTAS.rollback')
    @mock.patch('nova.network.api.API.delete')
    def _test_network_delete_exception(self, ex, expex, delete_mock,
                                       rollback_mock, reserve_mock):
        req = fakes.HTTPRequest.blank('/v2/1234/os-tenant-networks')
        ctxt = req.environ['nova.context']

        reserve_mock.return_value = 'rv'
        delete_mock.side_effect = ex

        self.assertRaises(expex, self.controller.delete, req, 1)

        delete_mock.assert_called_once_with(ctxt, 1)
        rollback_mock.assert_called_once_with(ctxt, 'rv')
        reserve_mock.assert_called_once_with(ctxt, networks=-1)

    def test_network_delete_exception_network_not_found(self):
        ex = exception.NetworkNotFound(network_id=1)
        expex = webob.exc.HTTPNotFound
        self._test_network_delete_exception(ex, expex)

    def test_network_delete_exception_policy_failed(self):
        ex = exception.PolicyNotAuthorized(action='dummy')
        expex = webob.exc.HTTPForbidden
        self._test_network_delete_exception(ex, expex)

    def test_network_delete_exception_network_in_use(self):
        ex = exception.NetworkInUse(network_id=1)
        expex = webob.exc.HTTPConflict
        self._test_network_delete_exception(ex, expex)


class TenantNetworksTestV2(TenantNetworksTestV21):
    ctrlr = networks.NetworkController
