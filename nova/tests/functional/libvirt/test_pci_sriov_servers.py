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

from lxml import etree
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

import nova
from nova import context
from nova import objects
from nova.objects import fields
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base
from nova.tests.unit import fake_notifier
from nova.tests.unit.virt.libvirt import fakelibvirt

CONF = cfg.CONF
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

    def test_create_server_with_neutron(self):
        """Create an instance using a neutron-provisioned SR-IOV VIF."""

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=2)

        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            tree = etree.fromstring(xml)
            elem = tree.find('./devices/interface/source/address')

            # compare address
            expected = ('0x81', '0x00', '0x2')
            actual = (
                elem.get('bus'), elem.get('slot'), elem.get('function'),
            )
            self.assertEqual(expected, actual)

            return orig_create(xml, host)

        self.stub_out(
            'nova.virt.libvirt.guest.Guest.create',
            fake_create,
        )

        self.start_compute(pci_info=pci_info)

        # create the port
        self.neutron.create_port({'port': self.neutron.network_4_port_1})

        # ensure the binding details are currently unset
        port = self.neutron.show_port(
            base.LibvirtNeutronFixture.network_4_port_1['id'],
        )['port']
        self.assertNotIn('binding:profile', port)

        # create a server using the VF via neutron
        flavor_id = self._create_flavor()
        self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'port': base.LibvirtNeutronFixture.network_4_port_1['id']},
            ],
        )

        # ensure the binding details sent to "neutron" were correct
        port = self.neutron.show_port(
            base.LibvirtNeutronFixture.network_4_port_1['id'],
        )['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '8086:1515',
                'pci_slot': '0000:81:00.2',
                'physical_network': 'physnet4',
            },
            port['binding:profile'],
        )

    def test_get_server_diagnostics_server_with_VF(self):
        """Ensure server disagnostics include info on VF-type PCI devices."""

        pci_info = fakelibvirt.HostPCIDevicesInfo()
        self.start_compute(pci_info=pci_info)

        # create the SR-IOV port
        self.neutron.create_port({'port': self.neutron.network_4_port_1})

        # create a server using the VF and multiple networks
        extra_spec = {'pci_passthrough:alias': f'{self.VFS_ALIAS_NAME}:1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'uuid': base.LibvirtNeutronFixture.network_1['id']},
                {'port': base.LibvirtNeutronFixture.network_4_port_1['id']},
            ],
        )

        # now check the server diagnostics to ensure the VF-type PCI device is
        # attached
        diagnostics = self.admin_api.get_server_diagnostics(
            server['id']
        )

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
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=1)
        pci_info_no_sriov = copy.deepcopy(pci_info)

        # Disable SRIOV capabilties in PF and delete the VFs
        self._disable_sriov_in_pf(pci_info_no_sriov)

        fake_connection = self._get_connection(pci_info=pci_info_no_sriov,
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
        fake_connection = self._get_connection(pci_info=pci_info,
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


class SRIOVAttachDetachTest(_PCIServersTestBase):
    # no need for aliases as these test will request SRIOV via neutron
    PCI_ALIAS = []

    PCI_PASSTHROUGH_WHITELIST = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PF_PROD_ID,
            "physical_network": "physnet2",
        },
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.VF_PROD_ID,
            "physical_network": "physnet2",
        },
    )]

    def setUp(self):
        super().setUp()

        self.neutron = self.useFixture(nova_fixtures.NeutronFixture(self))

        # add extra ports and the related network to the neutron fixture
        # specifically for these tests. It cannot be added globally in the
        # fixture init as it adds a second network that makes auto allocation
        # based test to fail due to ambiguous networks.
        self.neutron._networks[
            self.neutron.network_2['id']] = self.neutron.network_2
        self.neutron._subnets[
            self.neutron.subnet_2['id']] = self.neutron.subnet_2
        for port in [self.neutron.sriov_port, self.neutron.sriov_port2,
                     self.neutron.sriov_pf_port, self.neutron.sriov_pf_port2,
                     self.neutron.macvtap_port, self.neutron.macvtap_port2]:
            self.neutron._ports[port['id']] = copy.deepcopy(port)

    def _get_attached_port_ids(self, instance_uuid):
        return [
            attachment['port_id']
            for attachment in self.api.get_port_interfaces(instance_uuid)]

    def _detach_port(self, instance_uuid, port_id):
        self.api.detach_interface(instance_uuid, port_id)
        fake_notifier.wait_for_versioned_notifications(
            'instance.interface_detach.end')

    def _attach_port(self, instance_uuid, port_id):
        self.api.attach_interface(
            instance_uuid,
            {'interfaceAttachment': {'port_id': port_id}})
        fake_notifier.wait_for_versioned_notifications(
            'instance.interface_attach.end')

    def _test_detach_attach(self, first_port_id, second_port_id):
        # This test takes two ports that requires PCI claim.
        # Starts a compute with one PF and one connected VF.
        # Then starts a VM with the first port. Then detach it, then
        # re-attach it. These expected to be successful. Then try to attach the
        # second port and asserts that it fails as no free PCI device left on
        # the host.
        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2,
                                         kB_mem=15740000)
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=1)
        fake_connection = self._get_connection(host_info, pci_info)
        self.mock_conn.return_value = fake_connection

        self.compute = self.start_service('compute', host='test_compute0')

        # Create server with a port
        server = self._create_server(networks=[{'port': first_port_id}])

        updated_port = self.neutron.show_port(first_port_id)['port']
        self.assertEqual('test_compute0', updated_port['binding:host_id'])
        self.assertIn(first_port_id, self._get_attached_port_ids(server['id']))

        self._detach_port(server['id'], first_port_id)

        updated_port = self.neutron.show_port(first_port_id)['port']
        self.assertIsNone(updated_port['binding:host_id'])
        self.assertNotIn(
            first_port_id,
            self._get_attached_port_ids(server['id']))

        # Attach back the port
        self._attach_port(server['id'], first_port_id)

        updated_port = self.neutron.show_port(first_port_id)['port']
        self.assertEqual('test_compute0', updated_port['binding:host_id'])
        self.assertIn(first_port_id, self._get_attached_port_ids(server['id']))

        # Try to attach the second port but no free PCI device left
        ex = self.assertRaises(
            client.OpenStackApiException, self._attach_port, server['id'],
            second_port_id)

        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Failed to claim PCI device', str(ex))
        attached_ports = self._get_attached_port_ids(server['id'])
        self.assertIn(first_port_id, attached_ports)
        self.assertNotIn(second_port_id, attached_ports)

    def test_detach_attach_direct(self):
        self._test_detach_attach(
            self.neutron.sriov_port['id'], self.neutron.sriov_port2['id'])

    def test_detach_macvtap(self):
        self._test_detach_attach(
            self.neutron.macvtap_port['id'],
            self.neutron.macvtap_port2['id'])

    def test_detach_direct_physical(self):
        self._test_detach_attach(
            self.neutron.sriov_pf_port['id'],
            self.neutron.sriov_pf_port2['id'])


