# Copyright 2014 IBM Corp.
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

from nova import db
from nova import exception
from nova.tests.functional.v3 import test_servers
from nova.tests.unit.objects import test_network
from nova.tests.unit import utils as test_utils


class FixedIpTest(test_servers.ServersSampleBase):
    extension_name = "os-fixed-ips"

    def setUp(self):
        super(FixedIpTest, self).setUp()

        instance = dict(test_utils.get_test_instance(),
                        hostname='openstack', host='host')
        fake_fixed_ips = [{'id': 1,
                   'address': '192.168.1.1',
                   'network_id': 1,
                   'virtual_interface_id': 1,
                   'instance_uuid': '1',
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'created_at': None,
                   'deleted_at': None,
                   'updated_at': None,
                   'deleted': None,
                   'instance': instance,
                   'network': test_network.fake_network,
                   'host': None},
                  {'id': 2,
                   'address': '192.168.1.2',
                   'network_id': 1,
                   'virtual_interface_id': 2,
                   'instance_uuid': '2',
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'created_at': None,
                   'deleted_at': None,
                   'updated_at': None,
                   'deleted': None,
                   'instance': instance,
                   'network': test_network.fake_network,
                   'host': None},
                  ]

        def fake_fixed_ip_get_by_address(context, address,
                                         columns_to_join=None):
            for fixed_ip in fake_fixed_ips:
                if fixed_ip['address'] == address:
                    return fixed_ip
            raise exception.FixedIpNotFoundForAddress(address=address)

        def fake_fixed_ip_update(context, address, values):
            fixed_ip = fake_fixed_ip_get_by_address(context, address)
            if fixed_ip is None:
                raise exception.FixedIpNotFoundForAddress(address=address)
            else:
                for key in values:
                    fixed_ip[key] = values[key]

        self.stubs.Set(db, "fixed_ip_get_by_address",
                       fake_fixed_ip_get_by_address)
        self.stubs.Set(db, "fixed_ip_update", fake_fixed_ip_update)

    def test_fixed_ip_reserve(self):
        # Reserve a Fixed IP.
        project = {'reserve': None}
        response = self._do_post('os-fixed-ips/192.168.1.1/action',
                                 'fixedip-post-req',
                                 project)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_get_fixed_ip(self):
        # Return data about the given fixed ip.
        response = self._do_get('os-fixed-ips/192.168.1.1')
        project = {'cidr': '192.168.1.0/24',
                   'hostname': 'openstack',
                   'host': 'host',
                   'address': '192.168.1.1'}
        self._verify_response('fixedips-get-resp', project, response, 200)
