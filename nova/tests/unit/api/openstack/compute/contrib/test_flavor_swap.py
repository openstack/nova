# Copyright 2012 Nebula, Inc.
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

from oslo_serialization import jsonutils
import webob

from nova.compute import flavors
from nova import test
from nova.tests.unit.api.openstack import fakes

FAKE_FLAVORS = {
    'flavor 1': {
        "flavorid": '1',
        "name": 'flavor 1',
        "memory_mb": '256',
        "root_gb": '10',
        "swap": 512,
        "vcpus": 1,
        "ephemeral_gb": 1,
        "disabled": False,
    },
    'flavor 2': {
        "flavorid": '2',
        "name": 'flavor 2',
        "memory_mb": '512',
        "root_gb": '10',
        "swap": None,
        "vcpus": 1,
        "ephemeral_gb": 1,
        "disabled": False,
    },
}


# TODO(jogo) dedup these across nova.api.openstack.contrib.test_flavor*
def fake_flavor_get_by_flavor_id(flavorid, ctxt=None):
    return FAKE_FLAVORS['flavor %s' % flavorid]


def fake_get_all_flavors_sorted_list(context=None, inactive=False,
                                     filters=None, sort_key='flavorid',
                                     sort_dir='asc', limit=None, marker=None):
    return [
        fake_flavor_get_by_flavor_id(1),
        fake_flavor_get_by_flavor_id(2)
    ]


class FlavorSwapTestV21(test.NoDBTestCase):
    base_url = '/v2/fake/flavors'
    content_type = 'application/json'
    prefix = ''

    def setUp(self):
        super(FlavorSwapTestV21, self).setUp()
        ext = ('nova.api.openstack.compute.contrib'
              '.flavor_swap.Flavor_swap')
        self.flags(osapi_compute_extension=[ext])
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(flavors, "get_all_flavors_sorted_list",
                       fake_get_all_flavors_sorted_list)
        self.stubs.Set(flavors,
                       "get_flavor_by_flavor_id",
                       fake_flavor_get_by_flavor_id)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app_v21(init_only=('flavors')))
        return res

    def _get_flavor(self, body):
        return jsonutils.loads(body).get('flavor')

    def _get_flavors(self, body):
        return jsonutils.loads(body).get('flavors')

    def assertFlavorSwap(self, flavor, swap):
        self.assertEqual(str(flavor.get('%sswap' % self.prefix)), swap)

    def test_show(self):
        url = self.base_url + '/1'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertFlavorSwap(self._get_flavor(res.body), '512')

    def test_detail(self):
        url = self.base_url + '/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        flavors = self._get_flavors(res.body)
        self.assertFlavorSwap(flavors[0], '512')
        self.assertFlavorSwap(flavors[1], '')


class FlavorSwapTestV2(FlavorSwapTestV21):

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app())
        return res
