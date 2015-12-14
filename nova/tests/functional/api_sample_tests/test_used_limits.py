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


class UsedLimitsSamplesJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extension_name = "os-used-limits"
    extra_extensions_to_load = ["limits"]

    def setUp(self):
        super(UsedLimitsSamplesJsonTest, self).setUp()
        # NOTE(park): We have to separate the template files between V2
        # and V2.1 as the response are different.
        self.template = 'usedlimits-get-resp'
        if self._legacy_v2_code:
            self.template = 'v2-usedlimits-get-resp'

    def _get_flags(self):
        f = super(UsedLimitsSamplesJsonTest, self)._get_flags()
        if self._legacy_v2_code:
            f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
            f['osapi_compute_extension'].append(
                "nova.api.openstack.compute."
                "legacy_v2.contrib.server_group_quotas."
                "Server_group_quotas")
            f['osapi_compute_extension'].append(
                "nova.api.openstack.compute."
                "legacy_v2.contrib.used_limits.Used_limits")
            f['osapi_compute_extension'].append(
                "nova.api.openstack.compute."
                "legacy_v2.contrib.used_limits_for_admin."
                "Used_limits_for_admin")
        return f

    def test_get_used_limits(self):
        # Get api sample to used limits.
        response = self._do_get('limits')
        self._verify_response(self.template, {}, response, 200)

    def test_get_used_limits_for_admin(self):
        # TODO(sdague): if we split the admin tests out the whole
        # class doesn't need admin api enabled.
        tenant_id = 'openstack'
        response = self._do_get('limits?tenant_id=%s' % tenant_id)
        self._verify_response(self.template, {}, response, 200)
