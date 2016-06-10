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
from nova import context
from nova.tests.functional.api_sample_tests import api_sample_base

CONF = nova.conf.CONF


class FloatingIpsBulkTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-floating-ips-bulk"

    def setUp(self):
        super(FloatingIpsBulkTest, self).setUp()
        pool = CONF.default_floating_pool
        interface = CONF.public_interface

        self.ip_pool = [
            {
                'address': "10.10.10.1",
                'pool': pool,
                'interface': interface,
                'host': None
                },
            {
                'address': "10.10.10.2",
                'pool': pool,
                'interface': interface,
                'host': None
                },
            {
                'address': "10.10.10.3",
                'pool': pool,
                'interface': interface,
                'host': "testHost"
                },
            ]
        self.compute.db.floating_ip_bulk_create(
            context.get_admin_context(), self.ip_pool)

        self.addCleanup(self.compute.db.floating_ip_bulk_destroy,
            context.get_admin_context(), self.ip_pool)

    def test_floating_ips_bulk_list(self):
        response = self._do_get('os-floating-ips-bulk')
        self._verify_response('floating-ips-bulk-list-resp',
                              {}, response, 200)

    def test_floating_ips_bulk_list_by_host(self):
        response = self._do_get('os-floating-ips-bulk/testHost')
        self._verify_response('floating-ips-bulk-list-by-host-resp',
                              {}, response, 200)

    def test_floating_ips_bulk_create(self):
        response = self._do_post('os-floating-ips-bulk',
                                 'floating-ips-bulk-create-req',
                                 {"ip_range": "192.168.1.0/24",
                                  "pool": CONF.default_floating_pool,
                                  "interface": CONF.public_interface})
        self._verify_response('floating-ips-bulk-create-resp', {},
                              response, 200)

    def test_floating_ips_bulk_delete(self):
        response = self._do_put('os-floating-ips-bulk/delete',
                                'floating-ips-bulk-delete-req',
                                {"ip_range": "192.168.1.0/24"})
        self._verify_response('floating-ips-bulk-delete-resp', {},
                              response, 200)
