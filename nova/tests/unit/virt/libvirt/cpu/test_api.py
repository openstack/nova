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

from unittest import mock

from nova import test
from nova.virt.libvirt.cpu import api
from nova.virt.libvirt.cpu import core


class TestAPI(test.NoDBTestCase):

    def setUp(self):
        super(TestAPI, self).setUp()
        self.core_1 = api.Core(1)

    @mock.patch.object(core, 'get_online')
    def test_online(self, mock_get_online):
        mock_get_online.return_value = True
        self.assertTrue(self.core_1.online)
        mock_get_online.assert_called_once_with(self.core_1.ident)

    @mock.patch.object(core, 'set_online')
    def test_set_online(self, mock_set_online):
        self.core_1.online = True
        mock_set_online.assert_called_once_with(self.core_1.ident)

    @mock.patch.object(core, 'set_offline')
    def test_set_offline(self, mock_set_offline):
        self.core_1.online = False
        mock_set_offline.assert_called_once_with(self.core_1.ident)

    def test_hash(self):
        self.assertEqual(hash(self.core_1.ident), hash(self.core_1))

    @mock.patch.object(core, 'get_governor')
    def test_governor(self, mock_get_governor):
        mock_get_governor.return_value = 'fake_governor'
        self.assertEqual('fake_governor', self.core_1.governor)
        mock_get_governor.assert_called_once_with(self.core_1.ident)

    @mock.patch.object(core, 'set_governor')
    def test_set_governor_low(self, mock_set_governor):
        self.flags(cpu_power_governor_low='fake_low_gov', group='libvirt')
        self.core_1.set_low_governor()
        mock_set_governor.assert_called_once_with(self.core_1.ident,
                                                  'fake_low_gov')

    @mock.patch.object(core, 'set_governor')
    def test_set_governor_high(self, mock_set_governor):
        self.flags(cpu_power_governor_high='fake_high_gov', group='libvirt')
        self.core_1.set_high_governor()
        mock_set_governor.assert_called_once_with(self.core_1.ident,
                                                  'fake_high_gov')
