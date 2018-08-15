# Copyright (C) 2016 Red Hat, Inc
# All Rights Reserved.
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

import mock
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova.objects import fields
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class _PCIServersTestBase(base.ServersTestBase):

    def setUp(self):
        self.flags(passthrough_whitelist=self.PCI_PASSTHROUGH_WHITELIST,
                   alias=self.PCI_ALIAS,
                   group='pci')

        super(_PCIServersTestBase, self).setUp()

        self.compute_started = False

        # Mock the 'PciPassthroughFilter' filter, as most tests need to inspect
        # this
        host_manager = self.scheduler.manager.driver.host_manager
        pci_filter_class = host_manager.filter_cls_map['PciPassthroughFilter']
        host_pass_mock = mock.Mock(wraps=pci_filter_class().host_passes)
        _p = mock.patch('nova.scheduler.filters.pci_passthrough_filter'
                        '.PciPassthroughFilter.host_passes',
                        side_effect=host_pass_mock)
        self.mock_filter = _p.start()
        self.addCleanup(_p.stop)

    def _setup_scheduler_service(self):
        # Enable the 'NUMATopologyFilter', 'PciPassthroughFilter'
        enabled_filters = CONF.filter_scheduler.enabled_filters + [
            'NUMATopologyFilter', 'PciPassthroughFilter']

        self.flags(driver='filter_scheduler', group='scheduler')
        self.flags(enabled_filters=enabled_filters, group='filter_scheduler')

        return self.start_service('scheduler')

    def _run_build_test(self, flavor_id, end_status='ACTIVE'):

        if not self.compute_started:
            self.compute = self.start_service('compute', host='test_compute0')
            self.compute_started = True

        # Create server
        good_server = self._build_server(flavor_id)

        post = {'server': good_server}

        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Validate that the server has been created
        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        # It should also be in the all-servers list
        servers = self.api.get_servers()
        server_ids = [s['id'] for s in servers]
        self.assertIn(created_server_id, server_ids)

        # Validate that PciPassthroughFilter has been called
        self.assertTrue(self.mock_filter.called)

        found_server = self._wait_for_state_change(found_server, 'BUILD')

        self.assertEqual(end_status, found_server['status'])
        self.addCleanup(self._delete_server, created_server_id)
        return created_server


class SRIOVServersTest(_PCIServersTestBase):

    VFS_ALIAS_NAME = 'vfs'
    PFS_ALIAS_NAME = 'pfs'

    PCI_PASSTHROUGH_WHITELIST = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PF_PROD_ID,
        },
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.VF_PROD_ID,
        },
    )]
    # PFs will be removed from pools unless they are specifically
    # requested, so we explicitly request them with the 'device_type'
    # attribute
    PCI_ALIAS = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PF_PROD_ID,
            'device_type': fields.PciDeviceType.SRIOV_PF,
            'name': PFS_ALIAS_NAME,
        },
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.VF_PROD_ID,
            'name': VFS_ALIAS_NAME,
        },
    )]

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image',
                return_value=(False, False))
    def test_create_server_with_VF(self, img_mock):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo()
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.VFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id)

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image',
                return_value=(False, False))
    def test_create_server_with_PF(self, img_mock):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo()
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.PFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id)

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image',
                return_value=(False, False))
    def test_create_server_with_PF_no_VF(self, img_mock):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=4)
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # Create a flavor
        extra_spec_pfs = {"pci_passthrough:alias": "%s:1" %
                          self.PFS_ALIAS_NAME}
        extra_spec_vfs = {"pci_passthrough:alias": "%s:1" %
                          self.VFS_ALIAS_NAME}
        flavor_id_pfs = self._create_flavor(extra_spec=extra_spec_pfs)
        flavor_id_vfs = self._create_flavor(extra_spec=extra_spec_vfs)

        self._run_build_test(flavor_id_pfs)
        self._run_build_test(flavor_id_vfs, end_status='ERROR')

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image',
                return_value=(False, False))
    def test_create_server_with_VF_no_PF(self, img_mock):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=4)
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # Create a flavor
        extra_spec_pfs = {"pci_passthrough:alias": "%s:1" %
                          self.PFS_ALIAS_NAME}
        extra_spec_vfs = {"pci_passthrough:alias": "%s:1" %
                          self.VFS_ALIAS_NAME}
        flavor_id_pfs = self._create_flavor(extra_spec=extra_spec_pfs)
        flavor_id_vfs = self._create_flavor(extra_spec=extra_spec_vfs)

        self._run_build_test(flavor_id_vfs)
        self._run_build_test(flavor_id_pfs, end_status='ERROR')


