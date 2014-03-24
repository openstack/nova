# Copyright 2013 IBM Corp.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import contextlib

import mock

from nova import context
from nova import db
from nova.network import nova_ipam_lib
from nova import test
from nova.tests.objects import test_fixed_ip
from nova.tests.objects import test_network


fake_vif = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'address': '00:00:00:00:00:00',
    'network_id': 123,
    'instance_uuid': 'fake-uuid',
    'uuid': 'fake-uuid-2',
}


class NeutronNovaIPAMTestCase(test.NoDBTestCase):
    def test_get_v4_ips_by_interface(self):
        fake_ips = [dict(test_fixed_ip.fake_fixed_ip,
                         address='192.168.1.101'),
                    dict(test_fixed_ip.fake_fixed_ip,
                         address='192.168.1.102')]
        with contextlib.nested(
                mock.patch.object(db, 'virtual_interface_get_by_uuid',
                                  return_value=fake_vif),
                mock.patch.object(db, 'fixed_ips_by_virtual_interface',
                                  return_value=fake_ips)
        ):
            ipam_lib = nova_ipam_lib.NeutronNovaIPAMLib(None)
            v4_IPs = ipam_lib.get_v4_ips_by_interface(None,
                                                      'net_id',
                                                      'vif_id',
                                                      'project_id')
            self.assertEqual(['192.168.1.101', '192.168.1.102'], v4_IPs)

    def test_get_v4_ips_by_interface_bad_id(self):
        with contextlib.nested(
                mock.patch.object(db, 'virtual_interface_get_by_uuid',
                                  return_value=None),
        ):
            ipam_lib = nova_ipam_lib.NeutronNovaIPAMLib(None)
            v4_IPs = ipam_lib.get_v4_ips_by_interface(None,
                                                      'net_id',
                                                      'vif_id',
                                                      'project_id')
            self.assertEqual([], v4_IPs)

    def test_get_v6_ips_by_interface(self):
        class FakeContext(context.RequestContext):
            def elevated(self):
                pass

        net = dict(test_network.fake_network,
                   cidr_v6='2001:db8::')
        with contextlib.nested(
                mock.patch.object(db, 'network_get_by_uuid',
                                  return_value=net),
                mock.patch.object(db, 'virtual_interface_get_by_uuid',
                                  return_value=fake_vif)
        ):
            ipam_lib = nova_ipam_lib.NeutronNovaIPAMLib(None)
            ctx = FakeContext('user_id', 'project_id')
            v6_IPs = ipam_lib.get_v6_ips_by_interface(ctx,
                                                      'net_id',
                                                      'vif_id',
                                                      'project_id')
            self.assertEqual(['2001:db8::200:ff:fe00:0'], v6_IPs)

    def test_get_v6_ips_by_interface_bad_id(self):
        class FakeContext(context.RequestContext):
            def elevated(self):
                pass

        net = dict(test_network.fake_network,
                   cidr_v6='2001:db8::')
        with contextlib.nested(
                mock.patch.object(db, 'network_get_by_uuid',
                                  return_value=net),
                mock.patch.object(db, 'virtual_interface_get_by_uuid',
                                  return_value=None)
        ):
            ipam_lib = nova_ipam_lib.NeutronNovaIPAMLib(None)
            ctx = FakeContext('user_id', 'project_id')
            v6_IPs = ipam_lib.get_v6_ips_by_interface(ctx,
                                                      'net_id',
                                                      'vif_id',
                                                      'project_id')
            self.assertEqual([], v6_IPs)
