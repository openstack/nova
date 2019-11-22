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

    def test_security_group_default_rules_create(self):
        self.api.api_post('os-security-group-default-rules', {},
                          check_response_status=[410])

    def test_security_group_default_rules_list(self):
        self.api.api_get('os-security-group-default-rules',
                         check_response_status=[410])

    def test_security_group_default_rules_show(self):
        self.api.api_get('os-security-group-default-rules/1',
                         check_response_status=[410])
