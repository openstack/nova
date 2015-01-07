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

from oslo.serialization import jsonutils
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
        "root_gb": '20',
        "swap": None,
        "vcpus": 1,
        "ephemeral_gb": 1,
        "disabled": True,
    },
}


def fake_flavor_get_by_flavor_id(flavorid, ctxt=None):
    return FAKE_FLAVORS['flavor %s' % flavorid]


def fake_get_all_flavors_sorted_list(context=None, inactive=False,
                                     filters=None, sort_key='flavorid',
                                     sort_dir='asc', limit=None, marker=None):
    return [
        fake_flavor_get_by_flavor_id(1),
        fake_flavor_get_by_flavor_id(2)
    ]


class FlavorDisabledTestV21(test.NoDBTestCase):
    base_url = '/v2/fake/flavors'
    content_type = 'application/json'
    prefix = "OS-FLV-DISABLED:"

    def setUp(self):
        super(FlavorDisabledTestV21, self).setUp()
        ext = ('nova.api.openstack.compute.contrib'
              '.flavor_disabled.Flavor_disabled')
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

    def assertFlavorDisabled(self, flavor, disabled):
        self.assertEqual(str(flavor.get('%sdisabled' % self.prefix)), disabled)

    def test_show(self):
        url = self.base_url + '/1'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertFlavorDisabled(self._get_flavor(res.body), 'False')

    def test_detail(self):
        url = self.base_url + '/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        flavors = self._get_flavors(res.body)
        self.assertFlavorDisabled(flavors[0], 'False')
        self.assertFlavorDisabled(flavors[1], 'True')


class FlavorDisabledTestV2(FlavorDisabledTestV21):

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app())
        return res
