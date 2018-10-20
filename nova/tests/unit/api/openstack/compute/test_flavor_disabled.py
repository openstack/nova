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


class FlavorDisabledTestV21(test.NoDBTestCase):
    base_url = '/v2/fake/flavors'
    content_type = 'application/json'
    prefix = "OS-FLV-DISABLED:"

    def setUp(self):
        super(FlavorDisabledTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_flavor_get_all(self)
        fakes.stub_out_flavor_get_by_flavor_id(self)

    def _make_request(self, url):
        req = fakes.HTTPRequest.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app_v21())
        return res

    def _get_flavor(self, body):
        return jsonutils.loads(body).get('flavor')

    def _get_flavors(self, body):
        return jsonutils.loads(body).get('flavors')

    def assertFlavorDisabled(self, flavor, disabled):
        self.assertEqual(flavor.get('%sdisabled' % self.prefix), disabled)

    def test_show(self):
        url = self.base_url + '/1'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertFlavorDisabled(self._get_flavor(res.body),
                                  fakes.FLAVORS['1'].disabled)

    def test_detail(self):
        url = self.base_url + '/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        flavors = self._get_flavors(res.body)
        self.assertFlavorDisabled(flavors[0], fakes.FLAVORS['1'].disabled)
        self.assertFlavorDisabled(flavors[1], fakes.FLAVORS['2'].disabled)
