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

import webob

from nova.api.openstack.compute.plugins.v3 import flavor_rxtx
from nova.compute import flavors
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes

FAKE_FLAVORS = {
    'flavor 1': {
        "flavorid": '1',
        "name": 'flavor 1',
        "memory_mb": '256',
        "root_gb": '10',
        "rxtx_factor": '1.0',
        "swap": 0,
        "ephemeral_gb": 0,
        "vcpus": 1,
        "disabled": False,
    },
    'flavor 2': {
        "flavorid": '2',
        "name": 'flavor 2',
        "memory_mb": '512',
        "root_gb": '10',
        "rxtx_factor": None,
        "swap": 0,
        "vcpus": 1,
        "ephemeral_gb": 0,
        "disabled": False,
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


class FlavorRxtxTest(test.NoDBTestCase):
    content_type = 'application/json'
    prefix = '%s:' % flavor_rxtx.ALIAS

    def setUp(self):
        super(FlavorRxtxTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(flavors, "get_all_flavors_sorted_list",
                       fake_get_all_flavors_sorted_list)
        self.stubs.Set(flavors,
                       "get_flavor_by_flavor_id",
                       fake_flavor_get_by_flavor_id)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        app = fakes.wsgi_app_v3(init_only=('servers', 'flavors',
                                           'os-flavor-rxtx'))
        res = req.get_response(app)
        return res

    def _get_flavor(self, body):
        return jsonutils.loads(body).get('flavor')

    def _get_flavors(self, body):
        return jsonutils.loads(body).get('flavors')

    def assertFlavorRxtx(self, flavor, rxtx):
        self.assertEqual(
            flavor.get('%srxtx_factor' % self.prefix), rxtx)

    def test_show(self):
        url = '/v3/flavors/1'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertFlavorRxtx(self._get_flavor(res.body), '1.0')

    def test_detail(self):
        url = '/v3/flavors/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        flavors = self._get_flavors(res.body)
        self.assertFlavorRxtx(flavors[0], '1.0')
        self.assertFlavorRxtx(flavors[1], '')
