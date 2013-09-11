# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


from nova.tests.volume.encryptors import test_cryptsetup
from nova.volume.encryptors import luks


"""
The utility of these test cases is limited given the simplicity of the
LuksEncryptor class. The attach_volume method has the only significant logic
to handle cases where the volume has not previously been formatted, but
exercising this logic requires "real" devices and actually executing the
various cryptsetup commands rather than simply logging them.
"""


class LuksEncryptorTestCase(test_cryptsetup.CryptsetupEncryptorTestCase):
    def _create(self, connection_info):
        return luks.LuksEncryptor(connection_info)

    def setUp(self):
        super(LuksEncryptorTestCase, self).setUp()

    def test__format_volume(self):
        self.encryptor._format_volume("passphrase")

        expected_commands = [('cryptsetup', '--batch-mode', 'luksFormat',
                              '--key-file=-', self.dev_path)]
        self.assertEqual(expected_commands, self.executes)

    def test__open_volume(self):
        self.encryptor._open_volume("passphrase")

        expected_commands = [('cryptsetup', 'luksOpen', '--key-file=-',
                              self.dev_path, self.dev_name)]
        self.assertEqual(expected_commands, self.executes)

    def test_attach_volume(self):
        self.stubs.Set(self.encryptor, '_get_key',
                       test_cryptsetup.fake__get_key)

        self.encryptor.attach_volume(None)

        expected_commands = [('cryptsetup', 'luksOpen', '--key-file=-',
                              self.dev_path, self.dev_name),
                             ('ln', '--symbolic', '--force',
                              '/dev/mapper/%s' % self.dev_name,
                              self.symlink_path)]
        self.assertEqual(expected_commands, self.executes)

    def test__close_volume(self):
        self.encryptor.detach_volume()

        expected_commands = [('cryptsetup', 'luksClose', self.dev_name)]
        self.assertEqual(expected_commands, self.executes)

    def test_detach_volume(self):
        self.encryptor.detach_volume()

        expected_commands = [('cryptsetup', 'luksClose', self.dev_name)]
        self.assertEqual(expected_commands, self.executes)
