# Copyright 2017,2018 IBM Corp.
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

import copy
import mock
import os
import six

from nova import conf
from nova import context
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova import test
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel
from nova.virt import fake
from nova.virt.zvm import driver as zvmdriver


CONF = conf.CONF


class TestZVMDriver(test.NoDBTestCase):

    def setUp(self):
        super(TestZVMDriver, self).setUp()
        self.flags(my_ip='192.168.1.1',
                   instance_name_template='abc%05d')
        self.flags(cloud_connector_url='https://1.1.1.1:1111', group='zvm')

        with mock.patch('nova.virt.zvm.utils.ConnectorClient.call') as mcall, \
            mock.patch('pwd.getpwuid', return_value=mock.Mock(pw_name='test')):
            mcall.return_value = {'hypervisor_hostname': 'TESTHOST',
                                  'ipl_time': 'IPL at 11/14/17 10:47:44 EST'}
            self._driver = zvmdriver.ZVMDriver(fake.FakeVirtAPI())
            self._hypervisor = self._driver._hypervisor

        self._context = context.RequestContext('fake_user', 'fake_project')
        self._image_id = uuidsentinel.imag_id

        self._instance_values = {
            'display_name': 'test',
            'uuid': uuidsentinel.inst_id,
            'vcpus': 1,
            'memory_mb': 1024,
            'image_ref': self._image_id,
            'root_gb': 0,
        }
        self._instance = fake_instance.fake_instance_obj(
                                self._context, **self._instance_values)
        self._instance.flavor = objects.Flavor(name='testflavor',
                                vcpus=1, root_gb=3, ephemeral_gb=10,
                                swap=0, memory_mb=512, extra_specs={})

        self._eph_disks = [{'guest_format': u'ext3',
                            'device_name': u'/dev/sdb',
                            'disk_bus': None,
                            'device_type': None,
                            'size': 1},
                           {'guest_format': u'ext4',
                            'device_name': u'/dev/sdc',
                            'disk_bus': None,
                            'device_type': None,
                            'size': 2}]
        self._block_device_info = {'swap': None,
                                   'root_device_name': u'/dev/sda',
                                   'ephemerals': self._eph_disks,
                                   'block_device_mapping': []}
        fake_image_meta = {'status': 'active',
                           'properties': {'os_distro': 'rhel7.2'},
                           'name': 'rhel72eckdimage',
                           'deleted': False,
                           'container_format': 'bare',
                           'disk_format': 'raw',
                           'id': self._image_id,
                           'owner': 'cfc26f9d6af948018621ab00a1675310',
                           'checksum': 'b026cd083ef8e9610a29eaf71459cc',
                           'min_disk': 0,
                           'is_public': False,
                           'deleted_at': None,
                           'min_ram': 0,
                           'size': 465448142}
        self._image_meta = objects.ImageMeta.from_dict(fake_image_meta)
        subnet_4 = network_model.Subnet(cidr='192.168.0.1/24',
                                        dns=[network_model.IP('192.168.0.1')],
                                        gateway=
                                            network_model.IP('192.168.0.1'),
                                        ips=[
                                            network_model.IP('192.168.0.100')],
                                        routes=None)
        network = network_model.Network(id=0,
                                        bridge='fa0',
                                        label='fake',
                                        subnets=[subnet_4],
                                        vlan=None,
                                        bridge_interface=None,
                                        injected=True)
        self._network_values = {
            'id': None,
            'address': 'DE:AD:BE:EF:00:00',
            'network': network,
            'type': network_model.VIF_TYPE_OVS,
            'devname': None,
            'ovs_interfaceid': None,
            'rxtx_cap': 3
        }
        self._network_info = network_model.NetworkInfo([
                network_model.VIF(**self._network_values)
        ])

        self.mock_update_task_state = mock.Mock()

    def test_driver_init_no_url(self):
        self.flags(cloud_connector_url=None, group='zvm')
        self.assertRaises(exception.ZVMDriverException,
                          zvmdriver.ZVMDriver, 'virtapi')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_available_resource_err_case(self, call):
        res = {'overallRC': 1, 'errmsg': 'err', 'rc': 0, 'rs': 0}
        call.side_effect = exception.ZVMConnectorError(res)
        results = self._driver.get_available_resource()
        self.assertEqual(0, results['vcpus'])
        self.assertEqual(0, results['memory_mb_used'])
        self.assertEqual(0, results['disk_available_least'])
        self.assertEqual('TESTHOST', results['hypervisor_hostname'])

    def test_driver_template_validation(self):
        self.flags(instance_name_template='abc%6d')
        self.assertRaises(exception.ZVMDriverException,
                          self._driver._validate_options)

    @mock.patch('nova.virt.zvm.guest.Guest.get_info')
    def test_get_info(self, mock_get):
        self._driver.get_info(self._instance)
        mock_get.assert_called_once_with()

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_private_get_image_info_err(self, call):
        res = {'overallRC': 500, 'errmsg': 'err', 'rc': 0, 'rs': 0}
        call.side_effect = exception.ZVMConnectorError(res)
        self.assertRaises(exception.ZVMConnectorError,
                          self._driver._get_image_info,
                          'context', 'image_meta_id', 'os_distro')

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    @mock.patch('nova.virt.zvm.driver.ZVMDriver._import_spawn_image')
    def test_private_get_image_info(self, image_import, call):
        res = {'overallRC': 404, 'errmsg': 'err', 'rc': 0, 'rs': 0}

        call_response = []
        call_response.append(exception.ZVMConnectorError(results=res))
        call_response.append([{'imagename': 'image-info'}])
        call.side_effect = call_response
        self._driver._get_image_info('context', 'image_meta_id', 'os_distro')
        image_import.assert_called_once_with('context', 'image_meta_id',
                                             'os_distro')
        call.assert_has_calls(
            [mock.call('image_query', imagename='image_meta_id')] * 2
        )

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_private_get_image_info_exist(self, call):
        call.return_value = [{'imagename': 'image-info'}]
        res = self._driver._get_image_info('context', 'image_meta_id',
                                          'os_distro')
        call.assert_called_once_with('image_query', imagename='image_meta_id')
        self.assertEqual('image-info', res)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def _test_set_disk_list(self, call, has_get_root_units=False,
                            has_eph_disks=False):
        disk_list = [{'is_boot_disk': True, 'size': '3g'}]
        eph_disk_list = [{'format': u'ext3', 'size': '1g'},
                         {'format': u'ext3', 'size': '2g'}]
        _inst = copy.deepcopy(self._instance)
        _bdi = copy.deepcopy(self._block_device_info)

        if has_get_root_units:
            # overwrite
            disk_list = [{'is_boot_disk': True, 'size': '3338'}]
            call.return_value = '3338'
            _inst['root_gb'] = 0
        else:
            _inst['root_gb'] = 3

        if has_eph_disks:
            disk_list += eph_disk_list
        else:
            _bdi['ephemerals'] = []
            eph_disk_list = []

        res1, res2 = self._driver._set_disk_list(_inst, self._image_meta.id,
                                                 _bdi)

        if has_get_root_units:
            call.assert_called_once_with('image_get_root_disk_size',
                                         self._image_meta.id)
        self.assertEqual(disk_list, res1)
        self.assertEqual(eph_disk_list, res2)

    def test_private_set_disk_list_simple(self):
        self._test_set_disk_list()

    def test_private_set_disk_list_with_eph_disks(self):
        self._test_set_disk_list(has_eph_disks=True)

    def test_private_set_disk_list_with_get_root_units(self):
        self._test_set_disk_list(has_get_root_units=True)

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_private_setup_network(self, call):
        inst_nets = []
        _net = {'ip_addr': '192.168.0.100',
                'gateway_addr': '192.168.0.1',
                'cidr': '192.168.0.1/24',
                'mac_addr': 'DE:AD:BE:EF:00:00',
                'nic_id': None}
        inst_nets.append(_net)
        self._driver._setup_network('vm_name', 'os_distro',
                                     self._network_info,
                                     self._instance)
        call.assert_called_once_with('guest_create_network_interface',
                                     'vm_name', 'os_distro', inst_nets)

    @mock.patch('nova.virt.images.fetch')
    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_private_import_spawn_image(self, call, fetch):

        image_name = CONF.zvm.image_tmp_path + '/image_name'
        image_url = "file://" + image_name
        image_meta = {'os_version': 'os_version'}
        with mock.patch('os.path.exists', side_effect=[False]):
            self._driver._import_spawn_image(self._context, 'image_name',
                                            'os_version')
        fetch.assert_called_once_with(self._context, 'image_name',
                                      image_name)
        call.assert_called_once_with('image_import', 'image_name', image_url,
                        image_meta, remote_host='test@192.168.1.1')

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_exists')
    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_destroy(self, call, guest_exists):
        guest_exists.return_value = True
        self._driver.destroy(self._context, self._instance,
                             network_info=self._network_info)
        call.assert_called_once_with('guest_delete', self._instance['name'])

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_exists')
    @mock.patch('nova.compute.manager.ComputeVirtAPI.wait_for_instance_event')
    @mock.patch('nova.virt.zvm.driver.ZVMDriver._setup_network')
    @mock.patch('nova.virt.zvm.driver.ZVMDriver._set_disk_list')
    @mock.patch('nova.virt.zvm.utils.generate_configdrive')
    @mock.patch('nova.virt.zvm.driver.ZVMDriver._get_image_info')
    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_spawn(self, call, get_image_info, gen_conf_file, set_disk_list,
                   setup_network, mock_wait, mock_exists):
        _bdi = copy.copy(self._block_device_info)
        get_image_info.return_value = 'image_name'
        gen_conf_file.return_value = 'transportfiles'
        set_disk_list.return_value = 'disk_list', 'eph_list'
        mock_exists.return_value = False
        self._driver.spawn(self._context, self._instance, self._image_meta,
                          injected_files=None, admin_password=None,
                          allocations=None, network_info=self._network_info,
                          block_device_info=_bdi)
        gen_conf_file.assert_called_once_with(self._context, self._instance,
                                              None, self._network_info, None)
        get_image_info.assert_called_once_with(self._context,
                                    self._image_meta.id,
                                    self._image_meta.properties.os_distro)
        set_disk_list.assert_called_once_with(self._instance, 'image_name',
                                              _bdi)
        setup_network.assert_called_once_with(self._instance.name,
                                self._image_meta.properties.os_distro,
                                self._network_info, self._instance)

        call.assert_has_calls([
            mock.call('guest_create', self._instance.name,
                      1, 1024, disk_list='disk_list'),
            mock.call('guest_deploy', self._instance.name, 'image_name',
                      transportfiles='transportfiles',
                      remotehost='test@192.168.1.1'),
            mock.call('guest_config_minidisks', self._instance.name,
                      'eph_list'),
            mock.call('guest_start', self._instance.name)
        ])

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_exists')
    @mock.patch('nova.virt.zvm.driver.ZVMDriver._get_image_info')
    def test_spawn_image_no_distro_empty(self, get_image_info, mock_exists):
        meta = {'status': 'active',
                'deleted': False,
                'properties': {'os_distro': ''},
                'id': self._image_id,
                'size': 465448142}
        self._image_meta = objects.ImageMeta.from_dict(meta)
        mock_exists.return_value = False
        self.assertRaises(exception.InvalidInput, self._driver.spawn,
                          self._context, self._instance, self._image_meta,
                          injected_files=None, admin_password=None,
                          allocations=None, network_info=self._network_info,
                          block_device_info=None)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_exists')
    @mock.patch('nova.virt.zvm.driver.ZVMDriver._get_image_info')
    def test_spawn_image_no_distro_none(self, get_image_info, mock_exists):
        meta = {'status': 'active',
                'deleted': False,
                'id': self._image_id,
                'size': 465448142}
        self._image_meta = objects.ImageMeta.from_dict(meta)
        mock_exists.return_value = False
        self.assertRaises(exception.InvalidInput, self._driver.spawn,
                          self._context, self._instance, self._image_meta,
                          injected_files=None, admin_password=None,
                          allocations=None, network_info=self._network_info,
                          block_device_info=None)

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.get_remote_image_service')
    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_snapshot(self, call, get_image_service, mock_open):
        image_service = mock.Mock()
        image_id = 'e9ee1562-3ea1-4cb1-9f4c-f2033000eab1'
        get_image_service.return_value = (image_service, image_id)
        call_resp = ['', {"os_version": "rhel7.2",
                          "dest_url": "file:///path/to/target"}, '']
        call.side_effect = call_resp
        new_image_meta = {
            'is_public': False,
            'status': 'active',
            'properties': {
                 'image_location': 'snapshot',
                 'image_state': 'available',
                 'owner_id': self._instance['project_id'],
                 'os_distro': call_resp[1]['os_version'],
                 'architecture': 's390x',
                 'hypervisor_type': 'zvm'
            },
            'disk_format': 'raw',
            'container_format': 'bare',
        }
        image_path = os.path.join(os.path.normpath(
                            CONF.zvm.image_tmp_path), image_id)
        dest_path = "file://" + image_path

        self._driver.snapshot(self._context, self._instance, image_id,
                              self.mock_update_task_state)
        get_image_service.assert_called_with(self._context, image_id)

        mock_open.assert_called_once_with(image_path, 'r')
        ret_file = mock_open.return_value.__enter__.return_value
        image_service.update.assert_called_once_with(self._context,
                                                     image_id,
                                                     new_image_meta,
                                                     ret_file,
                                                     purge_props=False)
        self.mock_update_task_state.assert_has_calls([
            mock.call(task_state='image_pending_upload'),
            mock.call(expected_state='image_pending_upload',
                      task_state='image_uploading')
        ])
        call.assert_has_calls([
            mock.call('guest_capture', self._instance.name, image_id),
            mock.call('image_export', image_id, dest_path,
                      remote_host=mock.ANY),
            mock.call('image_delete', image_id)
        ])

    @mock.patch('nova.image.glance.get_remote_image_service')
    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_capture')
    def test_snapshot_capture_fail(self, mock_capture, get_image_service):
        image_service = mock.Mock()
        image_id = 'e9ee1562-3ea1-4cb1-9f4c-f2033000eab1'
        get_image_service.return_value = (image_service, image_id)
        mock_capture.side_effect = exception.ZVMDriverException(error='error')

        self.assertRaises(exception.ZVMDriverException, self._driver.snapshot,
                          self._context, self._instance, image_id,
                          self.mock_update_task_state)

        self.mock_update_task_state.assert_called_once_with(
            task_state='image_pending_upload')
        image_service.delete.assert_called_once_with(self._context, image_id)

    @mock.patch('nova.image.glance.get_remote_image_service')
    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.image_delete')
    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.image_export')
    def test_snapshot_import_fail(self, mock_import, mock_delete,
                                  call, get_image_service):
        image_service = mock.Mock()
        image_id = 'e9ee1562-3ea1-4cb1-9f4c-f2033000eab1'
        get_image_service.return_value = (image_service, image_id)

        mock_import.side_effect = exception.ZVMDriverException(error='error')

        self.assertRaises(exception.ZVMDriverException, self._driver.snapshot,
                          self._context, self._instance, image_id,
                          self.mock_update_task_state)

        self.mock_update_task_state.assert_called_once_with(
            task_state='image_pending_upload')
        get_image_service.assert_called_with(self._context, image_id)
        call.assert_called_once_with('guest_capture',
                                     self._instance.name, image_id)
        mock_delete.assert_called_once_with(image_id)
        image_service.delete.assert_called_once_with(self._context, image_id)

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.get_remote_image_service')
    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.image_delete')
    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.image_export')
    def test_snapshot_update_fail(self, mock_import, mock_delete, call,
                                  get_image_service, mock_open):
        image_service = mock.Mock()
        image_id = 'e9ee1562-3ea1-4cb1-9f4c-f2033000eab1'
        get_image_service.return_value = (image_service, image_id)
        image_service.update.side_effect = exception.ImageNotAuthorized(
            image_id='dummy')
        image_path = os.path.join(os.path.normpath(
                            CONF.zvm.image_tmp_path), image_id)

        self.assertRaises(exception.ImageNotAuthorized, self._driver.snapshot,
                          self._context, self._instance, image_id,
                          self.mock_update_task_state)

        mock_open.assert_called_once_with(image_path, 'r')

        get_image_service.assert_called_with(self._context, image_id)
        mock_delete.assert_called_once_with(image_id)
        image_service.delete.assert_called_once_with(self._context, image_id)

        self.mock_update_task_state.assert_has_calls([
            mock.call(task_state='image_pending_upload'),
            mock.call(expected_state='image_pending_upload',
                      task_state='image_uploading')
        ])

        call.assert_called_once_with('guest_capture', self._instance.name,
                                     image_id)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_start')
    def test_guest_start(self, call):
        self._driver.power_on(self._context, self._instance, None)
        call.assert_called_once_with(self._instance.name)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_softstop')
    def test_power_off(self, ipa):
        self._driver.power_off(self._instance)
        ipa.assert_called_once_with(self._instance.name)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_softstop')
    def test_power_off_with_timeout_interval(self, ipa):
        self._driver.power_off(self._instance, 60, 10)
        ipa.assert_called_once_with(self._instance.name,
                                    timeout=60, retry_interval=10)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_pause')
    def test_pause(self, ipa):
        self._driver.pause(self._instance)
        ipa.assert_called_once_with(self._instance.name)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_unpause')
    def test_unpause(self, ipa):
        self._driver.unpause(self._instance)
        ipa.assert_called_once_with(self._instance.name)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_reboot')
    def test_reboot_soft(self, ipa):
        self._driver.reboot(None, self._instance, None, 'SOFT')
        ipa.assert_called_once_with(self._instance.name)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.guest_reset')
    def test_reboot_hard(self, ipa):
        self._driver.reboot(None, self._instance, None, 'HARD')
        ipa.assert_called_once_with(self._instance.name)

    @mock.patch('nova.virt.zvm.hypervisor.Hypervisor.list_names')
    def test_instance_exists(self, mock_list):
        mock_list.return_value = [self._instance.name.upper()]
        # Create a new server which not in list_instances's output
        another_instance = fake_instance.fake_instance_obj(self._context,
                                                           id=10)
        self.assertTrue(self._driver.instance_exists(self._instance))
        self.assertFalse(self._driver.instance_exists(another_instance))

    @mock.patch('nova.virt.zvm.utils.ConnectorClient.call')
    def test_get_console_output(self, call):
        call.return_value = 'console output'
        outputs = self._driver.get_console_output(None, self._instance)
        call.assert_called_once_with('guest_get_console_output', 'abc00001')
        self.assertEqual('console output', outputs)
