# Copyright 2013 IBM Corp.
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
import six

from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'
NW_CACHE = [
    {
        'address': 'aa:aa:aa:aa:aa:aa',
        'id': 1,
        'network': {
            'bridge': 'br0',
            'id': 1,
            'label': 'private',
            'subnets': [
                {
                    'cidr': '192.168.1.0/24',
                    'ips': [
                        {
                            'address': '192.168.1.100',
                            'type': 'fixed',
                            'floating_ips': [
                                {'address': '5.0.0.1', 'type': 'floating'},
                            ],
                        },
                    ],
                },
            ]
        }
    },
    {
        'address': 'bb:bb:bb:bb:bb:bb',
        'id': 2,
        'network': {
            'bridge': 'br1',
            'id': 2,
            'label': 'public',
            'subnets': [
                {
                    'cidr': '10.0.0.0/24',
                    'ips': [
                        {
                            'address': '10.0.0.100',
                            'type': 'fixed',
                            'floating_ips': [
                                {'address': '5.0.0.2', 'type': 'floating'},
                            ],
                        }
                    ],
                },
            ]
        }
    }
]
ALL_IPS = []
for cache in NW_CACHE:
    for subnet in cache['network']['subnets']:
        for fixed in subnet['ips']:
            sanitized = dict(fixed)
            sanitized['mac_address'] = cache['address']
            sanitized.pop('floating_ips')
            sanitized.pop('type')
            ALL_IPS.append(sanitized)
            for floating in fixed['floating_ips']:
                sanitized = dict(floating)
                sanitized['mac_address'] = cache['address']
                sanitized.pop('type')
                ALL_IPS.append(sanitized)
ALL_IPS.sort(key=lambda x: '%s-%s' % (x['address'], x['mac_address']))


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance_obj(None, 1, uuid=UUID3, nw_cache=NW_CACHE)
    return inst


def fake_compute_get_all(*args, **kwargs):
    inst_list = [
        fakes.stub_instance_obj(None, 1, uuid=UUID1, nw_cache=NW_CACHE),
        fakes.stub_instance_obj(None, 2, uuid=UUID2, nw_cache=NW_CACHE),
    ]
    return objects.InstanceList(objects=inst_list)


class ExtendedIpsMacTestV21(test.TestCase):
    content_type = 'application/json'
    prefix = 'OS-EXT-IPS-MAC:'

    def setUp(self):
        super(ExtendedIpsMacTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_secgroup_api(self)
        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        self.stub_out('nova.compute.api.API.get_all', fake_compute_get_all)

    def _make_request(self, url):
        req = fakes.HTTPRequest.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app_v21())
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def _get_ips(self, server):
        for network in six.itervalues(server['addresses']):
            for ip in network:
                yield ip

    def assertServerStates(self, server):
        results = []
        for ip in self._get_ips(server):
            results.append({'address': ip.get('addr'),
                            'mac_address': ip.get('%smac_addr' % self.prefix)})

        self.assertJsonEqual(ALL_IPS, results)

    def test_show(self):
        url = '/v2/%s/servers/%s' % (fakes.FAKE_PROJECT_ID, UUID3)
        res = self._make_request(url)

        self.assertEqual(200, res.status_int)
        self.assertServerStates(self._get_server(res.body))

    def test_detail(self):
        url = '/v2/%s/servers/detail' % fakes.FAKE_PROJECT_ID
        res = self._make_request(url)

        self.assertEqual(200, res.status_int)
        for _i, server in enumerate(self._get_servers(res.body)):
            self.assertServerStates(server)
