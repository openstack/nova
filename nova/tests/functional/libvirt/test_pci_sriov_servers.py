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
from urllib import parse as urlparse

import ddt
import fixtures
from lxml import etree
import mock
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import units

import nova
from nova import context
from nova.network import constants
from nova import objects
from nova.objects import fields
from nova.tests import fixtures as nova_fixtures
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class _PCIServersTestBase(base.ServersTestBase):

    ADDITIONAL_FILTERS = ['NUMATopologyFilter', 'PciPassthroughFilter']

    def setUp(self):
        self.ctxt = context.get_admin_context()
        self.flags(passthrough_whitelist=self.PCI_PASSTHROUGH_WHITELIST,
                   alias=self.PCI_ALIAS,
                   group='pci')

        super(_PCIServersTestBase, self).setUp()

        # Mock the 'PciPassthroughFilter' filter, as most tests need to inspect
        # this
        host_manager = self.scheduler.manager.host_manager
        pci_filter_class = host_manager.filter_cls_map['PciPassthroughFilter']
        host_pass_mock = mock.Mock(wraps=pci_filter_class().host_passes)
        self.mock_filter = self.useFixture(fixtures.MockPatch(
            'nova.scheduler.filters.pci_passthrough_filter'
            '.PciPassthroughFilter.host_passes',
            side_effect=host_pass_mock)).mock

    def assertPCIDeviceCounts(self, hostname, total, free):
        """Ensure $hostname has $total devices, $free of which are free."""
        devices = objects.PciDeviceList.get_by_compute_node(
            self.ctxt,
            objects.ComputeNode.get_by_nodename(self.ctxt, hostname).id,
        )
        self.assertEqual(total, len(devices))
        self.assertEqual(free, len([d for d in devices if d.is_available()]))


