# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM
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

from nova.compute import power_state
from nova import context
from nova import db
from nova import flags
from nova import test

from nova.openstack.common import log as logging
from nova.virt import images
from nova.virt.powervm import driver as powervm_driver
from nova.virt.powervm import lpar
from nova.virt.powervm import operator


FLAGS = flags.FLAGS
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

    def create_logical_volume(self, size):
        return 'lvfake01'

    def remove_logical_volume(self, lv_name):
        pass

    def copy_file_to_device(self, sourcePath, device):
        pass

    def copy_image_file(self, sourcePath, remotePath):
        finalPath = '/home/images/rhel62.raw.7e358754160433febd6f3318b7c9e335'
        size = 4294967296
        return finalPath, size

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


def fake_get_powervm_operator():
    return FakeIVMOperator()


class PowerVMDriverTestCase(test.TestCase):
    """Unit tests for PowerVM connection calls."""

    def setUp(self):
        super(PowerVMDriverTestCase, self).setUp()
        self.stubs.Set(operator, 'get_powervm_operator',
                       fake_get_powervm_operator)
        self.powervm_connection = powervm_driver.PowerVMDriver()
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
        def fake_image_fetch_to_raw(context, image_id, file_path,
                                    user_id, project_id):
            pass
        self.flags(powervm_img_local_path='/images/')
        self.stubs.Set(images, 'fetch_to_raw', fake_image_fetch_to_raw)
        image_meta = {}
        image_meta['id'] = '666'
        self.powervm_connection.spawn(context.get_admin_context(),
                                      self.instance, image_meta, 's3cr3t', [])
        state = self.powervm_connection.get_info(self.instance)['state']
        self.assertEqual(state, power_state.RUNNING)

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

    def test_get_host_stats(self):
        host_stats = self.powervm_connection.get_host_stats(True)
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

        self.assertEquals(host_stats['supported_instances'][0][0], "ppc64")
        self.assertEquals(host_stats['supported_instances'][0][1], "powervm")
        self.assertEquals(host_stats['supported_instances'][0][2], "hvm")
