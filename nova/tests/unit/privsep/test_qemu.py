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

import mock

import nova.privsep.qemu
from nova import test
from nova.tests import fixtures


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
