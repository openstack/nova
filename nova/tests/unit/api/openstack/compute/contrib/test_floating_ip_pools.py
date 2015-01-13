# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# All Rights Reserved.
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

from nova.api.openstack.compute.contrib import floating_ip_pools as fipp_v2
from nova.api.openstack.compute.plugins.v3 import floating_ip_pools as\
                                                      fipp_v21
from nova import context
from nova import network
from nova import test
from nova.tests.unit.api.openstack import fakes


def fake_get_floating_ip_pools(self, context):
    return ['nova', 'other']


class FloatingIpPoolTestV21(test.NoDBTestCase):
    floating_ip_pools = fipp_v21
    url = '/v2/fake/os-floating-ip-pools'

    def setUp(self):
        super(FloatingIpPoolTestV21, self).setUp()
        self.stubs.Set(network.api.API, "get_floating_ip_pools",
                       fake_get_floating_ip_pools)

        self.context = context.RequestContext('fake', 'fake')
        self.controller = self.floating_ip_pools.FloatingIPPoolsController()

    def test_translate_floating_ip_pools_view(self):
        pools = fake_get_floating_ip_pools(None, self.context)
        view = self.floating_ip_pools._translate_floating_ip_pools_view(pools)
        self.assertIn('floating_ip_pools', view)
        self.assertEqual(view['floating_ip_pools'][0]['name'],
                         pools[0])
        self.assertEqual(view['floating_ip_pools'][1]['name'],
                         pools[1])

    def test_floating_ips_pools_list(self):
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req)

        pools = fake_get_floating_ip_pools(None, self.context)
        response = {'floating_ip_pools': [{'name': name} for name in pools]}
        self.assertEqual(res_dict, response)


class FloatingIpPoolTestV2(FloatingIpPoolTestV21):
    floating_ip_pools = fipp_v2
