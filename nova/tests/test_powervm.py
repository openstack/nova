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

from nova import context
from nova import db
from nova import test

from nova.compute import power_state
from nova.network import model as network_model
from nova.openstack.common import log as logging
from nova.tests import fake_network_cache_model
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

    def stop_lpar(self, instance_name):
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


class FakeBlockAdapter(powervm_blockdev.PowerVMLocalVolumeAdapter):

    def __init__(self):
        pass

    def _create_logical_volume(self, size):
        return 'lvfake01'

    def _remove_logical_volume(self, lv_name):
        pass

    def _copy_file_to_device(self, sourcePath, device, decrompress=True):
        pass

    def _copy_image_file(self, sourcePath, remotePath, decompress=False):
        finalPath = '/home/images/rhel62.raw.7e358754160433febd6f3318b7c9e335'
        size = 4294967296
        return finalPath, size


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
        return db.instance_create(context.get_admin_context(),
                                  {'user_id': 'fake',
                                   'project_id': 'fake',
                                   'instance_type_id': 1,
                                   'memory_mb': 1024,
                                   'vcpus': 2})

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

        self.mox.StubOutWithMock(self.powervm_connection, 'instance_exists')
        self.mox.StubOutWithMock(self.powervm_connection._powervm, 'destroy')
        self.mox.StubOutWithMock(self.powervm_connection._powervm._operator,
                                 'rename_lpar')
        self.mox.StubOutWithMock(self.powervm_connection._powervm, 'power_on')

        self.powervm_connection.instance_exists('rsz_foo').AndReturn(
            backup_made)

        if backup_made:
            self.powervm_connection.instance_exists('foo').AndReturn(new_made)
            if new_made:
                self.powervm_connection._powervm.destroy('foo')
            self.powervm_connection._powervm._operator.rename_lpar('rsz_foo',
                                                                   'foo')
        self.powervm_connection._powervm.power_on('foo')

        self.mox.ReplayAll()

        self.powervm_connection.finish_revert_migration(inst, [])

    def test_finish_revert_migration_after_crash(self):
        self._test_finish_revert_migration_after_crash(True, True)

    def test_finish_revert_migration_after_crash_before_new(self):
        self._test_finish_revert_migration_after_crash(True, False)

    def test_finish_revert_migration_after_crash_before_backup(self):
        self._test_finish_revert_migration_after_crash(False, False)
