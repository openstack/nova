# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""
Bare-metal DB testcase for BareMetalPxeIp
"""

from nova import exception
from nova.openstack.common.db import exception as db_exc
from nova.tests.baremetal.db import base
from nova.tests.baremetal.db import utils
from nova.virt.baremetal import db


class BareMetalPxeIpTestCase(base.BMDBTestCase):

    def _create_pxe_ip(self):
        i1 = utils.new_bm_pxe_ip(address='10.1.1.1',
                                 server_address='10.1.1.101')
        i2 = utils.new_bm_pxe_ip(address='10.1.1.2',
                                 server_address='10.1.1.102')

        i1_ref = db.bm_pxe_ip_create_direct(self.context, i1)
        self.assertTrue(i1_ref['id'] is not None)
        self.assertEqual(i1_ref['address'], '10.1.1.1')
        self.assertEqual(i1_ref['server_address'], '10.1.1.101')

        i2_ref = db.bm_pxe_ip_create_direct(self.context, i2)
        self.assertTrue(i2_ref['id'] is not None)
        self.assertEqual(i2_ref['address'], '10.1.1.2')
        self.assertEqual(i2_ref['server_address'], '10.1.1.102')

        self.i1 = i1_ref
        self.i2 = i2_ref

    def test_unuque_address(self):
        self._create_pxe_ip()

        # address duplicates
        i = utils.new_bm_pxe_ip(address='10.1.1.1',
                                server_address='10.1.1.201')
        self.assertRaises(db_exc.DBError,
                          db.bm_pxe_ip_create_direct,
                          self.context, i)

        # server_address duplicates
        i = utils.new_bm_pxe_ip(address='10.1.1.3',
                                server_address='10.1.1.101')
        self.assertRaises(db_exc.DBError,
                          db.bm_pxe_ip_create_direct,
                          self.context, i)

        db.bm_pxe_ip_destroy(self.context, self.i1['id'])
        i = utils.new_bm_pxe_ip(address='10.1.1.1',
                                server_address='10.1.1.101')
        ref = db.bm_pxe_ip_create_direct(self.context, i)
        self.assertTrue(ref is not None)

    def test_bm_pxe_ip_associate(self):
        self._create_pxe_ip()
        node = db.bm_node_create(self.context, utils.new_bm_node())
        ip_id = db.bm_pxe_ip_associate(self.context, node['id'])
        ref = db.bm_pxe_ip_get(self.context, ip_id)
        self.assertEqual(ref['bm_node_id'], node['id'])

    def test_bm_pxe_ip_associate_raise(self):
        self._create_pxe_ip()
        node_id = 123
        self.assertRaises(exception.NovaException,
                          db.bm_pxe_ip_associate,
                          self.context, node_id)

    def test_delete_by_address(self):
        self._create_pxe_ip()
        db.bm_pxe_ip_destroy_by_address(self.context, '10.1.1.1')
        del_ref = db.bm_pxe_ip_get(self.context, self.i1['id'])
        self.assertTrue(del_ref is None)

    def test_delete_by_address_not_exist(self):
        self._create_pxe_ip()
        del_ref = db.bm_pxe_ip_destroy_by_address(self.context, '10.11.12.13')
        self.assertTrue(del_ref is None)
