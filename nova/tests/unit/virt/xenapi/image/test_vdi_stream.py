# Copyright 2017 Citrix System
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

from os_xenapi.client import exception as xenapi_except
from os_xenapi.client import image

from nova import context
from nova import exception
from nova.image.api import API as image_api
from nova.tests.unit.virt.xenapi import stubs
from nova.virt.xenapi.image import utils
from nova.virt.xenapi.image import vdi_stream
from nova.virt.xenapi import vm_utils


class TestVdiStreamStore(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(TestVdiStreamStore, self).setUp()
        self.store = vdi_stream.VdiStreamStore()

        self.flags(connection_url='test_url',
                   image_compression_level=5,
                   group='xenserver')

        self.session = mock.Mock()
        self.context = context.RequestContext(
                'user', 'project', auth_token='foobar')
        self.instance = {'uuid': 'e6ad57c9-115e-4b7d-a872-63cea0ac3cf2',
                         'system_metadata': [],
                         'auto_disk_config': True,
                         'os_type': 'default',
                         'xenapi_use_agent': 'true'}

    @mock.patch.object(image_api, 'download',
                       return_value='fake_data')
    @mock.patch.object(utils, 'IterableToFileAdapter',
                       return_value='fake_stream')
    @mock.patch.object(vm_utils, 'safe_find_sr',
                       return_value='fake_sr_ref')
    @mock.patch.object(image, 'stream_to_vdis')
    def test_download_image(self, stream_to, find_sr, to_file, download):
        self.store.download_image(self.context, self.session,
                                  self.instance, 'fake_image_uuid')

        download.assert_called_once_with(self.context, 'fake_image_uuid')
        to_file.assert_called_once_with('fake_data')
        find_sr.assert_called_once_with(self.session)
        stream_to.assert_called_once_with(self.context, self.session,
                                          self.instance, 'test_url',
                                          'fake_sr_ref', 'fake_stream')

    @mock.patch.object(image_api, 'download',
                       return_value='fake_data')
    @mock.patch.object(utils, 'IterableToFileAdapter',
                       return_value='fake_stream')
    @mock.patch.object(vm_utils, 'safe_find_sr',
                       return_value='fake_sr_ref')
    @mock.patch.object(image, 'stream_to_vdis',
                       side_effect=xenapi_except.OsXenApiException)
    def test_download_image_exception(self, stream_to, find_sr, to_file,
                                      download):
        self.assertRaises(exception.CouldNotFetchImage,
                          self.store.download_image,
                          self.context, self.session,
                          self.instance, 'fake_image_uuid')

    @mock.patch.object(vdi_stream.VdiStreamStore, '_get_metadata',
                       return_value='fake_meta_data')
    @mock.patch.object(image, 'stream_from_vdis',
                       return_value='fake_data')
    @mock.patch.object(utils, 'IterableToFileAdapter',
                       return_value='fake_stream')
    @mock.patch.object(image_api, 'update')
    def test_upload_image(self, update, to_file, to_stream, get):
        fake_vdi_uuids = ['fake-vdi-uuid']
        self.store.upload_image(self.context, self.session,
                                         self.instance, 'fake_image_uuid',
                                         fake_vdi_uuids)

        get.assert_called_once_with(self.context, self.instance,
                                    'fake_image_uuid')
        to_stream.assert_called_once_with(self.context, self.session,
                                          self.instance, 'test_url',
                                          fake_vdi_uuids, compresslevel=5)
        to_file.assert_called_once_with('fake_data')
        update.assert_called_once_with(self.context, 'fake_image_uuid',
                                       'fake_meta_data', data='fake_stream')

    @mock.patch.object(vdi_stream.VdiStreamStore, '_get_metadata')
    @mock.patch.object(image, 'stream_from_vdis',
                       side_effect=xenapi_except.OsXenApiException)
    @mock.patch.object(utils, 'IterableToFileAdapter',
                       return_value='fake_stream')
    @mock.patch.object(image_api, 'update')
    def test_upload_image_exception(self, update, to_file, to_stream, get):
        fake_vdi_uuids = ['fake-vdi-uuid']
        self.assertRaises(exception.CouldNotUploadImage,
                          self.store.upload_image,
                          self.context, self.session,
                          self.instance, 'fake_image_uuid',
                          fake_vdi_uuids)

    @mock.patch.object(image_api, 'get',
                       return_value={})
    def test_get_metadata(self, image_get):
        expect_metadata = {'disk_format': 'vhd',
                           'container_format': 'ovf',
                           'auto_disk_config': 'True',
                           'os_type': 'default',
                           'size': 0}

        result = self.store._get_metadata(self.context, self.instance,
                                          'fake_image_uuid')

        self.assertEqual(result, expect_metadata)

    @mock.patch.object(image_api, 'get',
                       return_value={})
    def test_get_metadata_disabled(self, image_get):
        # Verify the metadata contains auto_disk_config=disabled, when
        # image_auto_disk_config is ""Disabled".
        self.instance['system_metadata'] = [
            {"key": "image_auto_disk_config",
             "value": "Disabled"}]

        expect_metadata = {'disk_format': 'vhd',
                           'container_format': 'ovf',
                           'auto_disk_config': 'disabled',
                           'os_type': 'default',
                           'size': 0}

        result = self.store._get_metadata(self.context, self.instance,
                                          'fake_image_uuid')

        self.assertEqual(result, expect_metadata)
