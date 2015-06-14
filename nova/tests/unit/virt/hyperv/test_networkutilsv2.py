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

from nova.tests.unit.virt.hyperv import test_networkutils
from nova.virt.hyperv import networkutilsv2


class NetworkUtilsV2TestCase(test_networkutils.NetworkUtilsTestCase):
    """Unit tests for the Hyper-V NetworkUtilsV2 class."""

    _MSVM_VIRTUAL_SWITCH = 'Msvm_VirtualEthernetSwitch'

    def setUp(self):
        super(NetworkUtilsV2TestCase, self).setUp()
        self._networkutils = networkutilsv2.NetworkUtilsV2()
        self._networkutils._conn = mock.MagicMock()

    def _prepare_external_port(self, mock_vswitch, mock_ext_port):
        mock_lep = mock_ext_port.associators()[0]
        mock_lep1 = mock_lep.associators()[0]
        mock_esw = mock_lep1.associators()[0]
        mock_esw.associators.return_value = [mock_vswitch]

    def test_create_vswitch_port(self):
        self.assertRaises(
            NotImplementedError,
            self._networkutils.create_vswitch_port,
            mock.sentinel.FAKE_VSWITCH_PATH,
            mock.sentinel.FAKE_PORT_NAME)

    def test_vswitch_port_needed(self):
        self.assertFalse(self._networkutils.vswitch_port_needed())
