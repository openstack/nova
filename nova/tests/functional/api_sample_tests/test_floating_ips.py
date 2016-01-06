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


from oslo_config import cfg

from nova import context
from nova.tests.functional.api_sample_tests import api_sample_base

CONF = cfg.CONF
CONF.import_opt('default_floating_pool', 'nova.network.floating_ips')
CONF.import_opt('public_interface', 'nova.network.linux_net')
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class FloatingIpsTest(api_sample_base.ApiSampleTestBaseV21):
    extension_name = "os-floating-ips"

    def _get_flags(self):
        f = super(FloatingIpsTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.floating_ips.Floating_ips')
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.extended_floating_ips.Extended_floating_ips')
        return f

    def setUp(self):
        super(FloatingIpsTest, self).setUp()
        pool = CONF.default_floating_pool
        interface = CONF.public_interface

        self.ip_pool = [
            {
                'address': "10.10.10.1",
                'pool': pool,
                'interface': interface
                },
            {
                'address': "10.10.10.2",
                'pool': pool,
                'interface': interface
                },
            {
                'address': "10.10.10.3",
                'pool': pool,
                'interface': interface
                },
            ]
        self.compute.db.floating_ip_bulk_create(
            context.get_admin_context(), self.ip_pool)

    def tearDown(self):
        self.compute.db.floating_ip_bulk_destroy(
            context.get_admin_context(), self.ip_pool)
        super(FloatingIpsTest, self).tearDown()

    def test_floating_ips_list_empty(self):
        response = self._do_get('os-floating-ips')

        self._verify_response('floating-ips-list-empty-resp',
                              {}, response, 200)

    def test_floating_ips_list(self):
        self._do_post('os-floating-ips',
                      'floating-ips-create-nopool-req',
                      {})
        self._do_post('os-floating-ips',
                      'floating-ips-create-nopool-req',
                      {})

        response = self._do_get('os-floating-ips')
        self._verify_response('floating-ips-list-resp',
                              {}, response, 200)

    def test_floating_ips_create_nopool(self):
        response = self._do_post('os-floating-ips',
                                 'floating-ips-create-nopool-req',
                                 {})
        self._verify_response('floating-ips-create-resp',
                              {}, response, 200)

    def test_floating_ips_create(self):
        response = self._do_post('os-floating-ips',
                                 'floating-ips-create-req',
                                 {"pool": CONF.default_floating_pool})
        self._verify_response('floating-ips-create-resp', {}, response, 200)

    def test_floating_ips_get(self):
        self.test_floating_ips_create()
        # NOTE(sdague): the first floating ip will always have 1 as an id,
        # but it would be better if we could get this from the create
        response = self._do_get('os-floating-ips/%d' % 1)
        self._verify_response('floating-ips-get-resp', {}, response, 200)

    def test_floating_ips_delete(self):
        self.test_floating_ips_create()
        response = self._do_delete('os-floating-ips/%d' % 1)
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.content)
