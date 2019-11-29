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
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api_sample_tests import api_sample_base


class NetworksJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = 'os-networks'

    def test_network_list(self):
        response = self._do_get('os-networks')
        self._verify_response('networks-list-resp', {}, response, 200)

    def test_network_show(self):
        uuid = nova_fixtures.NeutronFixture.network_1['id']
        response = self._do_get('os-networks/%s' % uuid)
        self._verify_response('network-show-resp', {}, response, 200)

    @mock.patch('nova.network.neutron.API.get',
                side_effect=exception.Unauthorized)
    def test_network_show_token_expired(self, mock_get):
        uuid = nova_fixtures.NeutronFixture.network_1['id']
        response = self._do_get('os-networks/%s' % uuid)
        self.assertEqual(401, response.status_code)

    def test_network_create(self):
        self.api.api_post('os-networks', {},
                          check_response_status=[410])

    def test_network_add(self):
        self.api.api_post('os-networks/add', {},
                          check_response_status=[410])

    def test_network_delete(self):
        self.api.api_delete('os-networks/always-delete',
                            check_response_status=[410])
