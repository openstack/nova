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

import mock

from nova import exception
from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit.api.openstack.compute import test_networks


def _fixtures_passthrough(method_name):
    # This compensates for how fixtures 3.x handles the signatures of
    # MonkeyPatched functions vs fixtures < 3.x. In fixtures 3 if a bound
    # method is patched in for a bound method then both objects will be passed
    # in when called. This means the patch method should have the signature of
    # (self, targetself, *args, **kwargs). However that will not work for
    # fixtures < 3. This method captures self from the call point and discards
    # it since it's not needed.
    fake_network_api = test_networks.FakeNetworkAPI()
    method = getattr(fake_network_api, method_name)

    def call(self, *args, **kwargs):
        # self is the nova.network.api.API object that has been patched
        # method is bound to FakeNetworkAPI so that will be passed in as self
        return method(*args, **kwargs)

    return call


class NetworksJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-networks"

    def setUp(self):
        super(NetworksJsonTests, self).setUp()
        self.stub_out("nova.network.api.API.get_all",
                      _fixtures_passthrough('get_all'))
        self.stub_out("nova.network.api.API.get",
                      _fixtures_passthrough('get'))
        self.stub_out("nova.network.api.API.associate",
                      _fixtures_passthrough('associate'))
        self.stub_out("nova.network.api.API.delete",
                      _fixtures_passthrough('delete'))
        self.stub_out("nova.network.api.API.create",
                      _fixtures_passthrough('create'))
        self.stub_out("nova.network.api.API.add_network_to_project",
                      _fixtures_passthrough('add_network_to_project'))

    def test_network_list(self):
        response = self._do_get('os-networks')
        self._verify_response('networks-list-resp', {}, response, 200)

    def test_network_show(self):
        uuid = test_networks.FAKE_NETWORKS[0]['uuid']
        response = self._do_get('os-networks/%s' % uuid)
        self._verify_response('network-show-resp', {}, response, 200)

    @mock.patch('nova.network.api.API.get', side_effect=exception.Unauthorized)
    def test_network_show_token_expired(self, mock_get):
        uuid = test_networks.FAKE_NETWORKS[0]['uuid']
        response = self._do_get('os-networks/%s' % uuid)
        self.assertEqual(401, response.status_code)

    @mock.patch('nova.network.api.API.create',
                side_effect=exception.Forbidden)
    def test_network_create_forbidden(self, mock_create):
        response = self._do_post("os-networks",
                                 'network-create-req', {})
        self.assertEqual(403, response.status_code)

    def test_network_create(self):
        response = self._do_post("os-networks",
                                 'network-create-req', {})
        self._verify_response('network-create-resp', {}, response, 200)

    def test_network_add(self):
        response = self._do_post("os-networks/add",
                                 'network-add-req', {})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

    def test_network_delete(self):
        response = self._do_delete('os-networks/always_delete')
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)
