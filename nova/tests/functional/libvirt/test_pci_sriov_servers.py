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

import ddt
import fixtures
import mock

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova.objects import fields
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fakelibvirt


LOG = logging.getLogger(__name__)


class _PCIServersTestBase(base.ServersTestBase):

    ADDITIONAL_FILTERS = ['NUMATopologyFilter', 'PciPassthroughFilter']

    def setUp(self):
        self.flags(passthrough_whitelist=self.PCI_PASSTHROUGH_WHITELIST,
                   alias=self.PCI_ALIAS,
                   group='pci')

        super(_PCIServersTestBase, self).setUp()

        # Mock the 'PciPassthroughFilter' filter, as most tests need to inspect
        # this
        host_manager = self.scheduler.manager.driver.host_manager
        pci_filter_class = host_manager.filter_cls_map['PciPassthroughFilter']
        host_pass_mock = mock.Mock(wraps=pci_filter_class().host_passes)
        self.mock_filter = self.useFixture(fixtures.MockPatch(
            'nova.scheduler.filters.pci_passthrough_filter'
            '.PciPassthroughFilter.host_passes',
            side_effect=host_pass_mock)).mock


class SRIOVServersTest(_PCIServersTestBase):

    microversion = '2.48'

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

    def setUp(self):
        super().setUp()

        # The ultimate base class _IntegratedTestBase uses NeutronFixture but
        # we need a bit more intelligent neutron for these tests. Applying the
        # new fixture here means that we re-stub what the previous neutron
        # fixture already stubbed.
        self.neutron = self.useFixture(base.LibvirtNeutronFixture(self))

    def test_create_server_with_VF(self):
        """Create a server with an SR-IOV VF-type PCI device."""

        pci_info = fakelibvirt.HostPCIDevicesInfo()
        self.start_compute(pci_info=pci_info)

        # create a server
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.VFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id, networks='none')

        # ensure the filter was called
        self.assertTrue(self.mock_filter.called)

    def test_create_server_with_PF(self):
        """Create a server with an SR-IOV PF-type PCI device."""

        pci_info = fakelibvirt.HostPCIDevicesInfo()
        self.start_compute(pci_info=pci_info)

        # create a server
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.PFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id, networks='none')

        # ensure the filter was called
        self.assertTrue(self.mock_filter.called)

    def test_create_server_with_PF_no_VF(self):
        """Create a server with a PF and ensure the VFs are then reserved."""

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=4)
        self.start_compute(pci_info=pci_info)

        # create a server using the PF
        extra_spec_pfs = {"pci_passthrough:alias": f"{self.PFS_ALIAS_NAME}:1"}
        flavor_id_pfs = self._create_flavor(extra_spec=extra_spec_pfs)
        self._create_server(flavor_id=flavor_id_pfs, networks='none')

        # now attempt to build another server, this time using the VF; this
        # should fail because the VF is used by an instance
        extra_spec_vfs = {"pci_passthrough:alias": f"{self.VFS_ALIAS_NAME}:1"}
        flavor_id_vfs = self._create_flavor(extra_spec=extra_spec_vfs)
        self._create_server(
            flavor_id=flavor_id_vfs, networks='none', expected_state='ERROR',
        )

    def test_create_server_with_VF_no_PF(self):
        """Create a server with a VF and ensure the PF is then reserved."""

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=4)
        self.start_compute(pci_info=pci_info)

        # create a server using the VF
        extra_spec_vfs = {'pci_passthrough:alias': f'{self.VFS_ALIAS_NAME}:1'}
        flavor_id_vfs = self._create_flavor(extra_spec=extra_spec_vfs)
        self._create_server(flavor_id=flavor_id_vfs, networks='none')

        # now attempt to build another server, this time using the PF; this
        # should fail because the PF is used by an instance
        extra_spec_pfs = {'pci_passthrough:alias': f'{self.PFS_ALIAS_NAME}:1'}
        flavor_id_pfs = self._create_flavor(extra_spec=extra_spec_pfs)
        self._create_server(
            flavor_id=flavor_id_pfs, networks='none', expected_state='ERROR',
        )

    def test_get_server_diagnostics_server_with_VF(self):
        """Ensure server disagnostics include info on VF-type PCI devices."""

        pci_info = fakelibvirt.HostPCIDevicesInfo()
        self.start_compute(pci_info=pci_info)

        # create a server using the VF and multiple networks
        extra_spec = {'pci_passthrough:alias': f'{self.VFS_ALIAS_NAME}:1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'uuid': base.LibvirtNeutronFixture.network_1['id']},
                {'uuid': base.LibvirtNeutronFixture.network_4['id']},
            ],
        )

        # now check the server diagnostics to ensure the VF-type PCI device is
        # attached
        diagnostics = self.api.get_server_diagnostics(server['id'])

        self.assertEqual(
            base.LibvirtNeutronFixture.network_1_port_2['mac_address'],
            diagnostics['nic_details'][0]['mac_address'],
        )
        self.assertIsNotNone(diagnostics['nic_details'][0]['tx_packets'])

        self.assertEqual(
            base.LibvirtNeutronFixture.network_4_port_1['mac_address'],
            diagnostics['nic_details'][1]['mac_address'],
        )
        self.assertIsNone(diagnostics['nic_details'][1]['tx_packets'])


