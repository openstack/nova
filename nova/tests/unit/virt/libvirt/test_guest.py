#    Copyright 2010 OpenStack Foundation
#    Copyright 2012 University Of Minho
#    Copyright 2014-2015 Red Hat, Inc
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
from oslo_config import cfg
from oslo_utils import encodeutils

from nova import context
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova import utils
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host


host.libvirt = fakelibvirt
libvirt_guest.libvirt = fakelibvirt

CONF = cfg.CONF


class GuestTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GuestTestCase, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        self.host = host.Host("qemu:///system")
        self.context = context.get_admin_context()

    def test_repr(self):
        domain = mock.MagicMock()
        domain.ID.return_value = 99
        domain.UUIDString.return_value = "UUID"
        domain.name.return_value = "foo"

        guest = libvirt_guest.Guest(domain)
        self.assertEqual("<Guest 99 foo UUID>", repr(guest))

    @mock.patch.object(fakelibvirt.Connection, 'defineXML')
    def test_create(self, mock_define):
        libvirt_guest.Guest.create("xml", self.host)
        mock_define.assert_called_once_with("xml")

    @mock.patch.object(fakelibvirt.Connection, 'defineXML')
    def test_create_exception(self, mock_define):
        mock_define.side_effect = test.TestingException
        self.assertRaises(test.TestingException,
                          libvirt_guest.Guest.create,
                          "foo", self.host)

    def test_launch(self):
        domain = mock.MagicMock()

        guest = libvirt_guest.Guest(domain)
        guest.launch()

        domain.createWithFlags.assert_called_once_with(0)

    def test_launch_and_pause(self):
        domain = mock.MagicMock()

        guest = libvirt_guest.Guest(domain)
        guest.launch(pause=True)

        domain.createWithFlags.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_START_PAUSED)

    @mock.patch.object(encodeutils, 'safe_decode')
    def test_launch_exception(self, mock_safe_decode):
        domain = mock.MagicMock()
        domain.createWithFlags.side_effect = test.TestingException
        mock_safe_decode.return_value = "</xml>"

        guest = libvirt_guest.Guest(domain)
        self.assertRaises(test.TestingException, guest.launch)
        self.assertEqual(1, mock_safe_decode.called)

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(libvirt_guest.Guest, 'get_interfaces')
    def test_enable_hairpin(self, mock_get_interfaces, mock_execute):
        mock_get_interfaces.return_value = ["vnet0", "vnet1"]

        guest = libvirt_guest.Guest(mock.MagicMock())
        guest.enable_hairpin()
        mock_execute.assert_has_calls([
            mock.call(
                'tee', '/sys/class/net/vnet0/brport/hairpin_mode',
                run_as_root=True, process_input='1', check_exit_code=[0, 1]),
            mock.call(
                'tee', '/sys/class/net/vnet1/brport/hairpin_mode',
                run_as_root=True, process_input='1', check_exit_code=[0, 1])])

    @mock.patch.object(encodeutils, 'safe_decode')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(libvirt_guest.Guest, 'get_interfaces')
    def test_enable_hairpin_exception(self, mock_get_interfaces,
                            mock_execute, mock_safe_decode):
        mock_get_interfaces.return_value = ["foo"]
        mock_execute.side_effect = test.TestingException('oops')

        guest = libvirt_guest.Guest(mock.MagicMock())
        self.assertRaises(test.TestingException, guest.enable_hairpin)
        self.assertEqual(1, mock_safe_decode.called)

    def test_get_interfaces(self):
        dom = mock.MagicMock()
        dom.XMLDesc.return_value = """
<domain>
  <devices>
    <interface type="network">
      <target dev="vnet0"/>
    </interface>
    <interface type="network">
      <target dev="vnet1"/>
    </interface>
  </devices>
</domain>"""
        guest = libvirt_guest.Guest(dom)
        self.assertEqual(["vnet0", "vnet1"], guest.get_interfaces())

    def test_get_interfaces_exception(self):
        dom = mock.MagicMock()
        dom.XMLDesc.return_value = "<bad xml>"
        guest = libvirt_guest.Guest(dom)
        self.assertEqual([], guest.get_interfaces())

    def test_poweroff(self):
        domain = mock.MagicMock()

        guest = libvirt_guest.Guest(domain)
        guest.poweroff()

        domain.destroy.assert_called_once_with()

    def test_resume(self):
        domain = mock.MagicMock()

        guest = libvirt_guest.Guest(domain)
        guest.resume()

        domain.resume.assert_called_once_with()

    def test_get_vcpus_info(self):
        domain = mock.MagicMock()
        domain.vcpus.return_value = ([(0, 1, 10290000000L, 2)],
                                     [(True, True)])
        guest = libvirt_guest.Guest(domain)
        vcpus = list(guest.get_vcpus_info())
        self.assertEqual(0, vcpus[0].id)
        self.assertEqual(2, vcpus[0].cpu)
        self.assertEqual(1, vcpus[0].state)
        self.assertEqual(10290000000L, vcpus[0].time)

    def test_delete_configuration(self):
        domain = mock.MagicMock()

        guest = libvirt_guest.Guest(domain)
        guest.delete_configuration()

        domain.undefineFlags.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)

    def test_delete_configuration_exception(self):
        domain = mock.MagicMock()
        domain.undefineFlags.side_effect = fakelibvirt.libvirtError('oops')

        guest = libvirt_guest.Guest(domain)
        guest.delete_configuration()

        domain.undefine.assert_called_once_with()
