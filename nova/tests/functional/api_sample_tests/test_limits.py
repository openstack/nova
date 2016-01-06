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

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import api_sample_base

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class LimitsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extension_name = "limits"

    def setUp(self):
        super(LimitsSampleJsonTest, self).setUp()
        # NOTE(gmann): We have to separate the template files between V2
        # and V2.1 as the response are different.
        self.template = 'limit-get-resp'
        if self._legacy_v2_code:
            self.template = 'v2-limit-get-resp'

    def _get_flags(self):
        f = super(LimitsSampleJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append("nova.api.openstack.compute."
                      "legacy_v2.contrib.server_group_quotas."
                      "Server_group_quotas")
        return f

    def test_limits_get(self):
        response = self._do_get('limits')
        self._verify_response(self.template, {}, response, 200)
