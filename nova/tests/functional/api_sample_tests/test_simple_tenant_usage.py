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

import mock
from oslo_utils import timeutils
from six.moves.urllib import parse

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
                                                parse.urlencode(self.query)))
        self._verify_response('simple-tenant-usage-get', {}, response, 200)

    def test_get_tenants_usage_with_detail(self):
        # Get all tenants usage information with detail.
        query = self.query.copy()
        query.update({'detailed': 1})
        response = self._do_get('os-simple-tenant-usage?%s' % (
                                                parse.urlencode(query)))
        self._verify_response('simple-tenant-usage-get-detail', {},
                              response, 200)

    def test_get_tenant_usage_details(self):
        # Get api sample to get specific tenant usage request.
        tenant_id = astb.PROJECT_ID
        response = self._do_get('os-simple-tenant-usage/%s?%s' % (tenant_id,
                                                parse.urlencode(self.query)))
        self._verify_response('simple-tenant-usage-get-specific', {},
                              response, 200)


class SimpleTenantUsageV240Test(test_servers.ServersSampleBase):
    sample_dir = 'os-simple-tenant-usage'
    microversion = '2.40'
    scenarios = [('v2_40', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(SimpleTenantUsageV240Test, self).setUp()
        self.api.microversion = self.microversion

        started = timeutils.utcnow()
        now = started + datetime.timedelta(hours=1)

        timeutils.set_time_override(started)
        with mock.patch('oslo_utils.uuidutils.generate_uuid') as mock_uuids:
            # make uuids incrementing, so that sort order is deterministic
            uuid_format = '1f1deceb-17b5-4c04-84c7-e0d4499c8f%02d'
            mock_uuids.side_effect = [uuid_format % x for x in range(100)]
            self.instance1_uuid = self._post_server(name='instance-1')
            self.instance2_uuid = self._post_server(name='instance-2')
            self.instance3_uuid = self._post_server(name='instance-3')
        timeutils.set_time_override(now)

        self.query = {
            'start': str(started),
            'end': str(now),
            'limit': '1',
            'marker': self.instance1_uuid,
        }

    def tearDown(self):
        super(SimpleTenantUsageV240Test, self).tearDown()
        timeutils.clear_time_override()

    def test_get_tenants_usage(self):
        url = 'os-simple-tenant-usage?%s'
        response = self._do_get(url % (parse.urlencode(self.query)))
        template_name = 'simple-tenant-usage-get'
        self._verify_response(template_name, {}, response, 200)

    def test_get_tenants_usage_with_detail(self):
        query = self.query.copy()
        query.update({'detailed': 1})
        url = 'os-simple-tenant-usage?%s'
        response = self._do_get(url % (parse.urlencode(query)))
        template_name = 'simple-tenant-usage-get-detail'
        self._verify_response(template_name, {}, response, 200)

    def test_get_tenant_usage_details(self):
        tenant_id = astb.PROJECT_ID
        url = 'os-simple-tenant-usage/{tenant}?%s'.format(tenant=tenant_id)
        response = self._do_get(url % (parse.urlencode(self.query)))
        template_name = 'simple-tenant-usage-get-specific'
        subs = {'tenant_id': self.api.project_id}
        self._verify_response(template_name, subs, response, 200)
