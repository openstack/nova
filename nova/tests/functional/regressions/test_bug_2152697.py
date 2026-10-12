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

"""Regression test for bug .

https://bugs.launchpad.net/nova/+bug/2152697

In Gazpacho nova started adding one iothread for each VM unconditionally.
For VMs with dedicated cpus the iothreadpin field also needed to be defined.
During live migration the iothreadpin value is recalculated based on the
destination compute's cpu configuration. This recaclulation assumed that
the source XML always have the iothreadpin field defined. This is not true for
VMs that was created before the IOThread feature was merged and haven't been
restarted or moved since then.
"""

from lxml import etree

from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class TestLiveMigrationIOThreadPinningPreExistingInstance(
    base.LibvirtMigrationMixin,
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
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

    def test_live_migrate_pre_existing_pinned_instance(self):
        self.flags(
            cpu_shared_set='0,1', cpu_dedicated_set='2,3', group='compute')
        self.restart_compute_service('src')
        self.restart_compute_service('dest')

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor = self._create_flavor(vcpu=1, extra_spec=extra_spec)

        self.server = self._create_server(
            flavor_id=flavor, host='src', networks='none')

        # Hack the instance to simulate that it was created before the IOThread
        # feature exist by deleting the iothread related fields from it.
        conn = self.src.driver._host.get_connection()
        vm_domain = list(conn._vms.values())[0]
        del vm_domain._def["iothreads"]
        del vm_domain._def["iothread_pin"]

        # Ensure the hack works
        dom = conn.lookupByUUIDString(self.server['id'])
        src_xml = dom.XMLDesc(0)
        src_emulatorpin = self._get_xml_element(
            src_xml, './cputune/emulatorpin')
        src_iothreadpin = self._get_xml_element(
            src_xml, './cputune/iothreadpin')
        self.assertIsNotNone(src_emulatorpin)
        self.assertIsNone(src_iothreadpin)

        # Live migrate
        self._live_migrate(self.server, 'completed')
        self.assertEqual('dest', self.get_host(self.server['id']))

        # Get dest XML
        conn = self.dest.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        dest_xml = dom.XMLDesc(0)

        # Verify iothreadpin is not defined
        dest_iothreadpin = self._get_xml_element(
            dest_xml, './cputune/iothreadpin')
        self.assertIsNone(dest_iothreadpin)
