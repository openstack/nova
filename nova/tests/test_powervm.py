# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM Corp.
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

"""
Test suite for PowerVMDriver.
"""

import contextlib

from nova import context
from nova import db
from nova import test

from nova.compute import instance_types
from nova.compute import power_state
from nova.compute import task_states
from nova.network import model as network_model
from nova.openstack.common import log as logging
from nova.tests import fake_network_cache_model
from nova.tests.image import fake
from nova.virt import images
from nova.virt.powervm import blockdev as powervm_blockdev
from nova.virt.powervm import common
from nova.virt.powervm import driver as powervm_driver
from nova.virt.powervm import exception
from nova.virt.powervm import lpar
from nova.virt.powervm import operator

LOG = logging.getLogger(__name__)


def fake_lpar(instance_name):
    return lpar.LPAR(name=instance_name,
                     lpar_id=1, desired_mem=1024,
                     max_mem=2048, max_procs=2,
                     uptime=939395, state='Running')


class FakeIVMOperator(object):

    def get_lpar(self, instance_name, resource_type='lpar'):
        return fake_lpar(instance_name)

    def list_lpar_instances(self):
        return ['instance-00000001', 'instance-00000002']

    def create_lpar(self, lpar):
        pass

    def start_lpar(self, instance_name):
        pass

    def stop_lpar(self, instance_name, time_out=30):
        pass

    def remove_lpar(self, instance_name):
        pass

    def get_vhost_by_instance_id(self, instance_id):
        return 'vhostfake'

    def get_virtual_eth_adapter_id(self):
        return 1

    def get_disk_name_by_vhost(self, vhost):
        return 'lvfake01'

    def remove_disk(self, disk_name):
        pass

    def run_cfg_dev(self, device_name):
        pass

    def attach_disk_to_vhost(self, disk, vhost):
        pass

    def get_memory_info(self):
        return {'total_mem': 65536, 'avail_mem': 46336}

    def get_cpu_info(self):
        return {'total_procs': 8.0, 'avail_procs': 6.3}

    def get_disk_info(self):
        return {'disk_total': 10168,
                'disk_used': 0,
                'disk_avail': 10168}

    def get_hostname(self):
        return 'fake-powervm'

    def rename_lpar(self, old, new):
        pass

    def set_lpar_mac_base_value(self, instance_name, mac):
        pass

    def get_logical_vol_size(self, diskname):
        pass

    def macs_for_instance(self, instance):
        return set(['FA:98:64:2B:29:39'])

    def run_vios_command(self, cmd):
        pass


class FakeBlockAdapter(powervm_blockdev.PowerVMLocalVolumeAdapter):

    def __init__(self):
        self.connection_data = common.Connection(host='fake_compute_1',
                                                  username='fake_user',
                                                  password='fake_pass')
        pass

    def _create_logical_volume(self, size):
        return 'lvfake01'

    def _remove_logical_volume(self, lv_name):
        pass

    def _copy_file_to_device(self, sourcePath, device, decrompress=True):
        pass

    def _copy_image_file(self, sourcePath, remotePath, decompress=False):
        finalPath = '/tmp/rhel62.raw.7e358754160433febd6f3318b7c9e335'
        size = 4294967296
        return finalPath, size

    def _copy_device_to_file(self, device_name, file_path):
        pass

    def _copy_image_file_from_host(self, remote_source_path, local_dest_dir,
                                   compress=False):
        snapshot_file = '/tmp/rhel62.raw.7e358754160433febd6f3318b7c9e335'
        snap_ref = open(snapshot_file, 'w+')
        snap_ref.close()
        return snapshot_file


def fake_get_powervm_operator():
    return FakeIVMOperator()


