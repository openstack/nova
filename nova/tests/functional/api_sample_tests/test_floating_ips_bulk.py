# Copyright 2014 IBM Corp.
#
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

import nova.conf
from nova.tests.functional.api import client as api_client
from nova.tests.functional.api_sample_tests import api_sample_base

CONF = nova.conf.CONF


class FloatingIpsBulkTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True

    def test_floating_ips_bulk_list(self):
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_get, 'os-floating-ips-bulk')
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ips_bulk_list_by_host(self):
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_get,
                               'os-floating-ips-bulk/testHost')
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ips_bulk_create(self):
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_post,
                               '/os-floating-ips-bulk',
                               {"ip_range": "192.168.1.0/24",
                                "pool": CONF.default_floating_pool,
                                "interface": CONF.public_interface})
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ips_bulk_delete(self):
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_put,
                               'os-floating-ips-bulk/delete',
                               {"ip_range": "192.168.1.0/24"})
        self.assertEqual(410, ex.response.status_code)