class SRIOVServersTest(_PCIServersTestBase):

    # TODO(stephenfin): We're using this because we want to be able to force
    # the host during scheduling. We should instead look at overriding policy
    ADMIN_API = True
    microversion = 'latest'

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

        self.useFixture(fixtures.MonkeyPatch(
            'nova.tests.fixtures.libvirt.Domain.migrateToURI3',
            self._migrate_stub))

    def _migrate_stub(self, domain, destination, params, flags):
        """Stub out migrateToURI3."""

        src_hostname = domain._connection.hostname
        dst_hostname = urlparse.urlparse(destination).netloc

        # In a real live migration, libvirt and QEMU on the source and
        # destination talk it out, resulting in the instance starting to exist
        # on the destination. Fakelibvirt cannot do that, so we have to
        # manually create the "incoming" instance on the destination
        # fakelibvirt.
        dst = self.computes[dst_hostname]
        dst.driver._host.get_connection().createXML(
            params['destination_xml'],
            'fake-createXML-doesnt-care-about-flags')

        src = self.computes[src_hostname]
        conn = src.driver._host.get_connection()

        # because migrateToURI3 is spawned in a background thread, this method
        # does not block the upper nova layers. Because we don't want nova to
        # think the live migration has finished until this method is done, the
        # last thing we do is make fakelibvirt's Domain.jobStats() return
        # VIR_DOMAIN_JOB_COMPLETED.
        server = etree.fromstring(
            params['destination_xml']
        ).find('./uuid').text
        dom = conn.lookupByUUIDString(server)
        dom.complete_job()

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
        self._create_server(
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

    def test_live_migrate_server_with_PF(self):
        """Live migrate an instance with a PCI PF.

        This should fail because it's not possible to live migrate an instance
        with a PCI passthrough device, even if it's a SR-IOV PF.
        """

        # start two compute services
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=4))
        self.start_compute(
            hostname='test_compute1',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=4))

        # create a server
        extra_spec = {'pci_passthrough:alias': f'{self.PFS_ALIAS_NAME}:1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks='none')

        # now live migrate that server
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._live_migrate,
            server, 'completed')
        # NOTE(stephenfin): this wouldn't happen in a real deployment since
        # live migration is a cast, but since we are using CastAsCallFixture
        # this will bubble to the API
        self.assertEqual(500, ex.response.status_code)
        self.assertIn('NoValidHost', str(ex))

    def test_live_migrate_server_with_VF(self):
        """Live migrate an instance with a PCI VF.

        This should fail because it's not possible to live migrate an instance
        with a PCI passthrough device, even if it's a SR-IOV VF.
        """

        # start two compute services
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=4))
        self.start_compute(
            hostname='test_compute1',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=4))

        # create a server
        extra_spec = {'pci_passthrough:alias': f'{self.VFS_ALIAS_NAME}:1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks='none')

        # now live migrate that server
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._live_migrate,
            server, 'completed')
        # NOTE(stephenfin): this wouldn't happen in a real deployment since
        # live migration is a cast, but since we are using CastAsCallFixture
        # this will bubble to the API
        self.assertEqual(500, ex.response.status_code)
        self.assertIn('NoValidHost', str(ex))

    def _test_move_operation_with_neutron(self, move_operation,
                                          expect_fail=False):
        # The purpose here is to force an observable PCI slot update when
        # moving from source to dest. This is accomplished by having a single
        # PCI device on the source, 2 PCI devices on the test, and relying on
        # the fact that our fake HostPCIDevicesInfo creates predictable PCI
        # addresses. The PCI device on source and the first PCI device on dest
        # will have identical PCI addresses. By sticking a "placeholder"
        # instance on that first PCI device on the dest, the incoming instance
        # from source will be forced to consume the second dest PCI device,
        # with a different PCI address.
        self.start_compute(
            hostname='source',
            pci_info=fakelibvirt.HostPCIDevicesInfo(
                num_pfs=1, num_vfs=1))
        self.start_compute(
            hostname='dest',
            pci_info=fakelibvirt.HostPCIDevicesInfo(
                num_pfs=1, num_vfs=2))

        source_port = self.neutron.create_port(
            {'port': self.neutron.network_4_port_1})
        dest_port1 = self.neutron.create_port(
            {'port': self.neutron.network_4_port_2})
        dest_port2 = self.neutron.create_port(
            {'port': self.neutron.network_4_port_3})

        source_server = self._create_server(
            networks=[{'port': source_port['port']['id']}], host='source')
        dest_server1 = self._create_server(
            networks=[{'port': dest_port1['port']['id']}], host='dest')
        dest_server2 = self._create_server(
            networks=[{'port': dest_port2['port']['id']}], host='dest')

        # Refresh the ports.
        source_port = self.neutron.show_port(source_port['port']['id'])
        dest_port1 = self.neutron.show_port(dest_port1['port']['id'])
        dest_port2 = self.neutron.show_port(dest_port2['port']['id'])

        # Find the server on the dest compute that's using the same pci_slot as
        # the server on the source compute, and delete the other one to make
        # room for the incoming server from the source.
        source_pci_slot = source_port['port']['binding:profile']['pci_slot']
        dest_pci_slot1 = dest_port1['port']['binding:profile']['pci_slot']
        if dest_pci_slot1 == source_pci_slot:
            same_slot_port = dest_port1
            self._delete_server(dest_server2)
        else:
            same_slot_port = dest_port2
            self._delete_server(dest_server1)

        # Before moving, explictly assert that the servers on source and dest
        # have the same pci_slot in their port's binding profile
        self.assertEqual(source_port['port']['binding:profile']['pci_slot'],
                         same_slot_port['port']['binding:profile']['pci_slot'])

        # Before moving, assert that the servers on source and dest have the
        # same PCI source address in their XML for their SRIOV nic.
        source_conn = self.computes['source'].driver._host.get_connection()
        dest_conn = self.computes['source'].driver._host.get_connection()
        source_vms = [vm._def for vm in source_conn._vms.values()]
        dest_vms = [vm._def for vm in dest_conn._vms.values()]
        self.assertEqual(1, len(source_vms))
        self.assertEqual(1, len(dest_vms))
        self.assertEqual(1, len(source_vms[0]['devices']['nics']))
        self.assertEqual(1, len(dest_vms[0]['devices']['nics']))
        self.assertEqual(source_vms[0]['devices']['nics'][0]['source'],
                         dest_vms[0]['devices']['nics'][0]['source'])

        move_operation(source_server)

        # Refresh the ports again, keeping in mind the source_port is now bound
        # on the dest after unshelving.
        source_port = self.neutron.show_port(source_port['port']['id'])
        same_slot_port = self.neutron.show_port(same_slot_port['port']['id'])

        self.assertNotEqual(
            source_port['port']['binding:profile']['pci_slot'],
            same_slot_port['port']['binding:profile']['pci_slot'])

        conn = self.computes['dest'].driver._host.get_connection()
        vms = [vm._def for vm in conn._vms.values()]
        self.assertEqual(2, len(vms))
        for vm in vms:
            self.assertEqual(1, len(vm['devices']['nics']))
        self.assertNotEqual(vms[0]['devices']['nics'][0]['source'],
                            vms[1]['devices']['nics'][0]['source'])

    def test_unshelve_server_with_neutron(self):
        def move_operation(source_server):
            self._shelve_server(source_server)
            # Disable the source compute, to force unshelving on the dest.
            self.api.put_service(self.computes['source'].service_ref.uuid,
                                 {'status': 'disabled'})
            self._unshelve_server(source_server)
        self._test_move_operation_with_neutron(move_operation)

    def test_cold_migrate_server_with_neutron(self):
        def move_operation(source_server):
            # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
            # probably be less...dumb
            with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                            '.migrate_disk_and_power_off', return_value='{}'):
                self._migrate_server(source_server)
            self._confirm_resize(source_server)
        self._test_move_operation_with_neutron(move_operation)

    def test_evacuate_server_with_neutron(self):
        def move_operation(source_server):
            # Down the source compute to enable the evacuation
            self.api.put_service(self.computes['source'].service_ref.uuid,
                                 {'forced_down': True})
            self.computes['source'].stop()
            self._evacuate_server(source_server)
        self._test_move_operation_with_neutron(move_operation)

    def test_live_migrate_server_with_neutron(self):
        """Live migrate an instance using a neutron-provisioned SR-IOV VIF.

        This should succeed since we support this, via detach and attach of the
        PCI device.
        """

        # start two compute services with differing PCI device inventory
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(
                num_pfs=2, num_vfs=8, numa_node=0))
        self.start_compute(
            hostname='test_compute1',
            pci_info=fakelibvirt.HostPCIDevicesInfo(
                num_pfs=1, num_vfs=2, numa_node=1))

        # create the port
        self.neutron.create_port({'port': self.neutron.network_4_port_1})

        # create a server using the VF via neutron
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'port': base.LibvirtNeutronFixture.network_4_port_1['id']},
            ],
            host='test_compute0',
        )

        # our source host should have marked two PCI devices as used, the VF
        # and the parent PF, while the future destination is currently unused
        self.assertEqual('test_compute0', server['OS-EXT-SRV-ATTR:host'])
        self.assertPCIDeviceCounts('test_compute0', total=10, free=8)
        self.assertPCIDeviceCounts('test_compute1', total=3, free=3)

        # the instance should be on host NUMA node 0, since that's where our
        # PCI devices are
        host_numa = objects.NUMATopology.obj_from_db_obj(
            objects.ComputeNode.get_by_nodename(
                self.ctxt, 'test_compute0',
            ).numa_topology
        )
        self.assertEqual({0, 1, 2, 3}, host_numa.cells[0].pinned_cpus)
        self.assertEqual(set(), host_numa.cells[1].pinned_cpus)

        # ensure the binding details sent to "neutron" are correct
        port = self.neutron.show_port(
            base.LibvirtNeutronFixture.network_4_port_1['id'],
        )['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '8086:1515',
                # TODO(stephenfin): Stop relying on a side-effect of how nova
                # chooses from multiple PCI devices (apparently the last
                # matching one)
                'pci_slot': '0000:81:01.4',
                'physical_network': 'physnet4',
            },
            port['binding:profile'],
        )

        # now live migrate that server
        self._live_migrate(server, 'completed')

        # we should now have transitioned our usage to the destination, freeing
        # up the source in the process
        self.assertPCIDeviceCounts('test_compute0', total=10, free=10)
        self.assertPCIDeviceCounts('test_compute1', total=3, free=1)

        # the instance should now be on host NUMA node 1, since that's where
        # our PCI devices are for this second host
        host_numa = objects.NUMATopology.obj_from_db_obj(
            objects.ComputeNode.get_by_nodename(
                self.ctxt, 'test_compute1',
            ).numa_topology
        )
        self.assertEqual(set(), host_numa.cells[0].pinned_cpus)
        self.assertEqual({4, 5, 6, 7}, host_numa.cells[1].pinned_cpus)

        # ensure the binding details sent to "neutron" have been updated
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
        port = self.neutron.create_port(
            {'port': self.neutron.network_4_port_1})

        flavor_id = self._create_flavor()
        server = self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'uuid': base.LibvirtNeutronFixture.network_1['id']},
                {'port': port['port']['id']},
            ],
        )

        # now check the server diagnostics to ensure the VF-type PCI device is
        # attached
        diagnostics = self.api.get_server_diagnostics(
            server['id']
        )

        self.assertEqual(
            base.LibvirtNeutronFixture.network_1_port_2['mac_address'],
            diagnostics['nic_details'][0]['mac_address'],
        )

        for key in ('rx_packets', 'tx_packets'):
            self.assertIn(key, diagnostics['nic_details'][0])

        self.assertEqual(
            base.LibvirtNeutronFixture.network_4_port_1['mac_address'],
            diagnostics['nic_details'][1]['mac_address'],
        )
        for key in ('rx_packets', 'tx_packets'):
            self.assertIn(key, diagnostics['nic_details'][1])

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
        self._create_server(
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
        self.notifier.wait_for_versioned_notifications(
            'instance.interface_detach.end')

    def _attach_port(self, instance_uuid, port_id):
        self.api.attach_interface(
            instance_uuid,
            {'interfaceAttachment': {'port_id': port_id}})
        self.notifier.wait_for_versioned_notifications(
            'instance.interface_attach.end')

    def _test_detach_attach(self, first_port_id, second_port_id):
        # This test takes two ports that requires PCI claim.
        # Starts a compute with one PF and one connected VF.
        # Then starts a VM with the first port. Then detach it, then
        # re-attach it. These expected to be successful. Then try to attach the
        # second port and asserts that it fails as no free PCI device left on
        # the host.
        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=2)
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


