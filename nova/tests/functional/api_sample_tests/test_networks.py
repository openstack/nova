# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit.api.openstack.compute import test_networks

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class NetworksJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extension_name = "os-networks"

    def _get_flags(self):
        f = super(NetworksJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.os_networks.Os_networks')
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.extended_networks.Extended_networks')
        return f

    def setUp(self):
        super(NetworksJsonTests, self).setUp()
        fake_network_api = test_networks.FakeNetworkAPI()
        self.stub_out("nova.network.api.API.get_all", fake_network_api.get_all)
        self.stub_out("nova.network.api.API.get", fake_network_api.get)
        self.stub_out("nova.network.api.API.associate",
                      fake_network_api.associate)
        self.stub_out("nova.network.api.API.delete", fake_network_api.delete)
        self.stub_out("nova.network.api.API.create", fake_network_api.create)
        self.stub_out("nova.network.api.API.add_network_to_project",
                      fake_network_api.add_network_to_project)

    def test_network_list(self):
        response = self._do_get('os-networks')
        self._verify_response('networks-list-resp', {}, response, 200)

    def test_network_disassociate(self):
        uuid = test_networks.FAKE_NETWORKS[0]['uuid']
        response = self._do_post('os-networks/%s/action' % uuid,
                                 'networks-disassociate-req', {})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.content)

    def test_network_show(self):
        uuid = test_networks.FAKE_NETWORKS[0]['uuid']
        response = self._do_get('os-networks/%s' % uuid)
        self._verify_response('network-show-resp', {}, response, 200)

    def test_network_create(self):
        response = self._do_post("os-networks",
                                 'network-create-req', {})
        self._verify_response('network-create-resp', {}, response, 200)

    def test_network_add(self):
        response = self._do_post("os-networks/add",
                                 'network-add-req', {})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.content)

    def test_network_delete(self):
        response = self._do_delete('os-networks/always_delete')
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.content)
