# Copyright 2015 Cloudbase Solutions SRL
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
Unit tests for the Hyper-V RDPConsoleOps.
"""

import mock

from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import rdpconsoleops


class RDPConsoleOpsTestCase(test_base.HyperVBaseTestCase):

    def setUp(self):
        super(RDPConsoleOpsTestCase, self).setUp()

        self.rdpconsoleops = rdpconsoleops.RDPConsoleOps()
        self.rdpconsoleops._hostops = mock.MagicMock()
        self.rdpconsoleops._vmutils = mock.MagicMock()
        self.rdpconsoleops._rdpconsoleutils = mock.MagicMock()

    def test_get_rdp_console(self):
        mock_get_host_ip = self.rdpconsoleops._hostops.get_host_ip_addr
        mock_get_rdp_port = (
            self.rdpconsoleops._rdpconsoleutils.get_rdp_console_port)
        mock_get_vm_id = self.rdpconsoleops._vmutils.get_vm_id

        connect_info = self.rdpconsoleops.get_rdp_console(mock.DEFAULT)

        self.assertEqual(mock_get_host_ip.return_value, connect_info.host)
        self.assertEqual(mock_get_rdp_port.return_value, connect_info.port)
        self.assertEqual(mock_get_vm_id.return_value,
                         connect_info.internal_access_path)