class GetServerDiagnosticsServerWithVfTestV21(_PCIServersTestBase):

    api_major_version = 'v2.1'
    microversion = '2.48'
    image_ref_parameter = 'imageRef'

    VFS_ALIAS_NAME = 'vfs'

    PCI_PASSTHROUGH_WHITELIST = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.VF_PROD_ID,
        },
    )]
    PCI_ALIAS = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.VF_PROD_ID,
            'name': VFS_ALIAS_NAME,
        },
    )]

    def setUp(self):
        super(GetServerDiagnosticsServerWithVfTestV21, self).setUp()
        self.api.microversion = self.microversion

        # The ultimate base class _IntegratedTestBase uses NeutronFixture but
        # we need a bit more intelligent neutron for these tests. Applying the
        # new fixture here means that we re-stub what the previous neutron
        # fixture already stubbed.
        self.neutron = self.useFixture(base.LibvirtNeutronFixture(self))

    def test_get_server_diagnostics_server_with_VF(self):

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo()
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.VFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        if not self.compute_started:
            self.compute = self.start_service('compute', host='test_compute0')
            self.compute_started = True

        # Create server
        good_server = self._build_server(flavor_id,
                                       '155d900f-4e14-4e4c-a73d-069cbf4541e6')
        good_server['networks'] = [
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
            {'uuid': base.LibvirtNeutronFixture.network_4['id']},
        ]

        post = {'server': good_server}
        created_server = self.api.post_server(post)
        self._wait_for_state_change(created_server, 'BUILD')

        diagnostics = self.api.get_server_diagnostics(created_server['id'])

        self.assertEqual(base.LibvirtNeutronFixture.
                         network_1_port_2['mac_address'],
                         diagnostics['nic_details'][0]['mac_address'])

        self.assertEqual(base.LibvirtNeutronFixture.
                         network_4_port_1['mac_address'],
                         diagnostics['nic_details'][1]['mac_address'])

        self.assertIsNotNone(diagnostics['nic_details'][0]['tx_packets'])

        self.assertIsNone(diagnostics['nic_details'][1]['tx_packets'])


class PCIServersTest(_PCIServersTestBase):

    ALIAS_NAME = 'a1'
    PCI_PASSTHROUGH_WHITELIST = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
        }
    )]
    PCI_ALIAS = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
            'name': ALIAS_NAME,
        }
    )]

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image',
                return_value=(False, False))
    def test_create_server_with_pci_dev_and_numa(self, img_mock):
        """Verifies that an instance can be booted with cpu pinning and with an
           assigned pci device.
        """

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=1)
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # create a flavor
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id)

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image',
                return_value=(False, False))
    def test_create_server_with_pci_dev_and_numa_fails(self, img_mock):
        """This test ensures that it is not possible to allocated CPU and
           memory resources from one NUMA node and a PCI device from another.
        """

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=0)
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # boot one instance with no PCI device to "fill up" NUMA node 0
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)

        self._run_build_test(flavor_id)

        # now boot one with a PCI device, which should fail to boot
        extra_spec['pci_passthrough:alias'] = '%s:1' % self.ALIAS_NAME
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id, end_status='ERROR')


class PCIServersWithNUMAPoliciesTest(_PCIServersTestBase):

    ALIAS_NAME = 'a1'
    PCI_PASSTHROUGH_WHITELIST = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
        }
    )]
    PCI_ALIAS = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
            'name': ALIAS_NAME,
            'device_type': fields.PciDeviceType.STANDARD,
            'numa_policy': fields.PCINUMAAffinityPolicy.PREFERRED,
        }
    )]

    @mock.patch('nova.virt.libvirt.LibvirtDriver._create_image',
                return_value=(False, False))
    def test_create_server_with_pci_dev_and_numa(self, img_mock):
        """Validate behavior of 'preferred' PCI NUMA policy.

        This test ensures that it *is* possible to allocate CPU and memory
        resources from one NUMA node and a PCI device from another *if* PCI
        NUMA policies are in use.
        """

        host_info = fakelibvirt.NUMAHostInfo(cpu_nodes=2, cpu_sockets=1,
                                             cpu_cores=2, cpu_threads=2,
                                             kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=0)
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # boot one instance with no PCI device to "fill up" NUMA node 0
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)

        self._run_build_test(flavor_id)

        # now boot one with a PCI device, which should succeed thanks to the
        # use of the PCI policy
        extra_spec['pci_passthrough:alias'] = '%s:1' % self.ALIAS_NAME
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id)
