# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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


import array
import os

from nova.keymgr import key
from nova.tests.volume.encryptors import test_base
from nova import utils
from nova.volume.encryptors import cryptsetup


def fake__get_key(context):
    raw = array.array('B', ('0' * 64).decode('hex')).tolist()

    symmetric_key = key.SymmetricKey('AES', raw)
    return symmetric_key


class CryptsetupEncryptorTestCase(test_base.VolumeEncryptorTestCase):
    def _create(self, connection_info):
        return cryptsetup.CryptsetupEncryptor(connection_info)

    def setUp(self):
        super(CryptsetupEncryptorTestCase, self).setUp()

        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(os.path, "realpath", lambda x: x)

        self.dev_path = self.connection_info['data']['device_path']
        self.dev_name = self.dev_path.split('/')[-1]

        self.symlink_path = self.dev_path

    def test__open_volume(self):
        self.encryptor._open_volume("passphrase")

        expected_commands = [('cryptsetup', 'create', '--key-file=-',
                              self.dev_name, self.dev_path)]
        self.assertEqual(expected_commands, self.executes)

    def test_attach_volume(self):
        self.stubs.Set(self.encryptor, '_get_key', fake__get_key)

        self.encryptor.attach_volume(None)

        expected_commands = [('cryptsetup', 'create', '--key-file=-',
                              self.dev_name, self.dev_path),
                             ('ln', '--symbolic', '--force',
                              '/dev/mapper/%s' % self.dev_name,
                              self.symlink_path)]
        self.assertEqual(expected_commands, self.executes)

    def test__close_volume(self):
        self.encryptor.detach_volume()

        expected_commands = [('cryptsetup', 'remove', self.dev_name)]
        self.assertEqual(expected_commands, self.executes)

    def test_detach_volume(self):
        self.encryptor.detach_volume()

        expected_commands = [('cryptsetup', 'remove', self.dev_name)]
        self.assertEqual(expected_commands, self.executes)