class PCIServersTest(_PCIServersTestBase):

    microversion = 'latest'

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

    def test_create_server_with_pci_dev_and_numa(self):
        """Verifies that an instance can be booted with cpu pinning and with an
           assigned pci device.
        """

        self.flags(cpu_dedicated_set='0-7', group='compute')

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=1)
        self.start_compute(pci_info=pci_info)

        # create a flavor
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._create_server(flavor_id=flavor_id, networks='none')

    def test_create_server_with_pci_dev_and_numa_fails(self):
        """This test ensures that it is not possible to allocated CPU and
           memory resources from one NUMA node and a PCI device from another.
        """

        self.flags(cpu_dedicated_set='0-7', group='compute')

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=0)
        self.start_compute(pci_info=pci_info)

        # boot one instance with no PCI device to "fill up" NUMA node 0
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id, networks='none')

        # now boot one with a PCI device, which should fail to boot
        extra_spec['pci_passthrough:alias'] = '%s:1' % self.ALIAS_NAME
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._create_server(
            flavor_id=flavor_id, networks='none', expected_state='ERROR')


class PCIServersWithPreferredNUMATest(_PCIServersTestBase):

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
    expected_state = 'ACTIVE'

    def test_create_server_with_pci_dev_and_numa(self):
        """Validate behavior of 'preferred' PCI NUMA policy.

        This test ensures that it *is* possible to allocate CPU and memory
        resources from one NUMA node and a PCI device from another *if* PCI
        NUMA policies are in use.
        """

        self.flags(cpu_dedicated_set='0-7', group='compute')

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=0)
        self.start_compute(pci_info=pci_info)

        # boot one instance with no PCI device to "fill up" NUMA node 0
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id)

        # now boot one with a PCI device, which should succeed thanks to the
        # use of the PCI policy
        extra_spec['pci_passthrough:alias'] = '%s:1' % self.ALIAS_NAME
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._create_server(
            flavor_id=flavor_id, expected_state=self.expected_state)


class PCIServersWithRequiredNUMATest(PCIServersWithPreferredNUMATest):

    ALIAS_NAME = 'a1'
    PCI_ALIAS = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
            'name': ALIAS_NAME,
            'device_type': fields.PciDeviceType.STANDARD,
            'numa_policy': fields.PCINUMAAffinityPolicy.REQUIRED,
        }
    )]
    expected_state = 'ERROR'


