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
from oslo_concurrency import processutils

from nova.tests.unit.volume.encryptors import test_cryptsetup
from nova.volume.encryptors import luks


class LuksEncryptorTestCase(test_cryptsetup.CryptsetupEncryptorTestCase):
    def _create(self, connection_info):
        return luks.LuksEncryptor(connection_info)

    @mock.patch('nova.utils.execute')
    def test_is_luks(self, mock_execute):
        luks.is_luks(self.dev_path)

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'isLuks', '--verbose', self.dev_path,
                      run_as_root=True, check_exit_code=True),
        ], any_order=False)
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.volume.encryptors.luks.LOG')
    @mock.patch('nova.utils.execute')
    def test_is_luks_with_error(self, mock_execute, mock_log):
        error_msg = "Device %s is not a valid LUKS device." % self.dev_path
        mock_execute.side_effect = \
                processutils.ProcessExecutionError(exit_code=1,
                                                   stderr=error_msg)

        luks.is_luks(self.dev_path)

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'isLuks', '--verbose', self.dev_path,
                      run_as_root=True, check_exit_code=True),
        ])
        self.assertEqual(1, mock_execute.call_count)

        self.assertEqual(1, mock_log.warning.call_count)  # warning logged

    @mock.patch('nova.utils.execute')
    def test__format_volume(self, mock_execute):
        self.encryptor._format_volume("passphrase")

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', '--batch-mode', 'luksFormat',
                      '--key-file=-', self.dev_path,
                      process_input='passphrase',
                      run_as_root=True, check_exit_code=True, attempts=3),
        ])
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test__open_volume(self, mock_execute):
        self.encryptor._open_volume("passphrase")

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksOpen', '--key-file=-', self.dev_path,
                      self.dev_name, process_input='passphrase',
                      run_as_root=True, check_exit_code=True),
        ])
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
        ])
        self.assertEqual(2, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_attach_volume_not_formatted(self, mock_execute):
        self.encryptor._get_key = mock.MagicMock()
        self.encryptor._get_key.return_value = \
                test_cryptsetup.fake__get_key(None)

        mock_execute.side_effect = [
                processutils.ProcessExecutionError(exit_code=1),  # luksOpen
                processutils.ProcessExecutionError(exit_code=1),  # isLuks
                mock.DEFAULT,  # luksFormat
                mock.DEFAULT,  # luksOpen
                mock.DEFAULT,  # ln
        ]

        self.encryptor.attach_volume(None)

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksOpen', '--key-file=-', self.dev_path,
                      self.dev_name, process_input='0' * 32,
                      run_as_root=True, check_exit_code=True),
            mock.call('cryptsetup', 'isLuks', '--verbose', self.dev_path,
                      run_as_root=True, check_exit_code=True),
            mock.call('cryptsetup', '--batch-mode', 'luksFormat',
                      '--key-file=-', self.dev_path, process_input='0' * 32,
                      run_as_root=True, check_exit_code=True, attempts=3),
            mock.call('cryptsetup', 'luksOpen', '--key-file=-', self.dev_path,
                      self.dev_name, process_input='0' * 32,
                      run_as_root=True, check_exit_code=True),
            mock.call('ln', '--symbolic', '--force',
                      '/dev/mapper/%s' % self.dev_name, self.symlink_path,
                      run_as_root=True, check_exit_code=True),
        ], any_order=False)
        self.assertEqual(5, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_attach_volume_fail(self, mock_execute):
        self.encryptor._get_key = mock.MagicMock()
        self.encryptor._get_key.return_value = \
                test_cryptsetup.fake__get_key(None)

        mock_execute.side_effect = [
                processutils.ProcessExecutionError(exit_code=1),  # luksOpen
                mock.DEFAULT,  # isLuks
        ]

        self.assertRaises(processutils.ProcessExecutionError,
                          self.encryptor.attach_volume, None)

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksOpen', '--key-file=-', self.dev_path,
                      self.dev_name, process_input='0' * 32,
                      run_as_root=True, check_exit_code=True),
            mock.call('cryptsetup', 'isLuks', '--verbose', self.dev_path,
                      run_as_root=True, check_exit_code=True),
        ], any_order=False)
        self.assertEqual(2, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test__close_volume(self, mock_execute):
        self.encryptor.detach_volume()

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksClose', self.dev_name,
                      attempts=3, run_as_root=True, check_exit_code=True),
        ])
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_detach_volume(self, mock_execute):
        self.encryptor.detach_volume()

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'luksClose', self.dev_name,
                      attempts=3, run_as_root=True, check_exit_code=True),
        ])
        self.assertEqual(1, mock_execute.call_count)
