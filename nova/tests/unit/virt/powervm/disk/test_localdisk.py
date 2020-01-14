# Copyright 2015, 2018 IBM Corp.
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

import fixtures
import mock

from nova import exception
from nova import test
from oslo_utils.fixture import uuidsentinel as uuids
from pypowervm import const as pvm_const
from pypowervm.tasks import storage as tsk_stg
from pypowervm.utils import transaction as pvm_tx
from pypowervm.wrappers import storage as pvm_stg
from pypowervm.wrappers import virtual_io_server as pvm_vios

from nova.virt.powervm.disk import driver as disk_dvr
from nova.virt.powervm.disk import localdisk


class TestLocalDisk(test.NoDBTestCase):
    """Unit Tests for the LocalDisk storage driver."""

    def setUp(self):
        super(TestLocalDisk, self).setUp()
        self.adpt = mock.Mock()

        # The mock VIOS needs to have scsi_mappings as a list.  Internals are
        # set by individual test cases as needed.
        smaps = [mock.Mock()]
        self.vio_wrap = mock.create_autospec(
            pvm_vios.VIOS, instance=True, scsi_mappings=smaps,
            uuid='vios-uuid')

        # Return the mgmt uuid.
        self.mgmt_uuid = self.useFixture(fixtures.MockPatch(
            'nova.virt.powervm.mgmt.mgmt_uuid', autospec=True)).mock
        self.mgmt_uuid.return_value = 'mgmt_uuid'

        self.pvm_uuid = self.useFixture(fixtures.MockPatch(
            'nova.virt.powervm.vm.get_pvm_uuid')).mock
        self.pvm_uuid.return_value = 'pvm_uuid'

        # Set up for the mocks for the disk adapter.
        self.mock_find_vg = self.useFixture(fixtures.MockPatch(
            'pypowervm.tasks.storage.find_vg', autospec=True)).mock
        self.vg_uuid = uuids.vg_uuid
        self.vg = mock.Mock(spec=pvm_stg.VG, uuid=self.vg_uuid)
        self.mock_find_vg.return_value = (self.vio_wrap, self.vg)

        self.flags(volume_group_name='fakevg', group='powervm')

        # Mock the feed tasks.
        self.mock_afs = self.useFixture(fixtures.MockPatch(
            'pypowervm.utils.transaction.FeedTask.add_functor_subtask',
            autospec=True)).mock
        self.mock_wtsk = mock.create_autospec(
            pvm_tx.WrapperTask, instance=True)
        self.mock_wtsk.configure_mock(wrapper=self.vio_wrap)
        self.mock_ftsk = mock.create_autospec(pvm_tx.FeedTask, instance=True)
        self.mock_ftsk.configure_mock(
            wrapper_tasks={'vios-uuid': self.mock_wtsk})

        # Create the adapter.
        self.ld_adpt = localdisk.LocalStorage(self.adpt, 'host_uuid')

    def test_init(self):
        # Localdisk adapter already initialized in setUp()
        # From super __init__()
        self.assertEqual(self.adpt, self.ld_adpt._adapter)
        self.assertEqual('host_uuid', self.ld_adpt._host_uuid)
        self.assertEqual('mgmt_uuid', self.ld_adpt.mp_uuid)

        # From LocalStorage __init__()
        self.assertEqual('fakevg', self.ld_adpt.vg_name)
        self.mock_find_vg.assert_called_once_with(self.adpt, 'fakevg')
        self.assertEqual('vios-uuid', self.ld_adpt._vios_uuid)
        self.assertEqual(self.vg_uuid, self.ld_adpt.vg_uuid)
        self.assertFalse(self.ld_adpt.capabilities['shared_storage'])
        self.assertFalse(self.ld_adpt.capabilities['has_imagecache'])
        self.assertFalse(self.ld_adpt.capabilities['snapshot'])

        # Assert snapshot capability is true if hosting I/O on mgmt partition.
        self.mgmt_uuid.return_value = 'vios-uuid'
        self.ld_adpt = localdisk.LocalStorage(self.adpt, 'host_uuid')
        self.assertTrue(self.ld_adpt.capabilities['snapshot'])

        # Assert volume_group_name is required.
        self.flags(volume_group_name=None, group='powervm')
        self.assertRaises(exception.OptRequiredIfOtherOptValue,
                          localdisk.LocalStorage, self.adpt, 'host_uuid')

    def test_vios_uuids(self):
        self.assertEqual(['vios-uuid'], self.ld_adpt._vios_uuids)

    @mock.patch('pypowervm.tasks.scsi_mapper.gen_match_func', autospec=True)
    @mock.patch('nova.virt.powervm.disk.driver.DiskAdapter._get_disk_name')
    def test_disk_match_func(self, mock_disk_name, mock_gen_match):
        mock_disk_name.return_value = 'disk_name'
        func = self.ld_adpt._disk_match_func('disk_type', 'instance')
        mock_disk_name.assert_called_once_with(
            'disk_type', 'instance', short=True)
        mock_gen_match.assert_called_once_with(
            pvm_stg.VDisk, names=['disk_name'])
        self.assertEqual(mock_gen_match.return_value, func)

    @mock.patch('nova.virt.powervm.disk.localdisk.LocalStorage._get_vg_wrap')
    def test_capacity(self, mock_vg):
        """Tests the capacity methods."""
        mock_vg.return_value = mock.Mock(
            capacity='5120', available_size='2048')
        self.assertEqual(5120.0, self.ld_adpt.capacity)
        self.assertEqual(3072.0, self.ld_adpt.capacity_used)

    @mock.patch('pypowervm.tasks.storage.rm_vg_storage', autospec=True)
    @mock.patch('nova.virt.powervm.disk.localdisk.LocalStorage._get_vg_wrap')
    def test_delete_disks(self, mock_vg, mock_rm_vg):
        self.ld_adpt.delete_disks('storage_elems')
        mock_vg.assert_called_once_with()
        mock_rm_vg.assert_called_once_with(
            mock_vg.return_value, vdisks='storage_elems')

    @mock.patch('pypowervm.wrappers.virtual_io_server.VIOS.get')
    @mock.patch('pypowervm.tasks.scsi_mapper.remove_maps', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.gen_match_func', autospec=True)
    def test_detach_disk(self, mock_match_fn, mock_rm_maps, mock_vios):
        mock_match_fn.return_value = 'match_func'
        mock_vios.return_value = self.vio_wrap
        mock_map1 = mock.Mock(backing_storage='back_stor1')
        mock_map2 = mock.Mock(backing_storage='back_stor2')
        mock_rm_maps.return_value = [mock_map1, mock_map2]

        back_stores = self.ld_adpt.detach_disk('instance')

        self.assertEqual(['back_stor1', 'back_stor2'], back_stores)
        mock_match_fn.assert_called_once_with(pvm_stg.VDisk)
        mock_vios.assert_called_once_with(
            self.ld_adpt._adapter, uuid='vios-uuid',
            xag=[pvm_const.XAG.VIO_SMAP])
        mock_rm_maps.assert_called_with(self.vio_wrap, 'pvm_uuid',
                                        match_func=mock_match_fn.return_value)
        mock_vios.return_value.update.assert_called_once()

    @mock.patch('pypowervm.tasks.scsi_mapper.remove_vdisk_mapping',
                autospec=True)
    def test_disconnect_disk_from_mgmt(self, mock_rm_vdisk_map):
        self.ld_adpt.disconnect_disk_from_mgmt('vios-uuid', 'disk_name')
        mock_rm_vdisk_map.assert_called_with(
            self.ld_adpt._adapter, 'vios-uuid', 'mgmt_uuid',
            disk_names=['disk_name'])

    @mock.patch('nova.virt.powervm.disk.localdisk.LocalStorage._upload_image')
    def test_create_disk_from_image(self, mock_upload_image):
        mock_image_meta = mock.Mock()
        mock_image_meta.size = 30
        mock_upload_image.return_value = 'mock_img'

        self.ld_adpt.create_disk_from_image(
            'context', 'instance', mock_image_meta)

        mock_upload_image.assert_called_once_with(
            'context', 'instance', mock_image_meta)

    @mock.patch('nova.image.glance.API.download')
    @mock.patch('nova.virt.powervm.disk.driver.IterableToFileAdapter')
    @mock.patch('pypowervm.tasks.storage.upload_new_vdisk')
    @mock.patch('nova.virt.powervm.disk.driver.DiskAdapter._get_disk_name')
    def test_upload_image(self, mock_name, mock_upload, mock_iter, mock_dl):
        mock_meta = mock.Mock(id='1', size=1073741824, disk_format='raw')
        mock_upload.return_value = ['mock_img']

        mock_img = self.ld_adpt._upload_image('context', 'inst', mock_meta)

        self.assertEqual('mock_img', mock_img)
        mock_name.assert_called_once_with(
            disk_dvr.DiskType.BOOT, 'inst', short=True)
        mock_dl.assert_called_once_with('context', '1')
        mock_iter.assert_called_once_with(mock_dl.return_value)
        mock_upload.assert_called_once_with(
            self.adpt, 'vios-uuid', self.vg_uuid, mock_iter.return_value,
            mock_name.return_value, 1073741824, d_size=1073741824,
            upload_type=tsk_stg.UploadType.IO_STREAM, file_format='raw')

    @mock.patch('pypowervm.tasks.scsi_mapper.add_map', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.build_vscsi_mapping',
                autospec=True)
    def test_attach_disk(self, mock_bldmap, mock_addmap):
        def test_afs(add_func):
            # Verify the internal add_func
            self.assertEqual(mock_addmap.return_value, add_func(self.vio_wrap))
            mock_bldmap.assert_called_once_with(
                self.ld_adpt._host_uuid, self.vio_wrap, 'pvm_uuid',
                'disk_info')
            mock_addmap.assert_called_once_with(
                self.vio_wrap, mock_bldmap.return_value)

        self.mock_wtsk.add_functor_subtask.side_effect = test_afs
        self.ld_adpt.attach_disk('instance', 'disk_info', self.mock_ftsk)
        self.pvm_uuid.assert_called_once_with('instance')
        self.assertEqual(1, self.mock_wtsk.add_functor_subtask.call_count)

    @mock.patch('pypowervm.wrappers.storage.VG.get')
    def test_get_vg_wrap(self, mock_vg):
        vg_wrap = self.ld_adpt._get_vg_wrap()
        self.assertEqual(mock_vg.return_value, vg_wrap)
        mock_vg.assert_called_once_with(
            self.adpt, uuid=self.vg_uuid, parent_type=pvm_vios.VIOS,
            parent_uuid='vios-uuid')

    @mock.patch('pypowervm.wrappers.virtual_io_server.VIOS.get')
    @mock.patch('pypowervm.tasks.scsi_mapper.find_maps', autospec=True)
    @mock.patch('nova.virt.powervm.disk.localdisk.LocalStorage.'
                '_disk_match_func')
    def test_get_bootdisk_path(self, mock_match_fn, mock_findmaps,
                                         mock_vios):
        mock_vios.return_value = self.vio_wrap

        # No maps found
        mock_findmaps.return_value = None
        devname = self.ld_adpt.get_bootdisk_path('inst', 'vios_uuid')
        self.pvm_uuid.assert_called_once_with('inst')
        mock_match_fn.assert_called_once_with(disk_dvr.DiskType.BOOT, 'inst')
        mock_vios.assert_called_once_with(
            self.adpt, uuid='vios_uuid', xag=[pvm_const.XAG.VIO_SMAP])
        mock_findmaps.assert_called_once_with(
            self.vio_wrap.scsi_mappings,
            client_lpar_id='pvm_uuid',
            match_func=mock_match_fn.return_value)
        self.assertIsNone(devname)

        # Good map
        mock_lu = mock.Mock()
        mock_lu.server_adapter.backing_dev_name = 'devname'
        mock_findmaps.return_value = [mock_lu]
        devname = self.ld_adpt.get_bootdisk_path('inst', 'vios_uuid')
        self.assertEqual('devname', devname)

    @mock.patch('nova.virt.powervm.vm.get_instance_wrapper', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.find_maps')
    @mock.patch('pypowervm.wrappers.virtual_io_server.VIOS.get')
    @mock.patch('pypowervm.wrappers.storage.VG.get', new=mock.Mock())
    def test_get_bootdisk_iter(self, mock_vios, mock_find_maps, mock_lw):
        inst, lpar_wrap, vios1 = self._bld_mocks_for_instance_disk()
        mock_lw.return_value = lpar_wrap

        # Good path
        mock_vios.return_value = vios1
        for vdisk, vios in self.ld_adpt._get_bootdisk_iter(inst):
            self.assertEqual(vios1.scsi_mappings[0].backing_storage, vdisk)
            self.assertEqual(vios1.uuid, vios.uuid)
        mock_vios.assert_called_once_with(
            self.adpt, uuid='vios-uuid', xag=[pvm_const.XAG.VIO_SMAP])

        # Not found, no storage of that name.
        mock_vios.reset_mock()
        mock_find_maps.return_value = []
        for vdisk, vios in self.ld_adpt._get_bootdisk_iter(inst):
            self.fail('Should not have found any storage elements.')
        mock_vios.assert_called_once_with(
            self.adpt, uuid='vios-uuid', xag=[pvm_const.XAG.VIO_SMAP])

    @mock.patch('nova.virt.powervm.disk.driver.DiskAdapter._get_bootdisk_iter',
                autospec=True)
    @mock.patch('nova.virt.powervm.vm.get_instance_wrapper', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.add_vscsi_mapping', autospec=True)
    def test_connect_instance_disk_to_mgmt(self, mock_add, mock_lw, mock_iter):
        inst, lpar_wrap, vios1 = self._bld_mocks_for_instance_disk()
        mock_lw.return_value = lpar_wrap

        # Good path
        mock_iter.return_value = [(vios1.scsi_mappings[0].backing_storage,
                                   vios1)]
        vdisk, vios = self.ld_adpt.connect_instance_disk_to_mgmt(inst)
        self.assertEqual(vios1.scsi_mappings[0].backing_storage, vdisk)
        self.assertIs(vios1, vios)
        self.assertEqual(1, mock_add.call_count)
        mock_add.assert_called_with('host_uuid', vios, 'mgmt_uuid', vdisk)

        # add_vscsi_mapping raises.  Show-stopper since only one VIOS.
        mock_add.reset_mock()
        mock_add.side_effect = Exception
        self.assertRaises(exception.InstanceDiskMappingFailed,
                          self.ld_adpt.connect_instance_disk_to_mgmt, inst)
        self.assertEqual(1, mock_add.call_count)

        # Not found
        mock_add.reset_mock()
        mock_iter.return_value = []
        self.assertRaises(exception.InstanceDiskMappingFailed,
                          self.ld_adpt.connect_instance_disk_to_mgmt, inst)
        self.assertFalse(mock_add.called)

    def _bld_mocks_for_instance_disk(self):
        inst = mock.Mock()
        inst.name = 'Name Of Instance'
        inst.uuid = uuids.inst_uuid
        lpar_wrap = mock.Mock()
        lpar_wrap.id = 2
        vios1 = self.vio_wrap
        back_stor_name = 'b_Name_Of__' + inst.uuid[:4]
        vios1.scsi_mappings[0].backing_storage.name = back_stor_name
        return inst, lpar_wrap, vios1
