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

from nova.objects import diagnostics
from nova import test


class DiagnosticsComparisonMixin(object):
    def assertDiagnosticsEqual(self, expected, actual):
        expected.obj_reset_changes(recursive=True)
        actual.obj_reset_changes(recursive=True)

        # NOTE(snikitin): Fields 'cpu_details', 'disk_details' and
        # 'nic_details' are list objects. They wouldn't be marked as 'changed'
        # if new item will be added by 'append()' method
        # (like # Diagnostics.add_*** methods do). So we have to reset these
        # objects manually.
        for obj in [expected, actual]:
            for field in ['cpu_details', 'disk_details', 'nic_details']:
                for item in getattr(obj, field):
                    item.obj_reset_changes()

        self.assertEqual(expected.obj_to_primitive(),
                         actual.obj_to_primitive())


class DiagnosticsTests(test.NoDBTestCase):

    def test_cpu_diagnostics(self):
        cpu = diagnostics.CpuDiagnostics(id=1, time=7, utilisation=15)
        self.assertEqual(1, cpu.id)
        self.assertEqual(7, cpu.time)
        self.assertEqual(15, cpu.utilisation)

    def test_nic_diagnostics(self):
        nic = diagnostics.NicDiagnostics(
            mac_address='00:00:ca:fe:00:00',
            rx_octets=1, rx_errors=2, rx_drop=3, rx_packets=4, rx_rate=5,
            tx_octets=6, tx_errors=7, tx_drop=8, tx_packets=9, tx_rate=10)
        self.assertEqual('00:00:ca:fe:00:00', nic.mac_address)
        self.assertEqual(1, nic.rx_octets)
        self.assertEqual(2, nic.rx_errors)
        self.assertEqual(3, nic.rx_drop)
        self.assertEqual(4, nic.rx_packets)
        self.assertEqual(5, nic.rx_rate)
        self.assertEqual(6, nic.tx_octets)
        self.assertEqual(7, nic.tx_errors)
        self.assertEqual(8, nic.tx_drop)
        self.assertEqual(9, nic.tx_packets)
        self.assertEqual(10, nic.tx_rate)

    def test_disk_diagnostics(self):
        disk = diagnostics.DiskDiagnostics(
            read_bytes=1, read_requests=2,
            write_bytes=3, write_requests=4,
            errors_count=5)
        self.assertEqual(1, disk.read_bytes)
        self.assertEqual(2, disk.read_requests)
        self.assertEqual(3, disk.write_bytes)
        self.assertEqual(4, disk.write_requests)
        self.assertEqual(5, disk.errors_count)

    def test_memory_diagnostics(self):
        memory = diagnostics.MemoryDiagnostics(maximum=1, used=2)
        self.assertEqual(1, memory.maximum)
        self.assertEqual(2, memory.used)

    def test_diagnostics(self):
        cpu_details = [diagnostics.CpuDiagnostics()]
        nic_details = [diagnostics.NicDiagnostics()]
        disk_details = [diagnostics.DiskDiagnostics()]
        memory_details = diagnostics.MemoryDiagnostics(maximum=1, used=1)
        diags = diagnostics.Diagnostics(
            state='running', driver='libvirt', hypervisor_os='fake-os',
            uptime=1, cpu_details=cpu_details, nic_details=nic_details,
            disk_details=disk_details, config_drive=True,
            memory_details=memory_details)
        self.assertEqual('running', diags.state)
        self.assertEqual('libvirt', diags.driver)
        self.assertEqual('fake-os', diags.hypervisor_os)
        self.assertEqual(1, diags.uptime)
        self.assertTrue(diags.config_drive)
        self.assertEqual(1, len(diags.cpu_details))
        self.assertEqual(1, len(diags.nic_details))
        self.assertEqual(1, len(diags.disk_details))
        self.assertEqual(1, diags.num_cpus)
        self.assertEqual(1, diags.num_disks)
        self.assertEqual(1, diags.num_nics)
        self.assertEqual(1, diags.memory_details.maximum)
        self.assertEqual(1, diags.memory_details.used)
        self.assertEqual('1.0', diags.VERSION)

    def test_add_cpu(self):
        diags = diagnostics.Diagnostics()
        self.assertEqual([], diags.cpu_details)
        diags.add_cpu(id=1, time=7, utilisation=15)
        self.assertEqual(1, len(diags.cpu_details))
        self.assertEqual(7, diags.cpu_details[0].time)
        self.assertEqual(1, diags.cpu_details[0].id)
        self.assertEqual(15, diags.cpu_details[0].utilisation)
        self.assertEqual(1, diags.num_cpus)

    def test_add_nic(self):
        diags = diagnostics.Diagnostics()
        self.assertEqual([], diags.nic_details)
        diags.add_nic(mac_address='00:00:ca:fe:00:00',
                rx_octets=1, rx_errors=2, rx_drop=3, rx_packets=4, rx_rate=5,
                tx_octets=6, tx_errors=7, tx_drop=8, tx_packets=9, tx_rate=10)
        self.assertEqual(1, len(diags.nic_details))
        self.assertEqual('00:00:ca:fe:00:00', diags.nic_details[0].mac_address)
        self.assertEqual(1, diags.nic_details[0].rx_octets)
        self.assertEqual(2, diags.nic_details[0].rx_errors)
        self.assertEqual(3, diags.nic_details[0].rx_drop)
        self.assertEqual(4, diags.nic_details[0].rx_packets)
        self.assertEqual(5, diags.nic_details[0].rx_rate)
        self.assertEqual(6, diags.nic_details[0].tx_octets)
        self.assertEqual(7, diags.nic_details[0].tx_errors)
        self.assertEqual(8, diags.nic_details[0].tx_drop)
        self.assertEqual(9, diags.nic_details[0].tx_packets)
        self.assertEqual(10, diags.nic_details[0].tx_rate)
        self.assertEqual(1, diags.num_nics)

    def test_add_disk(self):
        diags = diagnostics.Diagnostics()
        self.assertEqual([], diags.disk_details)
        diags.add_disk(read_bytes=1, read_requests=2,
                       write_bytes=3, write_requests=4,
                       errors_count=5)
        self.assertEqual(1, len(diags.disk_details))
        self.assertEqual(1, diags.disk_details[0].read_bytes)
        self.assertEqual(2, diags.disk_details[0].read_requests)
        self.assertEqual(3, diags.disk_details[0].write_bytes)
        self.assertEqual(4, diags.disk_details[0].write_requests)
        self.assertEqual(5, diags.disk_details[0].errors_count)
        self.assertEqual(1, diags.num_disks)
