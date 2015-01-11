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
import webob

from nova.api.openstack.compute.contrib import extended_ips_mac
from nova import compute
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance

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
ALL_IPS.sort()


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID3, nw_cache=NW_CACHE)
    return fake_instance.fake_instance_obj(args[1],
              expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS, **inst)


def fake_compute_get_all(*args, **kwargs):
    db_list = [
        fakes.stub_instance(1, uuid=UUID1, nw_cache=NW_CACHE),
        fakes.stub_instance(2, uuid=UUID2, nw_cache=NW_CACHE),
    ]
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            objects.InstanceList(),
                                            db_list, fields)


class ExtendedIpsMacTestV21(test.TestCase):
    content_type = 'application/json'
    prefix = '%s:' % extended_ips_mac.Extended_ips_mac.alias

    def setUp(self):
        super(ExtendedIpsMacTestV21, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app_v21(init_only=('servers',)))
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def _get_ips(self, server):
        for network in server['addresses'].itervalues():
            for ip in network:
                yield ip

    def assertServerStates(self, server):
        results = []
        for ip in self._get_ips(server):
            results.append({'address': ip.get('addr'),
                            'mac_address': ip.get('%smac_addr' % self.prefix)})

        self.assertEqual(ALL_IPS, sorted(results))

    def test_show(self):
        url = '/v2/fake/servers/%s' % UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertServerStates(self._get_server(res.body))

    def test_detail(self):
        url = '/v2/fake/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for _i, server in enumerate(self._get_servers(res.body)):
            self.assertServerStates(server)


class ExtendedIpsMacTestV2(ExtendedIpsMacTestV21):
    content_type = 'application/json'
    prefix = '%s:' % extended_ips_mac.Extended_ips_mac.alias

    def setUp(self):
        super(ExtendedIpsMacTestV2, self).setUp()
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Extended_ips_mac'])

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app(init_only=('servers',)))
        return res
