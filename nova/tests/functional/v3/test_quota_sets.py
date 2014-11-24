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

from nova.tests.functional.v3 import api_sample_base


class QuotaSetsSampleJsonTests(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-quota-sets"

    def test_show_quotas(self):
        # Get api sample to show quotas.
        response = self._do_get('os-quota-sets/fake_tenant')
        self._verify_response('quotas-show-get-resp', {}, response, 200)

    def test_show_quotas_defaults(self):
        # Get api sample to show quotas defaults.
        response = self._do_get('os-quota-sets/fake_tenant/defaults')
        self._verify_response('quotas-show-defaults-get-resp',
                              {}, response, 200)

    def test_update_quotas(self):
        # Get api sample to update quotas.
        response = self._do_put('os-quota-sets/fake_tenant',
                                'quotas-update-post-req',
                                {})
        self._verify_response('quotas-update-post-resp', {}, response, 200)

    def test_delete_quotas(self):
        # Get api sample to delete quota.
        response = self._do_delete('os-quota-sets/fake_tenant')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_update_quotas_force(self):
        # Get api sample to update quotas.
        response = self._do_put('os-quota-sets/fake_tenant',
                                'quotas-update-force-post-req',
                                {})
        return self._verify_response('quotas-update-force-post-resp', {},
                                     response, 200)

    def test_show_quotas_for_user(self):
        # Get api sample to show quotas for user.
        response = self._do_get('os-quota-sets/fake_tenant?user_id=1')
        self._verify_response('user-quotas-show-get-resp', {}, response, 200)

    def test_delete_quotas_for_user(self):
        response = self._do_delete('os-quota-sets/fake_tenant?user_id=1')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_update_quotas_for_user(self):
        # Get api sample to update quotas for user.
        response = self._do_put('os-quota-sets/fake_tenant?user_id=1',
                                'user-quotas-update-post-req',
                                {})
        return self._verify_response('user-quotas-update-post-resp', {},
                                     response, 200)
