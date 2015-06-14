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


from nova.console import type as ctype
from nova import test


class TypeTestCase(test.NoDBTestCase):
    def test_console(self):
        c = ctype.Console(host='127.0.0.1', port=8945)

        self.assertTrue(hasattr(c, 'host'))
        self.assertTrue(hasattr(c, 'port'))
        self.assertTrue(hasattr(c, 'internal_access_path'))

        self.assertEqual('127.0.0.1', c.host)
        self.assertEqual(8945, c.port)
        self.assertIsNone(c.internal_access_path)

        self.assertEqual({
            'host': '127.0.0.1',
            'port': 8945,
            'internal_access_path': None,
            'token': 'a-token',
            'access_url': 'an-url'},
            c.get_connection_info('a-token', 'an-url'))

    def test_console_vnc(self):
        c = ctype.ConsoleVNC(host='127.0.0.1', port=8945)

        self.assertIsInstance(c, ctype.Console)

    def test_console_rdp(self):
        c = ctype.ConsoleRDP(host='127.0.0.1', port=8945)

        self.assertIsInstance(c, ctype.Console)

    def test_console_spice(self):
        c = ctype.ConsoleSpice(host='127.0.0.1', port=8945, tlsPort=6547)

        self.assertIsInstance(c, ctype.Console)
        self.assertEqual(6547, c.tlsPort)
        self.assertEqual(
            6547, c.get_connection_info('a-token', 'an-url')['tlsPort'])

    def test_console_serial(self):
        c = ctype.ConsoleSerial(host='127.0.0.1', port=8945)

        self.assertIsInstance(c, ctype.Console)
