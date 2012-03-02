# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 University of Southern California
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
#

import __builtin__
import StringIO

from nova import test
from nova.virt.baremetal import tilera


class TileraBareMetalNodesTestCase(test.TestCase):

    def setUp(self):
        super(TileraBareMetalNodesTestCase, self).setUp()
        self.board_info = "\n".join([
'# board_id  ip_address mac_address 00:1A:CA:00:57:90 '
'00:1A:CA:00:58:98 00:1A:CA:00:58:50',
'6            10.0.2.7   00:1A:CA:00:58:5C 10 16218 917 476 1 tilera_hv 1 '
'{"vendor":"tilera","model":"TILEmpower","arch":"TILEPro64",'
 '"features":["8x8Grid","32bVLIW","5.6MBCache","443BOPS","37TbMesh",'
             '"700MHz-866MHz","4DDR2","2XAUIMAC/PHY","2GbEMAC"],'
 '"topology":{"cores":"64"}}',
'7            10.0.2.8   00:1A:CA:00:58:A4 10 16218 917 476 1 tilera_hv 1 '
'{"vendor":"tilera","model":"TILEmpower","arch":"TILEPro64",'
 '"features":["8x8Grid","32bVLIW","5.6MBCache","443BOPS","37TbMesh",'
             '"700MHz-866MHz","4DDR2","2XAUIMAC/PHY","2GbEMAC"],'
 '"topology":{"cores":"64"}}',
'8            10.0.2.9   00:1A:CA:00:58:1A 10 16218 917 476 1 tilera_hv 1 '
'{"vendor":"tilera","model":"TILEmpower","arch":"TILEPro64",'
 '"features":["8x8Grid","32bVLIW","5.6MBCache","443BOPS","37TbMesh",'
             '"700MHz-866MHz","4DDR2","2XAUIMAC/PHY","2GbEMAC"],'
 '"topology":{"cores":"64"}}',
'9            10.0.2.10  00:1A:CA:00:58:38 10 16385 1000 0 0 tilera_hv 1 '
'{"vendor":"tilera","model":"TILEmpower","arch":"TILEPro64",'
 '"features":["8x8Grid","32bVLIW","5.6MBCache","443BOPS","37TbMesh",'
             '"700MHz-866MHz","4DDR2","2XAUIMAC/PHY","2GbEMAC"],'
 '"topology":{"cores":"64"}}'])

    def tearDown(self):
        super(TileraBareMetalNodesTestCase, self).tearDown()

        # Reset the singleton state
        tilera.BareMetalNodes._instance = None
        tilera.BareMetalNodes._is_init = False

    def test_singleton(self):
        """Confirm that the object acts like a singleton.

        In this case, we check that it only loads the config file once,
        even though it has been instantiated multiple times"""

        self.mox.StubOutWithMock(__builtin__, 'open')

        open("/tftpboot/tilera_boards",
             "r").AndReturn(StringIO.StringIO(self.board_info))

        self.mox.ReplayAll()

        nodes = tilera.BareMetalNodes("/tftpboot/tilera_boards")
        nodes = tilera.BareMetalNodes("/tftpboot/tilera_boards")

    def test_get_hw_info(self):
        self.mox.StubOutWithMock(__builtin__, 'open')

        open("/tftpboot/tilera_boards",
             "r").AndReturn(StringIO.StringIO(self.board_info))

        self.mox.ReplayAll()
        nodes = tilera.BareMetalNodes()
        self.assertEqual(nodes.get_hw_info('vcpus'), 10)