class VDPAServersTest(_PCIServersTestBase):

    # this is needed for os_compute_api:os-migrate-server:migrate policy
    ADMIN_API = True
    microversion = 'latest'

    # Whitelist both the PF and VF; in reality, you probably wouldn't do this
    # but we want to make sure that the PF is correctly taken off the table
    # once any VF is used
    PCI_PASSTHROUGH_WHITELIST = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': '15b3',
            'product_id': '101d',
            'physical_network': 'physnet4',
        },
        {
            'vendor_id': '15b3',
            'product_id': '101e',
            'physical_network': 'physnet4',
        },
    )]
    # No need for aliases as these test will request SRIOV via neutron
    PCI_ALIAS = []

    NUM_PFS = 1
    NUM_VFS = 4

    FAKE_LIBVIRT_VERSION = 6_009_000  # 6.9.0
    FAKE_QEMU_VERSION = 5_001_000  # 5.1.0

    def setUp(self):
        super().setUp()

        # The ultimate base class _IntegratedTestBase uses NeutronFixture but
        # we need a bit more intelligent neutron for these tests. Applying the
        # new fixture here means that we re-stub what the previous neutron
        # fixture already stubbed.
        self.neutron = self.useFixture(base.LibvirtNeutronFixture(self))

    def start_compute(self):
        vf_ratio = self.NUM_VFS // self.NUM_PFS

        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0)
        vdpa_info = fakelibvirt.HostVDPADevicesInfo()

        pci_info.add_device(
            dev_type='PF',
            bus=0x6,
            slot=0x0,
            function=0,
            iommu_group=40,  # totally arbitrary number
            numa_node=0,
            vf_ratio=vf_ratio,
            vend_id='15b3',
            vend_name='Mellanox Technologies',
            prod_id='101d',
            prod_name='MT2892 Family [ConnectX-6 Dx]',
            driver_name='mlx5_core')

        for idx in range(self.NUM_VFS):
            vf = pci_info.add_device(
                dev_type='VF',
                bus=0x6,
                slot=0x0,
                function=idx + 1,
                iommu_group=idx + 41,  # totally arbitrary number + offset
                numa_node=0,
                vf_ratio=vf_ratio,
                parent=(0x6, 0x0, 0),
                vend_id='15b3',
                vend_name='Mellanox Technologies',
                prod_id='101e',
                prod_name='ConnectX Family mlx5Gen Virtual Function',
                driver_name='mlx5_core')
            vdpa_info.add_device(f'vdpa_vdpa{idx}', idx, vf)

        return super().start_compute(
            pci_info=pci_info, vdpa_info=vdpa_info,
            libvirt_version=self.FAKE_LIBVIRT_VERSION,
            qemu_version=self.FAKE_QEMU_VERSION)

    def create_vdpa_port(self):
        vdpa_port = {
            'id': uuids.vdpa_port,
            'network_id': self.neutron.network_4['id'],
            'status': 'ACTIVE',
            'mac_address': 'b5:bc:2e:e7:51:ee',
            'fixed_ips': [
                {
                    'ip_address': '192.168.4.6',
                    'subnet_id': self.neutron.subnet_4['id']
                }
            ],
            'binding:vif_details': {},
            'binding:vif_type': 'ovs',
            'binding:vnic_type': 'vdpa',
        }

        # create the port
        self.neutron.create_port({'port': vdpa_port})
        return vdpa_port

    def test_create_server(self):
        """Create an instance using a neutron-provisioned vDPA VIF."""

        orig_create = nova.virt.libvirt.guest.Guest.create

        def fake_create(cls, xml, host):
            tree = etree.fromstring(xml)
            elem = tree.find('./devices/interface/[@type="vdpa"]')

            # compare source device
            # the MAC address is derived from the neutron port, while the
            # source dev path assumes we attach vDPA devs in order
            expected = """
                <interface type="vdpa">
                  <mac address="b5:bc:2e:e7:51:ee"/>
                  <model type="virtio"/>
                  <source dev="/dev/vhost-vdpa-3"/>
                </interface>"""
            actual = etree.tostring(elem, encoding='unicode')

            self.assertXmlEqual(expected, actual)

            return orig_create(xml, host)

        self.stub_out(
            'nova.virt.libvirt.guest.Guest.create',
            fake_create,
        )

        hostname = self.start_compute()
        num_pci = self.NUM_PFS + self.NUM_VFS

        # both the PF and VF with vDPA capabilities (dev_type=vdpa) should have
        # been counted
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci)

        # create the port
        vdpa_port = self.create_vdpa_port()

        # ensure the binding details are currently unset
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertNotIn('binding:profile', port)

        # create a server using the vDPA device via neutron
        self._create_server(networks=[{'port': vdpa_port['id']}])

        # ensure there is one less VF available and that the PF is no longer
        # usable
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci - 2)

        # ensure the binding details sent to "neutron" were correct
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '15b3:101e',
                'pci_slot': '0000:06:00.4',
                'physical_network': 'physnet4',
            },
            port['binding:profile'],
        )

    def _test_common(self, op, *args, **kwargs):
        self.start_compute()

        # create the port and a server, with the port attached to the server
        vdpa_port = self.create_vdpa_port()
        server = self._create_server(networks=[{'port': vdpa_port['id']}])

        # attempt the unsupported action and ensure it fails
        ex = self.assertRaises(
            client.OpenStackApiException,
            op, server, *args, **kwargs)
        self.assertIn(
            'not supported for instance with vDPA ports',
            ex.response.text)

    def test_attach_interface(self):
        self.start_compute()

        # create the port and a server, but don't attach the port to the server
        # yet
        vdpa_port = self.create_vdpa_port()
        server = self._create_server(networks='none')

        # attempt to attach the port to the server
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._attach_interface, server, vdpa_port['id'])
        self.assertIn(
            'not supported for instance with vDPA ports',
            ex.response.text)

    def test_detach_interface(self):
        self._test_common(self._detach_interface, uuids.vdpa_port)

    def test_shelve(self):
        self._test_common(self._shelve_server)

    def test_suspend(self):
        self._test_common(self._suspend_server)

    def test_evacute(self):
        self._test_common(self._evacuate_server)

    def test_resize(self):
        flavor_id = self._create_flavor()
        self._test_common(self._resize_server, flavor_id)

    def test_cold_migrate(self):
        self._test_common(self._migrate_server)


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

    def test_live_migrate_server_with_pci(self):
        """Live migrate an instance with a PCI passthrough device.

        This should fail because it's not possible to live migrate an instance
        with a PCI passthrough device, even if it's a SR-IOV VF.
        """

        # start two compute services
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))
        self.start_compute(
            hostname='test_compute1',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))

        # create a server
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks='none')

        # now live migrate that server
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._live_migrate,
            server, 'completed')
        # NOTE(stephenfin): this wouldn't happen in a real deployment since
        # live migration is a cast, but since we are using CastAsCallFixture
        # this will bubble to the API
        self.assertEqual(500, ex.response.status_code)
        self.assertIn('NoValidHost', str(ex))

    def test_resize_pci_to_vanilla(self):
        # Start two computes, one with PCI and one without.
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))
        self.start_compute(hostname='test_compute1')

        # Boot a server with a single PCI device.
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=pci_flavor_id, networks='none')

        # Resize it to a flavor without PCI devices. We expect this to work, as
        # test_compute1 is available.
        # FIXME(artom) This is bug 1941005.
        flavor_id = self._create_flavor()
        ex = self.assertRaises(client.OpenStackApiException,
                               self._resize_server, server, flavor_id)
        self.assertEqual(500, ex.response.status_code)
        self.assertIn('NoValidHost', str(ex))
        # self._confirm_resize(server)

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

    def test_socket_policy_pass(self):
        # With 1 socket containing 2 NUMA nodes, make the first node's CPU
        # available for pinning, but affine the PCI device to the second node.
        # This should pass.
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=2, cpu_sockets=1, cpu_cores=2, cpu_threads=2,
            kB_mem=(16 * units.Gi) // units.Ki)
        self.flags(cpu_dedicated_set='0-3', group='compute')
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=1)

        self.start_compute(host_info=host_info, pci_info=pci_info)

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
            'hw:pci_numa_affinity_policy': 'socket'
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id)
        self.assertTrue(self.mock_filter.called)

    def test_socket_policy_fail(self):
        # With 2 sockets containing 1 NUMA node each, make the first socket's
        # CPUs available for pinning, but affine the PCI device to the second
        # NUMA node in the second socket. This should fail.
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=1, cpu_sockets=2, cpu_cores=2, cpu_threads=2,
            kB_mem=(16 * units.Gi) // units.Ki)
        self.flags(cpu_dedicated_set='0-3', group='compute')
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=1)
        self.start_compute(host_info=host_info, pci_info=pci_info)

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
            'hw:pci_numa_affinity_policy': 'socket'
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, expected_state='ERROR')
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

    def test_socket_policy_multi_numa_pass(self):
        # 2 sockets, 2 NUMA nodes each, with the PCI device on NUMA 0 and
        # socket 0. If we restrict cpu_dedicated_set to NUMA 1, 2 and 3, we
        # should still be able to boot an instance with hw:numa_nodes=3 and the
        # `socket` policy, because one of the instance's NUMA nodes will be on
        # the same socket as the PCI device (even if there is no direct NUMA
        # node affinity).
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=2, cpu_sockets=2, cpu_cores=2, cpu_threads=1,
            kB_mem=(16 * units.Gi) // units.Ki)
        self.flags(cpu_dedicated_set='2-7', group='compute')
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=0)

        self.start_compute(host_info=host_info, pci_info=pci_info)

        extra_spec = {
            'hw:numa_nodes': '3',
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
            'hw:pci_numa_affinity_policy': 'socket'
        }
        flavor_id = self._create_flavor(vcpu=6, memory_mb=3144,
                                        extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id)
        self.assertTrue(self.mock_filter.called)


