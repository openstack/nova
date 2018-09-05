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
Test suite for images.
"""

import os
import tarfile

import mock
from oslo_utils.fixture import uuidsentinel
from oslo_utils import units
from oslo_vmware import rw_handles

from nova import exception
from nova import objects
from nova import test
import nova.tests.unit.image.fake
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import images
from nova.virt.vmwareapi import vm_util


class VMwareImagesTestCase(test.NoDBTestCase):
    """Unit tests for Vmware API connection calls."""

    def test_fetch_image(self):
        """Test fetching images."""

        dc_name = 'fake-dc'
        file_path = 'fake_file'
        ds_name = 'ds1'
        host = mock.MagicMock()
        port = 7443
        context = mock.MagicMock()

        image_data = {
                'id': nova.tests.unit.image.fake.get_valid_image_id(),
                'disk_format': 'vmdk',
                'size': 512,
            }
        read_file_handle = mock.MagicMock()
        write_file_handle = mock.MagicMock()
        read_iter = mock.MagicMock()
        instance = objects.Instance(id=1,
                                    uuid=uuidsentinel.foo,
                                    image_ref=image_data['id'])

        def fake_read_handle(read_iter):
            return read_file_handle

        def fake_write_handle(host, port, dc_name, ds_name, cookies,
                              file_path, file_size):
            return write_file_handle

        with test.nested(
             mock.patch.object(rw_handles, 'ImageReadHandle',
                               side_effect=fake_read_handle),
             mock.patch.object(rw_handles, 'FileWriteHandle',
                               side_effect=fake_write_handle),
             mock.patch.object(images, 'image_transfer'),
             mock.patch.object(images.IMAGE_API, 'get',
                return_value=image_data),
             mock.patch.object(images.IMAGE_API, 'download',
                     return_value=read_iter),
        ) as (glance_read, http_write, image_transfer, image_show,
                image_download):
            images.fetch_image(context, instance,
                               host, port, dc_name,
                               ds_name, file_path)

        glance_read.assert_called_once_with(read_iter)
        http_write.assert_called_once_with(host, port, dc_name, ds_name, None,
                                           file_path, image_data['size'])
        image_transfer.assert_called_once_with(read_file_handle,
                                               write_file_handle)
        image_download.assert_called_once_with(context, instance['image_ref'])
        image_show.assert_called_once_with(context, instance['image_ref'])

    def _setup_mock_get_remote_image_service(self,
                                             mock_get_remote_image_service,
                                             metadata):
        mock_image_service = mock.MagicMock()
        mock_image_service.show.return_value = metadata
        mock_get_remote_image_service.return_value = [mock_image_service, 'i']

    def test_get_vmdk_name_from_ovf(self):
        ovf_path = os.path.join(os.path.dirname(__file__), 'ovf.xml')
        with open(ovf_path) as f:
            ovf_descriptor = f.read()
            vmdk_name = images.get_vmdk_name_from_ovf(ovf_descriptor)
            self.assertEqual("Damn_Small_Linux-disk1.vmdk", vmdk_name)

    @mock.patch('oslo_vmware.rw_handles.ImageReadHandle')
    @mock.patch('oslo_vmware.rw_handles.VmdkWriteHandle')
    @mock.patch.object(tarfile, 'open')
    def test_fetch_image_ova(self, mock_tar_open, mock_write_class,
                             mock_read_class):
        session = mock.MagicMock()
        ovf_descriptor = None
        ovf_path = os.path.join(os.path.dirname(__file__), 'ovf.xml')
        with open(ovf_path) as f:
            ovf_descriptor = f.read()

        with test.nested(
             mock.patch.object(images.IMAGE_API, 'get'),
             mock.patch.object(images.IMAGE_API, 'download'),
             mock.patch.object(images, 'image_transfer'),
             mock.patch.object(images, '_build_shadow_vm_config_spec'),
             mock.patch.object(session, '_call_method'),
             mock.patch.object(vm_util, 'get_vmdk_info')
        ) as (mock_image_api_get,
              mock_image_api_download,
              mock_image_transfer,
              mock_build_shadow_vm_config_spec,
              mock_call_method,
              mock_get_vmdk_info):
            image_data = {'id': 'fake-id',
                          'disk_format': 'vmdk',
                          'size': 512}
            instance = mock.MagicMock()
            instance.image_ref = image_data['id']
            mock_image_api_get.return_value = image_data

            vm_folder_ref = mock.MagicMock()
            res_pool_ref = mock.MagicMock()
            context = mock.MagicMock()

            mock_read_handle = mock.MagicMock()
            mock_read_class.return_value = mock_read_handle
            mock_write_handle = mock.MagicMock()
            mock_write_class.return_value = mock_write_handle
            mock_write_handle.get_imported_vm.return_value = \
                mock.sentinel.vm_ref

            mock_ovf = mock.MagicMock()
            mock_ovf.name = 'dsl.ovf'
            mock_vmdk = mock.MagicMock()
            mock_vmdk.name = "Damn_Small_Linux-disk1.vmdk"

            def fake_extract(name):
                if name == mock_ovf:
                    m = mock.MagicMock()
                    m.read.return_value = ovf_descriptor
                    return m
                elif name == mock_vmdk:
                    return mock_read_handle

            mock_tar = mock.MagicMock()
            mock_tar.__iter__ = mock.Mock(return_value = iter([mock_ovf,
                                                               mock_vmdk]))
            mock_tar.extractfile = fake_extract
            mock_tar_open.return_value.__enter__.return_value = mock_tar

            images.fetch_image_ova(
                    context, instance, session, 'fake-vm', 'fake-datastore',
                    vm_folder_ref, res_pool_ref)

            mock_tar_open.assert_called_once_with(mode='r|',
                                                  fileobj=mock_read_handle)
            mock_image_transfer.assert_called_once_with(mock_read_handle,
                                                        mock_write_handle)
            mock_get_vmdk_info.assert_called_once_with(
                    session, mock.sentinel.vm_ref, 'fake-vm')
            mock_call_method.assert_called_once_with(
                    session.vim, "UnregisterVM", mock.sentinel.vm_ref)

    @mock.patch('oslo_vmware.rw_handles.ImageReadHandle')
    @mock.patch('oslo_vmware.rw_handles.VmdkWriteHandle')
    def test_fetch_image_stream_optimized(self,
                                          mock_write_class,
                                          mock_read_class):
        """Test fetching streamOptimized disk image."""
        session = mock.MagicMock()

        with test.nested(
             mock.patch.object(images.IMAGE_API, 'get'),
             mock.patch.object(images.IMAGE_API, 'download'),
             mock.patch.object(images, 'image_transfer'),
             mock.patch.object(images, '_build_shadow_vm_config_spec'),
             mock.patch.object(session, '_call_method'),
             mock.patch.object(vm_util, 'get_vmdk_info')
        ) as (mock_image_api_get,
              mock_image_api_download,
              mock_image_transfer,
              mock_build_shadow_vm_config_spec,
              mock_call_method,
              mock_get_vmdk_info):
            image_data = {'id': 'fake-id',
                          'disk_format': 'vmdk',
                          'size': 512}
            instance = mock.MagicMock()
            instance.image_ref = image_data['id']
            mock_image_api_get.return_value = image_data

            vm_folder_ref = mock.MagicMock()
            res_pool_ref = mock.MagicMock()
            context = mock.MagicMock()

            mock_read_handle = mock.MagicMock()
            mock_read_class.return_value = mock_read_handle
            mock_write_handle = mock.MagicMock()
            mock_write_class.return_value = mock_write_handle
            mock_write_handle.get_imported_vm.return_value = \
                mock.sentinel.vm_ref

            images.fetch_image_stream_optimized(
                    context, instance, session, 'fake-vm', 'fake-datastore',
                    vm_folder_ref, res_pool_ref)

            mock_image_transfer.assert_called_once_with(mock_read_handle,
                                                        mock_write_handle)
            mock_call_method.assert_called_once_with(
                    session.vim, "UnregisterVM", mock.sentinel.vm_ref)
            mock_get_vmdk_info.assert_called_once_with(
                    session, mock.sentinel.vm_ref, 'fake-vm')

    def test_from_image_with_image_ref(self):
        raw_disk_size_in_gb = 83
        raw_disk_size_in_bytes = raw_disk_size_in_gb * units.Gi
        image_id = nova.tests.unit.image.fake.get_valid_image_id()
        mdata = {'size': raw_disk_size_in_bytes,
                 'disk_format': 'vmdk',
                 'properties': {
                     "vmware_ostype": constants.DEFAULT_OS_TYPE,
                     "vmware_adaptertype": constants.DEFAULT_ADAPTER_TYPE,
                     "vmware_disktype": constants.DEFAULT_DISK_TYPE,
                     "hw_vif_model": constants.DEFAULT_VIF_MODEL,
                     "vmware_linked_clone": True}}
        mdata = objects.ImageMeta.from_dict(mdata)
        with mock.patch.object(images, 'get_vsphere_location',
                               return_value=None):
            img_props = images.VMwareImage.from_image(None, image_id, mdata)

        image_size_in_kb = raw_disk_size_in_bytes / units.Ki

        # assert that defaults are set and no value returned is left empty
        self.assertEqual(constants.DEFAULT_OS_TYPE, img_props.os_type)
        self.assertEqual(constants.DEFAULT_ADAPTER_TYPE,
                         img_props.adapter_type)
        self.assertEqual(constants.DEFAULT_DISK_TYPE, img_props.disk_type)
        self.assertEqual(constants.DEFAULT_VIF_MODEL, img_props.vif_model)
        self.assertTrue(img_props.linked_clone)
        self.assertEqual(image_size_in_kb, img_props.file_size_in_kb)

    def _image_build(self, image_lc_setting, global_lc_setting,
                     disk_format=constants.DEFAULT_DISK_FORMAT,
                     os_type=constants.DEFAULT_OS_TYPE,
                     adapter_type=constants.DEFAULT_ADAPTER_TYPE,
                     disk_type=constants.DEFAULT_DISK_TYPE,
                     vif_model=constants.DEFAULT_VIF_MODEL,
                     vsphere_location=None):
        self.flags(use_linked_clone=global_lc_setting, group='vmware')
        raw_disk_size_in_gb = 93
        raw_disk_size_in_btyes = raw_disk_size_in_gb * units.Gi

        image_id = nova.tests.unit.image.fake.get_valid_image_id()
        mdata = {'size': raw_disk_size_in_btyes,
                 'disk_format': disk_format,
                 'properties': {
                     "vmware_ostype": os_type,
                     "vmware_adaptertype": adapter_type,
                     "vmware_disktype": disk_type,
                     "hw_vif_model": vif_model}}

        if image_lc_setting is not None:
            mdata['properties']["vmware_linked_clone"] = image_lc_setting

        context = mock.Mock()
        mdata = objects.ImageMeta.from_dict(mdata)
        with mock.patch.object(
                images, 'get_vsphere_location', return_value=vsphere_location):
            return images.VMwareImage.from_image(context, image_id, mdata)

    def test_use_linked_clone_override_nf(self):
        image_props = self._image_build(None, False)
        self.assertFalse(image_props.linked_clone,
                         "No overrides present but still overridden!")

    def test_use_linked_clone_override_nt(self):
        image_props = self._image_build(None, True)
        self.assertTrue(image_props.linked_clone,
                        "No overrides present but still overridden!")

    def test_use_linked_clone_override_ny(self):
        image_props = self._image_build(None, "yes")
        self.assertTrue(image_props.linked_clone,
                        "No overrides present but still overridden!")

    def test_use_linked_clone_override_ft(self):
        image_props = self._image_build(False, True)
        self.assertFalse(image_props.linked_clone,
                         "image level metadata failed to override global")

    def test_use_linked_clone_override_string_nt(self):
        image_props = self._image_build("no", True)
        self.assertFalse(image_props.linked_clone,
                         "image level metadata failed to override global")

    def test_use_linked_clone_override_string_yf(self):
        image_props = self._image_build("yes", False)
        self.assertTrue(image_props.linked_clone,
                        "image level metadata failed to override global")

    def test_use_disk_format_iso(self):
        image = self._image_build(None, True, disk_format='iso')
        self.assertEqual('iso', image.file_type)
        self.assertTrue(image.is_iso)

    def test_use_bad_disk_format(self):
        self.assertRaises(exception.InvalidDiskFormat,
                          self._image_build,
                          None,
                          True,
                          disk_format='bad_disk_format')

    def test_image_no_defaults(self):
        image = self._image_build(False, False,
                                  disk_format='iso',
                                  os_type='otherGuest',
                                  adapter_type='lsiLogic',
                                  disk_type='preallocated',
                                  vif_model='e1000e')
        self.assertEqual('iso', image.file_type)
        self.assertEqual('otherGuest', image.os_type)
        self.assertEqual('lsiLogic', image.adapter_type)
        self.assertEqual('preallocated', image.disk_type)
        self.assertEqual('e1000e', image.vif_model)
        self.assertFalse(image.linked_clone)

    def test_image_defaults(self):
        image = images.VMwareImage(image_id='fake-image-id')

        # N.B. We intentially don't use the defined constants here. Amongst
        # other potential failures, we're interested in changes to their
        # values, which would not otherwise be picked up.
        self.assertEqual('otherGuest', image.os_type)
        self.assertEqual('lsiLogic', image.adapter_type)
        self.assertEqual('preallocated', image.disk_type)
        self.assertEqual('e1000', image.vif_model)

    def test_use_vsphere_location(self):
        image = self._image_build(None, True, vsphere_location='vsphere://ok')
        self.assertEqual('vsphere://ok', image.vsphere_location)

    def test_get_vsphere_location(self):
        expected = 'vsphere://ok'
        metadata = {'locations': [{}, {'url': 'http://ko'}, {'url': expected}]}
        with mock.patch.object(images.IMAGE_API, 'get', return_value=metadata):
            context = mock.Mock()
            observed = images.get_vsphere_location(context, 'image_id')
            self.assertEqual(expected, observed)

    def test_get_no_vsphere_location(self):
        metadata = {'locations': [{}, {'url': 'http://ko'}]}
        with mock.patch.object(images.IMAGE_API, 'get', return_value=metadata):
            context = mock.Mock()
            observed = images.get_vsphere_location(context, 'image_id')
            self.assertIsNone(observed)

    def test_get_vsphere_location_no_image(self):
        context = mock.Mock()
        observed = images.get_vsphere_location(context, None)
        self.assertIsNone(observed)
