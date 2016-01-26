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

import copy

import mock
from oslo_config import cfg
import webob

from nova.api.openstack.compute.legacy_v2.contrib import os_tenant_networks \
        as networks
from nova.api.openstack.compute import tenant_networks \
        as networks_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF

NETWORKS = [
    {
        "id": 1,
        "cidr": "10.20.105.0/24",
        "label": "new net 1"
    },
    {
        "id": 2,
        "cidr": "10.20.105.0/24",
        "label": "new net 2"
    }
]

DEFAULT_NETWORK = {
    "id": 3,
    "cidr": "10.20.105.0/24",
    "label": "default"
}

NETWORKS_WITH_DEFAULT_NET = copy.deepcopy(NETWORKS)
NETWORKS_WITH_DEFAULT_NET.append(DEFAULT_NETWORK)

DEFAULT_TENANT_ID = 1


def fake_network_api_get_all(context):
    if (context.project_id == DEFAULT_TENANT_ID):
        return NETWORKS_WITH_DEFAULT_NET
    else:
        return NETWORKS


class TenantNetworksTestV21(test.NoDBTestCase):
    ctrlr = networks_v21.TenantNetworkController
    validation_error = exception.ValidationError

    def setUp(self):
        super(TenantNetworksTestV21, self).setUp()
        self.controller = self.ctrlr()
        self.flags(enable_network_quota=True)
        self.req = fakes.HTTPRequest.blank('')
        self.original_value = CONF.use_neutron_default_nets

    def tearDown(self):
        super(TenantNetworksTestV21, self).tearDown()
        CONF.set_override("use_neutron_default_nets", self.original_value)

    def _fake_network_api_create(self, context, **kwargs):
        self.assertEqual(context.project_id, kwargs['project_id'])
        return NETWORKS

    @mock.patch('nova.quota.QUOTAS.reserve')
    @mock.patch('nova.quota.QUOTAS.rollback')
    @mock.patch('nova.network.api.API.disassociate')
    @mock.patch('nova.network.api.API.delete')
    def _test_network_delete_exception(self, delete_ex, disassociate_ex, expex,
                                       delete_mock, disassociate_mock,
                                       rollback_mock, reserve_mock):
        ctxt = self.req.environ['nova.context']

        reserve_mock.return_value = 'rv'
        if delete_mock:
            delete_mock.side_effect = delete_ex
        if disassociate_ex:
            disassociate_mock.side_effect = disassociate_ex

        self.assertRaises(expex, self.controller.delete, self.req, 1)

        disassociate_mock.assert_called_once_with(ctxt, 1)
        if not disassociate_ex:
            delete_mock.assert_called_once_with(ctxt, 1)
        rollback_mock.assert_called_once_with(ctxt, 'rv')
        reserve_mock.assert_called_once_with(ctxt, networks=-1)

    def test_network_delete_exception_network_not_found(self):
        ex = exception.NetworkNotFound(network_id=1)
        expex = webob.exc.HTTPNotFound
        self._test_network_delete_exception(None, ex, expex)

    def test_network_delete_exception_policy_failed(self):
        ex = exception.PolicyNotAuthorized(action='dummy')
        expex = webob.exc.HTTPForbidden
        self._test_network_delete_exception(ex, None, expex)

    def test_network_delete_exception_network_in_use(self):
        ex = exception.NetworkInUse(network_id=1)
        expex = webob.exc.HTTPConflict
        self._test_network_delete_exception(ex, None, expex)

    @mock.patch('nova.quota.QUOTAS.reserve')
    @mock.patch('nova.quota.QUOTAS.commit')
    @mock.patch('nova.network.api.API.delete')
    @mock.patch('nova.network.api.API.disassociate')
    def test_network_delete(self, disassociate_mock, delete_mock, commit_mock,
                            reserve_mock):
        ctxt = self.req.environ['nova.context']

        reserve_mock.return_value = 'rv'

        res = self.controller.delete(self.req, 1)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.controller, networks_v21.TenantNetworkController):
            status_int = self.controller.delete.wsgi_code
        else:
            status_int = res.status_int
        self.assertEqual(202, status_int)

        disassociate_mock.assert_called_once_with(ctxt, 1)
        delete_mock.assert_called_once_with(ctxt, 1)
        commit_mock.assert_called_once_with(ctxt, 'rv')
        reserve_mock.assert_called_once_with(ctxt, networks=-1)

    @mock.patch('nova.network.api.API.get')
    def test_network_show(self, get_mock):
        get_mock.return_value = NETWORKS[0]

        res = self.controller.show(self.req, 1)
        self.assertEqual(NETWORKS[0], res['network'])

    @mock.patch('nova.network.api.API.get')
    def test_network_show_not_found(self, get_mock):
        ctxt = self.req.environ['nova.context']
        get_mock.side_effect = exception.NetworkNotFound(network_id=1)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, 1)
        get_mock.assert_called_once_with(ctxt, 1)

    @mock.patch('nova.network.api.API.get_all')
    def _test_network_index(self, get_all_mock, default_net=True):
        CONF.set_override("use_neutron_default_nets", default_net)
        get_all_mock.side_effect = fake_network_api_get_all

        expected = NETWORKS
        if default_net is True:
            self.req.environ['nova.context'].project_id = DEFAULT_TENANT_ID
            expected = NETWORKS_WITH_DEFAULT_NET

        res = self.controller.index(self.req)
        self.assertEqual(expected, res['networks'])

    def test_network_index_with_default_net(self):
        self._test_network_index()

    def test_network_index_without_default_net(self):
        self._test_network_index(default_net=False)

    @mock.patch('nova.quota.QUOTAS.reserve')
    @mock.patch('nova.quota.QUOTAS.commit')
    @mock.patch('nova.network.api.API.create')
    def test_network_create(self, create_mock, commit_mock, reserve_mock):
        ctxt = self.req.environ['nova.context']

        reserve_mock.return_value = 'rv'
        create_mock.side_effect = self._fake_network_api_create

        body = copy.deepcopy(NETWORKS[0])
        del body['id']
        body = {'network': body}
        res = self.controller.create(self.req, body=body)

        self.assertEqual(NETWORKS[0], res['network'])
        commit_mock.assert_called_once_with(ctxt, 'rv')
        reserve_mock.assert_called_once_with(ctxt, networks=1)

    @mock.patch('nova.quota.QUOTAS.reserve')
    def test_network_create_quota_error(self, reserve_mock):
        ctxt = self.req.environ['nova.context']

        reserve_mock.side_effect = exception.OverQuota(overs='fake')
        body = {'network': {"cidr": "10.20.105.0/24",
                            "label": "new net 1"}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=body)
        reserve_mock.assert_called_once_with(ctxt, networks=1)

    @mock.patch('nova.quota.QUOTAS.reserve')
    @mock.patch('nova.quota.QUOTAS.rollback')
    @mock.patch('nova.network.api.API.create')
    def _test_network_create_exception(self, ex, expex, create_mock,
                                       rollback_mock, reserve_mock):
        ctxt = self.req.environ['nova.context']

        reserve_mock.return_value = 'rv'
        create_mock.side_effect = ex
        body = {'network': {"cidr": "10.20.105.0/24",
                            "label": "new net 1"}}
        self.assertRaises(expex, self.controller.create, self.req, body=body)
        reserve_mock.assert_called_once_with(ctxt, networks=1)

    def test_network_create_exception_policy_failed(self):
        ex = exception.PolicyNotAuthorized(action='dummy')
        expex = webob.exc.HTTPForbidden
        self._test_network_create_exception(ex, expex)

    def test_network_create_exception_conflictcidr(self):
        ex = exception.CidrConflict(cidr='dummy', other='dummy')
        expex = webob.exc.HTTPConflict
        self._test_network_create_exception(ex, expex)

    def test_network_create_exception_service_unavailable(self):
        ex = Exception
        expex = webob.exc.HTTPServiceUnavailable
        self._test_network_create_exception(ex, expex)

    def test_network_create_empty_body(self):
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body={})

    def test_network_create_without_cidr(self):
        body = {'network': {"label": "new net 1"}}
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_network_create_bad_format_cidr(self):
        body = {'network': {"cidr": "123",
                            "label": "new net 1"}}
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_network_create_empty_network(self):
        body = {'network': {}}
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_network_create_without_label(self):
        body = {'network': {"cidr": "10.20.105.0/24"}}
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)


class TenantNetworksTestV2(TenantNetworksTestV21):
    ctrlr = networks.NetworkController
    validation_error = webob.exc.HTTPBadRequest

    def setUp(self):
        super(TenantNetworksTestV2, self).setUp()
        self.req = fakes.HTTPRequest.blank('', use_admin_context=True)

    def test_network_create_empty_body(self):
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, self.req, {})


class TenantNetworksEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(TenantNetworksEnforcementV21, self).setUp()
        self.controller = networks_v21.TenantNetworkController()
        self.req = fakes.HTTPRequest.blank('')

    def test_create_policy_failed(self):
        rule_name = 'os_compute_api:os-tenant-networks'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.create,
            self.req, body={'network': {'label': 'test',
                                        'cidr': '10.0.0.0/32'}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_index_policy_failed(self):
        rule_name = 'os_compute_api:os-tenant-networks'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index,
            self.req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_delete_policy_failed(self):
        rule_name = 'os_compute_api:os-tenant-networks'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.delete,
            self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_show_policy_failed(self):
        rule_name = 'os_compute_api:os-tenant-networks'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.show,
            self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())
