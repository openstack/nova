# Copyright 2012 OpenStack Foundation
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

from oslo_serialization import jsonutils

from nova import test
from nova.tests.unit.api.openstack import fakes


class FlavorExtraDataTestV21(test.NoDBTestCase):
    base_url = '/v2/%s/flavors' % fakes.FAKE_PROJECT_ID

    def setUp(self):
        super(FlavorExtraDataTestV21, self).setUp()
        fakes.stub_out_flavor_get_all(self)
        fakes.stub_out_flavor_get_by_flavor_id(self)

    @property
    def app(self):
        return fakes.wsgi_app_v21()

    def _verify_flavor_response(self, flavor, expected):
        for key in expected:
            self.assertEqual(flavor[key], expected[key])

    def test_show(self):
        expected = {
            'flavor': {
                'id': fakes.FLAVORS['1'].flavorid,
                'name': fakes.FLAVORS['1'].name,
                'ram': fakes.FLAVORS['1'].memory_mb,
                'vcpus': fakes.FLAVORS['1'].vcpus,
                'disk': fakes.FLAVORS['1'].root_gb,
                'OS-FLV-EXT-DATA:ephemeral': fakes.FLAVORS['1'].ephemeral_gb,
            }
        }

        url = self.base_url + '/1'
        req = fakes.HTTPRequest.blank(url)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)
        self._verify_flavor_response(body['flavor'], expected['flavor'])

    def test_detail(self):
        expected = [
            {
                'id': fakes.FLAVORS['1'].flavorid,
                'name': fakes.FLAVORS['1'].name,
                'ram': fakes.FLAVORS['1'].memory_mb,
                'vcpus': fakes.FLAVORS['1'].vcpus,
                'disk': fakes.FLAVORS['1'].root_gb,
                'OS-FLV-EXT-DATA:ephemeral': fakes.FLAVORS['1'].ephemeral_gb,
                'rxtx_factor': fakes.FLAVORS['1'].rxtx_factor or u'',
                'os-flavor-access:is_public': fakes.FLAVORS['1'].is_public,
            },
            {
                'id': fakes.FLAVORS['2'].flavorid,
                'name': fakes.FLAVORS['2'].name,
                'ram': fakes.FLAVORS['2'].memory_mb,
                'vcpus': fakes.FLAVORS['2'].vcpus,
                'disk': fakes.FLAVORS['2'].root_gb,
                'OS-FLV-EXT-DATA:ephemeral': fakes.FLAVORS['2'].ephemeral_gb,
                'rxtx_factor': fakes.FLAVORS['2'].rxtx_factor or u'',
                'os-flavor-access:is_public': fakes.FLAVORS['2'].is_public,
            },
        ]

        url = self.base_url + '/detail'
        req = fakes.HTTPRequest.blank(url)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)
        for i, flavor in enumerate(body['flavors']):
            self._verify_flavor_response(flavor, expected[i])
