# Copyright 2012 Nebula, Inc.
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

import nova.conf
from nova.tests.functional.api_sample_tests import api_sample_base

CONF = nova.conf.CONF


class TenantNetworksJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-tenant-networks"

    def test_list_networks(self):
        response = self._do_get('os-tenant-networks')
        self._verify_response('networks-list-res', {}, response, 200)

    def test_create_network(self):
        self.api.api_post('os-tenant-networks', {},
                          check_response_status=[410])

    def test_delete_network(self):
        self.api.api_delete('os-tenant-networks/1',
                            check_response_status=[410])
