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
from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import tenant_networks \
        as networks_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF

NETWORKS = [
    {
        "id": uuids.fake_net1,
        "name": "fake_net1",
    },
    {
        "id": uuids.fake_net2,
        "name": "fake_net2",
    }
]

DEFAULT_NETWORK = [
    {
        "id": uuids.fake_net3,
        "name": "default",
    }
]

NETWORKS_WITH_DEFAULT_NET = copy.deepcopy(NETWORKS)
NETWORKS_WITH_DEFAULT_NET.extend(DEFAULT_NETWORK)

DEFAULT_TENANT_ID = CONF.api.neutron_default_tenant_id


def fake_network_api_get_all(context):
    if context.project_id == DEFAULT_TENANT_ID:
        return DEFAULT_NETWORK
    else:
        return NETWORKS


class TenantNetworksTestV21(test.NoDBTestCase):
    ctrlr = networks_v21.TenantNetworkController
    validation_error = exception.ValidationError

    def setUp(self):
        # TODO(stephenfin): We should probably use NeutronFixture here
        super(TenantNetworksTestV21, self).setUp()
        # os-tenant-networks only supports Neutron when listing networks or
        # showing details about a network, create and delete operations
        # result in a 503 and 500 response, respectively.
        self.controller = self.ctrlr()
        self.req = fakes.HTTPRequest.blank('')
        self.original_value = CONF.api.use_neutron_default_nets

    def tearDown(self):
        super(TenantNetworksTestV21, self).tearDown()
        CONF.set_override("use_neutron_default_nets", self.original_value,
                          group='api')

    def test_network_show(self):
        with mock.patch.object(self.controller.network_api, 'get',
                               return_value=NETWORKS[0]):
            res = self.controller.show(self.req, 1)

        expected = {
            'id': NETWORKS[0]['id'],
            'label': NETWORKS[0]['name'],
            'cidr': str(None),
        }
        self.assertEqual(expected, res['network'])

    def test_network_show_not_found(self):
        ctxt = self.req.environ['nova.context']
        with mock.patch.object(self.controller.network_api, 'get',
                               side_effect=exception.NetworkNotFound(
                                   network_id=1)) as get_mock:
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.controller.show, self.req, 1)
        get_mock.assert_called_once_with(ctxt, 1)

    def _test_network_index(self, default_net=True):
        CONF.set_override("use_neutron_default_nets", default_net, group='api')

        networks = NETWORKS
        if default_net:
            networks = NETWORKS_WITH_DEFAULT_NET

        expected = []
        for network in networks:
            expected.append({
                'id': network['id'],
                'label': network['name'],
                'cidr': str(None),
            })

        with mock.patch.object(self.controller.network_api, 'get_all',
                               side_effect=fake_network_api_get_all):
            res = self.controller.index(self.req)
        self.assertEqual(expected, res['networks'])

    def test_network_index_with_default_net(self):
        self._test_network_index()

    def test_network_index_without_default_net(self):
        self._test_network_index(default_net=False)


class TenantNetworksDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(TenantNetworksDeprecationTest, self).setUp()
        self.controller = networks_v21.TenantNetworkController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
