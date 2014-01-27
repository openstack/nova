# Copyright 2013 Red Hat Inc.
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

"""Test class for baremetal iBoot power manager."""

from nova import exception
from nova import test
from nova.tests.virt.baremetal.db import utils as bm_db_utils
from nova.virt.baremetal import iboot_pdu


class BareMetalIbootPDUTestCase(test.TestCase):

    def setUp(self):
        super(BareMetalIbootPDUTestCase, self).setUp()
        self.node = bm_db_utils.new_bm_node(
                id=123,
                pm_address='192.168.1.254',
                pm_user='foo',
                pm_password='bar')
        self.pm = iboot_pdu.IBootManager(node=self.node)

    def test_construct(self):
        self.assertEqual(self.pm.address, '192.168.1.254')
        self.assertEqual(self.pm.port, 9100)
        self.assertEqual(self.pm.relay_id, 1)
        self.assertEqual(self.pm.user, 'foo')
        self.assertEqual(self.pm.password, 'bar')

    def test_construct_with_port_and_relay(self):
        self.node = bm_db_utils.new_bm_node(
                id=123,
                pm_address='192.168.1.254:1234,8',
                pm_user='foo',
                pm_password='bar')
        self.pm = iboot_pdu.IBootManager(node=self.node)

        self.assertEqual(self.pm.address, '192.168.1.254')
        self.assertEqual(self.pm.port, 1234)
        self.assertEqual(self.pm.relay_id, 8)
        self.assertEqual(self.pm.user, 'foo')
        self.assertEqual(self.pm.password, 'bar')

    def test_construct_with_invalid_port(self):
        self.node = bm_db_utils.new_bm_node(
                id=123,
                pm_address='192.168.1.254:not_a_number',
                pm_user='foo',
                pm_password='bar')
        self.assertRaises(exception.InvalidParameterValue,
                            iboot_pdu.IBootManager, node=self.node)

    def test_construct_with_relay_id(self):
        self.node = bm_db_utils.new_bm_node(
                id=123,
                pm_address='192.168.1.254:1234,not_a_number',
                pm_user='foo',
                pm_password='bar')
        self.assertRaises(exception.InvalidParameterValue,
                            iboot_pdu.IBootManager, node=self.node)

    def test_activate_node(self):
        self.mox.StubOutWithMock(self.pm, '_create_connection')
        self.mox.StubOutWithMock(self.pm, '_switch')
        self.mox.StubOutWithMock(self.pm, 'is_power_on')
        self.pm._create_connection().AndReturn(True)
        self.pm._switch(1, True).AndReturn(True)
        self.pm.is_power_on().AndReturn(True)
        self.mox.ReplayAll()

        self.pm.activate_node()
        self.mox.VerifyAll()

    def test_deactivate_node(self):
        self.mox.StubOutWithMock(self.pm, '_create_connection')
        self.mox.StubOutWithMock(self.pm, '_switch')
        self.mox.StubOutWithMock(self.pm, 'is_power_on')
        self.pm._create_connection().AndReturn(True)
        self.pm.is_power_on().AndReturn(True)
        self.pm._switch(1, False).AndReturn(True)
        self.pm.is_power_on().AndReturn(False)
        self.mox.ReplayAll()

        self.pm.deactivate_node()
        self.mox.VerifyAll()

    def test_reboot_node(self):
        self.mox.StubOutWithMock(self.pm, '_create_connection')
        self.mox.StubOutWithMock(self.pm, '_switch')
        self.mox.StubOutWithMock(self.pm, 'is_power_on')
        self.pm._create_connection().AndReturn(True)
        self.pm._switch(1, False).AndReturn(True)
        self.pm._switch(1, True).AndReturn(True)
        self.pm.is_power_on().AndReturn(True)
        self.mox.ReplayAll()

        self.pm.reboot_node()
        self.mox.VerifyAll()

    def test_is_power_on(self):
        self.mox.StubOutWithMock(self.pm, '_create_connection')
        self.mox.StubOutWithMock(self.pm, '_get_relay')
        self.pm._create_connection().AndReturn(True)
        self.pm._get_relay(1).AndReturn(True)
        self.mox.ReplayAll()

        self.pm.is_power_on()
        self.mox.VerifyAll()
