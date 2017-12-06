# Copyright 2015, 2018 IBM Corp.
#
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
from pypowervm import const as pvm_const
from pypowervm.tasks import hdisk
from pypowervm.tests import test_fixtures as pvm_fx
from pypowervm.utils import transaction as pvm_tx
from pypowervm.wrappers import storage as pvm_stor
from pypowervm.wrappers import virtual_io_server as pvm_vios

from nova import conf as cfg
from nova import exception as exc
from nova import test
from nova.virt.powervm.volume import fcvscsi

CONF = cfg.CONF

I_WWPN_1 = '21000024FF649104'
I_WWPN_2 = '21000024FF649105'


class TestVSCSIAdapter(test.NoDBTestCase):

    def setUp(self):
        super(TestVSCSIAdapter, self).setUp()

        self.adpt = self.useFixture(pvm_fx.AdapterFx()).adpt
        self.wtsk = mock.create_autospec(pvm_tx.WrapperTask, instance=True)
        self.ftsk = mock.create_autospec(pvm_tx.FeedTask, instance=True)
        self.ftsk.configure_mock(wrapper_tasks={'vios_uuid': self.wtsk})

        @mock.patch('nova.virt.powervm.vm.get_pvm_uuid')
        def init_vol_adpt(mock_pvm_uuid):
            con_info = {
                'serial': 'id',
                'data': {
                    'initiator_target_map': {
                        I_WWPN_1: ['t1'],
                        I_WWPN_2: ['t2', 't3']
                    },
                    'target_lun': '1',
                    'volume_id': 'a_volume_identifier',
                },
            }
            mock_inst = mock.MagicMock()
            mock_pvm_uuid.return_value = '1234'

            return fcvscsi.FCVscsiVolumeAdapter(
                self.adpt, mock_inst, con_info, stg_ftsk=self.ftsk)
        self.vol_drv = init_vol_adpt()

    @mock.patch('pypowervm.utils.transaction.FeedTask', autospec=True)
    @mock.patch('pypowervm.wrappers.virtual_io_server.VIOS', autospec=True)
    def test_reset_stg_ftsk(self, mock_vios, mock_ftsk):
        self.vol_drv.reset_stg_ftsk('stg_ftsk')
        self.assertEqual('stg_ftsk', self.vol_drv.stg_ftsk)

        mock_vios.getter.return_value = 'getter'
        mock_ftsk.return_value = 'local_feed_task'
        self.vol_drv.reset_stg_ftsk()
        self.assertEqual('local_feed_task', self.vol_drv.stg_ftsk)
        mock_vios.getter.assert_called_once_with(
            self.adpt, xag=[pvm_const.XAG.VIO_SMAP])
        mock_ftsk.assert_called_once_with('local_feed_task', 'getter')

    @mock.patch('pypowervm.tasks.partition.get_physical_wwpns', autospec=True)
    def test_wwpns(self, mock_vio_wwpns):
        mock_vio_wwpns.return_value = ['aa', 'bb']
        wwpns = fcvscsi.wwpns(self.adpt)
        self.assertListEqual(['aa', 'bb'], wwpns)
        mock_vio_wwpns.assert_called_once_with(self.adpt, force_refresh=False)

    def test_set_udid(self):
        # Mock connection info
        self.vol_drv.connection_info['data'][fcvscsi.UDID_KEY] = None

        # Set the UDID
        self.vol_drv._set_udid('udid')

        # Verify
        self.assertEqual('udid',
            self.vol_drv.connection_info['data'][fcvscsi.UDID_KEY])

    def test_get_udid(self):
        # Set the value to retrieve
        self.vol_drv.connection_info['data'][fcvscsi.UDID_KEY] = 'udid'
        retrieved_udid = self.vol_drv._get_udid()
        # Check key found
        self.assertEqual('udid', retrieved_udid)

        # Check key not found
        self.vol_drv.connection_info['data'].pop(fcvscsi.UDID_KEY)
        retrieved_udid = self.vol_drv._get_udid()
        # Check key not found
        self.assertIsNone(retrieved_udid)

    @mock.patch('nova.virt.powervm.vm.get_instance_wrapper')
    @mock.patch('pypowervm.utils.transaction.FeedTask', autospec=True)
    def test_attach_volume(self, mock_feed_task, mock_get_wrap):
        mock_lpar_wrap = mock.MagicMock()
        mock_lpar_wrap.can_modify_io.return_value = True, None
        mock_get_wrap.return_value = mock_lpar_wrap
        mock_attach_ftsk = mock_feed_task.return_value

        # Pass if all vioses modified
        mock_ret = {'wrapper_task_rets': {'vios1': {'vio_modified': True},
                                          'vios2': {'vio_modified': True}}}
        mock_attach_ftsk.execute.return_value = mock_ret
        self.vol_drv.attach_volume()
        mock_feed_task.assert_called_once()
        mock_attach_ftsk.add_functor_subtask.assert_called_once_with(
            self.vol_drv._attach_volume_to_vio, provides='vio_modified',
            flag_update=False)
        mock_attach_ftsk.execute.assert_called_once()
        self.ftsk.execute.assert_called_once()

        mock_feed_task.reset_mock()
        mock_attach_ftsk.reset_mock()
        self.ftsk.reset_mock()

        # Pass if 1 vios modified
        mock_ret = {'wrapper_task_rets': {'vios1': {'vio_modified': True},
                                          'vios2': {'vio_modified': False}}}
        mock_attach_ftsk.execute.return_value = mock_ret
        self.vol_drv.attach_volume()
        mock_feed_task.assert_called_once()
        mock_attach_ftsk.add_functor_subtask.assert_called_once_with(
            self.vol_drv._attach_volume_to_vio, provides='vio_modified',
            flag_update=False)
        mock_attach_ftsk.execute.assert_called_once()
        self.ftsk.execute.assert_called_once()

        # Raise if no vios modified
        mock_ret = {'wrapper_task_rets': {'vios1': {'vio_modified': False},
                                          'vios2': {'vio_modified': False}}}
        mock_attach_ftsk.execute.return_value = mock_ret
        self.assertRaises(exc.VolumeAttachFailed, self.vol_drv.attach_volume)

        # Raise if vm in invalid state
        mock_lpar_wrap.can_modify_io.return_value = False, None
        self.assertRaises(exc.VolumeAttachFailed, self.vol_drv.attach_volume)

    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter.'
                '_set_udid')
    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter.'
                '_add_append_mapping')
    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter.'
                '_discover_volume_on_vios')
    @mock.patch('pypowervm.tasks.hdisk.good_discovery', autospec=True)
    def test_attach_volume_to_vio(self, mock_good_disc, mock_disc_vol,
                                  mock_add_map, mock_set_udid):
        # Setup mocks
        mock_vios = mock.MagicMock()
        mock_vios.uuid = 'uuid'
        mock_disc_vol.return_value = 'status', 'devname', 'udid'

        # Bad discovery
        mock_good_disc.return_value = False
        ret = self.vol_drv._attach_volume_to_vio(mock_vios)
        self.assertFalse(ret)
        mock_disc_vol.assert_called_once_with(mock_vios)
        mock_good_disc.assert_called_once_with('status', 'devname')

        # Good discovery
        mock_good_disc.return_value = True
        ret = self.vol_drv._attach_volume_to_vio(mock_vios)
        self.assertTrue(ret)
        mock_add_map.assert_called_once_with(
            'uuid', 'devname', tag='a_volume_identifier')
        mock_set_udid.assert_called_once_with('udid')

    def test_extend_volume(self):
        # Ensure the method is implemented
        self.vol_drv.extend_volume()

    @mock.patch('nova.virt.powervm.volume.fcvscsi.LOG')
    @mock.patch('pypowervm.tasks.hdisk.good_discovery', autospec=True)
    @mock.patch('pypowervm.tasks.hdisk.discover_hdisk', autospec=True)
    @mock.patch('pypowervm.tasks.hdisk.build_itls', autospec=True)
    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter.'
                '_get_hdisk_itls')
    def test_discover_volume_on_vios(self, mock_get_itls, mock_build_itls,
                                     mock_disc_hdisk, mock_good_disc,
                                     mock_log):
        mock_vios = mock.MagicMock()
        mock_vios.uuid = 'uuid'
        mock_get_itls.return_value = 'v_wwpns', 't_wwpns', 'lun'
        mock_build_itls.return_value = 'itls'
        mock_disc_hdisk.return_value = 'status', 'devname', 'udid'

        # Good discovery
        mock_good_disc.return_value = True
        status, devname, udid = self.vol_drv._discover_volume_on_vios(
            mock_vios)
        self.assertEqual(mock_disc_hdisk.return_value[0], status)
        self.assertEqual(mock_disc_hdisk.return_value[1], devname)
        self.assertEqual(mock_disc_hdisk.return_value[2], udid)
        mock_get_itls.assert_called_once_with(mock_vios)
        mock_build_itls.assert_called_once_with('v_wwpns', 't_wwpns', 'lun')
        mock_disc_hdisk.assert_called_once_with(self.adpt, 'uuid', 'itls')
        mock_good_disc.assert_called_once_with('status', 'devname')
        mock_log.info.assert_called_once()
        mock_log.warning.assert_not_called()

        mock_log.reset_mock()

        # Bad discovery, not device in use status
        mock_good_disc.return_value = False
        self.vol_drv._discover_volume_on_vios(mock_vios)
        mock_log.warning.assert_not_called()
        mock_log.info.assert_not_called()

        # Bad discovery, device in use status
        mock_disc_hdisk.return_value = (hdisk.LUAStatus.DEVICE_IN_USE, 'dev',
                                        'udid')
        self.vol_drv._discover_volume_on_vios(mock_vios)
        mock_log.warning.assert_called_once()

    def test_get_hdisk_itls(self):
        """Validates the _get_hdisk_itls method."""

        mock_vios = mock.MagicMock()
        mock_vios.get_active_pfc_wwpns.return_value = [I_WWPN_1]

        i_wwpn, t_wwpns, lun = self.vol_drv._get_hdisk_itls(mock_vios)
        self.assertListEqual([I_WWPN_1], i_wwpn)
        self.assertListEqual(['t1'], t_wwpns)
        self.assertEqual('1', lun)

        mock_vios.get_active_pfc_wwpns.return_value = [I_WWPN_2]
        i_wwpn, t_wwpns, lun = self.vol_drv._get_hdisk_itls(mock_vios)
        self.assertListEqual([I_WWPN_2], i_wwpn)
        self.assertListEqual(['t2', 't3'], t_wwpns)

        mock_vios.get_active_pfc_wwpns.return_value = ['12345']
        i_wwpn, t_wwpns, lun = self.vol_drv._get_hdisk_itls(mock_vios)
        self.assertListEqual([], i_wwpn)

    @mock.patch('pypowervm.wrappers.storage.PV', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.build_vscsi_mapping',
                autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.add_map', autospec=True)
    def test_add_append_mapping(self, mock_add_map, mock_bld_map, mock_pv):
        def test_afs(add_func):
            mock_vios = mock.create_autospec(pvm_vios.VIOS)
            self.assertEqual(mock_add_map.return_value, add_func(mock_vios))
            mock_pv.bld.assert_called_once_with(self.adpt, 'devname', tag=None)
            mock_bld_map.assert_called_once_with(
                None, mock_vios, self.vol_drv.vm_uuid,
                mock_pv.bld.return_value)
            mock_add_map.assert_called_once_with(
                mock_vios, mock_bld_map.return_value)

        self.wtsk.add_functor_subtask.side_effect = test_afs
        self.vol_drv._add_append_mapping('vios_uuid', 'devname')
        self.wtsk.add_functor_subtask.assert_called_once()

    @mock.patch('nova.virt.powervm.volume.fcvscsi.LOG.warning')
    @mock.patch('nova.virt.powervm.vm.get_instance_wrapper')
    @mock.patch('pypowervm.utils.transaction.FeedTask', autospec=True)
    def test_detach_volume(self, mock_feed_task, mock_get_wrap, mock_log):
        mock_lpar_wrap = mock.MagicMock()
        mock_lpar_wrap.can_modify_io.return_value = True, None
        mock_get_wrap.return_value = mock_lpar_wrap
        mock_detach_ftsk = mock_feed_task.return_value

        # Multiple vioses modified
        mock_ret = {'wrapper_task_rets': {'vios1': {'vio_modified': True},
                                          'vios2': {'vio_modified': True}}}
        mock_detach_ftsk.execute.return_value = mock_ret
        self.vol_drv.detach_volume()
        mock_feed_task.assert_called_once()
        mock_detach_ftsk.add_functor_subtask.assert_called_once_with(
            self.vol_drv._detach_vol_for_vio, provides='vio_modified',
            flag_update=False)
        mock_detach_ftsk.execute.assert_called_once_with()
        self.ftsk.execute.assert_called_once_with()
        mock_log.assert_not_called()

        # 1 vios modified
        mock_ret = {'wrapper_task_rets': {'vios1': {'vio_modified': True},
                                          'vios2': {'vio_modified': False}}}
        mock_detach_ftsk.execute.return_value = mock_ret
        self.vol_drv.detach_volume()
        mock_log.assert_not_called()

        # No vioses modifed
        mock_ret = {'wrapper_task_rets': {'vios1': {'vio_modified': False},
                                          'vios2': {'vio_modified': False}}}
        mock_detach_ftsk.execute.return_value = mock_ret
        self.vol_drv.detach_volume()
        mock_log.assert_called_once()

        # Raise if exception during execute
        mock_detach_ftsk.execute.side_effect = Exception()
        self.assertRaises(exc.VolumeDetachFailed, self.vol_drv.detach_volume)

        # Raise if vm in invalid state
        mock_lpar_wrap.can_modify_io.return_value = False, None
        self.assertRaises(exc.VolumeDetachFailed, self.vol_drv.detach_volume)

    @mock.patch('pypowervm.tasks.hdisk.good_discovery', autospec=True)
    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter.'
                '_discover_volume_on_vios')
    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter.'
                '_add_remove_mapping')
    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter.'
                '_add_remove_hdisk')
    @mock.patch('nova.virt.powervm.vm.get_vm_qp')
    def test_detach_vol_for_vio(self, mock_get_qp, mock_rm_hdisk, mock_rm_map,
                                mock_disc_vol, mock_good_disc):
        # Good detach, bdm data is found
        self.vol_drv._set_udid('udid')
        mock_vios = mock.MagicMock()
        mock_vios.uuid = 'vios_uuid'
        mock_vios.hdisk_from_uuid.return_value = 'devname'
        mock_get_qp.return_value = 'part_id'
        ret = self.vol_drv._detach_vol_for_vio(mock_vios)
        self.assertTrue(ret)
        mock_vios.hdisk_from_uuid.assert_called_once_with('udid')
        mock_rm_map.assert_called_once_with('part_id', 'vios_uuid', 'devname')
        mock_rm_hdisk.assert_called_once_with(mock_vios, 'devname')

        mock_vios.reset_mock()
        mock_rm_map.reset_mock()
        mock_rm_hdisk.reset_mock()

        # Good detach, no udid
        self.vol_drv._set_udid(None)
        mock_disc_vol.return_value = 'status', 'devname', 'udid'
        mock_good_disc.return_value = True
        ret = self.vol_drv._detach_vol_for_vio(mock_vios)
        self.assertTrue(ret)
        mock_vios.hdisk_from_uuid.assert_not_called()
        mock_disc_vol.assert_called_once_with(mock_vios)
        mock_good_disc.assert_called_once_with('status', 'devname')
        mock_rm_map.assert_called_once_with('part_id', 'vios_uuid', 'devname')
        mock_rm_hdisk.assert_called_once_with(mock_vios, 'devname')

        mock_vios.reset_mock()
        mock_disc_vol.reset_mock()
        mock_good_disc.reset_mock()
        mock_rm_map.reset_mock()
        mock_rm_hdisk.reset_mock()

        # Good detach, no device name
        self.vol_drv._set_udid('udid')
        mock_vios.hdisk_from_uuid.return_value = None
        ret = self.vol_drv._detach_vol_for_vio(mock_vios)
        self.assertTrue(ret)
        mock_vios.hdisk_from_uuid.assert_called_once_with('udid')
        mock_disc_vol.assert_called_once_with(mock_vios)
        mock_good_disc.assert_called_once_with('status', 'devname')
        mock_rm_map.assert_called_once_with('part_id', 'vios_uuid', 'devname')
        mock_rm_hdisk.assert_called_once_with(mock_vios, 'devname')

        mock_rm_map.reset_mock()
        mock_rm_hdisk.reset_mock()

        # Bad detach, invalid state
        mock_good_disc.return_value = False
        ret = self.vol_drv._detach_vol_for_vio(mock_vios)
        self.assertFalse(ret)
        mock_rm_map.assert_not_called()
        mock_rm_hdisk.assert_not_called()

        # Bad detach, exception discovering volume on vios
        mock_disc_vol.side_effect = Exception()
        ret = self.vol_drv._detach_vol_for_vio(mock_vios)
        self.assertFalse(ret)
        mock_rm_map.assert_not_called()
        mock_rm_hdisk.assert_not_called()

    @mock.patch('pypowervm.tasks.scsi_mapper.gen_match_func', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.remove_maps', autospec=True)
    def test_add_remove_mapping(self, mock_rm_maps, mock_gen_match):
        def test_afs(rm_func):
            mock_vios = mock.create_autospec(pvm_vios.VIOS)
            self.assertEqual(mock_rm_maps.return_value, rm_func(mock_vios))
            mock_gen_match.assert_called_once_with(
                pvm_stor.PV, names=['devname'])
            mock_rm_maps.assert_called_once_with(
                mock_vios, 'vm_uuid', mock_gen_match.return_value)

        self.wtsk.add_functor_subtask.side_effect = test_afs
        self.vol_drv._add_remove_mapping('vm_uuid', 'vios_uuid', 'devname')
        self.wtsk.add_functor_subtask.assert_called_once()

    @mock.patch('pypowervm.tasks.hdisk.remove_hdisk', autospec=True)
    @mock.patch('taskflow.task.FunctorTask', autospec=True)
    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter.'
                '_check_host_mappings')
    def test_add_remove_hdisk(self, mock_check_maps, mock_functask,
                              mock_rm_hdisk):
        mock_vios = mock.MagicMock()
        mock_vios.uuid = 'uuid'
        mock_check_maps.return_value = True
        self.vol_drv._add_remove_hdisk(mock_vios, 'devname')
        mock_functask.assert_not_called()
        self.ftsk.add_post_execute.assert_not_called()
        mock_check_maps.assert_called_once_with(mock_vios, 'devname')
        self.assertEqual(0, mock_rm_hdisk.call_count)

        def test_functor_task(rm_hdisk, name=None):
            rm_hdisk()
            return 'functor_task'

        mock_check_maps.return_value = False
        mock_functask.side_effect = test_functor_task
        self.vol_drv._add_remove_hdisk(mock_vios, 'devname')
        mock_functask.assert_called_once()
        self.ftsk.add_post_execute.assert_called_once_with('functor_task')
        mock_rm_hdisk.assert_called_once_with(self.adpt, CONF.host,
                                              'devname', 'uuid')

    @mock.patch('pypowervm.tasks.scsi_mapper.gen_match_func', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.find_maps', autospec=True)
    def test_check_host_mappings(self, mock_find_maps, mock_gen_match):
        mock_vios = mock.MagicMock()
        mock_vios.uuid = 'uuid2'
        mock_v1 = mock.MagicMock(scsi_mappings='scsi_maps_1', uuid='uuid1')
        mock_v2 = mock.MagicMock(scsi_mappings='scsi_maps_2', uuid='uuid2')
        mock_feed = [mock_v1, mock_v2]
        self.ftsk.feed = mock_feed

        # Multiple mappings found
        mock_find_maps.return_value = ['map1', 'map2']
        ret = self.vol_drv._check_host_mappings(mock_vios, 'devname')
        self.assertTrue(ret)
        mock_gen_match.assert_called_once_with(pvm_stor.PV, names=['devname'])
        mock_find_maps.assert_called_once_with('scsi_maps_2', None,
                                               mock_gen_match.return_value)

        # One mapping found
        mock_find_maps.return_value = ['map1']
        ret = self.vol_drv._check_host_mappings(mock_vios, 'devname')
        self.assertFalse(ret)

        # No mappings found
        mock_find_maps.return_value = []
        ret = self.vol_drv._check_host_mappings(mock_vios, 'devname')
        self.assertFalse(ret)
