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

import mock

from nova.keymgr import key
from nova.tests.unit.volume.encryptors import test_base
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

        self.dev_path = self.connection_info['data']['device_path']
        self.dev_name = self.dev_path.split('/')[-1]

        self.symlink_path = self.dev_path

    @mock.patch('nova.utils.execute')
    def test__open_volume(self, mock_execute):
        self.encryptor._open_volume("passphrase")

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'create', '--key-file=-', self.dev_name,
                      self.dev_path, process_input='passphrase',
                      run_as_root=True, check_exit_code=True),
        ])
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_attach_volume(self, mock_execute):
        self.encryptor._get_key = mock.MagicMock()
        self.encryptor._get_key.return_value = fake__get_key(None)

        self.encryptor.attach_volume(None)

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'create', '--key-file=-', self.dev_name,
                      self.dev_path, process_input='0' * 32,
                      run_as_root=True, check_exit_code=True),
            mock.call('ln', '--symbolic', '--force',
                      '/dev/mapper/%s' % self.dev_name, self.symlink_path,
                      run_as_root=True, check_exit_code=True),
        ])
        self.assertEqual(2, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test__close_volume(self, mock_execute):
        self.encryptor.detach_volume()

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'remove', self.dev_name,
                      run_as_root=True, check_exit_code=True),
        ])
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_detach_volume(self, mock_execute):
        self.encryptor.detach_volume()

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'remove', self.dev_name,
                      run_as_root=True, check_exit_code=True),
        ])
        self.assertEqual(1, mock_execute.call_count)
