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

from nova.tests.functional.api import client as api_client
from nova.tests.functional.api_sample_tests import api_sample_base


class FloatingIpDNSTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True

    def test_floating_ip_dns_list(self):
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_get,
                               'os-floating-ip-dns')
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ip_dns_create_or_update(self):
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_put,
                               'os-floating-ip-dns/domain1.example.org',
                               {'project': 'project1',
                                'scope': 'public'})
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ip_dns_delete(self):
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_delete,
                               'os-floating-ip-dns/domain1.example.org')
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ip_dns_create_or_update_entry(self):
        url = 'os-floating-ip-dns/domain1.example.org/entries/instance1'
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_put,
                               url,
                               {'ip': '192.168.1.1',
                                'dns_type': 'A'})
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ip_dns_entry_get(self):
        url = 'os-floating-ip-dns/domain1.example.org/entries/instance1'
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_get,
                               url)
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ip_dns_entry_delete(self):
        url = 'os-floating-ip-dns/domain1.example.org/entries/instance1'
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_delete,
                               url)
        self.assertEqual(410, ex.response.status_code)

    def test_floating_ip_dns_entry_list(self):
        url = 'os-floating-ip-dns/domain1.example.org/entries/192.168.1.1'
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.api_get,
                               url)
        self.assertEqual(410, ex.response.status_code)