class PCIServersTest(_PCIServersTestBase):

    ADMIN_API = True
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

    def _confirm_resize(self, server, host='host1'):
        # NOTE(sbauza): Unfortunately, _cleanup_resize() in libvirt checks the
        # host option to know the source hostname but given we have a global
        # CONF, the value will be the hostname of the last compute service that
        # was created, so we need to change it here.
        # TODO(sbauza): Remove the below once we stop using CONF.host in
        # libvirt and rather looking at the compute host value.
        orig_host = CONF.host
        self.flags(host=host)
        super()._confirm_resize(server)
        self.flags(host=orig_host)

    def assertPCIDeviceCounts(self, hostname, total, free):
        """Ensure $hostname has $total devices, $free of which are free."""
        ctxt = context.get_admin_context()
        devices = objects.PciDeviceList.get_by_compute_node(
            ctxt, objects.ComputeNode.get_by_nodename(ctxt, hostname).id,
        )
        self.assertEqual(total, len(devices))
        self.assertEqual(free, len([d for d in devices if d.is_available()]))

    def test_cold_migrate_server_with_pci(self):

        host_devices = {}
        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            tree = etree.fromstring(xml)
            elem = tree.find('./devices/hostdev/source/address')

            hostname = host.get_hostname()
            address = (
                elem.get('bus'), elem.get('slot'), elem.get('function'),
            )
            if hostname in host_devices:
                self.assertNotIn(address, host_devices[hostname])
            else:
                host_devices[hostname] = []
            host_devices[host.get_hostname()].append(address)

            return orig_create(xml, host)

        self.stub_out(
            'nova.virt.libvirt.guest.Guest.create',
            fake_create,
        )

        # start two compute services
        for hostname in ('test_compute0', 'test_compute1'):
            pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=2)
            self.start_compute(hostname=hostname, pci_info=pci_info)

        # boot an instance with a PCI device on each host
        extra_spec = {
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        server_a = self._create_server(
            flavor_id=flavor_id, networks='none', host='test_compute0')
        server_b = self._create_server(
            flavor_id=flavor_id, networks='none', host='test_compute1')

        # the instances should have landed on separate hosts; ensure both hosts
        # have one used PCI device and one free PCI device
        self.assertNotEqual(
            server_a['OS-EXT-SRV-ATTR:host'], server_b['OS-EXT-SRV-ATTR:host'],
        )
        for hostname in ('test_compute0', 'test_compute1'):
            self.assertPCIDeviceCounts(hostname, total=2, free=1)

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            # TODO(stephenfin): Use a helper
            self.api.post_server_action(server_a['id'], {'migrate': None})
            server_a = self._wait_for_state_change(server_a, 'VERIFY_RESIZE')

        # the instances should now be on the same host; ensure the source host
        # still has one used PCI device while the destination now has two used
        # test_compute0 initially
        self.assertEqual(
            server_a['OS-EXT-SRV-ATTR:host'], server_b['OS-EXT-SRV-ATTR:host'],
        )
        self.assertPCIDeviceCounts('test_compute0', total=2, free=1)
        self.assertPCIDeviceCounts('test_compute1', total=2, free=0)

        # now, confirm the migration and check our counts once again
        self._confirm_resize(server_a)

        self.assertPCIDeviceCounts('test_compute0', total=2, free=2)
        self.assertPCIDeviceCounts('test_compute1', total=2, free=0)


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
