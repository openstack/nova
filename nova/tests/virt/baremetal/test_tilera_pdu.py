# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright (c) 2011-2013 University of Southern California / ISI
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

"""Test class for baremetal PDU power manager."""

from oslo.config import cfg

from nova import test
from nova.tests.virt.baremetal.db import utils as bm_db_utils
from nova import utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import tilera_pdu
from nova.virt.baremetal import utils as bm_utils

CONF = cfg.CONF


class BareMetalPduTestCase(test.TestCase):

    def setUp(self):
        super(BareMetalPduTestCase, self).setUp()
        self.flags(tile_power_wait=0, group='baremetal')
        self.node = bm_db_utils.new_bm_node(
                id=123,
                pm_address='fake-address',
                pm_user='fake-user',
                pm_password='fake-password')
        self.tilera_pdu = tilera_pdu.Pdu(self.node)
        self.tile_pdu_on = 1
        self.tile_pdu_off = 2
        self.tile_pdu_status = 9

    def test_construct(self):
        self.assertEqual(self.tilera_pdu.node_id, 123)
        self.assertEqual(self.tilera_pdu.address, 'fake-address')
        self.assertEqual(self.tilera_pdu.user, 'fake-user')
        self.assertEqual(self.tilera_pdu.password, 'fake-password')

    def test_exec_pdutool(self):
        self.flags(tile_pdu_mgr='fake-pdu-mgr', group='baremetal')
        self.flags(tile_pdu_ip='fake-address', group='baremetal')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(bm_utils, 'unlink_without_raise')
        args = [
                'fake-pdu-mgr',
                'fake-address',
                self.tile_pdu_on,
                ]
        utils.execute(*args).AndReturn('')
        self.mox.ReplayAll()

        self.tilera_pdu._exec_pdutool(self.tile_pdu_on)
        self.mox.VerifyAll()

    def test_is_power(self):
        self.mox.StubOutWithMock(self.tilera_pdu, '_exec_pdutool')
        self.tilera_pdu._exec_pdutool(self.tile_pdu_status).AndReturn(
                self.tile_pdu_on)
        self.mox.ReplayAll()

        self.tilera_pdu._is_power(self.tile_pdu_on)
        self.mox.VerifyAll()

    def test_power_already_on(self):
        self.mox.StubOutWithMock(self.tilera_pdu, '_exec_pdutool')

        self.tilera_pdu._exec_pdutool(self.tile_pdu_on).AndReturn(None)
        self.tilera_pdu._exec_pdutool(self.tile_pdu_status).AndReturn(
                self.tile_pdu_on)
        self.mox.ReplayAll()

        self.tilera_pdu.state = baremetal_states.DELETED
        self.tilera_pdu._power_on()
        self.mox.VerifyAll()
        self.assertEqual(self.tilera_pdu.state, baremetal_states.ACTIVE)

    def test_power_on_ok(self):
        self.mox.StubOutWithMock(self.tilera_pdu, '_exec_pdutool')

        self.tilera_pdu._exec_pdutool(self.tile_pdu_on).AndReturn(None)
        self.tilera_pdu._exec_pdutool(self.tile_pdu_status).AndReturn(
                self.tile_pdu_on)
        self.mox.ReplayAll()

        self.tilera_pdu.state = baremetal_states.DELETED
        self.tilera_pdu._power_on()
        self.mox.VerifyAll()
        self.assertEqual(self.tilera_pdu.state, baremetal_states.ACTIVE)

    def test_power_on_fail(self):
        self.mox.StubOutWithMock(self.tilera_pdu, '_exec_pdutool')

        self.tilera_pdu._exec_pdutool(self.tile_pdu_on).AndReturn(None)
        self.tilera_pdu._exec_pdutool(self.tile_pdu_status).AndReturn(
                 self.tile_pdu_off)
        self.mox.ReplayAll()

        self.tilera_pdu.state = baremetal_states.DELETED
        self.tilera_pdu._power_on()
        self.mox.VerifyAll()
        self.assertEqual(self.tilera_pdu.state, baremetal_states.ERROR)

    def test_power_on_max_retries(self):
        self.mox.StubOutWithMock(self.tilera_pdu, '_exec_pdutool')

        self.tilera_pdu._exec_pdutool(self.tile_pdu_on).AndReturn(None)
        self.tilera_pdu._exec_pdutool(self.tile_pdu_status).AndReturn(
                self.tile_pdu_off)
        self.mox.ReplayAll()

        self.tilera_pdu.state = baremetal_states.DELETED
        self.tilera_pdu._power_on()
        self.mox.VerifyAll()
        self.assertEqual(self.tilera_pdu.state, baremetal_states.ERROR)

    def test_power_off_ok(self):
        self.mox.StubOutWithMock(self.tilera_pdu, '_exec_pdutool')

        self.tilera_pdu._exec_pdutool(self.tile_pdu_off).AndReturn(None)
        self.tilera_pdu._exec_pdutool(self.tile_pdu_status).AndReturn(
                self.tile_pdu_off)
        self.mox.ReplayAll()

        self.tilera_pdu.state = baremetal_states.ACTIVE
        self.tilera_pdu._power_off()
        self.mox.VerifyAll()
        self.assertEqual(self.tilera_pdu.state, baremetal_states.DELETED)
