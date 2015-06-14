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

from nova.network import api as network_api
from nova.tests.functional.v3 import api_sample_base

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.extensions')


class FloatingIPPoolsSampleTests(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-floating-ip-pools"
    # TODO(gmann): Overriding '_api_version' till all functional tests
    # are merged between v2 and v2.1. After that base class variable
    # itself can be changed to 'v2'
    _api_version = 'v2'

    def _get_flags(self):
        f = super(FloatingIPPoolsSampleTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.floating_ip_pools.Floating_ip_pools')
        return f

    def test_list_floatingippools(self):
        pool_list = ["pool1", "pool2"]

        def fake_get_floating_ip_pools(self, context):
            return pool_list

        self.stubs.Set(network_api.API, "get_floating_ip_pools",
                       fake_get_floating_ip_pools)
        response = self._do_get('os-floating-ip-pools')
        subs = {
            'pool1': pool_list[0],
            'pool2': pool_list[1]
        }
        self._verify_response('floatingippools-list-resp', subs, response, 200)
