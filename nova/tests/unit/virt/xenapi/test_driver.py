# Copyright (c) 2013 Rackspace Hosting
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


import math

import mock
from oslo_utils import units

from nova.compute import arch
from nova.tests.unit.virt.xenapi import stubs
from nova.virt import driver
from nova.virt import fake
from nova.virt import xenapi
from nova.virt.xenapi import driver as xenapi_driver


class XenAPIDriverTestCase(stubs.XenAPITestBaseNoDB):
    """Unit tests for Driver operations."""

    def _get_driver(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.flags(connection_url='test_url',
                   connection_password='test_pass', group='xenserver')
        return xenapi.XenAPIDriver(fake.FakeVirtAPI(), False)

    def host_stats(self, refresh=True):
        return {'host_memory_total': 3 * units.Mi,
                'host_memory_free_computed': 2 * units.Mi,
                'disk_total': 5 * units.Gi,
                'disk_used': 2 * units.Gi,
                'disk_allocated': 4 * units.Gi,
                'host_hostname': 'somename',
                'supported_instances': arch.X86_64,
                'host_cpu_info': {'cpu_count': 50},
                'cpu_model': {
                    'vendor': 'GenuineIntel',
                    'model': 'Intel(R) Xeon(R) CPU           X3430  @ 2.40GHz',
                    'topology': {
                        'sockets': 1,
                        'cores': 4,
                        'threads': 1,
                    },
                    'features': [
                        'fpu', 'de', 'tsc', 'msr', 'pae', 'mce',
                        'cx8', 'apic', 'sep', 'mtrr', 'mca',
                        'cmov', 'pat', 'clflush', 'acpi', 'mmx',
                        'fxsr', 'sse', 'sse2', 'ss', 'ht',
                        'nx', 'constant_tsc', 'nonstop_tsc',
                        'aperfmperf', 'pni', 'vmx', 'est', 'ssse3',
                        'sse4_1', 'sse4_2', 'popcnt', 'hypervisor',
                        'ida', 'tpr_shadow', 'vnmi', 'flexpriority',
                        'ept', 'vpid',
                    ],
                },
                'vcpus_used': 10,
                'pci_passthrough_devices': '',
                'host_other-config': {'iscsi_iqn': 'someiqn'}}

    def test_available_resource(self):
        driver = self._get_driver()
        driver._session.product_version = (6, 8, 2)

        self.stubs.Set(driver.host_state, 'get_host_stats', self.host_stats)

        resources = driver.get_available_resource(None)
        self.assertEqual(6008002, resources['hypervisor_version'])
        self.assertEqual(50, resources['vcpus'])
        self.assertEqual(3, resources['memory_mb'])
        self.assertEqual(5, resources['local_gb'])
        self.assertEqual(10, resources['vcpus_used'])
        self.assertEqual(3 - 2, resources['memory_mb_used'])
        self.assertEqual(2, resources['local_gb_used'])
        self.assertEqual('XenServer', resources['hypervisor_type'])
        self.assertEqual('somename', resources['hypervisor_hostname'])
        self.assertEqual(1, resources['disk_available_least'])

    def test_overhead(self):
        driver = self._get_driver()
        instance = {'memory_mb': 30720, 'vcpus': 4}

        # expected memory overhead per:
        # https://wiki.openstack.org/wiki/XenServer/Overhead
        expected = ((instance['memory_mb'] * xenapi_driver.OVERHEAD_PER_MB) +
                    (instance['vcpus'] * xenapi_driver.OVERHEAD_PER_VCPU) +
                    xenapi_driver.OVERHEAD_BASE)
        expected = math.ceil(expected)
        overhead = driver.estimate_instance_overhead(instance)
        self.assertEqual(expected, overhead['memory_mb'])

    def test_set_bootable(self):
        driver = self._get_driver()

        self.mox.StubOutWithMock(driver._vmops, 'set_bootable')
        driver._vmops.set_bootable('inst', True)
        self.mox.ReplayAll()

        driver.set_bootable('inst', True)

    def test_post_interrupted_snapshot_cleanup(self):
        driver = self._get_driver()
        fake_vmops_cleanup = mock.Mock()
        driver._vmops.post_interrupted_snapshot_cleanup = fake_vmops_cleanup

        driver.post_interrupted_snapshot_cleanup("context", "instance")

        fake_vmops_cleanup.assert_called_once_with("context", "instance")

    def test_public_api_signatures(self):
        inst = self._get_driver()
        self.assertPublicAPISignatures(driver.ComputeDriver(None), inst)

    def test_get_volume_connector(self):
        ip = '123.123.123.123'
        driver = self._get_driver()
        self.flags(connection_url='http://%s' % ip,
                   connection_password='test_pass', group='xenserver')
        self.stubs.Set(driver.host_state, 'get_host_stats', self.host_stats)

        connector = driver.get_volume_connector({'uuid': 'fake'})
        self.assertIn('ip', connector)
        self.assertEqual(connector['ip'], ip)
        self.assertIn('initiator', connector)
        self.assertEqual(connector['initiator'], 'someiqn')

    def test_get_block_storage_ip(self):
        my_ip = '123.123.123.123'
        connection_ip = '124.124.124.124'
        driver = self._get_driver()
        self.flags(connection_url='http://%s' % connection_ip,
                   group='xenserver')
        self.flags(my_ip=my_ip, my_block_storage_ip=my_ip)

        ip = driver._get_block_storage_ip()
        self.assertEqual(connection_ip, ip)

    def test_get_block_storage_ip_conf(self):
        driver = self._get_driver()
        my_ip = '123.123.123.123'
        my_block_storage_ip = '124.124.124.124'
        self.flags(my_ip=my_ip, my_block_storage_ip=my_block_storage_ip)

        ip = driver._get_block_storage_ip()
        self.assertEqual(my_block_storage_ip, ip)
