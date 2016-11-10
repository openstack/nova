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


import binascii
import copy

from castellan.common.objects import symmetric_key as key
import mock
from oslo_concurrency import processutils
import six
import uuid

from nova import exception
from nova.tests.unit.volume.encryptors import test_base
from nova.volume.encryptors import cryptsetup


def fake__get_key(context, passphrase):
    raw = bytes(binascii.unhexlify(passphrase))
    symmetric_key = key.SymmetricKey('AES', len(raw) * 8, raw)
    return symmetric_key


class CryptsetupEncryptorTestCase(test_base.VolumeEncryptorTestCase):
    @mock.patch('os.path.exists', return_value=False)
    def _create(self, connection_info, mock_exists):
        return cryptsetup.CryptsetupEncryptor(connection_info)

    def setUp(self):
        super(CryptsetupEncryptorTestCase, self).setUp()

        self.dev_path = self.connection_info['data']['device_path']
        self.dev_name = 'crypt-%s' % self.dev_path.split('/')[-1]

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
        fake_key = uuid.uuid4().hex
        self.encryptor._get_key = mock.MagicMock()
        self.encryptor._get_key.return_value = fake__get_key(None, fake_key)

        self.encryptor.attach_volume(None)

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'create', '--key-file=-', self.dev_name,
                      self.dev_path, process_input=fake_key,
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
                      run_as_root=True, check_exit_code=[0, 4]),
        ])
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_detach_volume(self, mock_execute):
        self.encryptor.detach_volume()

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'remove', self.dev_name,
                      run_as_root=True, check_exit_code=[0, 4]),
        ])
        self.assertEqual(1, mock_execute.call_count)

    def test_init_volume_encryption_not_supported(self):
        # Tests that creating a CryptsetupEncryptor fails if there is no
        # device_path key.
        type = 'unencryptable'
        data = dict(volume_id='a194699b-aa07-4433-a945-a5d23802043e')
        connection_info = dict(driver_volume_type=type, data=data)
        exc = self.assertRaises(exception.VolumeEncryptionNotSupported,
                                cryptsetup.CryptsetupEncryptor,
                                connection_info)
        self.assertIn(type, six.text_type(exc))

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_init_volume_encryption_with_old_name(self, mock_execute,
                                                  mock_exists):
        # If an old name crypt device exists, dev_path should be the old name.
        old_dev_name = self.dev_path.split('/')[-1]
        encryptor = cryptsetup.CryptsetupEncryptor(self.connection_info)
        self.assertFalse(encryptor.dev_name.startswith('crypt-'))
        self.assertEqual(old_dev_name, encryptor.dev_name)
        self.assertEqual(self.dev_path, encryptor.dev_path)
        self.assertEqual(self.symlink_path, encryptor.symlink_path)
        mock_exists.assert_called_once_with('/dev/mapper/%s' % old_dev_name)
        mock_execute.assert_called_once_with(
            'cryptsetup', 'status', old_dev_name, run_as_root=True)

    @mock.patch('os.path.exists', side_effect=[False, True])
    @mock.patch('nova.utils.execute')
    def test_init_volume_encryption_with_wwn(self, mock_execute, mock_exists):
        # If an wwn name crypt device exists, dev_path should be based on wwn.
        old_dev_name = self.dev_path.split('/')[-1]
        wwn = 'fake_wwn'
        connection_info = copy.deepcopy(self.connection_info)
        connection_info['data']['multipath_id'] = wwn
        encryptor = cryptsetup.CryptsetupEncryptor(connection_info)
        self.assertFalse(encryptor.dev_name.startswith('crypt-'))
        self.assertEqual(wwn, encryptor.dev_name)
        self.assertEqual(self.dev_path, encryptor.dev_path)
        self.assertEqual(self.symlink_path, encryptor.symlink_path)
        mock_exists.assert_has_calls([
            mock.call('/dev/mapper/%s' % old_dev_name),
            mock.call('/dev/mapper/%s' % wwn)])
        mock_execute.assert_called_once_with(
            'cryptsetup', 'status', wwn, run_as_root=True)

    @mock.patch('nova.utils.execute')
    def test_attach_volume_unmangle_passphrase(self, mock_execute):
        fake_key = '0725230b'
        fake_key_mangled = '72523b'
        self.encryptor._get_key = mock.MagicMock()
        self.encryptor._get_key.return_value = fake__get_key(None, fake_key)

        mock_execute.side_effect = [
            processutils.ProcessExecutionError(exit_code=2),  # luksOpen
            mock.DEFAULT,
            mock.DEFAULT,
        ]

        self.encryptor.attach_volume(None)

        mock_execute.assert_has_calls([
            mock.call('cryptsetup', 'create', '--key-file=-', self.dev_name,
                      self.dev_path, process_input=fake_key,
                      run_as_root=True, check_exit_code=True),
            mock.call('cryptsetup', 'create', '--key-file=-', self.dev_name,
                      self.dev_path, process_input=fake_key_mangled,
                      run_as_root=True, check_exit_code=True),
            mock.call('ln', '--symbolic', '--force',
                      '/dev/mapper/%s' % self.dev_name, self.symlink_path,
                      run_as_root=True, check_exit_code=True),
        ])
        self.assertEqual(3, mock_execute.call_count)
