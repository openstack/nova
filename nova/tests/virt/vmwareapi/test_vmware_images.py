# Copyright (c) 2014 VMware, Inc.
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

"""
Test suite for vmware_images.
"""

import contextlib

import mock

from nova import test
import nova.tests.image.fake
from nova.virt.vmwareapi import read_write_util
from nova.virt.vmwareapi import vmware_images


class VMwareImagesTestCase(test.NoDBTestCase):
    """Unit tests for Vmware API connection calls."""

    def test_fetch_image(self):
        """Test fetching images."""

        dc_name = 'fake-dc'
        file_path = 'fake_file'
        ds_name = 'ds1'
        host = mock.MagicMock()
        context = mock.MagicMock()

        image_data = {
                'id': nova.tests.image.fake.get_valid_image_id(),
                'disk_format': 'vmdk',
                'size': 512,
            }
        read_file_handle = mock.MagicMock()
        write_file_handle = mock.MagicMock()
        read_iter = mock.MagicMock()
        instance = {}
        instance['image_ref'] = image_data['id']
        instance['uuid'] = 'fake-uuid'

        def fake_read_handle(read_iter):
            return read_file_handle

        def fake_write_handle(host, dc_name, ds_name, cookies,
                              file_path, file_size):
            return write_file_handle

        with contextlib.nested(
             mock.patch.object(read_write_util, 'GlanceFileRead',
                               side_effect=fake_read_handle),
             mock.patch.object(read_write_util, 'VMwareHTTPWriteFile',
                               side_effect=fake_write_handle),
             mock.patch.object(vmware_images, 'start_transfer'),
             mock.patch.object(vmware_images.IMAGE_API, 'get',
                return_value=image_data),
             mock.patch.object(vmware_images.IMAGE_API, 'download',
                     return_value=read_iter),
        ) as (glance_read, http_write, start_transfer, image_show,
                image_download):
            vmware_images.fetch_image(context, instance,
                                      host, dc_name,
                                      ds_name, file_path)

        glance_read.assert_called_once_with(read_iter)
        http_write.assert_called_once_with(host, dc_name, ds_name, None,
                                           file_path, image_data['size'])
        start_transfer.assert_called_once_with(
                context, read_file_handle,
                image_data['size'],
                write_file_handle=write_file_handle)
        image_download.assert_called_once_with(context, instance['image_ref'])
        image_show.assert_called_once_with(context, instance['image_ref'])
