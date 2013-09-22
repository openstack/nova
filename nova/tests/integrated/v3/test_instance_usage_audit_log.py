# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

import urllib

from nova.tests.integrated.v3 import api_sample_base


class InstanceUsageAuditLogJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-instance-usage-audit-log"

    def test_index_instance_usage_audit_log(self):
        response = self._do_get('os-instance-usage-audit-log')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('inst-usage-audit-log-index-get-resp',
                              subs, response, 200)

    def test_index_instance_usage_audit_log_with_before(self):
        response = self._do_get('os-instance-usage-audit-log?before=%s' %
                                urllib.quote('2012-07-05 10:00:00'))
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response(
            'inst-usage-audit-log-index-with-before-get-resp',
            subs, response, 200)


class InstanceUsageAuditLogXmlTest(InstanceUsageAuditLogJsonTest):
    ctype = "xml"
