# Copyright 2015, 2017 IBM Corp.
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

import fixtures
import mock
from oslo_utils.fixture import uuidsentinel
from pypowervm import const as pvm_const
from pypowervm.tasks import scsi_mapper as tsk_map
from pypowervm.tests import test_fixtures as pvm_fx
from pypowervm.utils import transaction as pvm_tx
from pypowervm.wrappers import network as pvm_net
from pypowervm.wrappers import storage as pvm_stg
from pypowervm.wrappers import virtual_io_server as pvm_vios

from nova import test
from nova.virt.powervm import media as m


class TestConfigDrivePowerVM(test.NoDBTestCase):
    """Unit Tests for the ConfigDrivePowerVM class."""

    def setUp(self):
        super(TestConfigDrivePowerVM, self).setUp()

        self.apt = self.useFixture(pvm_fx.AdapterFx()).adpt

        self.validate_vopt = self.useFixture(fixtures.MockPatch(
            'pypowervm.tasks.vopt.validate_vopt_repo_exists',
            autospec=True)).mock
        self.validate_vopt.return_value = 'vios_uuid', 'vg_uuid'

    @mock.patch('nova.api.metadata.base.InstanceMetadata')
    @mock.patch('nova.virt.configdrive.ConfigDriveBuilder.make_drive')
    def test_crt_cfg_dr_iso(self, mock_mkdrv, mock_meta):
        """Validates that the image creation method works."""
        cfg_dr_builder = m.ConfigDrivePowerVM(self.apt)
        self.assertTrue(self.validate_vopt.called)
        mock_instance = mock.MagicMock()
        mock_instance.uuid = uuidsentinel.inst_id
        mock_files = mock.MagicMock()
        mock_net = mock.MagicMock()
        iso_path = '/tmp/cfgdrv.iso'
        cfg_dr_builder._create_cfg_dr_iso(mock_instance, mock_files, mock_net,
                                          iso_path)
        self.assertEqual(mock_mkdrv.call_count, 1)

        # Test retry iso create
        mock_mkdrv.reset_mock()
        mock_mkdrv.side_effect = [OSError, mock_mkdrv]
        cfg_dr_builder._create_cfg_dr_iso(mock_instance, mock_files, mock_net,
                                          iso_path)
        self.assertEqual(mock_mkdrv.call_count, 2)

    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch('nova.virt.powervm.vm.get_pvm_uuid')
    @mock.patch('pypowervm.tasks.scsi_mapper.build_vscsi_mapping')
    @mock.patch('pypowervm.tasks.scsi_mapper.add_map')
    @mock.patch('os.path.getsize')
    @mock.patch('pypowervm.tasks.storage.upload_vopt')
    @mock.patch('nova.virt.powervm.media.ConfigDrivePowerVM.'
                '_create_cfg_dr_iso')
    def test_create_cfg_drv_vopt(self, mock_ccdi, mock_upl, mock_getsize,
                                 mock_addmap, mock_bldmap, mock_vm_id,
                                 mock_ntf):
        cfg_dr = m.ConfigDrivePowerVM(self.apt)
        mock_instance = mock.MagicMock()
        mock_instance.uuid = uuidsentinel.inst_id
        mock_upl.return_value = 'vopt', 'f_uuid'
        fh = mock_ntf.return_value.__enter__.return_value
        fh.name = 'iso_path'
        wtsk = mock.create_autospec(pvm_tx.WrapperTask, instance=True)
        ftsk = mock.create_autospec(pvm_tx.FeedTask, instance=True)
        ftsk.configure_mock(wrapper_tasks={'vios_uuid': wtsk})

        def test_afs(add_func):
            # Validate the internal add_func
            vio = mock.create_autospec(pvm_vios.VIOS)
            self.assertEqual(mock_addmap.return_value, add_func(vio))
            mock_vm_id.assert_called_once_with(mock_instance)
            mock_bldmap.assert_called_once_with(
                None, vio, mock_vm_id.return_value, 'vopt')
            mock_addmap.assert_called_once_with(vio, mock_bldmap.return_value)
        wtsk.add_functor_subtask.side_effect = test_afs

        # calculate expected file name
        expected_file_name = 'cfg_' + mock_instance.uuid.replace('-', '')
        allowed_len = pvm_const.MaxLen.VOPT_NAME - 4  # '.iso' is 4 chars
        expected_file_name = expected_file_name[:allowed_len] + '.iso'

        cfg_dr.create_cfg_drv_vopt(
            mock_instance, 'files', 'netinfo', ftsk, admin_pass='pass')

        mock_ntf.assert_called_once_with(mode='rb')
        mock_ccdi.assert_called_once_with(mock_instance, 'files', 'netinfo',
                                          'iso_path', admin_pass='pass')
        mock_getsize.assert_called_once_with('iso_path')
        mock_upl.assert_called_once_with(self.apt, 'vios_uuid', fh,
                                         expected_file_name,
                                         mock_getsize.return_value)
        wtsk.add_functor_subtask.assert_called_once()

    def test_sanitize_network_info(self):
        network_info = [{'type': 'lbr'}, {'type': 'pvm_sea'},
                        {'type': 'ovs'}]

        cfg_dr_builder = m.ConfigDrivePowerVM(self.apt)

        resp = cfg_dr_builder._sanitize_network_info(network_info)
        expected_ret = [{'type': 'vif'}, {'type': 'vif'},
                        {'type': 'ovs'}]
        self.assertEqual(resp, expected_ret)

    @mock.patch('pypowervm.wrappers.storage.VG', autospec=True)
    @mock.patch('pypowervm.tasks.storage.rm_vg_storage', autospec=True)
    @mock.patch('nova.virt.powervm.vm.get_pvm_uuid')
    @mock.patch('pypowervm.tasks.scsi_mapper.gen_match_func', autospec=True)
    @mock.patch('pypowervm.tasks.scsi_mapper.find_maps', autospec=True)
    @mock.patch('pypowervm.wrappers.virtual_io_server.VIOS', autospec=True)
    @mock.patch('taskflow.task.FunctorTask', autospec=True)
    def test_dlt_vopt(self, mock_functask, mock_vios, mock_find_maps, mock_gmf,
                      mock_uuid, mock_rmstg, mock_vg):
        cfg_dr = m.ConfigDrivePowerVM(self.apt)
        wtsk = mock.create_autospec(pvm_tx.WrapperTask, instance=True)
        ftsk = mock.create_autospec(pvm_tx.FeedTask, instance=True)
        ftsk.configure_mock(wrapper_tasks={'vios_uuid': wtsk})

        # Test with no media to remove
        mock_find_maps.return_value = []
        cfg_dr.dlt_vopt('inst', ftsk)
        mock_uuid.assert_called_once_with('inst')
        mock_gmf.assert_called_once_with(pvm_stg.VOptMedia)
        wtsk.add_functor_subtask.assert_called_once_with(
            tsk_map.remove_maps, mock_uuid.return_value,
            match_func=mock_gmf.return_value)
        ftsk.get_wrapper.assert_called_once_with('vios_uuid')
        mock_find_maps.assert_called_once_with(
            ftsk.get_wrapper.return_value.scsi_mappings,
            client_lpar_id=mock_uuid.return_value,
            match_func=mock_gmf.return_value)
        mock_functask.assert_not_called()

        # Test with media to remove
        mock_find_maps.return_value = [mock.Mock(backing_storage=media)
                                       for media in ['m1', 'm2']]

        def test_functor_task(rm_vopt):
            # Validate internal rm_vopt function
            rm_vopt()
            mock_vg.get.assert_called_once_with(
                self.apt, uuid='vg_uuid', parent_type=pvm_vios.VIOS,
                parent_uuid='vios_uuid')
            mock_rmstg.assert_called_once_with(
                mock_vg.get.return_value, vopts=['m1', 'm2'])
            return 'functor_task'
        mock_functask.side_effect = test_functor_task

        cfg_dr.dlt_vopt('inst', ftsk)
        mock_functask.assert_called_once()
        ftsk.add_post_execute.assert_called_once_with('functor_task')

    def test_mgmt_cna_to_vif(self):
        mock_cna = mock.Mock(spec=pvm_net.CNA, mac="FAD4433ED120")

        # Run
        cfg_dr_builder = m.ConfigDrivePowerVM(self.apt)
        vif = cfg_dr_builder._mgmt_cna_to_vif(mock_cna)

        # Validate
        self.assertEqual(vif.get('address'), "fa:d4:43:3e:d1:20")
        self.assertEqual(vif.get('id'), 'mgmt_vif')
        self.assertIsNotNone(vif.get('network'))
        self.assertEqual(1, len(vif.get('network').get('subnets')))
        subnet = vif.get('network').get('subnets')[0]
        self.assertEqual(6, subnet.get('version'))
        self.assertEqual('fe80::/64', subnet.get('cidr'))
        ip = subnet.get('ips')[0]
        self.assertEqual('fe80::f8d4:43ff:fe3e:d120', ip.get('address'))

    def test_mac_to_link_local(self):
        mac = 'fa:d4:43:3e:d1:20'
        self.assertEqual('fe80::f8d4:43ff:fe3e:d120',
                         m.ConfigDrivePowerVM._mac_to_link_local(mac))

        mac = '00:00:00:00:00:00'
        self.assertEqual('fe80::0200:00ff:fe00:0000',
                         m.ConfigDrivePowerVM._mac_to_link_local(mac))

        mac = 'ff:ff:ff:ff:ff:ff'
        self.assertEqual('fe80::fdff:ffff:feff:ffff',
        m.ConfigDrivePowerVM._mac_to_link_local(mac))
