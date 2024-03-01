# Copyright 2019 Aptira Pty Ltd
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

from unittest import mock

import ddt

import nova.privsep.qemu
from nova import test
from nova.tests import fixtures


@ddt.ddt
class QemuTestCase(test.NoDBTestCase):
    """Test qemu related utility methods."""

    def setUp(self):
        super(QemuTestCase, self).setUp()
        self.useFixture(fixtures.PrivsepFixture())

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('nova.privsep.utils.supports_direct_io')
    def _test_convert_image(self, meth, mock_supports_direct_io, mock_execute):
        mock_supports_direct_io.return_value = True
        meth('/fake/source', '/fake/destination', 'informat', 'outformat',
             '/fake/instances/path', compress=True)
        mock_execute.assert_called_with(
            'qemu-img', 'convert', '-t', 'none', '-O', 'outformat',
            '-f', 'informat', '-c', '/fake/source', '/fake/destination')

        mock_supports_direct_io.reset_mock()
        mock_execute.reset_mock()

        mock_supports_direct_io.return_value = False
        meth('/fake/source', '/fake/destination', 'informat', 'outformat',
             '/fake/instances/path', compress=True)
        mock_execute.assert_called_with(
            'qemu-img', 'convert', '-t', 'writeback', '-O', 'outformat',
            '-f', 'informat', '-c', '/fake/source', '/fake/destination')

    def test_convert_image(self):
        self._test_convert_image(nova.privsep.qemu.convert_image)

    def test_convert_image_unprivileged(self):
        self._test_convert_image(nova.privsep.qemu.unprivileged_convert_image)

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch('nova.privsep.utils.supports_direct_io',
                new=mock.Mock(return_value=True))
    @ddt.data(
        ('qcow2', 'qcow2'), ('qcow2', 'raw'),
        ('luks', 'raw'), ('luks', 'qcow2'))
    @ddt.unpack
    def test_convert_image_encrypted_source_to_unencrypted_dest(
            self, in_format, out_format, mock_tempfile, mock_execute):
        # Simulate an encrypted source image conversion to an unencrypted
        # destination image.
        mock_file = mock.Mock()
        mock_file.name = '/tmp/filename'
        mock_tempfile.return_value.__enter__.return_value = mock_file
        src_encryption = {'format': 'luks', 'secret': '12345'}

        nova.privsep.qemu.convert_image(
            '/fake/source', '/fake/dest', in_format, out_format,
            '/fake/instances/path', compress=True,
            src_encryption=src_encryption)

        mock_file.write.assert_called_once_with('12345')
        mock_file.flush.assert_called_once()
        prefix = 'encrypt.' if in_format == 'qcow2' else ''
        mock_execute.assert_called_once_with(
            'qemu-img', 'convert', '-t', 'none', '-O', out_format, '-c',
            '--object', 'secret,id=sec0,file=/tmp/filename', '--image-opts',
            f'driver={in_format},file.driver=file,file.filename=/fake/source,'
            f'{prefix}key-secret=sec0', '/fake/dest')

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch('nova.privsep.utils.supports_direct_io',
                new=mock.Mock(return_value=True))
    @ddt.data(
        ('qcow2', 'qcow2'), ('qcow2', 'raw'),
        ('raw', 'luks'), ('raw', 'qcow2'))
    @ddt.unpack
    def test_convert_image_unencrypted_source_to_encrypted_dest(
            self, in_format, out_format, mock_tempfile, mock_execute):
        # Simulate an unencrypted source image conversion to an encrypted
        # destination image.
        mock_file = mock.Mock()
        mock_file.name = '/tmp/filename'
        mock_tempfile.return_value.__enter__.return_value = mock_file
        encryption = {'format': 'luks', 'secret': '12345'}

        nova.privsep.qemu.convert_image(
            '/fake/source', '/fake/dest', in_format, out_format,
            '/fake/instances/path', compress=True, dest_encryption=encryption)

        mock_file.write.assert_called_once_with('12345')
        mock_file.flush.assert_called_once()

        prefix = 'encrypt.' if out_format == 'qcow2' else ''
        expected_args = [
            'qemu-img', 'convert', '-t', 'none', '-O', out_format,
            '-f', in_format, '-c',
            '--object', 'secret,id=sec1,file=/tmp/filename',
            '-o', f'{prefix}key-secret=sec1',
        ]
        if prefix:
            expected_args += ['-o', f'{prefix}format=luks']

        expected_args += [
            '-o', f'{prefix}cipher-alg=aes-256',
            '-o', f'{prefix}cipher-mode=xts',
            '-o', f'{prefix}hash-alg=sha256',
            '-o', f'{prefix}iter-time=2000',
            '-o', f'{prefix}ivgen-alg=plain64',
            '-o', f'{prefix}ivgen-hash-alg=sha256',
            '/fake/source', '/fake/dest',
        ]
        mock_execute.assert_called_once_with(*expected_args)

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch('nova.privsep.utils.supports_direct_io',
                new=mock.Mock(return_value=True))
    @ddt.data(
        ('qcow2', 'qcow2'), ('qcow2', 'luks'),
        ('luks', 'luks'), ('luks', 'qcow2'))
    @ddt.unpack
    def test_convert_image_encrypted_source_and_dest(
            self, in_format, out_format, mock_tempfile, mock_execute):
        # Simulate an encrypted source image conversion to an encrypted
        # destination image.
        mock_file1 = mock.Mock()
        mock_file1.name = '/tmp/filename1'
        src_encryption = {'format': 'luks', 'secret': '12345'}
        mock_file2 = mock.Mock()
        mock_file2.name = '/tmp/filename2'
        mock_tempfile.return_value.__enter__.side_effect = [
            mock_file1, mock_file2]
        dest_encryption = {'format': 'luks', 'secret': '67890'}

        nova.privsep.qemu.convert_image(
            '/fake/source', '/fake/dest', in_format, out_format,
            '/fake/instances/path', compress=True,
            src_encryption=src_encryption,
            dest_encryption=dest_encryption)

        mock_file1.write.assert_called_once_with('12345')
        mock_file1.flush.assert_called_once()
        mock_file2.write.assert_called_once_with('67890')
        mock_file2.flush.assert_called_once()

        in_prefix = 'encrypt.' if in_format == 'qcow2' else ''
        out_prefix = 'encrypt.' if out_format == 'qcow2' else ''
        expected_args = [
            'qemu-img', 'convert', '-t', 'none', '-O', out_format, '-c',
            '--object', 'secret,id=sec0,file=/tmp/filename1', '--image-opts',
            f'driver={in_format},file.driver=file,file.filename=/fake/source,'
            f'{in_prefix}key-secret=sec0',
            '--object', 'secret,id=sec1,file=/tmp/filename2',
            '-o', f'{out_prefix}key-secret=sec1',
        ]
        if out_prefix:
            expected_args += ['-o', f'{out_prefix}format=luks']
        expected_args += [
            '-o', f'{out_prefix}cipher-alg=aes-256',
            '-o', f'{out_prefix}cipher-mode=xts',
            '-o', f'{out_prefix}hash-alg=sha256',
            '-o', f'{out_prefix}iter-time=2000',
            '-o', f'{out_prefix}ivgen-alg=plain64',
            '-o', f'{out_prefix}ivgen-hash-alg=sha256', '/fake/dest',
        ]
        mock_execute.assert_called_once_with(*expected_args)

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('os.path.isdir')
    def _test_qemu_img_info(self, method, mock_isdir, mock_execute):
        mock_isdir.return_value = False
        mock_execute.return_value = (mock.sentinel.out, None)
        expected_cmd = (
            'env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info',
            mock.sentinel.path, '--force-share', '--output=json', '-f',
            mock.sentinel.format)

        # Assert that the output from processutils is returned
        self.assertEqual(
            mock.sentinel.out,
            method(mock.sentinel.path, format=mock.sentinel.format))
        # Assert that the expected command is used
        mock_execute.assert_called_once_with(
            *expected_cmd, prlimit=nova.privsep.qemu.QEMU_IMG_LIMITS)

    def test_privileged_qemu_img_info(self):
        self._test_qemu_img_info(nova.privsep.qemu.privileged_qemu_img_info)

    def test_unprivileged_qemu_img_info(self):
        self._test_qemu_img_info(nova.privsep.qemu.unprivileged_qemu_img_info)
