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


from oslo_serialization import jsonutils

import nova.conf
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api_sample_tests import api_sample_base

CONF = nova.conf.CONF


class TenantNetworksJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-tenant-networks"

    def setUp(self):
        super(TenantNetworksJsonTests, self).setUp()
        CONF.set_override("enable_network_quota", True)
        self.useFixture(nova_fixtures.RegisterNetworkQuota())

        def fake(*args, **kwargs):
            pass

        self.stub_out("nova.quota.QUOTAS.reserve", fake)
        self.stub_out("nova.quota.QUOTAS.commit", fake)
        self.stub_out("nova.quota.QUOTAS.rollback", fake)
        self.stub_out("nova.quota.QuotaEngine.reserve", fake)
        self.stub_out("nova.quota.QuotaEngine.commit", fake)
        self.stub_out("nova.quota.QuotaEngine.rollback", fake)

    def test_list_networks(self):
        response = self._do_get('os-tenant-networks')
        self._verify_response('networks-list-res', {}, response, 200)

    def test_create_network(self):
        response = self._do_post('os-tenant-networks', "networks-post-req", {})
        self._verify_response('networks-post-res', {}, response, 200)

    def test_delete_network(self):
        response = self._do_post('os-tenant-networks', "networks-post-req", {})
        net = jsonutils.loads(response.content)
        response = self._do_delete('os-tenant-networks/%s' %
                                                net["network"]["id"])
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)
