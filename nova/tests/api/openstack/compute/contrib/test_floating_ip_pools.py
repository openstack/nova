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

from lxml import etree

from nova.api.openstack.compute.contrib import floating_ip_pools
from nova import context
from nova import network
from nova import test
from nova.tests.api.openstack import fakes


def fake_get_floating_ip_pools(self, context):
    return [{'name': 'nova'},
            {'name': 'other'}]


class FloatingIpPoolTest(test.TestCase):
    def setUp(self):
        super(FloatingIpPoolTest, self).setUp()
        self.stubs.Set(network.api.API, "get_floating_ip_pools",
                       fake_get_floating_ip_pools)

        self.context = context.RequestContext('fake', 'fake')
        self.controller = floating_ip_pools.FloatingIPPoolsController()

    def test_translate_floating_ip_pools_view(self):
        pools = fake_get_floating_ip_pools(None, self.context)
        view = floating_ip_pools._translate_floating_ip_pools_view(pools)
        self.assertTrue('floating_ip_pools' in view)
        self.assertEqual(view['floating_ip_pools'][0]['name'],
                         pools[0]['name'])
        self.assertEqual(view['floating_ip_pools'][1]['name'],
                         pools[1]['name'])

    def test_floating_ips_pools_list(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-floating-ip-pools')
        res_dict = self.controller.index(req)

        pools = fake_get_floating_ip_pools(None, self.context)
        response = {'floating_ip_pools': pools}
        self.assertEqual(res_dict, response)


class FloatingIpPoolSerializerTest(test.TestCase):
    def test_index_serializer(self):
        serializer = floating_ip_pools.FloatingIPPoolsSerializer()
        text = serializer.serialize(dict(
                floating_ip_pools=[
                    dict(name='nova'),
                    dict(name='other')
                ]), 'index')

        tree = etree.fromstring(text)

        self.assertEqual('floating_ip_pools', tree.tag)
        self.assertEqual(2, len(tree))
        self.assertEqual('floating_ip_pool', tree[0].tag)
        self.assertEqual('floating_ip_pool', tree[1].tag)
        self.assertEqual('nova', tree[0].get('name'))
        self.assertEqual('other', tree[1].get('name'))
