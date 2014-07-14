# Copyright (c) 2014 VMware, Inc.
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

from nova import exception
from nova import test
from nova.virt import diagnostics


class DiagnosticsTests(test.NoDBTestCase):

    def test_cpu_diagnostics_default(self):
        cpu = diagnostics.CpuDiagnostics()
        self.assertEqual(0, cpu.time)

    def test_cpu_diagnostics(self):
        cpu = diagnostics.CpuDiagnostics(time=7)
        self.assertEqual(7, cpu.time)

    def test_nic_diagnostics_default(self):
        nic = diagnostics.NicDiagnostics()
        self.assertEqual('00:00:00:00:00:00', nic.mac_address)
        self.assertEqual(0, nic.rx_octets)
        self.assertEqual(0, nic.rx_errors)
        self.assertEqual(0, nic.rx_drop)
        self.assertEqual(0, nic.rx_packets)
        self.assertEqual(0, nic.tx_octets)
        self.assertEqual(0, nic.tx_errors)
        self.assertEqual(0, nic.tx_drop)
        self.assertEqual(0, nic.tx_packets)

    def test_nic_diagnostics(self):
        nic = diagnostics.NicDiagnostics(mac_address='00:00:ca:fe:00:00',
                    rx_octets=1, rx_errors=2, rx_drop=3, rx_packets=4,
                    tx_octets=5, tx_errors=6, tx_drop=7, tx_packets=8)
        self.assertEqual('00:00:ca:fe:00:00', nic.mac_address)
        self.assertEqual(1, nic.rx_octets)
        self.assertEqual(2, nic.rx_errors)
        self.assertEqual(3, nic.rx_drop)
        self.assertEqual(4, nic.rx_packets)
        self.assertEqual(5, nic.tx_octets)
        self.assertEqual(6, nic.tx_errors)
        self.assertEqual(7, nic.tx_drop)
        self.assertEqual(8, nic.tx_packets)

    def test_disk_diagnostics_default(self):
        disk = diagnostics.DiskDiagnostics()
        self.assertEqual('', disk.id)
        self.assertEqual(0, disk.read_bytes)
        self.assertEqual(0, disk.read_requests)
        self.assertEqual(0, disk.write_bytes)
        self.assertEqual(0, disk.write_requests)
        self.assertEqual(0, disk.errors_count)

    def test_disk_diagnostics(self):
        disk = diagnostics.DiskDiagnostics(id='fake_disk_id',
                    read_bytes=1, read_requests=2,
                    write_bytes=3, write_requests=4,
                    errors_count=5)
        self.assertEqual('fake_disk_id', disk.id)
        self.assertEqual(1, disk.read_bytes)
        self.assertEqual(2, disk.read_requests)
        self.assertEqual(3, disk.write_bytes)
        self.assertEqual(4, disk.write_requests)
        self.assertEqual(5, disk.errors_count)

    def test_memory_diagnostics_default(self):
        memory = diagnostics.MemoryDiagnostics()
        self.assertEqual(0, memory.maximum)
        self.assertEqual(0, memory.used)

    def test_memory_diagnostics(self):
        memory = diagnostics.MemoryDiagnostics(maximum=1, used=2)
        self.assertEqual(1, memory.maximum)
        self.assertEqual(2, memory.used)

    def test_diagnostics_default(self):
        diags = diagnostics.Diagnostics()
        self.assertIsNone(diags.state)
        self.assertIsNone(diags.driver)
        self.assertIsNone(diags.hypervisor_os)
        self.assertEqual(0, diags.uptime)
        self.assertFalse(diags.config_drive)
        self.assertEqual([], diags.cpu_details)
        self.assertEqual([], diags.nic_details)
        self.assertEqual([], diags.disk_details)
        self.assertEqual(0, diags.memory_details.maximum)
        self.assertEqual(0, diags.memory_details.used)
        self.assertEqual('1.0', diags.version)

    def test_diagnostics(self):
        cpu_details = [diagnostics.CpuDiagnostics()]
        nic_details = [diagnostics.NicDiagnostics()]
        disk_details = [diagnostics.DiskDiagnostics()]
        diags = diagnostics.Diagnostics(
                state='fake-state', driver='fake-driver',
                hypervisor_os='fake-os',
                uptime=1, cpu_details=cpu_details,
                nic_details=nic_details, disk_details=disk_details,
                config_drive=True)
        self.assertEqual('fake-state', diags.state)
        self.assertEqual('fake-driver', diags.driver)
        self.assertEqual('fake-os', diags.hypervisor_os)
        self.assertEqual(1, diags.uptime)
        self.assertTrue(diags.config_drive)
        self.assertEqual(1, len(diags.cpu_details))
        self.assertEqual(1, len(diags.nic_details))
        self.assertEqual(1, len(diags.disk_details))
        self.assertEqual(0, diags.memory_details.maximum)
        self.assertEqual(0, diags.memory_details.used)
        self.assertEqual('1.0', diags.version)

    def test_add_cpu(self):
        diags = diagnostics.Diagnostics()
        self.assertEqual([], diags.cpu_details)
        diags.add_cpu(time=7)
        self.assertEqual(1, len(diags.cpu_details))
        self.assertEqual(7, diags.cpu_details[0].time)

    def test_add_nic(self):
        diags = diagnostics.Diagnostics()
        self.assertEqual([], diags.nic_details)
        diags.add_nic(mac_address='00:00:ca:fe:00:00',
                      rx_octets=1, rx_errors=2, rx_drop=3, rx_packets=4,
                      tx_octets=5, tx_errors=6, tx_drop=7, tx_packets=8)
        self.assertEqual(1, len(diags.nic_details))
        self.assertEqual('00:00:ca:fe:00:00', diags.nic_details[0].mac_address)
        self.assertEqual(1, diags.nic_details[0].rx_octets)
        self.assertEqual(2, diags.nic_details[0].rx_errors)
        self.assertEqual(3, diags.nic_details[0].rx_drop)
        self.assertEqual(4, diags.nic_details[0].rx_packets)
        self.assertEqual(5, diags.nic_details[0].tx_octets)
        self.assertEqual(6, diags.nic_details[0].tx_errors)
        self.assertEqual(7, diags.nic_details[0].tx_drop)
        self.assertEqual(8, diags.nic_details[0].tx_packets)

    def test_add_disk(self):
        diags = diagnostics.Diagnostics()
        self.assertEqual([], diags.disk_details)
        diags.add_disk(id='fake_disk_id',
                       read_bytes=1, read_requests=2,
                       write_bytes=3, write_requests=4,
                       errors_count=5)
        self.assertEqual(1, len(diags.disk_details))
        self.assertEqual('fake_disk_id', diags.disk_details[0].id)
        self.assertEqual(1, diags.disk_details[0].read_bytes)
        self.assertEqual(2, diags.disk_details[0].read_requests)
        self.assertEqual(3, diags.disk_details[0].write_bytes)
        self.assertEqual(4, diags.disk_details[0].write_requests)
        self.assertEqual(5, diags.disk_details[0].errors_count)

    def test_diagnostics_serialize_default(self):
        diags = diagnostics.Diagnostics()
        expected = {'config_drive': False,
                    'cpu_details': [],
                    'disk_details': [],
                    'driver': None,
                    'hypervisor_os': None,
                    'memory_details': {'maximum': 0, 'used': 0},
                    'nic_details': [],
                    'state': None,
                    'uptime': 0,
                    'version': '1.0'}
        result = diags.serialize()
        self.assertEqual(expected, result)

    def test_diagnostics_serialize(self):
        cpu_details = [diagnostics.CpuDiagnostics()]
        nic_details = [diagnostics.NicDiagnostics()]
        disk_details = [diagnostics.DiskDiagnostics()]
        diags = diagnostics.Diagnostics(
                state='fake-state', driver='fake-driver',
                hypervisor_os='fake-os',
                uptime=1, cpu_details=cpu_details,
                nic_details=nic_details, disk_details=disk_details,
                config_drive=True)
        expected = {'config_drive': True,
                    'cpu_details': [{'time': 0}],
                    'disk_details': [{'errors_count': 0,
                                      'id': '',
                                      'read_bytes': 0,
                                      'read_requests': 0,
                                      'write_bytes': 0,
                                      'write_requests': 0}],
                    'driver': 'fake-driver',
                    'hypervisor_os': 'fake-os',
                    'memory_details': {'maximum': 0, 'used': 0},
                    'nic_details': [{'mac_address': '00:00:00:00:00:00',
                                     'rx_drop': 0,
                                     'rx_errors': 0,
                                     'rx_octets': 0,
                                     'rx_packets': 0,
                                     'tx_drop': 0,
                                     'tx_errors': 0,
                                     'tx_octets': 0,
                                     'tx_packets': 0}],
                    'state': 'fake-state',
                    'uptime': 1,
                    'version': '1.0'}
        result = diags.serialize()
        self.assertEqual(expected, result)

    def test_diagnostics_invalid_input(self):
        self.assertRaises(exception.InvalidInput,
                          diagnostics.Diagnostics,
                          cpu_details='invalid type')
        self.assertRaises(exception.InvalidInput,
                          diagnostics.Diagnostics,
                          cpu_details=['invalid entry'])
        self.assertRaises(exception.InvalidInput,
                          diagnostics.Diagnostics,
                          nic_details='invalid type')
        self.assertRaises(exception.InvalidInput,
                          diagnostics.Diagnostics,
                          nic_details=['invalid entry'])
        self.assertRaises(exception.InvalidInput,
                          diagnostics.Diagnostics,
                          disk_details='invalid type')
        self.assertRaises(exception.InvalidInput,
                          diagnostics.Diagnostics,
                          disk_details=['invalid entry'])
