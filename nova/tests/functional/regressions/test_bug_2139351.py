# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Regression test for bug 2139351.

https://bugs.launchpad.net/nova/+bug/2139351

Commit 76d64b9cb4241b73e62b3775f13d8eddcc0cb778 added iothread support,
creating one iothread per VM and pinning iothreads to the same cpuset as
emulator threads. During live migration, _update_numa_xml() in
nova/virt/libvirt/migration.py updates vcpupin and emulatorpin elements
but NOT iothreadpin. When cpu_shared_set differs between source and
destination hosts, the iothread remains incorrectly pinned to the source
host's CPU set.
"""

from lxml import etree

from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class TestLiveMigrationIOThreadPinning(
    base.LibvirtMigrationMixin,
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression test for iothreadpin during live migration.

    This tests that iothreadpin is correctly updated when live migrating
    between hosts with different cpu_shared_set configurations.
    """

    microversion = 'latest'
    ADMIN_API = True
    ADDITIONAL_FILTERS = ['NUMATopologyFilter']

    def setUp(self):
        super().setUp()
        self.src_hostname = self.start_compute(
            hostname='src',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))
        self.dest_hostname = self.start_compute(
            hostname='dest',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))
        self.src = self.computes['src']
        self.dest = self.computes['dest']

    def get_host(self, server_id):
        server = self.api.get_server(server_id)
        return server['OS-EXT-SRV-ATTR:host']

    def _get_xml_element(self, xml, xpath):
        """Get element from XML using xpath."""
        xml_doc = etree.fromstring(xml.encode('utf-8'))
        element = xml_doc.find(xpath)
        return element

    def test_live_migrate_iothread_pinning_numa(self):
        """Test iothread pinning updated for NUMA VMs with dedicated CPUs.

        BUG: emulatorpin updates correctly but iothreadpin does not.
        """
        # Configure both hosts: shared=0,1 dedicated=2,3
        self.flags(
            cpu_shared_set='0,1', cpu_dedicated_set='2,3', group='compute')
        self.restart_compute_service('src')
        self.restart_compute_service('dest')

        # Create VM with dedicated CPUs and shared emulator threads
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:emulator_threads_policy': 'share'
        }
        flavor = self._create_flavor(vcpu=1, extra_spec=extra_spec)
        self.server = self._create_server(
            flavor_id=flavor, host='src', networks='none')

        # Get source XML and verify pinning matches cpu_shared_set
        conn = self.src.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        src_xml = dom.XMLDesc(0)

        src_emulatorpin = self._get_xml_element(
            src_xml, './cputune/emulatorpin')
        src_iothreadpin = self._get_xml_element(
            src_xml, './cputune/iothreadpin')
        self.assertIsNotNone(src_emulatorpin)
        self.assertIsNotNone(src_iothreadpin)
        self.assertEqual('0-1', src_emulatorpin.get('cpuset'))
        self.assertEqual('0-1', src_iothreadpin.get('cpuset'))

        # Configure dest: shared=2,3 dedicated=0,1 (swapped)
        self.flags(
            cpu_shared_set='2,3', cpu_dedicated_set='0,1', group='compute')
        self.restart_compute_service('dest')

        # Live migrate
        self._live_migrate(self.server, 'completed')
        self.assertEqual('dest', self.get_host(self.server['id']))

        # Get dest XML
        conn = self.dest.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        dest_xml = dom.XMLDesc(0)

        # Verify emulatorpin updated (this works)
        dest_emulatorpin = self._get_xml_element(
            dest_xml, './cputune/emulatorpin')
        self.assertIsNotNone(dest_emulatorpin)
        self.assertEqual('2-3', dest_emulatorpin.get('cpuset'))

        # Verify iothreadpin updated
        dest_iothreadpin = self._get_xml_element(
            dest_xml, './cputune/iothreadpin')
        self.assertIsNotNone(dest_iothreadpin)
        self.assertEqual(
            '2-3', dest_iothreadpin.get('cpuset'),
            f"iothreadpin was not updated during live migration. "
            f"Expected '2-3' but got '{dest_iothreadpin.get('cpuset')}'")

        # Both should match
        self.assertEqual(
            dest_emulatorpin.get('cpuset'), dest_iothreadpin.get('cpuset'))

    def test_live_migrate_unpinned_vcpu_cpuset_updated(self):
        """Test vcpu cpuset updated for unpinned VMs with cpu_shared_set.

        This is a sanity check that the existing migration code correctly
        updates the vcpu cpuset for unpinned VMs. Unpinned VMs don't have
        cputune/emulatorpin or cputune/iothreadpin elements.
        """
        # Configure both hosts with cpu_shared_set
        self.flags(cpu_shared_set='0,1', group='compute')
        self.restart_compute_service('src')
        self.restart_compute_service('dest')

        # Create unpinned VM (default flavor, no dedicated CPU policy)
        self.server = self._create_server(host='src', networks='none')

        # Verify source XML has vcpu cpuset matching cpu_shared_set
        conn = self.src.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        src_xml = dom.XMLDesc(0)
        self.assertIn('<vcpu cpuset="0-1">1</vcpu>', src_xml)

        # Verify no cputune elements for unpinned VMs
        src_emulatorpin = self._get_xml_element(
            src_xml, './cputune/emulatorpin')
        src_iothreadpin = self._get_xml_element(
            src_xml, './cputune/iothreadpin')
        self.assertIsNone(src_emulatorpin)
        self.assertIsNone(src_iothreadpin)

        # Configure dest with different cpu_shared_set
        self.flags(cpu_shared_set='2,3', group='compute')
        self.restart_compute_service('dest')

        # Live migrate
        self._live_migrate(self.server, 'completed')
        self.assertEqual('dest', self.get_host(self.server['id']))

        # Verify dest XML has vcpu cpuset updated
        conn = self.dest.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        dest_xml = dom.XMLDesc(0)
        self.assertNotIn('<vcpu cpuset="0-1">1</vcpu>', dest_xml)
        self.assertIn('<vcpu cpuset="2-3">1</vcpu>', dest_xml)
