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

from nova.tests.functional.api_sample_tests import api_sample_base


class SecurityGroupDefaultRulesSampleJsonTest(
        api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = 'os-security-group-default-rules'

    def test_security_group_default_rules_create(self):
        response = self._do_post('os-security-group-default-rules',
                                 'security-group-default-rules-create-req',
                                 {})
        self._verify_response('security-group-default-rules-create-resp',
                              {}, response, 200)

    def test_security_group_default_rules_list(self):
        self.test_security_group_default_rules_create()
        response = self._do_get('os-security-group-default-rules')
        self._verify_response('security-group-default-rules-list-resp',
                              {}, response, 200)

    def test_security_group_default_rules_show(self):
        self.test_security_group_default_rules_create()
        rule_id = '1'
        response = self._do_get('os-security-group-default-rules/%s' % rule_id)
        self._verify_response('security-group-default-rules-show-resp',
                              {}, response, 200)
