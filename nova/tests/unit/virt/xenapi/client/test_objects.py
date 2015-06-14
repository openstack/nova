# Copyright (c) 2014 Rackspace Hosting
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

import mock

from nova.tests.unit.virt.xenapi import stubs
from nova import utils
from nova.virt.xenapi.client import objects


class XenAPISessionObjectTestCase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(XenAPISessionObjectTestCase, self).setUp()
        self.session = mock.Mock()
        self.obj = objects.XenAPISessionObject(self.session, "FAKE")

    def test_call_method_via_attr(self):
        self.session.call_xenapi.return_value = "asdf"

        result = self.obj.get_X("ref")

        self.assertEqual(result, "asdf")
        self.session.call_xenapi.assert_called_once_with("FAKE.get_X", "ref")


class ObjectsTestCase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(ObjectsTestCase, self).setUp()
        self.session = mock.Mock()

    def test_VM(self):
        vm = objects.VM(self.session)
        vm.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("VM.get_X", "ref")

    def test_SR(self):
        sr = objects.SR(self.session)
        sr.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("SR.get_X", "ref")

    def test_VDI(self):
        vdi = objects.VDI(self.session)
        vdi.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("VDI.get_X", "ref")

    def test_VBD(self):
        vbd = objects.VBD(self.session)
        vbd.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("VBD.get_X", "ref")

    def test_PBD(self):
        pbd = objects.PBD(self.session)
        pbd.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("PBD.get_X", "ref")

    def test_PIF(self):
        pif = objects.PIF(self.session)
        pif.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("PIF.get_X", "ref")

    def test_VLAN(self):
        vlan = objects.VLAN(self.session)
        vlan.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("VLAN.get_X", "ref")

    def test_host(self):
        host = objects.Host(self.session)
        host.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("host.get_X", "ref")

    def test_network(self):
        network = objects.Network(self.session)
        network.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("network.get_X",
                                                         "ref")

    def test_pool(self):
        pool = objects.Pool(self.session)
        pool.get_X("ref")
        self.session.call_xenapi.assert_called_once_with("pool.get_X", "ref")


class VBDTestCase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(VBDTestCase, self).setUp()
        self.session = mock.Mock()
        self.session.VBD = objects.VBD(self.session)

    def test_plug(self):
        self.session.VBD.plug("vbd_ref", "vm_ref")
        self.session.call_xenapi.assert_called_once_with("VBD.plug", "vbd_ref")

    def test_unplug(self):
        self.session.VBD.unplug("vbd_ref", "vm_ref")
        self.session.call_xenapi.assert_called_once_with("VBD.unplug",
                                                         "vbd_ref")

    @mock.patch.object(utils, 'synchronized')
    def test_vbd_plug_check_synchronized(self, mock_synchronized):
        self.session.VBD.unplug("vbd_ref", "vm_ref")
        mock_synchronized.assert_called_once_with("xenapi-vbd-vm_ref")
