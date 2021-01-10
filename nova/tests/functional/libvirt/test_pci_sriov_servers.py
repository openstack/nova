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

import copy
import ddt
import fixtures
import mock

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova import context
from nova import objects
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

        self.compute_started = False

        # Mock the 'PciPassthroughFilter' filter, as most tests need to inspect
        # this
        host_manager = self.scheduler.manager.driver.host_manager
        pci_filter_class = host_manager.filter_cls_map['PciPassthroughFilter']
        host_pass_mock = mock.Mock(wraps=pci_filter_class().host_passes)
        self.mock_filter = self.useFixture(fixtures.MockPatch(
            'nova.scheduler.filters.pci_passthrough_filter'
            '.PciPassthroughFilter.host_passes',
            side_effect=host_pass_mock)).mock

    def _run_build_test(self, flavor_id, end_status='ACTIVE'):

        if not self.compute_started:
            self.compute = self.start_service('compute', host='test_compute0')
            self.compute_started = True

        # Create server
        good_server = self._build_server(flavor_id=flavor_id)

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

        found_server = self._wait_for_state_change(found_server, end_status)

        self.addCleanup(self._delete_server, found_server)
        return created_server


class SRIOVServersTest(_PCIServersTestBase):

    VFS_ALIAS_NAME = 'vfs'
    PFS_ALIAS_NAME = 'pfs'

    PCI_PASSTHROUGH_WHITELIST = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PF_PROD_ID,
            'physical_network': 'physnet4',
        },
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.VF_PROD_ID,
            'physical_network': 'physnet4',
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

    def _disable_sriov_in_pf(self, pci_info):
        # Check for PF and change the capability from virt_functions
        # Delete all the VFs
        vfs_to_delete = []

        for device_name, device in pci_info.devices.items():
            if 'virt_functions' in device.pci_device:
                device.generate_xml(skip_capability=True)
            elif 'phys_function' in device.pci_device:
                vfs_to_delete.append(device_name)

        for device in vfs_to_delete:
            del pci_info.devices[device]

    def test_create_server_with_VF(self):

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo()
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.VFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id)

    def test_create_server_with_PF(self):

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo()
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # Create a flavor
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.PFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        self._run_build_test(flavor_id)

    def test_create_server_with_PF_no_VF(self):

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
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

    def test_create_server_with_VF_no_PF(self):

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
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

    def test_create_server_after_change_in_nonsriov_pf_to_sriov_pf(self):
        # Starts a compute with PF not configured with SRIOV capabilities
        # Updates the PF with SRIOV capability and restart the compute service
        # Then starts a VM with the sriov port. The VM should be in active
        # state with sriov port attached.

        # To emulate the device type changing, we first create a
        # HostPCIDevicesInfo object with PFs and VFs. Then we make a copy
        # and remove the VFs and the virt_function capability. This is
        # done to ensure the physical function product id is same in both
        # the versions.
        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=1)
        pci_info_no_sriov = copy.deepcopy(pci_info)

        # Disable SRIOV capabilties in PF and delete the VFs
        self._disable_sriov_in_pf(pci_info_no_sriov)

        fake_connection = self._get_connection(host_info,
                                               pci_info=pci_info_no_sriov,
                                               hostname='test_compute0')
        self.mock_conn.return_value = fake_connection

        self.compute = self.start_service('compute', host='test_compute0')

        ctxt = context.get_admin_context()
        pci_devices = objects.PciDeviceList.get_by_compute_node(
            ctxt,
            objects.ComputeNode.get_by_nodename(
                ctxt, 'test_compute0',
            ).id,
        )
        self.assertEqual(1, len(pci_devices))
        self.assertEqual('type-PCI', pci_devices[0].dev_type)

        # Update connection with original pci info with sriov PFs
        fake_connection = self._get_connection(host_info,
                                               pci_info=pci_info,
                                               hostname='test_compute0')
        self.mock_conn.return_value = fake_connection

        # Restart the compute service
        self.restart_compute_service(self.compute)

        # Verify if PCI devices are of type type-PF or type-VF
        pci_devices = objects.PciDeviceList.get_by_compute_node(
            ctxt,
            objects.ComputeNode.get_by_nodename(
                ctxt, 'test_compute0',
            ).id,
        )
        for pci_device in pci_devices:
            self.assertIn(pci_device.dev_type, ['type-PF', 'type-VF'])

        # create the port
        self.neutron.create_port({'port': self.neutron.network_4_port_1})

        # create a server using the VF via neutron
        flavor_id = self._create_flavor()
        self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'port': base.LibvirtNeutronFixture.network_4_port_1['id']},
            ],
        )


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

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
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
        good_server = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=flavor_id)
        good_server['networks'] = [
            {'uuid': base.LibvirtNeutronFixture.network_1['id']},
            {'uuid': base.LibvirtNeutronFixture.network_4['id']},
        ]

        post = {'server': good_server}
        created_server = self.api.post_server(post)
        self._wait_for_state_change(created_server, 'ACTIVE')

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

    def test_create_server_with_pci_dev_and_numa(self):
        """Verifies that an instance can be booted with cpu pinning and with an
           assigned pci device.
        """

        self.flags(cpu_dedicated_set='0-7', group='compute')

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
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

    def test_create_server_with_pci_dev_and_numa_fails(self):
        """This test ensures that it is not possible to allocated CPU and
           memory resources from one NUMA node and a PCI device from another.
        """

        self.flags(cpu_dedicated_set='0-7', group='compute')

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
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
    end_status = 'ACTIVE'

    def test_create_server_with_pci_dev_and_numa(self):
        """Validate behavior of 'preferred' PCI NUMA policy.

        This test ensures that it *is* possible to allocate CPU and memory
        resources from one NUMA node and a PCI device from another *if* PCI
        NUMA policies are in use.
        """

        self.flags(cpu_dedicated_set='0-7', group='compute')

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
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

        self._run_build_test(flavor_id, end_status=self.end_status)


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
    end_status = 'ERROR'


@ddt.ddt
class PCIServersWithSRIOVAffinityPoliciesTest(_PCIServersTestBase):

    # The order of the filters is required to make the assertion that the
    # PciPassthroughFilter is invoked in _run_build_test pass in the
    # numa affinity tests otherwise the NUMATopologyFilter will eliminate
    # all hosts before we execute the PciPassthroughFilter.
    ADDITIONAL_FILTERS = ['PciPassthroughFilter', 'NUMATopologyFilter']
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
        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=1, numa_node=pci_numa_node)
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        # only allow cpus on numa node 1 to be used for pinning
        self.flags(cpu_dedicated_set='4-7', group='compute')

        # request cpu pinning to create a numa toplogy and allow the test to
        # force which numa node the vm would have to be pinned too.
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
            'hw:pci_numa_affinity_policy': policy
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._run_build_test(flavor_id, end_status=status)

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
