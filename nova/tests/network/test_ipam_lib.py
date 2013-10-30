# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


class NeutronNovaIPAMTestCase(test.NoDBTestCase):
    def test_get_v4_ips_by_interface(self):
        with contextlib.nested(
                mock.patch.object(db, 'virtual_interface_get_by_uuid',
                                  return_value={'id': 'fakeid'}),
                mock.patch.object(db, 'fixed_ips_by_virtual_interface',
                                  return_value=[{'address': '192.168.1.101'},
                                                {'address': '192.168.1.102'}])
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

        with contextlib.nested(
                mock.patch.object(db, 'network_get_by_uuid',
                                  return_value={'cidr_v6': '2001:db8::'}),
                mock.patch.object(db, 'virtual_interface_get_by_uuid',
                                  return_value={'address':
                                                '02:16:3e:33:44:55'})
        ):
            ipam_lib = nova_ipam_lib.NeutronNovaIPAMLib(None)
            ctx = FakeContext('user_id', 'project_id')
            v6_IPs = ipam_lib.get_v6_ips_by_interface(ctx,
                                                      'net_id',
                                                      'vif_id',
                                                      'project_id')
            self.assertEqual(['2001:db8::16:3eff:fe33:4455'], v6_IPs)

    def test_get_v6_ips_by_interface_bad_id(self):
        class FakeContext(context.RequestContext):
            def elevated(self):
                pass

        with contextlib.nested(
                mock.patch.object(db, 'network_get_by_uuid',
                                  return_value={'cidr_v6': '2001:db8::'}),
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