class PowerVMDriverTestCase(test.TestCase):
    """Unit tests for PowerVM connection calls."""

    def setUp(self):
        super(PowerVMDriverTestCase, self).setUp()
        self.stubs.Set(operator, 'get_powervm_operator',
                       fake_get_powervm_operator)
        self.stubs.Set(operator, 'get_powervm_disk_adapter',
                       lambda: FakeBlockAdapter())
        self.powervm_connection = powervm_driver.PowerVMDriver(None)
        self.instance = self._create_instance()

    def _create_instance(self):
        fake.stub_out_image_service(self.stubs)
        ctxt = context.get_admin_context()
        instance_type = db.instance_type_get(ctxt, 1)
        sys_meta = instance_types.save_instance_type_info({}, instance_type)
        return db.instance_create(ctxt,
                        {'user_id': 'fake',
                        'project_id': 'fake',
                        'instance_type_id': 1,
                        'memory_mb': 1024,
                        'vcpus': 2,
                        'image_ref': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                        'system_metadata': sys_meta})

    def test_list_instances(self):
        instances = self.powervm_connection.list_instances()
        self.assertTrue('instance-00000001' in instances)
        self.assertTrue('instance-00000002' in instances)

    def test_instance_exists(self):
        name = self.instance['name']
        self.assertTrue(self.powervm_connection.instance_exists(name))

    def test_spawn(self):
        def fake_image_fetch(context, image_id, file_path,
                                    user_id, project_id):
            pass
        self.flags(powervm_img_local_path='/images/')
        self.stubs.Set(images, 'fetch', fake_image_fetch)
        image_meta = {}
        image_meta['id'] = '666'
        fake_net_info = network_model.NetworkInfo([
                                     fake_network_cache_model.new_vif()])
        self.powervm_connection.spawn(context.get_admin_context(),
                                      self.instance, image_meta, [], 's3cr3t',
                                      fake_net_info)
        state = self.powervm_connection.get_info(self.instance)['state']
        self.assertEqual(state, power_state.RUNNING)

    def test_spawn_cleanup_on_fail(self):
        # Verify on a failed spawn, we get the original exception raised.
        # helper function
        def raise_(ex):
            raise ex

        self.flags(powervm_img_local_path='/images/')
        self.stubs.Set(images, 'fetch', lambda *x, **y: None)
        self.stubs.Set(
            self.powervm_connection._powervm._disk_adapter,
            'create_volume_from_image',
            lambda *x, **y: raise_(exception.PowerVMImageCreationFailed()))
        self.stubs.Set(
            self.powervm_connection._powervm, '_cleanup',
            lambda *x, **y: raise_(Exception('This should be logged.')))
        fake_net_info = network_model.NetworkInfo([
                                     fake_network_cache_model.new_vif()])
        self.assertRaises(exception.PowerVMImageCreationFailed,
                          self.powervm_connection.spawn,
                          context.get_admin_context(),
                          self.instance,
                          {'id': 'ANY_ID'}, [], 's3cr3t', fake_net_info)

    def test_snapshot(self):

        def update_task_state(task_state, expected_state=None):
            self._loc_task_state = task_state
            self._loc_expected_task_state = expected_state

        loc_context = context.get_admin_context()
        properties = {'instance_id': self.instance['id'],
                      'user_id': str(loc_context.user_id)}
        sent_meta = {'name': 'fake_snap', 'is_public': False,
                     'status': 'creating', 'properties': properties}
        image_service = fake.FakeImageService()
        recv_meta = image_service.create(loc_context, sent_meta)

        self.powervm_connection.snapshot(loc_context,
                                      self.instance, recv_meta['id'],
                                      update_task_state)

        self.assertTrue(self._loc_task_state == task_states.IMAGE_UPLOADING and
            self._loc_expected_task_state == task_states.IMAGE_PENDING_UPLOAD)

    def test_destroy(self):
        self.powervm_connection.destroy(self.instance, None)
        self.stubs.Set(FakeIVMOperator, 'get_lpar', lambda x, y: None)
        name = self.instance['name']
        self.assertFalse(self.powervm_connection.instance_exists(name))

    def test_get_info(self):
        info = self.powervm_connection.get_info(self.instance)
        self.assertEqual(info['state'], power_state.RUNNING)
        self.assertEqual(info['max_mem'], 2048)
        self.assertEqual(info['mem'], 1024)
        self.assertEqual(info['num_cpu'], 2)
        self.assertEqual(info['cpu_time'], 939395)

    def test_remote_utility_1(self):
        path_one = '/some/file/'
        path_two = '/path/filename'
        joined_path = common.aix_path_join(path_one, path_two)
        expected_path = '/some/file/path/filename'
        self.assertEqual(joined_path, expected_path)

    def test_remote_utility_2(self):
        path_one = '/some/file/'
        path_two = 'path/filename'
        joined_path = common.aix_path_join(path_one, path_two)
        expected_path = '/some/file/path/filename'
        self.assertEqual(joined_path, expected_path)

    def test_remote_utility_3(self):
        path_one = '/some/file'
        path_two = '/path/filename'
        joined_path = common.aix_path_join(path_one, path_two)
        expected_path = '/some/file/path/filename'
        self.assertEqual(joined_path, expected_path)

    def test_remote_utility_4(self):
        path_one = '/some/file'
        path_two = 'path/filename'
        joined_path = common.aix_path_join(path_one, path_two)
        expected_path = '/some/file/path/filename'
        self.assertEqual(joined_path, expected_path)

    def _test_finish_revert_migration_after_crash(self, backup_made, new_made):
        inst = {'name': 'foo'}
        network_info = []
        network_info.append({'address': 'fa:89:f0:8b:9b:39'})

        self.mox.StubOutWithMock(self.powervm_connection, 'instance_exists')
        self.mox.StubOutWithMock(self.powervm_connection._powervm, 'destroy')
        self.mox.StubOutWithMock(self.powervm_connection._powervm._operator,
                                 'rename_lpar')
        self.mox.StubOutWithMock(self.powervm_connection._powervm, 'power_on')
        self.mox.StubOutWithMock(self.powervm_connection._powervm._operator,
                                 'set_lpar_mac_base_value')

        self.powervm_connection.instance_exists('rsz_foo').AndReturn(
            backup_made)

        if backup_made:
            self.powervm_connection.instance_exists('foo').AndReturn(new_made)
            if new_made:
                self.powervm_connection._powervm.destroy('foo')
            self.powervm_connection._powervm._operator.rename_lpar('rsz_foo',
                                                                   'foo')
        self.powervm_connection._powervm._operator.set_lpar_mac_base_value(
                'foo', 'fa:89:f0:8b:9b:39')
        self.powervm_connection._powervm.power_on('foo')

        self.mox.ReplayAll()

        self.powervm_connection.finish_revert_migration(inst, network_info,
                                                    block_device_info=None)

    def test_finish_revert_migration_after_crash(self):
        self._test_finish_revert_migration_after_crash(True, True)

    def test_finish_revert_migration_after_crash_before_new(self):
        self._test_finish_revert_migration_after_crash(True, False)

    def test_finish_revert_migration_after_crash_before_backup(self):
        self._test_finish_revert_migration_after_crash(False, False)

    def test_migrate_volume_use_instance_name(self):
        inst_name = 'instance-00000000'
        lv_name = 'logical-vol-name'
        src_host = 'compute_host_1'
        dest = 'compute_host_1'
        image_path = 'some/image/path'
        fake_noop = lambda *args, **kwargs: None

        self.stubs.Set(self.powervm_connection._powervm._disk_adapter,
                       '_copy_device_to_file', fake_noop)

        self.stubs.Set(self.powervm_connection._powervm._disk_adapter,
                       'run_vios_command_as_root', fake_noop)
        blockdev_op = self.powervm_connection._powervm._disk_adapter
        file_path = blockdev_op.migrate_volume(lv_name, src_host, dest,
                                               image_path, inst_name)
        expected_path = 'some/image/path/instance-00000000_rsz.gz'
        self.assertEqual(file_path, expected_path)

    def test_migrate_volume_use_lv_name(self):
        lv_name = 'logical-vol-name'
        src_host = 'compute_host_1'
        dest = 'compute_host_1'
        image_path = 'some/image/path'
        fake_noop = lambda *args, **kwargs: None

        self.stubs.Set(self.powervm_connection._powervm._disk_adapter,
                       '_copy_device_to_file', fake_noop)

        self.stubs.Set(self.powervm_connection._powervm._disk_adapter,
                       'run_vios_command_as_root', fake_noop)
        blockdev_op = self.powervm_connection._powervm._disk_adapter
        file_path = blockdev_op.migrate_volume(lv_name, src_host, dest,
                                               image_path)
        expected_path = 'some/image/path/logical-vol-name_rsz.gz'
        self.assertEqual(file_path, expected_path)

    def test_set_lpar_mac_base_value(self):
        instance = self.instance
        context = 'fake_context'
        dest = '10.8.46.20'  # Some fake dest IP
        instance_type = 'fake_instance_type'
        network_info = []
        network_info.append({'address': 'fa:89:f0:8b:9b:39'})
        block_device_info = None
        self.flags(powervm_mgr=dest)
        fake_noop = lambda *args, **kwargs: None
        fake_op = self.powervm_connection._powervm._operator
        self.stubs.Set(fake_op, 'get_vhost_by_instance_id', fake_noop)
        self.stubs.Set(fake_op, 'get_disk_name_by_vhost', fake_noop)
        self.stubs.Set(self.powervm_connection._powervm, 'power_off',
                       fake_noop)
        self.stubs.Set(fake_op, 'get_logical_vol_size',
                       lambda *args, **kwargs: '20')
        self.stubs.Set(self.powervm_connection, '_get_resize_name', fake_noop)
        self.stubs.Set(fake_op, 'rename_lpar', fake_noop)

        def fake_migrate_disk(*args, **kwargs):
            disk_info = {}
            disk_info['fake_dict'] = 'some/file/path.gz'
            return disk_info

        def fake_set_lpar_mac_base_value(inst_name, mac, *args, **kwargs):
            # get expected mac address from FakeIVM set
            fake_ivm = FakeIVMOperator()
            exp_mac = fake_ivm.macs_for_instance(inst_name).pop()
            self.assertEqual(exp_mac, mac)

        self.stubs.Set(self.powervm_connection._powervm, 'migrate_disk',
                       fake_migrate_disk)
        self.stubs.Set(fake_op, 'set_lpar_mac_base_value',
                       fake_set_lpar_mac_base_value)
        disk_info = self.powervm_connection.migrate_disk_and_power_off(
                        context, instance,
                        dest, instance_type, network_info, block_device_info)

    def test_set_lpar_mac_base_value_command(self):
        inst_name = 'some_instance'
        mac = 'FA:98:64:2B:29:39'
        exp_mac_str = mac[:-2].replace(':', '').lower()

        def fake_run_vios_command(cmd, *args, **kwargs):
            exp_cmd = ('chsyscfg -r lpar -i "name=%(inst_name)s, ',
                       'virtual_eth_mac_base_value=%(exp_mac_str)s"' %
                       locals())
            assertEqual(exp_cmd, cmd)

        self.stubs.Set(self.powervm_connection._powervm._operator,
                       'run_vios_command', fake_run_vios_command)

        fake_op = self.powervm_connection._powervm
        fake_op._operator.set_lpar_mac_base_value(inst_name, mac)

    def test_migrate_build_scp_command(self):
        lv_name = 'logical-vol-name'
        src_host = 'compute_host_1'
        dest = 'compute_host_2'
        image_path = 'some/image/path'
        fake_noop = lambda *args, **kwargs: None

        @contextlib.contextmanager
        def fake_vios_to_vios_auth(*args, **kwargs):
            key_name = 'some_key'
            yield key_name
        self.stubs.Set(common, 'vios_to_vios_auth',
                       fake_vios_to_vios_auth)

        self.stubs.Set(self.powervm_connection._powervm._disk_adapter,
                       'run_vios_command_as_root', fake_noop)

        def fake_run_vios_command(*args, **kwargs):
            cmd = args[0]
            exp_cmd = ' '.join(['scp -o "StrictHostKeyChecking no" -i',
                                'some_key',
                                'some/image/path/logical-vol-name_rsz.gz',
                                'fake_user@compute_host_2:some/image/path'])
            self.assertEqual(exp_cmd, cmd)

        self.stubs.Set(self.powervm_connection._powervm._disk_adapter,
                       'run_vios_command',
                       fake_run_vios_command)

        blockdev_op = self.powervm_connection._powervm._disk_adapter
        file_path = blockdev_op.migrate_volume(lv_name, src_host, dest,
                                               image_path)

    def test_get_resize_name(self):
        inst_name = 'instance-00000001'
        expected_name = 'rsz_instance-00000001'
        result = self.powervm_connection._get_resize_name(inst_name)
        self.assertEqual(expected_name, result)

    def test_get_long_resize_name(self):
        inst_name = 'some_really_long_instance_name_00000001'
        expected_name = 'rsz__really_long_instance_name_00000001'
        result = self.powervm_connection._get_resize_name(inst_name)
        self.assertEqual(expected_name, result)

    def test_get_host_stats(self):
        host_stats = self.powervm_connection.get_host_stats(True)
        self.assertIsNotNone(host_stats)
        self.assertEquals(host_stats['vcpus'], 8.0)
        self.assertEquals(round(host_stats['vcpus_used'], 1), 1.7)
        self.assertEquals(host_stats['host_memory_total'], 65536)
        self.assertEquals(host_stats['host_memory_free'], 46336)
        self.assertEquals(host_stats['disk_total'], 10168)
        self.assertEquals(host_stats['disk_used'], 0)
        self.assertEquals(host_stats['disk_available'], 10168)
        self.assertEquals(host_stats['disk_total'],
                          host_stats['disk_used'] +
                          host_stats['disk_available'])

        self.assertEquals(host_stats['cpu_info'], ('ppc64', 'powervm', '3940'))
        self.assertEquals(host_stats['hypervisor_type'], 'powervm')
        self.assertEquals(host_stats['hypervisor_version'], '7.1')

        self.assertEquals(host_stats['hypervisor_hostname'], "fake-powervm")
        self.assertEquals(host_stats['supported_instances'][0][0], "ppc64")
        self.assertEquals(host_stats['supported_instances'][0][1], "powervm")
        self.assertEquals(host_stats['supported_instances'][0][2], "hvm")
