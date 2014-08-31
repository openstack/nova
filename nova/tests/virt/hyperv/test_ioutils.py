# Copyright 2014 Cloudbase Solutions Srl
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
#    under the License.import mock

import mock

from nova import test
from nova.virt.hyperv import ioutils


class IOThreadTestCase(test.NoDBTestCase):
    _FAKE_SRC = r'fake_source_file'
    _FAKE_DEST = r'fake_dest_file'
    _FAKE_MAX_BYTES = 1

    def setUp(self):
        self._iothread = ioutils.IOThread(
            self._FAKE_SRC, self._FAKE_DEST, self._FAKE_MAX_BYTES)
        super(IOThreadTestCase, self).setUp()

    @mock.patch('__builtin__.open')
    @mock.patch('os.rename')
    @mock.patch('os.path.exists')
    @mock.patch('os.remove')
    def test_copy(self, fake_remove, fake_exists, fake_rename, fake_open):
        fake_data = 'a'
        fake_src = mock.Mock()
        fake_dest = mock.Mock()

        fake_src.read.return_value = fake_data
        fake_dest.tell.return_value = 0
        fake_exists.return_value = True

        mock_context_manager = mock.MagicMock()
        fake_open.return_value = mock_context_manager
        mock_context_manager.__enter__.side_effect = [fake_src, fake_dest]
        self._iothread._stopped.isSet = mock.Mock(side_effect = [False, True])

        self._iothread._copy(self._FAKE_SRC, self._FAKE_DEST)

        fake_dest.write.assert_called_once_with(fake_data)
        fake_dest.close.assert_called_once()
        fake_rename.assert_called_once_with(
            self._iothread._dest, self._iothread._dest_archive)
        fake_remove.assert_called_once_with(
            self._iothread._dest_archive)
        self.assertEqual(3, fake_open.call_count)
