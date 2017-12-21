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

from nova.tests import fixtures
from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.functional import integrated_helpers


class MultinicSampleJsonTest(integrated_helpers.InstanceHelperMixin,
                             api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    USE_NEUTRON = True
    sample_dir = "os-multinic"

    def setUp(self):
        super(MultinicSampleJsonTest, self).setUp()
        server = self._boot_a_server(
            extra_params={'networks': [
                {'port': fixtures.NeutronFixture.port_1['id']}]})
        self.uuid = server['id']

    def _boot_a_server(self, expected_status='ACTIVE', extra_params=None):
        server = self._build_minimal_create_server_request(
            self.api, 'MultinicSampleJsonTestServer')
        if extra_params:
            server.update(extra_params)

        created_server = self.api.post_server({'server': server})

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(self.api, created_server,
                                                   expected_status)
        return found_server

    def _add_fixed_ip(self):
        subs = {"networkId": fixtures.NeutronFixture.network_1['id']}
        response = self._do_post('servers/%s/action' % (self.uuid),
                                 'multinic-add-fixed-ip-req', subs)
        self.assertEqual(202, response.status_code)

    def test_add_fixed_ip(self):
        self._add_fixed_ip()

    def test_remove_fixed_ip(self):
        self._add_fixed_ip()

        subs = {"ip": "10.0.0.4"}
        response = self._do_post('servers/%s/action' % (self.uuid),
                                 'multinic-remove-fixed-ip-req', subs)
        self.assertEqual(202, response.status_code)
