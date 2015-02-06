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


from oslo_config import cfg
from oslo_serialization import jsonutils

import nova.quota
from nova.tests.functional.v3 import api_sample_base

CONF = cfg.CONF
CONF.import_opt('enable_network_quota',
                'nova.api.openstack.compute.contrib.os_tenant_networks')


class TenantNetworksJsonTests(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-tenant-networks"

    def setUp(self):
        super(TenantNetworksJsonTests, self).setUp()
        CONF.set_override("enable_network_quota", True)

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(nova.quota.QUOTAS, "reserve", fake)
        self.stubs.Set(nova.quota.QUOTAS, "commit", fake)
        self.stubs.Set(nova.quota.QUOTAS, "rollback", fake)
        self.stubs.Set(nova.quota.QuotaEngine, "reserve", fake)
        self.stubs.Set(nova.quota.QuotaEngine, "commit", fake)
        self.stubs.Set(nova.quota.QuotaEngine, "rollback", fake)

    def test_list_networks(self):
        response = self._do_get('os-tenant-networks')
        subs = self._get_regexes()
        self._verify_response('networks-list-res', subs, response, 200)

    def test_create_network(self):
        response = self._do_post('os-tenant-networks', "networks-post-req", {})
        subs = self._get_regexes()
        self._verify_response('networks-post-res', subs, response, 200)

    def test_delete_network(self):
        response = self._do_post('os-tenant-networks', "networks-post-req", {})
        net = jsonutils.loads(response.content)
        response = self._do_delete('os-tenant-networks/%s' %
                                                net["network"]["id"])
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")
