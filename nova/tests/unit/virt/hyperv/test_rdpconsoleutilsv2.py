#  Copyright 2013 Cloudbase Solutions Srl
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

from nova import test
from nova.virt.hyperv import rdpconsoleutilsv2


class RDPConsoleUtilsV2TestCase(test.NoDBTestCase):
    _FAKE_RDP_PORT = 1000

    def setUp(self):
        self._rdpconsoleutils = rdpconsoleutilsv2.RDPConsoleUtilsV2()
        self._rdpconsoleutils._conn = mock.MagicMock()

        super(RDPConsoleUtilsV2TestCase, self).setUp()

    def test_get_rdp_console_port(self):
        conn = self._rdpconsoleutils._conn
        mock_rdp_setting_data = conn.Msvm_TerminalServiceSettingData()[0]
        mock_rdp_setting_data.ListenerPort = self._FAKE_RDP_PORT

        listener_port = self._rdpconsoleutils.get_rdp_console_port()

        self.assertEqual(self._FAKE_RDP_PORT, listener_port)
