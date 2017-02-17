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

from nova.objects import fields as obj_fields
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
                'supported_instances': obj_fields.Architecture.X86_64,
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

        with mock.patch.object(driver.host_state, 'get_host_stats',
                               side_effect=self.host_stats) as mock_get:

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
            mock_get.assert_called_once_with(refresh=True)

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

        with mock.patch.object(driver._vmops,
                               'set_bootable') as mock_set_bootable:
            driver.set_bootable('inst', True)
            mock_set_bootable.assert_called_once_with('inst', True)

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
        with mock.patch.object(driver.host_state, 'get_host_stats',
                               side_effect=self.host_stats) as mock_get:

            connector = driver.get_volume_connector({'uuid': 'fake'})
            self.assertIn('ip', connector)
            self.assertEqual(connector['ip'], ip)
            self.assertIn('initiator', connector)
            self.assertEqual(connector['initiator'], 'someiqn')
            mock_get.assert_called_once_with(refresh=True)

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

    @mock.patch.object(xenapi_driver, 'invalid_option')
    @mock.patch.object(xenapi_driver.vm_utils, 'ensure_correct_host')
    def test_invalid_options(self, mock_ensure, mock_invalid):
        driver = self._get_driver()
        self.flags(independent_compute=True, group='xenserver')
        self.flags(check_host=True, group='xenserver')
        self.flags(flat_injected=True)
        self.flags(default_ephemeral_format='vfat')

        driver.init_host('host')

        expected_calls = [
            mock.call('CONF.xenserver.check_host', False),
            mock.call('CONF.flat_injected', False),
            mock.call('CONF.default_ephemeral_format', 'ext3')]
        mock_invalid.assert_has_calls(expected_calls)

    @mock.patch.object(xenapi_driver.vm_utils, 'cleanup_attached_vdis')
    @mock.patch.object(xenapi_driver.vm_utils, 'ensure_correct_host')
    def test_independent_compute_no_vdi_cleanup(self, mock_ensure,
                                                mock_cleanup):
        driver = self._get_driver()
        self.flags(independent_compute=True, group='xenserver')
        self.flags(check_host=False, group='xenserver')
        self.flags(flat_injected=False)

        driver.init_host('host')

        self.assertFalse(mock_cleanup.called)
        self.assertFalse(mock_ensure.called)

    @mock.patch.object(xenapi_driver.vm_utils, 'cleanup_attached_vdis')
    @mock.patch.object(xenapi_driver.vm_utils, 'ensure_correct_host')
    def test_dependent_compute_vdi_cleanup(self, mock_ensure, mock_cleanup):
        driver = self._get_driver()
        self.assertFalse(mock_cleanup.called)
        self.flags(independent_compute=False, group='xenserver')
        self.flags(check_host=True, group='xenserver')

        driver.init_host('host')

        self.assertTrue(mock_cleanup.called)
        self.assertTrue(mock_ensure.called)

    @mock.patch.object(xenapi_driver.vmops.VMOps, 'attach_interface')
    def test_attach_interface(self, mock_attach_interface):
        driver = self._get_driver()
        driver.attach_interface('fake_context', 'fake_instance',
                                'fake_image_meta', 'fake_vif')
        mock_attach_interface.assert_called_once_with('fake_instance',
                                                      'fake_vif')

    @mock.patch.object(xenapi_driver.vmops.VMOps, 'detach_interface')
    def test_detach_interface(self, mock_detach_interface):
        driver = self._get_driver()
        driver.detach_interface('fake_context', 'fake_instance', 'fake_vif')
        mock_detach_interface.assert_called_once_with('fake_instance',
                                                      'fake_vif')

    @mock.patch.object(xenapi_driver.vmops.VMOps,
                       'post_live_migration_at_source')
    def test_post_live_migration_at_source(self, mock_post_live_migration):
        driver = self._get_driver()
        driver.post_live_migration_at_source('fake_context', 'fake_instance',
                                             'fake_network_info')
        mock_post_live_migration.assert_called_once_with(
            'fake_context', 'fake_instance', 'fake_network_info')

    @mock.patch.object(xenapi_driver.vmops.VMOps,
                       'rollback_live_migration_at_destination')
    def test_rollback_live_migration_at_destination(self, mock_rollback):
        driver = self._get_driver()
        driver.rollback_live_migration_at_destination(
            'fake_context', 'fake_instance', 'fake_network_info',
            'fake_block_device')
        mock_rollback.assert_called_once_with('fake_instance',
                                              'fake_network_info',
                                              'fake_block_device')