@ddt.ddt
class PCIServersWithSRIOVAffinityPoliciesTest(_PCIServersTestBase):

    ALIAS_NAME = 'a1'
    PCI_PASSTHROUGH_WHITELIST = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
        }
    )]
    # we set the numa_affinity policy to required to ensure strict affinity
    # between pci devices and the guest cpu and memory will be enforced.
    PCI_ALIAS = [jsonutils.dumps(
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PCI_PROD_ID,
            'name': ALIAS_NAME,
            'device_type': fields.PciDeviceType.STANDARD,
            'numa_policy': fields.PCINUMAAffinityPolicy.REQUIRED,
        }
    )]

    # NOTE(sean-k-mooney): i could just apply the ddt decorators
    # to this function for the most part but i have chosen to
    # keep one top level function per policy to make documenting
    # the test cases simpler.
    def _test_policy(self, pci_numa_node, status, policy):
        # only allow cpus on numa node 1 to be used for pinning
        self.flags(cpu_dedicated_set='4-7', group='compute')

        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, numa_node=pci_numa_node)
        self.start_compute(pci_info=pci_info)

        # request cpu pinning to create a numa toplogy and allow the test to
        # force which numa node the vm would have to be pinned too.
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
            'hw:pci_numa_affinity_policy': policy
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id, expected_state=status)

        if status == 'ACTIVE':
            self.assertTrue(self.mock_filter.called)
        else:
            # the PciPassthroughFilter should not have been called, since the
            # NUMATopologyFilter should have eliminated the filter first
            self.assertFalse(self.mock_filter.called)

    @ddt.unpack  # unpacks each sub-tuple e.g. *(pci_numa_node, status)
    # the preferred policy should always pass regardless of numa affinity
    @ddt.data((-1, 'ACTIVE'), (0, 'ACTIVE'), (1, 'ACTIVE'))
    def test_create_server_with_sriov_numa_affinity_policy_preferred(
            self, pci_numa_node, status):
        """Validate behavior of 'preferred' PCI NUMA affinity policy.

        This test ensures that it *is* possible to allocate CPU and memory
        resources from one NUMA node and a PCI device from another *if*
        the SR-IOV NUMA affinity policy is set to preferred.
        """
        self._test_policy(pci_numa_node, status, 'preferred')

    @ddt.unpack  # unpacks each sub-tuple e.g. *(pci_numa_node, status)
    # the legacy policy allow a PCI device to be used if it has NUMA
    # affinity or if no NUMA info is available so we set the NUMA
    # node for this device to -1 which is the sentinel value use by the
    # Linux kernel for a device with no NUMA affinity.
    @ddt.data((-1, 'ACTIVE'), (0, 'ERROR'), (1, 'ACTIVE'))
    def test_create_server_with_sriov_numa_affinity_policy_legacy(
            self, pci_numa_node, status):
        """Validate behavior of 'legacy' PCI NUMA affinity policy.

        This test ensures that it *is* possible to allocate CPU and memory
        resources from one NUMA node and a PCI device from another *if*
        the SR-IOV NUMA affinity policy is set to legacy and the device
        does not report NUMA information.
        """
        self._test_policy(pci_numa_node, status, 'legacy')

    @ddt.unpack  # unpacks each sub-tuple e.g. *(pci_numa_node, status)
    # The required policy requires a PCI device to both report a NUMA
    # and for the guest cpus and ram to be affinitized to the same
    # NUMA node so we create 1 pci device in the first NUMA node.
    @ddt.data((-1, 'ERROR'), (0, 'ERROR'), (1, 'ACTIVE'))
    def test_create_server_with_sriov_numa_affinity_policy_required(
            self, pci_numa_node, status):
        """Validate behavior of 'required' PCI NUMA affinity policy.

        This test ensures that it *is not* possible to allocate CPU and memory
        resources from one NUMA node and a PCI device from another *if*
        the SR-IOV NUMA affinity policy is set to required and the device
        does reports NUMA information.
        """

        # we set the numa_affinity policy to preferred to allow the PCI device
        # to be selected from any numa node so we can prove the flavor
        # overrides the alias.
        alias = [jsonutils.dumps(
            {
                'vendor_id': fakelibvirt.PCI_VEND_ID,
                'product_id': fakelibvirt.PCI_PROD_ID,
                'name': self.ALIAS_NAME,
                'device_type': fields.PciDeviceType.STANDARD,
                'numa_policy': fields.PCINUMAAffinityPolicy.PREFERRED,
            }
        )]

        self.flags(passthrough_whitelist=self.PCI_PASSTHROUGH_WHITELIST,
                   alias=alias,
                   group='pci')

        self._test_policy(pci_numa_node, status, 'required')
