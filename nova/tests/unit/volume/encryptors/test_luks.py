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


import mock

from nova.tests.unit.volume.encryptors import test_cryptsetup
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

    @mock.patch('nova.utils.execute')
    def test__format_volume(self, mock_execute):
        self.encryptor._format_volume("passphrase")

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', '--batch-mode', 'luksFormat',
                      '--key-file=-', self.dev_path,
                      process_input='passphrase',
                      run_as_root=True, check_exit_code=True),
        ], any_order=False)
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test__open_volume(self, mock_execute):
        self.encryptor._open_volume("passphrase")

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksOpen', '--key-file=-', self.dev_path,
                      self.dev_name, process_input='passphrase',
                      run_as_root=True, check_exit_code=True),
        ], any_order=False)
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_attach_volume(self, mock_execute):
        self.encryptor._get_key = mock.MagicMock()
        self.encryptor._get_key.return_value = \
                test_cryptsetup.fake__get_key(None)

        self.encryptor.attach_volume(None)

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksOpen', '--key-file=-', self.dev_path,
                      self.dev_name, process_input='0' * 32,
                      run_as_root=True, check_exit_code=True),
            mock.call('ln', '--symbolic', '--force',
                      '/dev/mapper/%s' % self.dev_name, self.symlink_path,
                      run_as_root=True, check_exit_code=True),
        ], any_order=False)
        self.assertEqual(2, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test__close_volume(self, mock_execute):
        self.encryptor.detach_volume()

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksClose', self.dev_name,
                      attempts=3, run_as_root=True, check_exit_code=True),
        ], any_order=False)
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_detach_volume(self, mock_execute):
        self.encryptor.detach_volume()

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksClose', self.dev_name,
                      attempts=3, run_as_root=True, check_exit_code=True),
        ], any_order=False)
        self.assertEqual(1, mock_execute.call_count)
