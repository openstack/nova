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

"""Regression test for bug 2140537.

https://bugs.launchpad.net/nova/+bug/2140537

When creating an instance with hw:cpu_policy=dedicated, pinned CPUs,
Nova was incorrectly setting <iothreads>1</iothreads> in the libvirt XML
without a corresponding <iothreadpin> element. This caused libvirt to
reject the XML with: "XML error: Missing required attribute 'iothread'
in element 'iothreadpin'".
"""

from lxml import etree
from unittest import mock

from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class TestIOThreadPinningPinnedCPU(
    base.LibvirtMigrationMixin,
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression test for bug 2140537.

    Instances with dedicated CPU policy (pinned CPUs) should NOT have
    IOThreads configured and have IOThreadPin in their domain xml,
    as they are incompatible with CPU pinning.
    """

    microversion = 'latest'
    ADMIN_API = True
    ADDITIONAL_FILTERS = ['NUMATopologyFilter']

    def setUp(self):
        # TODO(lajoskatona): remove this patch when the fix for
        # bug/2140537 is merged, and the libvirt fixture has the
        # necessary validation for XML fields for IOThreads.
        patcher = mock.patch.object(
            fakelibvirt.Connection, 'defineXML',
            fakelibvirt.Connection._defineXMLIOThreads)
        patcher.start()
        self.addCleanup(patcher.stop)

        super().setUp()
        self.hostname = self.start_compute(
            hostname='host1',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=2, cpu_sockets=1, cpu_cores=4, cpu_threads=1))
        self.host = self.computes['host1']

    def get_host(self, server_id):
        server = self.api.get_server(server_id)
        return server['OS-EXT-SRV-ATTR:host']

    def _get_xml_element(self, xml, xpath):
        """Get element from XML using xpath."""
        xml_doc = etree.fromstring(xml.encode('utf-8'))
        element = xml_doc.find(xpath)
        return element

    def test_iothread_pinning_pinned_cpu(self):
        """Test that pinned CPU instances fail with iothreadpin bug.

        This reproduces bug 2140537: When creating an instance with
        hw:cpu_policy=dedicated, Nova incorrectly creates an <iothreadpin>
        element without the required 'iothread' attribute, causing libvirt
        to reject the XML.
        """
        # Configure host with dedicated CPUs
        self.flags(
            cpu_shared_set='0,1', cpu_dedicated_set='2,3', group='compute')
        self.restart_compute_service('host1')

        # Create VM with dedicated CPUs
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor = self._create_flavor(vcpu=1, extra_spec=extra_spec)

        # BUG: This fails with libvirt error about missing 'iothread' attribute
        # The server creation will fail and go to ERROR state
        server = self._create_server(
            flavor_id=flavor, host='host1', networks='none',
            expected_state='ERROR')

        # Verify the server is in ERROR state due to the libvirt XML error
        self.assertEqual('ERROR', server['status'])

        # Check the fault message contains the libvirt error
        self.assertIn('Exceeded maximum number of retries',
                      server['fault']['message'])
        # Check the logs for the exception
        self.assertIn("Missing required attribute 'iothread'",
                      self.stdlog.logger.output)
        self.assertIn("element 'iothreadpin'", self.stdlog.logger.output)

    def test_iothread_pinning_explicit_numa(self):
        """Test iothread pinning with explicit multi-node NUMA topology."""
        self.flags(
            cpu_shared_set='0-1', cpu_dedicated_set='2-7', group='compute')
        self.restart_compute_service('host1')

        # Create flavor with explicit 2-node NUMA topology
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:numa_nodes': '2',
        }
        flavor = self._create_flavor(vcpu=4, extra_spec=extra_spec)

        # Server should go ACTIVE
        # server = self._create_server(
        #     flavor_id=flavor, host='host1', networks='none',
        #     expected_state='ACTIVE')
        server = self._create_server(
            flavor_id=flavor, host='host1', networks='none',
            expected_state='ERROR')

        # conn = self.host.driver._host.get_connection()
        # dom = conn.lookupByUUIDString(server['id'])
        # srv_xml = dom.XMLDesc(0)

        # # Should have iothreads element
        # srv_iothread = self._get_xml_element(srv_xml, './iothreads')
        # self.assertIsNotNone(srv_iothread)
        # self.assertEqual('1', srv_iothread.text)

        # # Should have emulatorpin and iothreadpin
        # srv_emulatorpin = self._get_xml_element(
        #     srv_xml, './cputune/emulatorpin')
        # srv_iothreadpin = self._get_xml_element(
        #     srv_xml, './cputune/iothreadpin')
        # self.assertIsNotNone(srv_emulatorpin)
        # self.assertIsNotNone(srv_iothreadpin)

        # # iothreadpin should have iothread attribute set to 1
        # self.assertEqual('1', srv_iothreadpin.get('iothread'))

        # # Both should be pinned to the union of NUMA nodes
        # self.assertEqual(srv_emulatorpin.get('cpuset'),
        #                  srv_iothreadpin.get('cpuset'))

        self.assertEqual('ERROR', server['status'])

        # Check the fault message contains the libvirt error
        self.assertIn('Exceeded maximum number of retries',
                      server['fault']['message'])
        # Check the logs for the exception
        self.assertIn("Missing required attribute 'iothread'",
                      self.stdlog.logger.output)
        self.assertIn("element 'iothreadpin'", self.stdlog.logger.output)

    def test_iothread_pinning_isolated_emulator(self):
        """Test iothread pinning with isolated emulator threads policy."""
        self.flags(
            cpu_shared_set='0-1', cpu_dedicated_set='2-7', group='compute')
        self.restart_compute_service('host1')

        # Create flavor with isolated emulator threads
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:emulator_threads_policy': 'isolate',
        }
        flavor = self._create_flavor(vcpu=2, extra_spec=extra_spec)

        server = self._create_server(
            flavor_id=flavor, host='host1', networks='none',
            expected_state='ERROR')
        # Server should go ACTIVE
        # server = self._create_server(
        #     flavor_id=flavor, host='host1', networks='none',
        #     expected_state='ACTIVE')

        # conn = self.host.driver._host.get_connection()
        # dom = conn.lookupByUUIDString(server['id'])
        # srv_xml = dom.XMLDesc(0)

        # # Should have iothreads element
        # srv_iothread = self._get_xml_element(srv_xml, './iothreads')
        # self.assertIsNotNone(srv_iothread)
        # self.assertEqual('1', srv_iothread.text)

        # # Should have emulatorpin and iothreadpin
        # srv_emulatorpin = self._get_xml_element(
        #     srv_xml, './cputune/emulatorpin')
        # srv_iothreadpin = self._get_xml_element(
        #     srv_xml, './cputune/iothreadpin')
        # self.assertIsNotNone(srv_emulatorpin)
        # self.assertIsNotNone(srv_iothreadpin)

        # # iothreadpin should have iothread attribute set to 1
        # self.assertEqual('1', srv_iothreadpin.get('iothread'))

        # # Both should be pinned to the same reserved/isolated CPU
        # self.assertEqual(srv_emulatorpin.get('cpuset'),
        #                  srv_iothreadpin.get('cpuset'))

        # # Should be pinned to a single CPU (the reserved one)
        # # With vcpu=2 and isolate policy, one extra CPU is reserved
        # cpuset = srv_iothreadpin.get('cpuset')
        # # The cpuset should be a single CPU from cpu_dedicated_set
        # self.assertIsNotNone(cpuset)
        self.assertEqual('ERROR', server['status'])

        # Check the fault message contains the libvirt error
        self.assertIn('Exceeded maximum number of retries',
                      server['fault']['message'])
        # Check the logs for the exception
        self.assertIn("Missing required attribute 'iothread'",
                      self.stdlog.logger.output)
        self.assertIn("element 'iothreadpin'", self.stdlog.logger.output)

    def test_iothread_pinning_shared_emulator(self):
        """Test iothread pinning with shared emulator threads policy."""
        self.flags(
            cpu_shared_set='0-1', cpu_dedicated_set='2-7', group='compute')
        self.restart_compute_service('host1')

        # Create flavor with shared emulator threads
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:emulator_threads_policy': 'share',
        }
        flavor = self._create_flavor(vcpu=2, extra_spec=extra_spec)

        server = self._create_server(
            flavor_id=flavor, host='host1', networks='none',
            expected_state='ERROR')
        # Server should go ACTIVE
        # server = self._create_server(
        #     flavor_id=flavor, host='host1', networks='none',
        #     expected_state='ACTIVE')

        # conn = self.host.driver._host.get_connection()
        # dom = conn.lookupByUUIDString(server['id'])
        # srv_xml = dom.XMLDesc(0)

        # # Should have iothreads element
        # srv_iothread = self._get_xml_element(srv_xml, './iothreads')
        # self.assertIsNotNone(srv_iothread)
        # self.assertEqual('1', srv_iothread.text)

        # # Should have emulatorpin and iothreadpin
        # srv_emulatorpin = self._get_xml_element(
        #     srv_xml, './cputune/emulatorpin')
        # srv_iothreadpin = self._get_xml_element(
        #     srv_xml, './cputune/iothreadpin')
        # self.assertIsNotNone(srv_emulatorpin)
        # self.assertIsNotNone(srv_iothreadpin)

        # # iothreadpin should have iothread attribute set to 1
        # self.assertEqual('1', srv_iothreadpin.get('iothread'))

        # # Both should be pinned to cpu_shared_set (0-1)
        # self.assertEqual(srv_emulatorpin.get('cpuset'),
        #                  srv_iothreadpin.get('cpuset'))
        # self.assertEqual('0-1', srv_iothreadpin.get('cpuset'))

        self.assertEqual('ERROR', server['status'])

        # Check the fault message contains the libvirt error
        self.assertIn('Exceeded maximum number of retries',
                      server['fault']['message'])
        # Check the logs for the exception
        self.assertIn("Missing required attribute 'iothread'",
                      self.stdlog.logger.output)
        self.assertIn("element 'iothreadpin'", self.stdlog.logger.output)

    def test_iothread_no_pinning(self):
        # No CPU pinning (shared CPUs only)
        # Expects: NO cputune element at all (no emulatorpin, no iothreadpin)
        flavor = self._create_flavor(vcpu=1,)
        server = self._create_server(
            flavor_id=flavor, host='host1', networks='none',
            expected_state='ACTIVE')
        conn = self.host.driver._host.get_connection()
        dom = conn.lookupByUUIDString(server['id'])
        srv_xml = dom.XMLDesc(0)

        srv_iothread = self._get_xml_element(srv_xml, './iothreads')
        srv_iothreadpin = self._get_xml_element(
            srv_xml, './cputune/iothreadpin')

        # iothreads should be set to 1 for all instances
        self.assertIsNotNone(srv_iothread)
        self.assertEqual('1', srv_iothread.text)

        # And no pinning for shared CPUs, no iothreadpin
        self.assertIsNone(srv_iothreadpin)
