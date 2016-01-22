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
import six.moves.urllib.parse as urlparse

from nova import exception
from nova.image.download import file as tm_file
from nova import test


class TestFileTransferModule(test.NoDBTestCase):

    @mock.patch('nova.virt.libvirt.utils.copy_image')
    def test_filesystem_success(self, copy_mock):
        self.flags(allowed_direct_url_schemes=['file'], group='glance')
        self.flags(group='image_file_url', filesystems=['gluster'])

        mountpoint = '/gluster'
        url = 'file:///gluster/my/image/path'
        url_parts = urlparse.urlparse(url)
        fs_id = 'someid'
        loc_meta = {
            'id': fs_id,
            'mountpoint': mountpoint
        }
        dst_file = mock.MagicMock()

        tm = tm_file.FileTransfer()

        # NOTE(Jbresnah) The following options must be added after the module
        # has added the specific groups.
        self.flags(group='image_file_url:gluster', id=fs_id)
        self.flags(group='image_file_url:gluster', mountpoint=mountpoint)

        tm.download(mock.sentinel.ctx, url_parts, dst_file, loc_meta)
        copy_mock.assert_called_once_with('/gluster/my/image/path', dst_file)

    @mock.patch('nova.virt.libvirt.utils.copy_image')
    def test_filesystem_mismatched_mountpoint(self, copy_mock):
        self.flags(allowed_direct_url_schemes=['file'], group='glance')
        self.flags(group='image_file_url', filesystems=['gluster'])

        mountpoint = '/gluster'
        # Should include the mountpoint before my/image/path
        url = 'file:///my/image/path'
        url_parts = urlparse.urlparse(url)
        fs_id = 'someid'
        loc_meta = {
            'id': fs_id,
            'mountpoint': mountpoint
        }
        dst_file = mock.MagicMock()

        tm = tm_file.FileTransfer()

        self.flags(group='image_file_url:gluster', id=fs_id)
        self.flags(group='image_file_url:gluster', mountpoint=mountpoint)

        self.assertRaises(exception.ImageDownloadModuleMetaDataError,
                          tm.download, mock.sentinel.ctx, url_parts,
                          dst_file, loc_meta)
        self.assertFalse(copy_mock.called)

    @mock.patch('nova.virt.libvirt.utils.copy_image')
    def test_filesystem_mismatched_filesystem(self, copy_mock):
        self.flags(allowed_direct_url_schemes=['file'], group='glance')
        self.flags(group='image_file_url', filesystems=['gluster'])

        mountpoint = '/gluster'
        # Should include the mountpoint before my/image/path
        url = 'file:///my/image/path'
        url_parts = urlparse.urlparse(url)
        fs_id = 'someid'
        loc_meta = {
            'id': 'funky',
            'mountpoint': mountpoint
        }
        dst_file = mock.MagicMock()

        tm = tm_file.FileTransfer()

        self.flags(group='image_file_url:gluster', id=fs_id)
        self.flags(group='image_file_url:gluster', mountpoint=mountpoint)

        self.assertRaises(exception.ImageDownloadModuleError,
                          tm.download, mock.sentinel.ctx, url_parts,
                          dst_file, loc_meta)
        self.assertFalse(copy_mock.called)
