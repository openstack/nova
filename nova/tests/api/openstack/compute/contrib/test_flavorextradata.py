# Copyright 2012 OpenStack LLC.
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
import json

import webob

from nova import test
from nova.tests.api.openstack import fakes
from nova.compute import instance_types


def fake_get_instance_type_by_flavor_id(flavorid):
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
        'swap': 512,
        'rxtx_factor': 1.0,
        'extra_specs': {},
        'deleted_at': None,
        'vcpu_weight': None
    }


def fake_get_all_types(inactive=0, filters=None):
    return {
        'fake1': fake_get_instance_type_by_flavor_id(1),
        'fake2': fake_get_instance_type_by_flavor_id(2)
    }


class FlavorextradataTest(test.TestCase):
    def setUp(self):
        super(FlavorextradataTest, self).setUp()
        self.stubs.Set(instance_types, 'get_instance_type_by_flavor_id',
                                        fake_get_instance_type_by_flavor_id)
        self.stubs.Set(instance_types, 'get_all_types', fake_get_all_types)

    def _verify_server_response(self, flavor, expected):
        for key in expected:
            self.assertEquals(flavor[key], expected[key])

    def test_show(self):
        expected = {
            'flavor': {
                'id': '1',
                'name': 'test',
                'ram': 512,
                'vcpus': 1,
                'disk': 1,
                'OS-FLV-EXT-DATA:ephemeral': 1,
                'swap': 512,
                'rxtx_factor': 1,
            }
        }

        url = '/v2/fake/flavors/1'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        body = json.loads(res.body)
        self._verify_server_response(body['flavor'], expected['flavor'])

    def test_detail(self):
        expected = [
            {
                'id': '1',
                'name': 'test',
                'ram': 512,
                'vcpus': 1,
                'disk': 1,
                'OS-FLV-EXT-DATA:ephemeral': 1,
                'swap': 512,
                'rxtx_factor': 1,
            },
            {
                'id': '2',
                'name': 'test',
                'ram': 512,
                'vcpus': 1,
                'disk': 1,
                'OS-FLV-EXT-DATA:ephemeral': 1,
                'swap': 512,
                'rxtx_factor': 1,
            },
        ]

        url = '/v2/fake/flavors/detail'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        body = json.loads(res.body)
        for i, flavor in enumerate(body['flavors']):
            self._verify_server_response(flavor, expected[i])