@ddt.ddt
class PCIServersWithPortNUMAPoliciesTest(_PCIServersTestBase):

    ALIAS_NAME = 'a1'
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

    def setUp(self):
        super().setUp()

        # The ultimate base class _IntegratedTestBase uses NeutronFixture but
        # we need a bit more intelligent neutron for these tests. Applying the
        # new fixture here means that we re-stub what the previous neutron
        # fixture already stubbed.
        self.neutron = self.useFixture(base.LibvirtNeutronFixture(self))
        self.flags(disable_fallback_pcpu_query=True, group='workarounds')

    def _create_port_with_policy(self, policy):
        port_data = copy.deepcopy(
            base.LibvirtNeutronFixture.network_4_port_1)
        port_data[constants.NUMA_POLICY] = policy
        # create the port
        new_port = self.neutron.create_port({'port': port_data})
        port_id = new_port['port']['id']
        port = self.neutron.show_port(port_id)['port']
        self.assertEqual(port[constants.NUMA_POLICY], policy)
        return port_id

    # NOTE(sean-k-mooney): i could just apply the ddt decorators
    # to this function for the most part but i have chosen to
    # keep one top level function per policy to make documenting
    # the test cases simpler.
    def _test_policy(self, pci_numa_node, status, policy):
        # only allow cpus on numa node 1 to be used for pinning
        self.flags(cpu_dedicated_set='4-7', group='compute')
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=1, num_vfs=2, numa_node=pci_numa_node)
        self.start_compute(pci_info=pci_info)

        # request cpu pinning to create a numa toplogy and allow the test to
        # force which numa node the vm would have to be pinned too.
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        port_id = self._create_port_with_policy(policy)
        # create a server using the VF via neutron
        self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'port': port_id},
            ],
            expected_state=status
        )

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
        the port NUMA affinity policy is set to preferred.
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
        the port NUMA affinity policy is set to legacy and the device
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
        the port NUMA affinity policy is set to required and the device
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

    def test_socket_policy_pass(self):
        # With 1 socket containing 2 NUMA nodes, make the first node's CPU
        # available for pinning, but affine the PCI device to the second node.
        # This should pass.
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=2, cpu_sockets=1, cpu_cores=2, cpu_threads=2,
            kB_mem=(16 * units.Gi) // units.Ki)
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=1, num_vfs=1, numa_node=1)
        self.flags(cpu_dedicated_set='0-3', group='compute')
        self.start_compute(host_info=host_info, pci_info=pci_info)

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        port_id = self._create_port_with_policy('socket')
        # create a server using the VF via neutron
        self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'port': port_id},
            ],
        )
        self.assertTrue(self.mock_filter.called)

    def test_socket_policy_fail(self):
        # With 2 sockets containing 1 NUMA node each, make the first socket's
        # CPUs available for pinning, but affine the PCI device to the second
        # NUMA node in the second socket. This should fail.
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=1, cpu_sockets=2, cpu_cores=2, cpu_threads=2,
            kB_mem=(16 * units.Gi) // units.Ki)
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=1, num_vfs=1, numa_node=1)
        self.flags(cpu_dedicated_set='0-3', group='compute')
        self.start_compute(host_info=host_info, pci_info=pci_info)

        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        port_id = self._create_port_with_policy('socket')
        # create a server using the VF via neutron
        server = self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'port': port_id},
            ],
            expected_state='ERROR'
        )
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])
        self.assertFalse(self.mock_filter.called)

    def test_socket_policy_multi_numa_pass(self):
        # 2 sockets, 2 NUMA nodes each, with the PCI device on NUMA 0 and
        # socket 0. If we restrict cpu_dedicated_set to NUMA 1, 2 and 3, we
        # should still be able to boot an instance with hw:numa_nodes=3 and the
        # `socket` policy, because one of the instance's NUMA nodes will be on
        # the same socket as the PCI device (even if there is no direct NUMA
        # node affinity).
        host_info = fakelibvirt.HostInfo(
            cpu_nodes=2, cpu_sockets=2, cpu_cores=2, cpu_threads=1,
            kB_mem=(16 * units.Gi) // units.Ki)
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=1, num_vfs=1, numa_node=0)
        self.flags(cpu_dedicated_set='2-7', group='compute')
        self.start_compute(host_info=host_info, pci_info=pci_info)

        extra_spec = {
            'hw:numa_nodes': '3',
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(vcpu=6, memory_mb=3144,
                                        extra_spec=extra_spec)
        port_id = self._create_port_with_policy('socket')
        # create a server using the VF via neutron
        self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'port': port_id},
            ],
        )
        self.assertTrue(self.mock_filter.called)
