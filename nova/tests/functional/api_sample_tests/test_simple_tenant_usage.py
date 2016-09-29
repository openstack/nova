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

import datetime
import urllib

from oslo_utils import timeutils

from nova.tests.functional.api_sample_tests import test_servers
import nova.tests.functional.api_samples_test_base as astb


class SimpleTenantUsageSampleJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-simple-tenant-usage"

    def setUp(self):
        """setUp method for simple tenant usage."""
        super(SimpleTenantUsageSampleJsonTest, self).setUp()

        started = timeutils.utcnow()
        now = started + datetime.timedelta(hours=1)

        timeutils.set_time_override(started)
        self._post_server()
        timeutils.set_time_override(now)

        self.query = {
            'start': str(started),
            'end': str(now)
        }

    def tearDown(self):
        """tearDown method for simple tenant usage."""
        super(SimpleTenantUsageSampleJsonTest, self).tearDown()
        timeutils.clear_time_override()

    def test_get_tenants_usage(self):
        # Get api sample to get all tenants usage request.
        response = self._do_get('os-simple-tenant-usage?%s' % (
                                                urllib.urlencode(self.query)))
        self._verify_response('simple-tenant-usage-get', {}, response, 200)

    def test_get_tenants_usage_with_detail(self):
        # Get all tenants usage information with detail.
        query = self.query.copy()
        query.update({'detailed': 1})
        response = self._do_get('os-simple-tenant-usage?%s' % (
                                                urllib.urlencode(query)))
        self._verify_response('simple-tenant-usage-get-detail', {},
                              response, 200)

    def test_get_tenant_usage_details(self):
        # Get api sample to get specific tenant usage request.
        tenant_id = astb.PROJECT_ID
        response = self._do_get('os-simple-tenant-usage/%s?%s' % (tenant_id,
                                                urllib.urlencode(self.query)))
        self._verify_response('simple-tenant-usage-get-specific', {},
                              response, 200)
