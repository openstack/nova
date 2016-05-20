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

import datetime

from oslo_serialization import jsonutils
import webob

from nova.compute import flavors
from nova import test
from nova.tests.unit.api.openstack import fakes


def fake_get_flavor_by_flavor_id(flavorid, ctxt=None):
    return {
        'id': flavorid,
        'flavorid': str(flavorid),
        'root_gb': 1,
        'ephemeral_gb': 1,
        'name': u'test',
        'deleted': False,
        'created_at': datetime.datetime(2012, 1, 1, 1, 1, 1, 1),
        'updated_at': None,
        'memory_mb': 512,
        'vcpus': 1,
        'extra_specs': {},
        'deleted_at': None,
        'vcpu_weight': None,
        'swap': 0,
        'disabled': False,
    }


def fake_get_all_flavors_sorted_list(context=None, inactive=False,
                                     filters=None, sort_key='flavorid',
                                     sort_dir='asc', limit=None, marker=None):
    return [
        fake_get_flavor_by_flavor_id(1),
        fake_get_flavor_by_flavor_id(2)
    ]


class FlavorExtraDataTestV21(test.NoDBTestCase):
    base_url = '/v2/fake/flavors'

    def setUp(self):
        super(FlavorExtraDataTestV21, self).setUp()
        ext = ('nova.api.openstack.compute.contrib'
              '.flavorextradata.Flavorextradata')
        self.flags(osapi_compute_extension=[ext])
        self.stubs.Set(flavors, 'get_flavor_by_flavor_id',
                                        fake_get_flavor_by_flavor_id)
        self.stubs.Set(flavors, 'get_all_flavors_sorted_list',
                       fake_get_all_flavors_sorted_list)

    @property
    def app(self):
        return fakes.wsgi_app_v21(init_only=('flavors'))

    def _verify_flavor_response(self, flavor, expected):
        for key in expected:
            self.assertEqual(flavor[key], expected[key])

    def test_show(self):
        expected = {
            'flavor': {
                'id': '1',
                'name': 'test',
                'ram': 512,
                'vcpus': 1,
                'disk': 1,
                'OS-FLV-EXT-DATA:ephemeral': 1,
            }
        }

        url = self.base_url + '/1'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)
        self._verify_flavor_response(body['flavor'], expected['flavor'])

    def test_detail(self):
        expected = [
            {
                'id': '1',
                'name': 'test',
                'ram': 512,
                'vcpus': 1,
                'disk': 1,
                'OS-FLV-EXT-DATA:ephemeral': 1,
            },
            {
                'id': '2',
                'name': 'test',
                'ram': 512,
                'vcpus': 1,
                'disk': 1,
                'OS-FLV-EXT-DATA:ephemeral': 1,
            },
        ]

        url = self.base_url + '/detail'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(self.app)
        body = jsonutils.loads(res.body)
        for i, flavor in enumerate(body['flavors']):
            self._verify_flavor_response(flavor, expected[i])


class FlavorExtraDataTestV2(FlavorExtraDataTestV21):

    @property
    def app(self):
        return fakes.wsgi_app(init_only=('flavors',))
