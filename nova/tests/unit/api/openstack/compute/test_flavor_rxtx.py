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

from nova import test
from nova.tests.unit.api.openstack import fakes


class FlavorRxtxTestV21(test.NoDBTestCase):
    content_type = 'application/json'
    _prefix = "/v2/fake"

    def setUp(self):
        super(FlavorRxtxTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_flavor_get_all(self)
        fakes.stub_out_flavor_get_by_flavor_id(self)

    def _make_request(self, url):
        req = fakes.HTTPRequest.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(self._get_app())
        return res

    def _get_app(self):
        return fakes.wsgi_app_v21()

    def _get_flavor(self, body):
        return jsonutils.loads(body).get('flavor')

    def _get_flavors(self, body):
        return jsonutils.loads(body).get('flavors')

    def assertFlavorRxtx(self, flavor, rxtx):
        self.assertEqual(flavor.get('rxtx_factor'), rxtx or u'')

    def test_show(self):
        url = self._prefix + '/flavors/1'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertFlavorRxtx(self._get_flavor(res.body),
                              fakes.FLAVORS['1'].rxtx_factor)

    def test_detail(self):
        url = self._prefix + '/flavors/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        flavors = self._get_flavors(res.body)
        self.assertFlavorRxtx(flavors[0],
                              fakes.FLAVORS['1'].rxtx_factor)
        self.assertFlavorRxtx(flavors[1],
                              fakes.FLAVORS['2'].rxtx_factor)
