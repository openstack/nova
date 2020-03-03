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

from __future__ import absolute_import

import fixtures
import mock
from oslo_utils import uuidutils
from pypowervm import const as pvm_const
from pypowervm import exceptions as pvm_exc
from pypowervm.tasks import storage as tsk_stg
from pypowervm.utils import transaction as pvm_tx
from pypowervm.wrappers import cluster as pvm_clust
from pypowervm.wrappers import storage as pvm_stg
from pypowervm.wrappers import virtual_io_server as pvm_vios

from nova import exception
from nova import test
from nova.tests.unit.virt import powervm
from nova.virt.powervm.disk import ssp as ssp_dvr
from nova.virt.powervm import vm

FAKE_INST_UUID = uuidutils.generate_uuid(dashed=True)
FAKE_INST_UUID_PVM = vm.get_pvm_uuid(mock.Mock(uuid=FAKE_INST_UUID))


class TestSSPDiskAdapter(test.NoDBTestCase):
    """Unit Tests for the LocalDisk storage driver."""

    def setUp(self):
        super(TestSSPDiskAdapter, self).setUp()

        self.inst = powervm.TEST_INSTANCE

        self.apt = mock.Mock()
        self.host_uuid = 'host_uuid'

        self.ssp_wrap = mock.create_autospec(pvm_stg.SSP, instance=True)

        # SSP.refresh() returns itself
        self.ssp_wrap.refresh.return_value = self.ssp_wrap
        self.node1 = mock.create_autospec(pvm_clust.Node, instance=True)
        self.node2 = mock.create_autospec(pvm_clust.Node, instance=True)
        self.clust_wrap = mock.create_autospec(
            pvm_clust.Cluster, instance=True)
        self.clust_wrap.nodes = [self.node1, self.node2]
        self.clust_wrap.refresh.return_value = self.clust_wrap
        self.tier_wrap = mock.create_autospec(pvm_stg.Tier, instance=True)
        # Tier.refresh() returns itself
        self.tier_wrap.refresh.return_value = self.tier_wrap
        self.vio_wrap = mock.create_autospec(pvm_vios.VIOS, instance=True)

        # For _cluster
        self.mock_clust = self.useFixture(fixtures.MockPatch(
            'pypowervm.wrappers.cluster.Cluster', autospec=True)).mock
        self.mock_clust.get.return_value = [self.clust_wrap]

        # For _ssp
        self.mock_ssp_gbhref = self.useFixture(fixtures.MockPatch(
            'pypowervm.wrappers.storage.SSP.get_by_href')).mock
        self.mock_ssp_gbhref.return_value = self.ssp_wrap

        # For _tier
        self.mock_get_tier = self.useFixture(fixtures.MockPatch(
            'pypowervm.tasks.storage.default_tier_for_ssp',
            autospec=True)).mock
        self.mock_get_tier.return_value = self.tier_wrap

        # A FeedTask
        self.mock_wtsk = mock.create_autospec(
            pvm_tx.WrapperTask, instance=True)
        self.mock_wtsk.configure_mock(wrapper=self.vio_wrap)
        self.mock_ftsk = mock.create_autospec(pvm_tx.FeedTask, instance=True)
        self.mock_afs = self.mock_ftsk.add_functor_subtask
        self.mock_ftsk.configure_mock(
            wrapper_tasks={self.vio_wrap.uuid: self.mock_wtsk})

        self.pvm_uuid = self.useFixture(fixtures.MockPatch(
            'nova.virt.powervm.vm.get_pvm_uuid')).mock

        # Return the mgmt uuid
        self.mgmt_uuid = self.useFixture(fixtures.MockPatch(
            'nova.virt.powervm.mgmt.mgmt_uuid')).mock
        self.mgmt_uuid.return_value = 'mp_uuid'

        # The SSP disk adapter
        self.ssp_drv = ssp_dvr.SSPDiskAdapter(self.apt, self.host_uuid)

    def test_init(self):
        self.assertEqual(self.apt, self.ssp_drv._adapter)
        self.assertEqual(self.host_uuid, self.ssp_drv._host_uuid)
        self.mock_clust.get.assert_called_once_with(self.apt)
        self.assertEqual(self.mock_clust.get.return_value,
                         [self.ssp_drv._clust])
        self.mock_ssp_gbhref.assert_called_once_with(
            self.apt, self.clust_wrap.ssp_uri)
        self.assertEqual(self.mock_ssp_gbhref.return_value, self.ssp_drv._ssp)
        self.mock_get_tier.assert_called_once_with(self.ssp_wrap)
        self.assertEqual(self.mock_get_tier.return_value, self.ssp_drv._tier)

    def test_init_error(self):
        # Do these in reverse order to verify we trap all of 'em
        for raiser in (self.mock_get_tier, self.mock_ssp_gbhref,
                       self.mock_clust.get):
            raiser.side_effect = pvm_exc.TimeoutError("timed out")
            self.assertRaises(exception.NotFound,
                              ssp_dvr.SSPDiskAdapter, self.apt, self.host_uuid)
            raiser.side_effect = ValueError
            self.assertRaises(ValueError,
                              ssp_dvr.SSPDiskAdapter, self.apt, self.host_uuid)

    def test_capabilities(self):
        self.assertTrue(self.ssp_drv.capabilities.get('shared_storage'))
        self.assertFalse(self.ssp_drv.capabilities.get('has_imagecache'))
        self.assertTrue(self.ssp_drv.capabilities.get('snapshot'))

    @mock.patch('pypowervm.util.get_req_path_uuid', autospec=True)
    def test_vios_uuids(self, mock_rpu):
        mock_rpu.return_value = self.host_uuid
        vios_uuids = self.ssp_drv._vios_uuids
        self.assertEqual({self.node1.vios_uuid, self.node2.vios_uuid},
                         set(vios_uuids))
        mock_rpu.assert_has_calls(
            [mock.call(node.vios_uri, preserve_case=True, root=True)
             for node in [self.node1, self.node2]])

        mock_rpu.reset_mock()

        # Test VIOSes on other nodes, which won't have uuid or url
        node1 = mock.Mock(vios_uuid=None, vios_uri='uri1')
        node2 = mock.Mock(vios_uuid='2', vios_uri=None)
        # This mock is good and should be returned
        node3 = mock.Mock(vios_uuid='3', vios_uri='uri3')
        self.clust_wrap.nodes = [node1, node2, node3]
        self.assertEqual(['3'], self.ssp_drv._vios_uuids)
        # get_req_path_uuid was only called on the good one
        mock_rpu.assert_called_once_with('uri3', preserve_case=True, root=True)

    def test_capacity(self):
        self.tier_wrap.capacity = 10
        self.assertAlmostEqual(10.0, self.ssp_drv.capacity)
        self.tier_wrap.refresh.assert_called_once_with()

    def test_capacity_used(self):
        self.ssp_wrap.capacity = 4.56
        self.ssp_wrap.free_space = 1.23
        self.assertAlmostEqual((4.56 - 1.23), self.ssp_drv.capacity_used)
        self.ssp_wrap.refresh.assert_called_once_with()

    @mock.patch('pypowervm.tasks.cluster_ssp.get_or_upload_image_lu',
                autospec=True)
    @mock.patch('nova.virt.powervm.disk.ssp.SSPDiskAdapter._vios_uuids',
                new_callable=mock.PropertyMock)
    @mock.patch('pypowervm.util.sanitize_file_name_for_api', autospec=True)
    @mock.patch('pypowervm.tasks.storage.crt_lu', autospec=True)
    @mock.patch('nova.image.glance.API.download')
    @mock.patch('nova.virt.powervm.disk.driver.IterableToFileAdapter',
                autospec=True)
    def test_create_disk_from_image(self, mock_it2f, mock_dl, mock_crt_lu,
                                    mock_san, mock_vuuid, mock_goru):
        img = powervm.TEST_IMAGE1

        mock_crt_lu.return_value = self.ssp_drv._ssp, 'boot_lu'
        mock_san.return_value = 'disk_name'
        mock_vuuid.return_value = ['vuuid']

        self.assertEqual('boot_lu', self.ssp_drv.create_disk_from_image(
            'context', self.inst, img))
        mock_dl.assert_called_once_with('context', img.id)
        mock_san.assert_has_calls([
            mock.call(img.name, prefix='image_', suffix='_' + img.checksum),
            mock.call(self.inst.name, prefix='boot_')])
        mock_it2f.assert_called_once_with(mock_dl.return_value)
        mock_goru.assert_called_once_with(
            self.ssp_drv._tier, 'disk_name', 'vuuid',
            mock_it2f.return_value, img.size,
            upload_type=tsk_stg.UploadType.IO_STREAM)
        mock_crt_lu.assert_called_once_with(
            self.mock_get_tier.return_value, mock_san.return_value,
            self.inst.flavor.root_gb, typ=pvm_stg.LUType.DISK,
            clone=mock_goru.return_value)

    @mock.patch('nova.virt.powervm.disk.ssp.SSPDiskAdapter._vios_uuids',
                new_callable=mock.PropertyMock)
    @mock.patch('pypowervm.tasks.scsi_mapper.add_map', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.build_vscsi_mapping',
                autospec=True)
    @mock.patch('pypowervm.wrappers.storage.LU', autospec=True)
    def test_connect_disk(self, mock_lu, mock_bldmap, mock_addmap,
                          mock_vio_uuids):
        disk_info = mock.Mock()
        disk_info.configure_mock(name='dname', udid='dudid')
        mock_vio_uuids.return_value = [self.vio_wrap.uuid]

        def test_afs(add_func):
            # Verify the internal add_func
            self.assertEqual(mock_addmap.return_value, add_func(self.vio_wrap))
            mock_bldmap.assert_called_once_with(
                self.host_uuid, self.vio_wrap, self.pvm_uuid.return_value,
                mock_lu.bld_ref.return_value)
            mock_addmap.assert_called_once_with(
                self.vio_wrap, mock_bldmap.return_value)
        self.mock_wtsk.add_functor_subtask.side_effect = test_afs

        self.ssp_drv.attach_disk(self.inst, disk_info, self.mock_ftsk)
        mock_lu.bld_ref.assert_called_once_with(self.apt, 'dname', 'dudid')
        self.pvm_uuid.assert_called_once_with(self.inst)
        self.assertEqual(1, self.mock_wtsk.add_functor_subtask.call_count)

    @mock.patch('pypowervm.tasks.storage.rm_tier_storage', autospec=True)
    def test_delete_disks(self, mock_rm_tstor):
        self.ssp_drv.delete_disks(['disk1', 'disk2'])
        mock_rm_tstor.assert_called_once_with(['disk1', 'disk2'],
                                              tier=self.ssp_drv._tier)

    @mock.patch('nova.virt.powervm.disk.ssp.SSPDiskAdapter._vios_uuids',
                new_callable=mock.PropertyMock)
    @mock.patch('pypowervm.tasks.scsi_mapper.find_maps', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.remove_maps', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.gen_match_func', autospec=True)
    @mock.patch('pypowervm.tasks.partition.build_active_vio_feed_task',
                autospec=True)
    def test_disconnect_disk(self, mock_bld_ftsk, mock_gmf, mock_rmmaps,
                             mock_findmaps, mock_vio_uuids):
        mock_vio_uuids.return_value = [self.vio_wrap.uuid]
        mock_bld_ftsk.return_value = self.mock_ftsk
        lu1, lu2 = [mock.create_autospec(pvm_stg.LU, instance=True)] * 2
        # Two mappings have the same LU, to verify set behavior
        mock_findmaps.return_value = [
            mock.Mock(spec=pvm_vios.VSCSIMapping, backing_storage=lu)
            for lu in (lu1, lu2, lu1)]

        def test_afs(rm_func):
            # verify the internal rm_func
            self.assertEqual(mock_rmmaps.return_value, rm_func(self.vio_wrap))
            mock_rmmaps.assert_called_once_with(
                self.vio_wrap, self.pvm_uuid.return_value,
                match_func=mock_gmf.return_value)
        self.mock_wtsk.add_functor_subtask.side_effect = test_afs

        self.assertEqual(
            {lu1, lu2}, set(self.ssp_drv.detach_disk(self.inst)))
        mock_bld_ftsk.assert_called_once_with(
            self.apt, name='ssp', xag=[pvm_const.XAG.VIO_SMAP])
        self.pvm_uuid.assert_called_once_with(self.inst)
        mock_gmf.assert_called_once_with(pvm_stg.LU)
        self.assertEqual(1, self.mock_wtsk.add_functor_subtask.call_count)
        mock_findmaps.assert_called_once_with(
            self.vio_wrap.scsi_mappings,
            client_lpar_id=self.pvm_uuid.return_value,
            match_func=mock_gmf.return_value)
        self.mock_ftsk.execute.assert_called_once_with()

    @mock.patch('pypowervm.wrappers.virtual_io_server.VIOS.get')
    @mock.patch('pypowervm.tasks.scsi_mapper.find_maps', autospec=True)
    @mock.patch('nova.virt.powervm.disk.ssp.SSPDiskAdapter._disk_match_func')
    def test_get_bootdisk_path(self, mock_match_fn, mock_findmaps,
                                         mock_vios):
        mock_vios.return_value = self.vio_wrap

        # No maps found
        mock_findmaps.return_value = None
        devname = self.ssp_drv.get_bootdisk_path('inst', 'vios_uuid')
        mock_vios.assert_called_once_with(
            self.apt, uuid='vios_uuid', xag=[pvm_const.XAG.VIO_SMAP])
        mock_findmaps.assert_called_once_with(
            self.vio_wrap.scsi_mappings,
            client_lpar_id=self.pvm_uuid.return_value,
            match_func=mock_match_fn.return_value)
        self.assertIsNone(devname)

        # Good map
        mock_lu = mock.Mock()
        mock_lu.server_adapter.backing_dev_name = 'devname'
        mock_findmaps.return_value = [mock_lu]
        devname = self.ssp_drv.get_bootdisk_path('inst', 'vios_uuid')
        self.assertEqual('devname', devname)

    @mock.patch('nova.virt.powervm.disk.ssp.SSPDiskAdapter.'
                '_vios_uuids', new_callable=mock.PropertyMock)
    @mock.patch('nova.virt.powervm.vm.get_instance_wrapper', autospec=True)
    @mock.patch('pypowervm.wrappers.virtual_io_server.VIOS.get')
    @mock.patch('pypowervm.tasks.scsi_mapper.add_vscsi_mapping', autospec=True)
    def test_connect_instance_disk_to_mgmt(self, mock_add, mock_vio_get,
                                           mock_lw, mock_vio_uuids):
        inst, lpar_wrap, vio1, vio2, vio3 = self._bld_mocks_for_instance_disk()
        mock_lw.return_value = lpar_wrap
        mock_vio_uuids.return_value = [1, 2]

        # Test with two VIOSes, both of which contain the mapping
        mock_vio_get.side_effect = [vio1, vio2]
        lu, vios = self.ssp_drv.connect_instance_disk_to_mgmt(inst)
        self.assertEqual('lu_udid', lu.udid)
        # Should hit on the first VIOS
        self.assertIs(vio1, vios)
        mock_add.assert_called_once_with(self.host_uuid, vio1, 'mp_uuid', lu)

        # Now the first VIOS doesn't have the mapping, but the second does
        mock_add.reset_mock()
        mock_vio_get.side_effect = [vio3, vio2]
        lu, vios = self.ssp_drv.connect_instance_disk_to_mgmt(inst)
        self.assertEqual('lu_udid', lu.udid)
        # Should hit on the second VIOS
        self.assertIs(vio2, vios)
        self.assertEqual(1, mock_add.call_count)
        mock_add.assert_called_once_with(self.host_uuid, vio2, 'mp_uuid', lu)

        # No hits
        mock_add.reset_mock()
        mock_vio_get.side_effect = [vio3, vio3]
        self.assertRaises(exception.InstanceDiskMappingFailed,
                          self.ssp_drv.connect_instance_disk_to_mgmt, inst)
        self.assertEqual(0, mock_add.call_count)

        # First add_vscsi_mapping call raises
        mock_vio_get.side_effect = [vio1, vio2]
        mock_add.side_effect = [Exception("mapping failed"), None]
        # Should hit on the second VIOS
        self.assertIs(vio2, vios)

    @mock.patch('pypowervm.tasks.scsi_mapper.remove_lu_mapping', autospec=True)
    def test_disconnect_disk_from_mgmt(self, mock_rm_lu_map):
        self.ssp_drv.disconnect_disk_from_mgmt('vios_uuid', 'disk_name')
        mock_rm_lu_map.assert_called_with(self.apt, 'vios_uuid',
                                          'mp_uuid', disk_names=['disk_name'])

    @mock.patch('pypowervm.tasks.scsi_mapper.gen_match_func', autospec=True)
    @mock.patch('nova.virt.powervm.disk.ssp.SSPDiskAdapter._get_disk_name')
    def test_disk_match_func(self, mock_disk_name, mock_gen_match):
        mock_disk_name.return_value = 'disk_name'
        self.ssp_drv._disk_match_func('disk_type', 'instance')
        mock_disk_name.assert_called_once_with('disk_type', 'instance')
        mock_gen_match.assert_called_with(pvm_stg.LU, names=['disk_name'])

    @mock.patch('nova.virt.powervm.disk.ssp.SSPDiskAdapter.'
                '_vios_uuids', new_callable=mock.PropertyMock)
    @mock.patch('nova.virt.powervm.vm.get_instance_wrapper', autospec=True)
    @mock.patch('pypowervm.wrappers.virtual_io_server.VIOS.get')
    def test_get_bootdisk_iter(self, mock_vio_get, mock_lw, mock_vio_uuids):
        inst, lpar_wrap, vio1, vio2, vio3 = self._bld_mocks_for_instance_disk()
        mock_lw.return_value = lpar_wrap
        mock_vio_uuids.return_value = [1, 2]

        # Test with two VIOSes, both of which contain the mapping.  Force the
        # method to get the lpar_wrap.
        mock_vio_get.side_effect = [vio1, vio2]
        idi = self.ssp_drv._get_bootdisk_iter(inst)
        lu, vios = next(idi)
        self.assertEqual('lu_udid', lu.udid)
        self.assertEqual('vios1', vios.name)
        mock_vio_get.assert_called_once_with(self.apt, uuid=1,
                                             xag=[pvm_const.XAG.VIO_SMAP])
        lu, vios = next(idi)
        self.assertEqual('lu_udid', lu.udid)
        self.assertEqual('vios2', vios.name)
        mock_vio_get.assert_called_with(self.apt, uuid=2,
                                        xag=[pvm_const.XAG.VIO_SMAP])
        self.assertRaises(StopIteration, next, idi)
        self.assertEqual(2, mock_vio_get.call_count)
        mock_lw.assert_called_once_with(self.apt, inst)

        # Same, but prove that breaking out of the loop early avoids the second
        # get call.  Supply lpar_wrap from here on, and prove no calls to
        # get_instance_wrapper
        mock_vio_get.reset_mock()
        mock_lw.reset_mock()
        mock_vio_get.side_effect = [vio1, vio2]
        for lu, vios in self.ssp_drv._get_bootdisk_iter(inst):
            self.assertEqual('lu_udid', lu.udid)
            self.assertEqual('vios1', vios.name)
            break
        mock_vio_get.assert_called_once_with(self.apt, uuid=1,
                                             xag=[pvm_const.XAG.VIO_SMAP])

        # Now the first VIOS doesn't have the mapping, but the second does
        mock_vio_get.reset_mock()
        mock_vio_get.side_effect = [vio3, vio2]
        idi = self.ssp_drv._get_bootdisk_iter(inst)
        lu, vios = next(idi)
        self.assertEqual('lu_udid', lu.udid)
        self.assertEqual('vios2', vios.name)
        mock_vio_get.assert_has_calls(
            [mock.call(self.apt, uuid=uuid, xag=[pvm_const.XAG.VIO_SMAP])
             for uuid in (1, 2)])
        self.assertRaises(StopIteration, next, idi)
        self.assertEqual(2, mock_vio_get.call_count)

        # No hits
        mock_vio_get.reset_mock()
        mock_vio_get.side_effect = [vio3, vio3]
        self.assertEqual([], list(self.ssp_drv._get_bootdisk_iter(inst)))
        self.assertEqual(2, mock_vio_get.call_count)

    def _bld_mocks_for_instance_disk(self):
        inst = mock.Mock()
        inst.name = 'my-instance-name'
        lpar_wrap = mock.Mock()
        lpar_wrap.id = 4
        lu_wrap = mock.Mock(spec=pvm_stg.LU)
        lu_wrap.configure_mock(name='boot_my_instance_name', udid='lu_udid')
        smap = mock.Mock(backing_storage=lu_wrap,
                         server_adapter=mock.Mock(lpar_id=4))
        # Build mock VIOS Wrappers as the returns from VIOS.wrap.
        # vios1 and vios2 will both have the mapping for client ID 4 and LU
        # named boot_my_instance_name.
        smaps = [mock.Mock(), mock.Mock(), mock.Mock(), smap]
        vios1 = mock.Mock(spec=pvm_vios.VIOS)
        vios1.configure_mock(name='vios1', uuid='uuid1', scsi_mappings=smaps)
        vios2 = mock.Mock(spec=pvm_vios.VIOS)
        vios2.configure_mock(name='vios2', uuid='uuid2', scsi_mappings=smaps)
        # vios3 will not have the mapping
        vios3 = mock.Mock(spec=pvm_vios.VIOS)
        vios3.configure_mock(name='vios3', uuid='uuid3',
                             scsi_mappings=[mock.Mock(), mock.Mock()])
        return inst, lpar_wrap, vios1, vios2, vios3
