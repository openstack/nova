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


class FloatingIpDNSTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-floating-ip-dns"

    domain = 'domain1.example.org'
    name = 'instance1'
    scope = 'public'
    project = 'project1'
    dns_type = 'A'
    ip = '192.168.1.1'

    def _create_or_update(self):
        subs = {'project': self.project,
                'scope': self.scope}
        response = self._do_put('os-floating-ip-dns/%s' % self.domain,
                                'floating-ip-dns-create-or-update-req', subs)
        subs.update({'domain': self.domain})
        self._verify_response('floating-ip-dns-create-or-update-resp', subs,
                              response, 200)

    def _create_or_update_entry(self):
        subs = {'ip': self.ip, 'dns_type': self.dns_type}
        response = self._do_put('os-floating-ip-dns/%s/entries/%s'
                                % (self.domain, self.name),
                                'floating-ip-dns-create-or-update-entry-req',
                                subs)
        subs.update({'name': self.name, 'domain': self.domain})
        self._verify_response('floating-ip-dns-create-or-update-entry-resp',
                              subs, response, 200)

    def test_floating_ip_dns_list(self):
        self._create_or_update()
        response = self._do_get('os-floating-ip-dns')
        subs = {'domain': self.domain,
                'project': self.project,
                'scope': self.scope}
        self._verify_response('floating-ip-dns-list-resp', subs,
                              response, 200)

    def test_floating_ip_dns_create_or_update(self):
        self._create_or_update()

    def test_floating_ip_dns_delete(self):
        self._create_or_update()
        response = self._do_delete('os-floating-ip-dns/%s' % self.domain)
        self.assertEqual(202, response.status_code)

    def test_floating_ip_dns_create_or_update_entry(self):
        self._create_or_update_entry()

    def test_floating_ip_dns_entry_get(self):
        self._create_or_update_entry()
        response = self._do_get('os-floating-ip-dns/%s/entries/%s'
                                % (self.domain, self.name))
        subs = {'domain': self.domain,
                'ip': self.ip,
                'name': self.name}
        self._verify_response('floating-ip-dns-entry-get-resp', subs,
                              response, 200)

    def test_floating_ip_dns_entry_delete(self):
        self._create_or_update_entry()
        response = self._do_delete('os-floating-ip-dns/%s/entries/%s'
                                   % (self.domain, self.name))
        self.assertEqual(202, response.status_code)

    def test_floating_ip_dns_entry_list(self):
        self._create_or_update_entry()
        response = self._do_get('os-floating-ip-dns/%s/entries/%s'
                                % (self.domain, self.ip))
        subs = {'domain': self.domain,
                'ip': self.ip,
                'name': self.name}
        self._verify_response('floating-ip-dns-entry-list-resp', subs,
                              response, 200)
