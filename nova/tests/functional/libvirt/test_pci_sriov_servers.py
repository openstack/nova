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
import pprint
import typing as ty
from unittest import mock
from urllib import parse as urlparse

import ddt
import fixtures
from lxml import etree
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import units

import nova
from nova.compute import pci_placement_translator
from nova import context
from nova import exception
from nova.network import constants
from nova import objects
from nova.objects import fields
from nova.pci.utils import parse_address
from nova.tests import fixtures as nova_fixtures
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class PciPlacementHealingFixture(fixtures.Fixture):
    """Allow asserting if the pci_placement_translator module needed to
    heal PCI allocations. Such healing is only normal during upgrade. After
    every compute is upgraded and the scheduling support of PCI tracking in
    placement is enabled there should be no need to heal PCI allocations in
    the resource tracker. We assert this as we eventually want to remove the
    automatic healing logic from the resource tracker.
    """

    def __init__(self):
        super().__init__()
        # a list of (nodename, result, allocation_before, allocation_after)
        # tuples recoding the result of the calls to
        # update_provider_tree_for_pci
        self.calls = []

    def setUp(self):
        super().setUp()

        orig = pci_placement_translator.update_provider_tree_for_pci

        def wrapped_update(
            provider_tree, nodename, pci_tracker, allocations, same_host
        ):
            alloc_before = copy.deepcopy(allocations)
            updated = orig(
                provider_tree, nodename, pci_tracker, allocations, same_host)
            alloc_after = copy.deepcopy(allocations)
            self.calls.append((nodename, updated, alloc_before, alloc_after))
            return updated

        self.useFixture(
            fixtures.MonkeyPatch(
                "nova.compute.pci_placement_translator."
                "update_provider_tree_for_pci",
                wrapped_update,
            )
        )

    def last_healing(self, hostname: str) -> ty.Optional[ty.Tuple[dict, dict]]:
        for h, updated, before, after in self.calls:
            if h == hostname and updated:
                return before, after
        return None


class _PCIServersTestBase(base.ServersTestBase):

    ADDITIONAL_FILTERS = ['NUMATopologyFilter', 'PciPassthroughFilter']

    PCI_RC = f"CUSTOM_PCI_{fakelibvirt.PCI_VEND_ID}_{fakelibvirt.PCI_PROD_ID}"

    def setUp(self):
        self.ctxt = context.get_admin_context()
        self.flags(
            device_spec=self.PCI_DEVICE_SPEC,
            alias=self.PCI_ALIAS,
            group='pci'
        )

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

        self.pci_healing_fixture = self.useFixture(
            PciPlacementHealingFixture())

    def assertPCIDeviceCounts(self, hostname, total, free):
        """Ensure $hostname has $total devices, $free of which are free."""
        devices = objects.PciDeviceList.get_by_compute_node(
            self.ctxt,
            objects.ComputeNode.get_by_nodename(self.ctxt, hostname).id,
        )
        self.assertEqual(total, len(devices))
        self.assertEqual(free, len([d for d in devices if d.is_available()]))

    def assert_no_pci_healing(self, hostname):
        last_healing = self.pci_healing_fixture.last_healing(hostname)
        before = last_healing[0] if last_healing else None
        after = last_healing[1] if last_healing else None
        self.assertIsNone(
            last_healing,
            "The resource tracker needed to heal PCI allocation in placement "
            "on host %s. This should not happen in normal operation as the "
            "scheduler should create the proper allocation instead.\n"
            "Allocations before healing:\n %s\n"
            "Allocations after healing:\n %s\n"
            % (
                hostname,
                pprint.pformat(before),
                pprint.pformat(after),
            ),
        )

    def _get_rp_by_name(self, name, rps):
        for rp in rps:
            if rp["name"] == name:
                return rp
        self.fail(f'RP {name} is not found in Placement {rps}')

    def assert_placement_pci_inventory(self, hostname, inventories, traits):
        compute_rp_uuid = self.compute_rp_uuids[hostname]
        rps = self._get_all_rps_in_a_tree(compute_rp_uuid)

        # rps also contains the root provider so we subtract 1
        self.assertEqual(
            len(inventories),
            len(rps) - 1,
            f"Number of RPs on {hostname} doesn't match. "
            f"Expected {list(inventories)} actual {[rp['name'] for rp in rps]}"
        )

        for rp_name, inv in inventories.items():
            real_rp_name = f'{hostname}_{rp_name}'
            rp = self._get_rp_by_name(real_rp_name, rps)
            rp_inv = self._get_provider_inventory(rp['uuid'])

            self.assertEqual(
                len(inv),
                len(rp_inv),
                f"Number of inventories on {real_rp_name} are not as "
                f"expected. Expected {inv}, actual {rp_inv}"
            )
            for rc, total in inv.items():
                self.assertEqual(
                    total,
                    rp_inv[rc]["total"])
                self.assertEqual(
                    total,
                    rp_inv[rc]["max_unit"])

            rp_traits = self._get_provider_traits(rp['uuid'])
            self.assertEqual(
                # COMPUTE_MANAGED_PCI_DEVICE is automatically reported on
                # PCI device RPs by nova
                set(traits[rp_name]) | {"COMPUTE_MANAGED_PCI_DEVICE"},
                set(rp_traits),
                f"Traits on RP {real_rp_name} does not match with expectation"
            )

    def assert_placement_pci_usages(self, hostname, usages):
        compute_rp_uuid = self.compute_rp_uuids[hostname]
        rps = self._get_all_rps_in_a_tree(compute_rp_uuid)

        for rp_name, usage in usages.items():
            real_rp_name = f'{hostname}_{rp_name}'
            rp = self._get_rp_by_name(real_rp_name, rps)
            rp_usage = self._get_provider_usages(rp['uuid'])
            self.assertEqual(
                usage,
                rp_usage,
                f"Usage on RP {real_rp_name} does not match with expectation"
            )

    def assert_placement_pci_allocations(self, allocations):
        for consumer, expected_allocations in allocations.items():
            actual_allocations = self._get_allocations_by_server_uuid(consumer)
            self.assertEqual(
                len(expected_allocations),
                len(actual_allocations),
                f"The consumer {consumer} allocates from different number of "
                f"RPs than expected. Expected: {expected_allocations}, "
                f"Actual: {actual_allocations}"
            )
            for rp_name, expected_rp_allocs in expected_allocations.items():
                rp_uuid = self._get_provider_uuid_by_name(rp_name)
                self.assertIn(
                    rp_uuid,
                    actual_allocations,
                    f"The consumer {consumer} expected to allocate from "
                    f"{rp_name}. Expected: {expected_allocations}, "
                    f"Actual: {actual_allocations}"
                )
                actual_rp_allocs = actual_allocations[rp_uuid]['resources']
                self.assertEqual(
                    expected_rp_allocs,
                    actual_rp_allocs,
                    f"The consumer {consumer} expected to have allocation "
                    f"{expected_rp_allocs} on {rp_name} but it has "
                    f"{actual_rp_allocs} instead."
                )

    def assert_placement_pci_allocations_on_host(self, hostname, allocations):
        compute_rp_uuid = self.compute_rp_uuids[hostname]
        rps = self._get_all_rps_in_a_tree(compute_rp_uuid)

        for consumer, expected_allocations in allocations.items():
            actual_allocations = self._get_allocations_by_server_uuid(consumer)
            self.assertEqual(
                len(expected_allocations),
                # actual_allocations also contains allocations against the
                # root provider for VCPU, MEMORY_MB, and DISK_GB so subtract
                # one
                len(actual_allocations) - 1,
                f"The consumer {consumer} allocates from different number of "
                f"RPs than expected. Expected: {expected_allocations}, "
                f"Actual: {actual_allocations}"
            )
            for rp_name, expected_rp_allocs in expected_allocations.items():
                real_rp_name = f'{hostname}_{rp_name}'
                rp = self._get_rp_by_name(real_rp_name, rps)
                self.assertIn(
                    rp['uuid'],
                    actual_allocations,
                    f"The consumer {consumer} expected to allocate from "
                    f"{rp['uuid']}. Expected: {expected_allocations}, "
                    f"Actual: {actual_allocations}"
                )
                actual_rp_allocs = actual_allocations[rp['uuid']]['resources']
                self.assertEqual(
                    expected_rp_allocs,
                    actual_rp_allocs,
                    f"The consumer {consumer} expected to have allocation "
                    f"{expected_rp_allocs} on {rp_name} but it has "
                    f"{actual_rp_allocs} instead."
                )

    def assert_placement_pci_view(
        self, hostname, inventories, traits, usages=None, allocations=None
    ):
        if not usages:
            usages = {}

        if not allocations:
            allocations = {}

        self.assert_placement_pci_inventory(hostname, inventories, traits)
        self.assert_placement_pci_usages(hostname, usages)
        self.assert_placement_pci_allocations_on_host(hostname, allocations)

    @staticmethod
    def _to_list_of_json_str(list):
        return [jsonutils.dumps(x) for x in list]

    @staticmethod
    def _move_allocation(allocations, from_uuid, to_uuid):
        allocations[to_uuid] = allocations[from_uuid]
        del allocations[from_uuid]

    def _move_server_allocation(self, allocations, server_uuid, revert=False):
        migration_uuid = self.get_migration_uuid_for_instance(server_uuid)
        if revert:
            self._move_allocation(allocations, migration_uuid, server_uuid)
        else:
            self._move_allocation(allocations, server_uuid, migration_uuid)


class _PCIServersWithMigrationTestBase(_PCIServersTestBase):

    def setUp(self):
        super().setUp()

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


class SRIOVServersTest(_PCIServersWithMigrationTestBase):

    # TODO(stephenfin): We're using this because we want to be able to force
    # the host during scheduling. We should instead look at overriding policy
    ADMIN_API = True
    microversion = 'latest'

    VFS_ALIAS_NAME = 'vfs'
    PFS_ALIAS_NAME = 'pfs'

    PCI_DEVICE_SPEC = [jsonutils.dumps(x) for x in (
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
        # PCI VF device on the source, 2 PCI VF devices on the dest, and
        # relying on the fact that our fake HostPCIDevicesInfo creates
        # predictable PCI addresses. The PCI VF device on source and the first
        # PCI VF device on dest will have identical PCI addresses. By sticking
        # a "placeholder" instance on that first PCI VF device on the dest, the
        # incoming instance from source will be forced to consume the second
        # dest PCI VF device, with a different PCI address.
        # We want to test server operations with SRIOV VFs and SRIOV PFs so
        # the config of the compute hosts also have one extra PCI PF devices
        # without any VF children. But the two compute has different PCI PF
        # addresses and MAC so that the test can observe the slot update as
        # well as the MAC updated during migration and after revert.
        source_pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=1)
        # add an extra PF without VF to be used by direct-physical ports
        source_pci_info.add_device(
            dev_type='PF',
            bus=0x82,  # the HostPCIDevicesInfo use the 0x81 by default
            slot=0x0,
            function=0,
            iommu_group=42,
            numa_node=0,
            vf_ratio=0,
            mac_address='b4:96:91:34:f4:aa',
        )
        self.start_compute(
            hostname='source',
            pci_info=source_pci_info)

        dest_pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=2)
        # add an extra PF without VF to be used by direct-physical ports
        dest_pci_info.add_device(
            dev_type='PF',
            bus=0x82,  # the HostPCIDevicesInfo use the 0x81 by default
            slot=0x6,  # make it different from the source host
            function=0,
            iommu_group=42,
            numa_node=0,
            vf_ratio=0,
            mac_address='b4:96:91:34:f4:bb',
        )
        self.start_compute(
            hostname='dest',
            pci_info=dest_pci_info)

        source_port = self.neutron.create_port(
            {'port': self.neutron.network_4_port_1})
        source_pf_port = self.neutron.create_port(
            {'port': self.neutron.network_4_port_pf})
        dest_port1 = self.neutron.create_port(
            {'port': self.neutron.network_4_port_2})
        dest_port2 = self.neutron.create_port(
            {'port': self.neutron.network_4_port_3})

        source_server = self._create_server(
            networks=[
                {'port': source_port['port']['id']},
                {'port': source_pf_port['port']['id']}
            ],
            host='source',
        )
        dest_server1 = self._create_server(
            networks=[{'port': dest_port1['port']['id']}], host='dest')
        dest_server2 = self._create_server(
            networks=[{'port': dest_port2['port']['id']}], host='dest')

        # Refresh the ports.
        source_port = self.neutron.show_port(source_port['port']['id'])
        source_pf_port = self.neutron.show_port(source_pf_port['port']['id'])
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

        # Before moving, explicitly assert that the servers on source and dest
        # have the same pci_slot in their port's binding profile
        self.assertEqual(source_port['port']['binding:profile']['pci_slot'],
                         same_slot_port['port']['binding:profile']['pci_slot'])

        # Assert that the direct-physical port got the pci_slot information
        # according to the source host PF PCI device.
        self.assertEqual(
            '0000:82:00.0',  # which is in sync with the source host pci_info
            source_pf_port['port']['binding:profile']['pci_slot']
        )
        # Assert that the direct-physical port is updated with the MAC address
        # of the PF device from the source host
        self.assertEqual(
            'b4:96:91:34:f4:aa',
            source_pf_port['port']['binding:profile']['device_mac_address']
        )

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
        # on the dest after the move.
        source_port = self.neutron.show_port(source_port['port']['id'])
        same_slot_port = self.neutron.show_port(same_slot_port['port']['id'])
        source_pf_port = self.neutron.show_port(source_pf_port['port']['id'])

        self.assertNotEqual(
            source_port['port']['binding:profile']['pci_slot'],
            same_slot_port['port']['binding:profile']['pci_slot'])

        # Assert that the direct-physical port got the pci_slot information
        # according to the dest host PF PCI device.
        self.assertEqual(
            '0000:82:06.0',  # which is in sync with the dest host pci_info
            source_pf_port['port']['binding:profile']['pci_slot']
        )
        # Assert that the direct-physical port is updated with the MAC address
        # of the PF device from the dest host
        self.assertEqual(
            'b4:96:91:34:f4:bb',
            source_pf_port['port']['binding:profile']['device_mac_address']
        )

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

    def test_cold_migrate_and_rever_server_with_neutron(self):
        # The purpose here is to force an observable PCI slot update when
        # moving from source to dest and the from dest to source after the
        # revert. This is accomplished by having a single
        # PCI VF device on the source, 2 PCI VF devices on the dest, and
        # relying on the fact that our fake HostPCIDevicesInfo creates
        # predictable PCI addresses. The PCI VF device on source and the first
        # PCI VF device on dest will have identical PCI addresses. By sticking
        # a "placeholder" instance on that first PCI VF device on the dest, the
        # incoming instance from source will be forced to consume the second
        # dest PCI VF device, with a different PCI address.
        # We want to test server operations with SRIOV VFs and SRIOV PFs so
        # the config of the compute hosts also have one extra PCI PF devices
        # without any VF children. But the two compute has different PCI PF
        # addresses and MAC so that the test can observe the slot update as
        # well as the MAC updated during migration and after revert.
        source_pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=1)
        # add an extra PF without VF to be used by direct-physical ports
        source_pci_info.add_device(
            dev_type='PF',
            bus=0x82,  # the HostPCIDevicesInfo use the 0x81 by default
            slot=0x0,
            function=0,
            iommu_group=42,
            numa_node=0,
            vf_ratio=0,
            mac_address='b4:96:91:34:f4:aa',
        )
        self.start_compute(
            hostname='source',
            pci_info=source_pci_info)
        dest_pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=2)
        # add an extra PF without VF to be used by direct-physical ports
        dest_pci_info.add_device(
            dev_type='PF',
            bus=0x82,  # the HostPCIDevicesInfo use the 0x81 by default
            slot=0x6,  # make it different from the source host
            function=0,
            iommu_group=42,
            numa_node=0,
            vf_ratio=0,
            mac_address='b4:96:91:34:f4:bb',
        )
        self.start_compute(
            hostname='dest',
            pci_info=dest_pci_info)
        source_port = self.neutron.create_port(
            {'port': self.neutron.network_4_port_1})
        source_pf_port = self.neutron.create_port(
            {'port': self.neutron.network_4_port_pf})
        dest_port1 = self.neutron.create_port(
            {'port': self.neutron.network_4_port_2})
        dest_port2 = self.neutron.create_port(
            {'port': self.neutron.network_4_port_3})
        source_server = self._create_server(
            networks=[
                {'port': source_port['port']['id']},
                {'port': source_pf_port['port']['id']}
            ],
            host='source',
        )
        dest_server1 = self._create_server(
            networks=[{'port': dest_port1['port']['id']}], host='dest')
        dest_server2 = self._create_server(
            networks=[{'port': dest_port2['port']['id']}], host='dest')
        # Refresh the ports.
        source_port = self.neutron.show_port(source_port['port']['id'])
        source_pf_port = self.neutron.show_port(source_pf_port['port']['id'])
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
        # Before moving, explicitly assert that the servers on source and dest
        # have the same pci_slot in their port's binding profile
        self.assertEqual(source_port['port']['binding:profile']['pci_slot'],
                         same_slot_port['port']['binding:profile']['pci_slot'])
        # Assert that the direct-physical port got the pci_slot information
        # according to the source host PF PCI device.
        self.assertEqual(
            '0000:82:00.0',  # which is in sync with the source host pci_info
            source_pf_port['port']['binding:profile']['pci_slot']
        )
        # Assert that the direct-physical port is updated with the MAC address
        # of the PF device from the source host
        self.assertEqual(
            'b4:96:91:34:f4:aa',
            source_pf_port['port']['binding:profile']['device_mac_address']
        )
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

        # TODO(stephenfin): The mock of 'migrate_disk_and_power_off' should
        # probably be less...dumb
        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                        '.migrate_disk_and_power_off', return_value='{}'):
            self._migrate_server(source_server)

        # Refresh the ports again, keeping in mind the ports are now bound
        # on the dest after migrating.
        source_port = self.neutron.show_port(source_port['port']['id'])
        same_slot_port = self.neutron.show_port(same_slot_port['port']['id'])
        source_pf_port = self.neutron.show_port(source_pf_port['port']['id'])
        self.assertNotEqual(
            source_port['port']['binding:profile']['pci_slot'],
            same_slot_port['port']['binding:profile']['pci_slot'])
        # Assert that the direct-physical port got the pci_slot information
        # according to the dest host PF PCI device.
        self.assertEqual(
            '0000:82:06.0',  # which is in sync with the dest host pci_info
            source_pf_port['port']['binding:profile']['pci_slot']
        )
        # Assert that the direct-physical port is updated with the MAC address
        # of the PF device from the dest host
        self.assertEqual(
            'b4:96:91:34:f4:bb',
            source_pf_port['port']['binding:profile']['device_mac_address']
        )
        conn = self.computes['dest'].driver._host.get_connection()
        vms = [vm._def for vm in conn._vms.values()]
        self.assertEqual(2, len(vms))
        for vm in vms:
            self.assertEqual(1, len(vm['devices']['nics']))
        self.assertNotEqual(vms[0]['devices']['nics'][0]['source'],
                            vms[1]['devices']['nics'][0]['source'])

        self._revert_resize(source_server)

        # Refresh the ports again, keeping in mind the ports are now bound
        # on the source as the migration is reverted
        source_pf_port = self.neutron.show_port(source_pf_port['port']['id'])

        # Assert that the direct-physical port got the pci_slot information
        # according to the source host PF PCI device.
        self.assertEqual(
            '0000:82:00.0',  # which is in sync with the source host pci_info
            source_pf_port['port']['binding:profile']['pci_slot']
        )
        # Assert that the direct-physical port is updated with the MAC address
        # of the PF device from the source host
        self.assertEqual(
            'b4:96:91:34:f4:aa',
            source_pf_port['port']['binding:profile']['device_mac_address']
        )

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
        source_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=1, num_vfs=4, numa_node=0)
        # add an extra PF without VF to be used by direct-physical ports
        source_pci_info.add_device(
            dev_type='PF',
            bus=0x82,  # the HostPCIDevicesInfo use the 0x81 by default
            slot=0x0,
            function=0,
            iommu_group=42,
            numa_node=0,
            vf_ratio=0,
            mac_address='b4:96:91:34:f4:aa',
        )
        self.start_compute(hostname='test_compute0', pci_info=source_pci_info)

        dest_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=1, num_vfs=2, numa_node=1)
        # add an extra PF without VF to be used by direct-physical ports
        dest_pci_info.add_device(
            dev_type='PF',
            bus=0x82,  # the HostPCIDevicesInfo use the 0x81 by default
            slot=0x6,  # make it different from the source host
            function=0,
            iommu_group=42,
            # numa node needs to be aligned with the other pci devices in this
            # host as the instance needs to fit into a single host numa node
            numa_node=1,
            vf_ratio=0,
            mac_address='b4:96:91:34:f4:bb',
        )

        self.start_compute(hostname='test_compute1', pci_info=dest_pci_info)

        # create the ports
        port = self.neutron.create_port(
            {'port': self.neutron.network_4_port_1})['port']
        pf_port = self.neutron.create_port(
            {'port': self.neutron.network_4_port_pf})['port']

        # create a server using the VF via neutron
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id,
            networks=[
                {'port': port['id']},
                {'port': pf_port['id']},
            ],
            host='test_compute0',
        )

        # our source host should have marked two PCI devices as used, the VF
        # and the parent PF, while the future destination is currently unused
        self.assertEqual('test_compute0', server['OS-EXT-SRV-ATTR:host'])
        self.assertPCIDeviceCounts('test_compute0', total=6, free=3)
        self.assertPCIDeviceCounts('test_compute1', total=4, free=4)

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
                'pci_slot': '0000:81:00.4',
                'physical_network': 'physnet4',
            },
            port['binding:profile'],
        )

        # ensure the binding details sent to "neutron" are correct
        pf_port = self.neutron.show_port(pf_port['id'],)['port']
        self.assertIn('binding:profile', pf_port)
        self.assertEqual(
            {
                'pci_vendor_info': '8086:1528',
                'pci_slot': '0000:82:00.0',
                'physical_network': 'physnet4',
                'device_mac_address': 'b4:96:91:34:f4:aa',
            },
            pf_port['binding:profile'],
        )

        # now live migrate that server
        self._live_migrate(server, 'completed')

        # we should now have transitioned our usage to the destination, freeing
        # up the source in the process
        self.assertPCIDeviceCounts('test_compute0', total=6, free=6)
        self.assertPCIDeviceCounts('test_compute1', total=4, free=1)

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
        # ensure the binding details sent to "neutron" are correct
        pf_port = self.neutron.show_port(pf_port['id'],)['port']
        self.assertIn('binding:profile', pf_port)
        self.assertEqual(
            {
                'pci_vendor_info': '8086:1528',
                'pci_slot': '0000:82:06.0',
                'physical_network': 'physnet4',
                'device_mac_address': 'b4:96:91:34:f4:bb',
            },
            pf_port['binding:profile'],
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

        self.start_compute('test_compute0', pci_info=pci_info_no_sriov)
        self.compute = self.computes['test_compute0']

        ctxt = context.get_admin_context()
        pci_devices = objects.PciDeviceList.get_by_compute_node(
            ctxt,
            objects.ComputeNode.get_by_nodename(
                ctxt, 'test_compute0',
            ).id,
        )
        self.assertEqual(1, len(pci_devices))
        self.assertEqual('type-PCI', pci_devices[0].dev_type)

        # Restart the compute service with sriov PFs
        self.restart_compute_service(
            self.compute.host, pci_info=pci_info, keep_hypervisor_state=False)

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

    def test_change_bound_port_vnic_type_kills_compute_at_restart(self):
        """Create a server with a direct port and change the vnic_type of the
        bound port to macvtap. Then restart the compute service.

        As the vnic_type is changed on the port but the vif_type is hwveb
        instead of macvtap the vif plug logic will try to look up the netdev
        of the parent VF. Howvere that VF consumed by the instance so the
        netdev does not exists. This causes that the compute service will fail
        with an exception during startup
        """
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=2)
        self.start_compute(pci_info=pci_info)

        # create a direct port
        port = self.neutron.network_4_port_1
        self.neutron.create_port({'port': port})

        # create a server using the VF via neutron
        server = self._create_server(networks=[{'port': port['id']}])

        # update the vnic_type of the port in neutron
        port = copy.deepcopy(port)
        port['binding:vnic_type'] = 'macvtap'
        self.neutron.update_port(port['id'], {"port": port})

        compute = self.computes['compute1']

        # Force an update on the instance info cache to ensure nova gets the
        # information about the updated port
        with context.target_cell(
            context.get_admin_context(),
            self.host_mappings['compute1'].cell_mapping
        ) as cctxt:
            compute.manager._heal_instance_info_cache(cctxt)
            self.assertIn(
                'The vnic_type of the bound port %s has been changed in '
                'neutron from "direct" to "macvtap". Changing vnic_type of a '
                'bound port is not supported by Nova. To avoid breaking the '
                'connectivity of the instance please change the port '
                'vnic_type back to "direct".' % port['id'],
                self.stdlog.logger.output,
            )

        def fake_get_ifname_by_pci_address(pci_addr: str, pf_interface=False):
            # we want to fail the netdev lookup only if the pci_address is
            # already consumed by our instance. So we look into the instance
            # definition to see if the device is attached to the instance as VF
            conn = compute.manager.driver._host.get_connection()
            dom = conn.lookupByUUIDString(server['id'])
            dev = dom._def['devices']['nics'][0]
            lookup_addr = pci_addr.replace(':', '_').replace('.', '_')
            if (
                dev['type'] == 'hostdev' and
                dev['source'] == 'pci_' + lookup_addr
            ):
                # nova tried to look up the netdev of an already consumed VF.
                # So we have to fail
                raise exception.PciDeviceNotFoundById(id=pci_addr)

        # We need to simulate the actual failure manually as in our functional
        # environment all the PCI lookup is mocked. In reality nova tries to
        # look up the netdev of the pci device on the host used by the port as
        # the parent of the macvtap. However, as the originally direct port is
        # bound to the instance, the VF pci device is already consumed by the
        # instance and therefore there is no netdev for the VF.
        self.libvirt.mock_get_ifname_by_pci_address.side_effect = (
            fake_get_ifname_by_pci_address
        )
        # Nova cannot prevent the vnic_type change on a bound port. Neutron
        # should prevent that instead. But the nova-compute should still
        # be able to start up and only log an ERROR for this instance in
        # inconsistent state.
        self.restart_compute_service('compute1')
        self.assertIn(
            'Virtual interface plugging failed for instance. Probably the '
            'vnic_type of the bound port has been changed. Nova does not '
            'support such change.',
            self.stdlog.logger.output,
        )


class SRIOVAttachDetachTest(_PCIServersTestBase):
    # no need for aliases as these test will request SRIOV via neutron
    PCI_ALIAS = []

    PCI_DEVICE_SPEC = [jsonutils.dumps(x) for x in (
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
        self.start_compute(
            'test_compute0', host_info=host_info, pci_info=pci_info)
        self.compute = self.computes['test_compute0']

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


class VDPAServersTest(_PCIServersWithMigrationTestBase):

    # this is needed for os_compute_api:os-migrate-server:migrate policy
    ADMIN_API = True
    microversion = 'latest'

    # Whitelist both the PF and VF; in reality, you probably wouldn't do this
    # but we want to make sure that the PF is correctly taken off the table
    # once any VF is used
    PCI_DEVICE_SPEC = [jsonutils.dumps(x) for x in (
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

    def start_vdpa_compute(self, hostname='compute-0'):
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

        return super().start_compute(hostname=hostname,
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
                  <source dev="/dev/vhost-vdpa-3"/>
                </interface>"""
            actual = etree.tostring(elem, encoding='unicode')

            self.assertXmlEqual(expected, actual)

            return orig_create(xml, host)

        self.stub_out(
            'nova.virt.libvirt.guest.Guest.create',
            fake_create,
        )

        hostname = self.start_vdpa_compute()
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

    def _create_port_and_server(self):
        # create the port and a server, with the port attached to the server
        vdpa_port = self.create_vdpa_port()
        server = self._create_server(networks=[{'port': vdpa_port['id']}])
        return vdpa_port, server

    def _test_common(self, op, *args, **kwargs):
        self.start_vdpa_compute()

        vdpa_port, server = self._create_port_and_server()

        # attempt the unsupported action and ensure it fails
        ex = self.assertRaises(
            client.OpenStackApiException,
            op, server, *args, **kwargs)
        self.assertIn(
            'not supported for instance with vDPA ports',
            ex.response.text)

    def test_attach_interface_service_version_61(self):
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=61
        ):
            self._test_common(self._attach_interface, uuids.vdpa_port)

    def test_attach_interface(self):
        hostname = self.start_vdpa_compute()
        # create the port and a server, but don't attach the port to the server
        # yet
        server = self._create_server(networks='none')
        vdpa_port = self.create_vdpa_port()
        # attempt to attach the port to the server
        self._attach_interface(server, vdpa_port['id'])
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
        self.assertEqual(hostname, port['binding:host_id'])
        self.assertEqual(server['id'], port['device_id'])

    def test_detach_interface_service_version_61(self):
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=61
        ):
            self._test_common(self._detach_interface, uuids.vdpa_port)

    def test_detach_interface(self):
        self.start_vdpa_compute()
        vdpa_port, server = self._create_port_and_server()
        # ensure the binding details sent to "neutron" were correct
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(server['id'], port['device_id'])
        self._detach_interface(server, vdpa_port['id'])
        # ensure the port is no longer owned by the vm
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual('', port['device_id'])
        self.assertEqual({}, port['binding:profile'])

    def test_shelve_offload(self):
        hostname = self.start_vdpa_compute()
        vdpa_port, server = self._create_port_and_server()
        # assert the port is bound to the vm and the compute host
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(server['id'], port['device_id'])
        self.assertEqual(hostname, port['binding:host_id'])
        num_pci = self.NUM_PFS + self.NUM_VFS
        # -2 we claim the vdpa device which make the parent PF unavailable
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci - 2)
        server = self._shelve_server(server)
        # now that the vm is shelve offloaded it should not be bound
        # to any host but should still be owned by the vm
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(server['id'], port['device_id'])
        # FIXME(sean-k-mooney): we should be unbinding the port from
        # the host when we shelve offload but we don't today.
        # This is unrelated to vdpa port and is a general issue.
        self.assertEqual(hostname, port['binding:host_id'])
        self.assertIn('binding:profile', port)
        self.assertIsNone(server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        self.assertIsNone(server['OS-EXT-SRV-ATTR:host'])
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci)

    def test_unshelve_to_same_host(self):
        hostname = self.start_vdpa_compute()
        num_pci = self.NUM_PFS + self.NUM_VFS
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci)

        vdpa_port, server = self._create_port_and_server()
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci - 2)
        self.assertEqual(
            hostname, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(hostname, port['binding:host_id'])

        server = self._shelve_server(server)
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci)
        self.assertIsNone(server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        port = self.neutron.show_port(vdpa_port['id'])['port']
        # FIXME(sean-k-mooney): shelve  offload should unbind the port
        # self.assertEqual('', port['binding:host_id'])
        self.assertEqual(hostname, port['binding:host_id'])

        server = self._unshelve_server(server)
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci - 2)
        self.assertEqual(
            hostname, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(hostname, port['binding:host_id'])

    def test_unshelve_to_different_host(self):
        source = self.start_vdpa_compute(hostname='source')
        dest = self.start_vdpa_compute(hostname='dest')

        num_pci = self.NUM_PFS + self.NUM_VFS
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)

        # ensure we boot the vm on the "source" compute
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'disabled'})
        vdpa_port, server = self._create_port_and_server()
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        self.assertEqual(
            source, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(source, port['binding:host_id'])

        server = self._shelve_server(server)
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertIsNone(server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        port = self.neutron.show_port(vdpa_port['id'])['port']
        # FIXME(sean-k-mooney): shelve should unbind the port
        # self.assertEqual('', port['binding:host_id'])
        self.assertEqual(source, port['binding:host_id'])

        # force the unshelve to the other host
        self.api.put_service(
            self.computes['source'].service_ref.uuid, {'status': 'disabled'})
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'enabled'})
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)
        server = self._unshelve_server(server)
        # the dest devices should be claimed
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci - 2)
        # and the source host devices should still be free
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertEqual(
            dest, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(dest, port['binding:host_id'])

    def test_evacute(self):
        source = self.start_vdpa_compute(hostname='source')
        dest = self.start_vdpa_compute(hostname='dest')

        num_pci = self.NUM_PFS + self.NUM_VFS
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)

        # ensure we boot the vm on the "source" compute
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'disabled'})
        vdpa_port, server = self._create_port_and_server()
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        self.assertEqual(
            source, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(source, port['binding:host_id'])

        # stop the source compute and enable the dest
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'enabled'})
        self.computes['source'].stop()
        # Down the source compute to enable the evacuation
        self.api.put_service(
            self.computes['source'].service_ref.uuid, {'forced_down': True})

        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)
        server = self._evacuate_server(server)
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci - 2)
        self.assertEqual(
            dest, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
        port = self.neutron.show_port(vdpa_port['id'])['port']
        self.assertEqual(dest, port['binding:host_id'])

        # as the source compute is offline the pci claims will not be cleaned
        # up on the source compute.
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        # but if you fix/restart the source node the allocations for evacuated
        # instances should be released.
        self.restart_compute_service(source)
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)

    def test_resize_same_host(self):
        self.flags(allow_resize_to_same_host=True)
        num_pci = self.NUM_PFS + self.NUM_VFS
        source = self.start_vdpa_compute()
        vdpa_port, server = self._create_port_and_server()
        # before we resize the vm should be using 1 VF but that will mark
        # the PF as unavailable so we assert 2 devices are in use.
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        flavor_id = self._create_flavor(name='new-flavor')
        self.assertNotEqual(server['flavor']['original_name'], 'new-flavor')
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            server = self._resize_server(server, flavor_id)
            self.assertEqual(
                server['flavor']['original_name'], 'new-flavor')
            # in resize verify the VF claims should be doubled even
            # for same host resize so assert that 3 are in devices in use
            # 1 PF and 2 VFs .
            self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 3)
            server = self._confirm_resize(server)
            # but once we confrim it should be reduced back to 1 PF and 1 VF
            self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
            # assert the hostname has not have changed as part
            # of the resize.
            self.assertEqual(
                source, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])

    def test_resize_different_host(self):
        self.flags(allow_resize_to_same_host=False)
        source = self.start_vdpa_compute(hostname='source')
        dest = self.start_vdpa_compute(hostname='dest')

        num_pci = self.NUM_PFS + self.NUM_VFS
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)

        # ensure we boot the vm on the "source" compute
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'disabled'})
        vdpa_port, server = self._create_port_and_server()
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        flavor_id = self._create_flavor(name='new-flavor')
        self.assertNotEqual(server['flavor']['original_name'], 'new-flavor')
        # disable the source compute and enable the dest
        self.api.put_service(
            self.computes['source'].service_ref.uuid, {'status': 'disabled'})
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'enabled'})
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            server = self._resize_server(server, flavor_id)
            self.assertEqual(
                server['flavor']['original_name'], 'new-flavor')
            self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
            self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci - 2)
            server = self._confirm_resize(server)
            self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
            self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci - 2)
            self.assertEqual(
                dest, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])

    def test_resize_revert(self):
        self.flags(allow_resize_to_same_host=False)
        source = self.start_vdpa_compute(hostname='source')
        dest = self.start_vdpa_compute(hostname='dest')

        num_pci = self.NUM_PFS + self.NUM_VFS
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)

        # ensure we boot the vm on the "source" compute
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'disabled'})
        vdpa_port, server = self._create_port_and_server()
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        flavor_id = self._create_flavor(name='new-flavor')
        self.assertNotEqual(server['flavor']['original_name'], 'new-flavor')
        # disable the source compute and enable the dest
        self.api.put_service(
            self.computes['source'].service_ref.uuid, {'status': 'disabled'})
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'enabled'})
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            server = self._resize_server(server, flavor_id)
            self.assertEqual(
                server['flavor']['original_name'], 'new-flavor')
            # in resize verify both the dest and source pci claims should be
            # present.
            self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
            self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci - 2)
            server = self._revert_resize(server)
            # but once we revert the dest claims should be freed.
            self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)
            self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
            self.assertEqual(
                source, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])

    def test_cold_migrate(self):
        source = self.start_vdpa_compute(hostname='source')
        dest = self.start_vdpa_compute(hostname='dest')

        num_pci = self.NUM_PFS + self.NUM_VFS
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)

        # ensure we boot the vm on the "source" compute
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'disabled'})
        vdpa_port, server = self._create_port_and_server()
        self.assertEqual(
            source, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])

        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        # enable the dest we do not need to disable the source since cold
        # migrate wont happen to the same host in the libvirt driver
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'enabled'})
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off', return_value='{}',
        ):
            server = self._migrate_server(server)
            self.assertEqual(
                dest, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
            self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
            self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci - 2)
            server = self._confirm_resize(server)
            self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
            self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci - 2)
            self.assertEqual(
                dest, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])

    def test_suspend_and_resume_service_version_62(self):
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=62
        ):
            self._test_common(self._suspend_server)

    def test_suspend_and_resume(self):
        source = self.start_vdpa_compute(hostname='source')
        vdpa_port, server = self._create_port_and_server()
        num_pci = self.NUM_PFS + self.NUM_VFS
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        server = self._suspend_server(server)
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        self.assertEqual('SUSPENDED', server['status'])
        server = self._resume_server(server)
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        self.assertEqual('ACTIVE', server['status'])

    def test_live_migrate_service_version_62(self):
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=62
        ):
            self._test_common(self._live_migrate)

    def test_live_migrate(self):
        source = self.start_vdpa_compute(hostname='source')
        dest = self.start_vdpa_compute(hostname='dest')

        num_pci = self.NUM_PFS + self.NUM_VFS
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci)

        # ensure we boot the vm on the "source" compute
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'disabled'})
        vdpa_port, server = self._create_port_and_server()
        self.assertEqual(
            source, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])

        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci - 2)
        # enable the dest we do not need to disable the source since cold
        # migrate wont happen to the same host in the libvirt driver
        self.api.put_service(
            self.computes['dest'].service_ref.uuid, {'status': 'enabled'})

        with mock.patch(
                'nova.virt.libvirt.LibvirtDriver.'
                '_detach_direct_passthrough_vifs'
        ):
            server = self._live_migrate(server)
        self.assertPCIDeviceCounts(source, total=num_pci, free=num_pci)
        self.assertPCIDeviceCounts(dest, total=num_pci, free=num_pci - 2)
        self.assertEqual(
            dest, server['OS-EXT-SRV-ATTR:hypervisor_hostname'])


class PCIServersTest(_PCIServersTestBase):

    ADMIN_API = True
    microversion = 'latest'

    ALIAS_NAME = 'a1'
    PCI_DEVICE_SPEC = [jsonutils.dumps(
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

    def setUp(self):
        super().setUp()
        self.flags(group="pci", report_in_placement=True)
        self.flags(group='filter_scheduler', pci_in_placement=True)

    def test_create_server_with_pci_dev_and_numa(self):
        """Verifies that an instance can be booted with cpu pinning and with an
           assigned pci device with legacy policy and numa info for the pci
           device.
        """

        self.flags(cpu_dedicated_set='0-7', group='compute')

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=1)
        self.start_compute(pci_info=pci_info)

        self.assert_placement_pci_view(
            "compute1",
            inventories={"0000:81:00.0": {self.PCI_RC: 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {self.PCI_RC: 0}},
        )

        # create a flavor
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        server = self._create_server(flavor_id=flavor_id, networks='none')

        self.assert_placement_pci_view(
            "compute1",
            inventories={"0000:81:00.0": {self.PCI_RC: 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {self.PCI_RC: 1}},
            allocations={server['id']: {"0000:81:00.0": {self.PCI_RC: 1}}},
        )
        self.assert_no_pci_healing("compute1")

    def test_create_server_with_pci_dev_and_numa_fails(self):
        """This test ensures that it is not possible to allocated CPU and
           memory resources from one NUMA node and a PCI device from another
           if we use the legacy policy and the pci device reports numa info.
        """
        self.flags(cpu_dedicated_set='0-7', group='compute')

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=0)
        self.start_compute(pci_info=pci_info)

        compute1_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_placement_pci_view)

        # boot one instance with no PCI device to "fill up" NUMA node 0
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id, networks='none')

        # now boot one with a PCI device, which should fail to boot
        extra_spec['pci_passthrough:alias'] = '%s:1' % self.ALIAS_NAME
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        self._create_server(
            flavor_id=flavor_id, networks='none', expected_state='ERROR')

        self.assert_placement_pci_view(
            "compute1", **compute1_placement_pci_view)
        self.assert_no_pci_healing("compute1")

    def test_live_migrate_server_with_pci(self):
        """Live migrate an instance with a PCI passthrough device.

        This should fail because it's not possible to live migrate an instance
        with a PCI passthrough device, even if it's a SR-IOV VF.
        """

        # start two compute services
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))

        test_compute0_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        self.start_compute(
            hostname='test_compute1',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))

        test_compute1_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
        }
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # create a server
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, networks='none', host="test_compute0")

        test_compute0_placement_pci_view[
            "usages"]["0000:81:00.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view[
            "allocations"][server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

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
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)
        self.assert_no_pci_healing("test_compute0")
        self.assert_no_pci_healing("test_compute1")

    def test_resize_pci_to_vanilla(self):
        # Start two computes, one with PCI and one without.
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))
        test_compute0_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        self.start_compute(hostname='test_compute1')
        test_compute1_placement_pci_view = {
            "inventories": {},
            "traits": {},
            "usages": {},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # Boot a server with a single PCI device.
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=pci_flavor_id, networks='none')

        test_compute0_placement_pci_view[
            "usages"]["0000:81:00.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view[
            "allocations"][server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # Resize it to a flavor without PCI devices. We expect this to work, as
        # test_compute1 is available.
        flavor_id = self._create_flavor()
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            return_value='{}',
        ):
            self._resize_server(server, flavor_id)
        self._confirm_resize(server)
        self.assertPCIDeviceCounts('test_compute0', total=1, free=1)
        self.assertPCIDeviceCounts('test_compute1', total=0, free=0)
        test_compute0_placement_pci_view[
            "usages"]["0000:81:00.0"][self.PCI_RC] = 0
        del test_compute0_placement_pci_view["allocations"][server['id']]
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)
        self.assert_no_pci_healing("test_compute0")
        self.assert_no_pci_healing("test_compute1")

    def test_resize_vanilla_to_pci(self):
        """Resize an instance from a non PCI flavor to a PCI flavor"""
        # Start two computes, one with PCI and one without.
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))
        test_compute0_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        self.start_compute(hostname='test_compute1')
        test_compute1_placement_pci_view = {
            "inventories": {},
            "traits": {},
            "usages": {},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # Boot a server without PCI device and make sure it lands on the
        # compute that has no device, so we can resize it later to the other
        # host having PCI device.
        extra_spec = {}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, networks='none', host="test_compute1")

        self.assertPCIDeviceCounts('test_compute0', total=1, free=1)
        self.assertPCIDeviceCounts('test_compute1', total=0, free=0)
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # Resize it to a flavor with a PCI devices. We expect this to work, as
        # test_compute0 is available and having PCI devices.
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            return_value='{}',
        ):
            self._resize_server(server, pci_flavor_id)
        self._confirm_resize(server)
        self.assertPCIDeviceCounts('test_compute0', total=1, free=0)
        self.assertPCIDeviceCounts('test_compute1', total=0, free=0)
        test_compute0_placement_pci_view[
            "usages"]["0000:81:00.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view[
            "allocations"][server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)
        self.assert_no_pci_healing("test_compute0")
        self.assert_no_pci_healing("test_compute1")

    def test_resize_from_one_dev_to_two(self):
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))
        self.assertPCIDeviceCounts('test_compute0', total=1, free=1)
        test_compute0_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        self.start_compute(
            hostname='test_compute1',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=2),
        )
        self.assertPCIDeviceCounts('test_compute1', total=2, free=2)
        test_compute1_placement_pci_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
                "0000:81:01.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
                "0000:81:01.0": {self.PCI_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # boot a VM on test_compute0 with a single PCI dev
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=pci_flavor_id, networks='none', host="test_compute0")

        self.assertPCIDeviceCounts('test_compute0', total=1, free=0)
        test_compute0_placement_pci_view["usages"][
            "0000:81:00.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view["allocations"][
            server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        # resize the server to a flavor requesting two devices
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:2'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            return_value='{}',
        ):
            self._resize_server(server, pci_flavor_id)

        self.assertPCIDeviceCounts('test_compute0', total=1, free=0)
        # one the source host the PCI allocation is now held by the migration
        self._move_server_allocation(
            test_compute0_placement_pci_view['allocations'], server['id'])
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        # on the dest we have now two device allocated
        self.assertPCIDeviceCounts('test_compute1', total=2, free=0)
        test_compute1_placement_pci_view["usages"] = {
            "0000:81:00.0": {self.PCI_RC: 1},
            "0000:81:01.0": {self.PCI_RC: 1},
        }
        test_compute1_placement_pci_view["allocations"][
            server['id']] = {
            "0000:81:00.0": {self.PCI_RC: 1},
            "0000:81:01.0": {self.PCI_RC: 1},
        }
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # now revert the resize
        self._revert_resize(server)

        self.assertPCIDeviceCounts('test_compute0', total=1, free=0)
        # on the host the allocation should move back to the instance UUID
        self._move_server_allocation(
            test_compute0_placement_pci_view["allocations"],
            server["id"],
            revert=True,
        )
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        # so the dest should be freed
        self.assertPCIDeviceCounts('test_compute1', total=2, free=2)
        test_compute1_placement_pci_view["usages"] = {
            "0000:81:00.0": {self.PCI_RC: 0},
            "0000:81:01.0": {self.PCI_RC: 0},
        }
        del test_compute1_placement_pci_view["allocations"][server['id']]
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # now resize again and confirm it
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            return_value='{}',
        ):
            self._resize_server(server, pci_flavor_id)
        self._confirm_resize(server)

        # the source host now need to be freed up
        self.assertPCIDeviceCounts('test_compute0', total=1, free=1)
        test_compute0_placement_pci_view["usages"] = {
            "0000:81:00.0": {self.PCI_RC: 0},
        }
        test_compute0_placement_pci_view["allocations"] = {}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        # and dest allocated
        self.assertPCIDeviceCounts('test_compute1', total=2, free=0)
        test_compute1_placement_pci_view["usages"] = {
            "0000:81:00.0": {self.PCI_RC: 1},
            "0000:81:01.0": {self.PCI_RC: 1},
        }
        test_compute1_placement_pci_view["allocations"][
            server['id']] = {
            "0000:81:00.0": {self.PCI_RC: 1},
            "0000:81:01.0": {self.PCI_RC: 1},
        }
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        self.assert_no_pci_healing("test_compute0")
        self.assert_no_pci_healing("test_compute1")

    def test_same_host_resize_with_pci(self):
        """Start a single compute with 3 PCI devs and resize and instance
        from one dev to two devs
        """
        self.flags(allow_resize_to_same_host=True)
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=3))
        self.assertPCIDeviceCounts('test_compute0', total=3, free=3)
        test_compute0_placement_pci_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
                "0000:81:02.0": {self.PCI_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
                "0000:81:01.0": [],
                "0000:81:02.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
                "0000:81:01.0": {self.PCI_RC: 0},
                "0000:81:02.0": {self.PCI_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        # Boot a server with a single PCI device.
        # To stabilize the test we reserve 81.01 and 81.02 in placement so
        # we can be sure that the instance will use 81.00, otherwise the
        # allocation will be random between 00, 01, and 02
        self._reserve_placement_resource(
            "test_compute0_0000:81:01.0", self.PCI_RC, 1)
        self._reserve_placement_resource(
            "test_compute0_0000:81:02.0", self.PCI_RC, 1)
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=pci_flavor_id, networks='none')

        self.assertPCIDeviceCounts('test_compute0', total=3, free=2)
        test_compute0_placement_pci_view[
            "usages"]["0000:81:00.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view[
            "allocations"][server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)
        # remove the reservations, so we can resize on the same host and
        # consume 01 and 02
        self._reserve_placement_resource(
            "test_compute0_0000:81:01.0", self.PCI_RC, 0)
        self._reserve_placement_resource(
            "test_compute0_0000:81:02.0", self.PCI_RC, 0)

        # Resize the server to use 2 PCI devices
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:2'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            return_value='{}',
        ):
            self._resize_server(server, pci_flavor_id)

        self.assertPCIDeviceCounts('test_compute0', total=3, free=0)
        # the source host side of the allocation is now held by the migration
        # UUID
        self._move_server_allocation(
            test_compute0_placement_pci_view["allocations"], server['id'])
        # but we have the dest host side of the allocations on the same host
        test_compute0_placement_pci_view[
            "usages"]["0000:81:01.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view[
            "usages"]["0000:81:02.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view["allocations"][server['id']] = {
            "0000:81:01.0": {self.PCI_RC: 1},
            "0000:81:02.0": {self.PCI_RC: 1},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        # revert the resize so the instance should go back to use a single
        # device
        self._revert_resize(server)
        self.assertPCIDeviceCounts('test_compute0', total=3, free=2)
        # the migration allocation is moved back to the instance UUID
        self._move_server_allocation(
            test_compute0_placement_pci_view["allocations"],
            server["id"],
            revert=True,
        )
        # and the "dest" side of the allocation is dropped
        test_compute0_placement_pci_view[
            "usages"]["0000:81:01.0"][self.PCI_RC] = 0
        test_compute0_placement_pci_view[
            "usages"]["0000:81:02.0"][self.PCI_RC] = 0
        test_compute0_placement_pci_view["allocations"][server['id']] = {
            "0000:81:00.0": {self.PCI_RC: 1},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        # resize again but now confirm the same host resize and assert that
        # only the new flavor usage remains
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            return_value='{}',
        ):
            self._resize_server(server, pci_flavor_id)
        self._confirm_resize(server)

        self.assertPCIDeviceCounts('test_compute0', total=3, free=1)
        test_compute0_placement_pci_view["usages"] = {
            "0000:81:01.0": {self.PCI_RC: 1},
            "0000:81:02.0": {self.PCI_RC: 1},
        }
        test_compute0_placement_pci_view["allocations"][
            server['id']] = {self.PCI_RC: 1}
        test_compute0_placement_pci_view["allocations"][server['id']] = {
            "0000:81:01.0": {self.PCI_RC: 1},
            "0000:81:02.0": {self.PCI_RC: 1},
        }
        self.assert_no_pci_healing("test_compute0")

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
        test_compute0_placement_pci_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
                "0000:81:01.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
                "0000:81:01.0": {self.PCI_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        test_compute1_placement_pci_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
                "0000:81:01.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
                "0000:81:01.0": {self.PCI_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # boot an instance with a PCI device on each host
        extra_spec = {
            'pci_passthrough:alias': '%s:1' % self.ALIAS_NAME,
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        # force the allocation on test_compute0 to 81:00 to make it easy
        # to assert the placement allocation
        self._reserve_placement_resource(
            "test_compute0_0000:81:01.0", self.PCI_RC, 1)
        server_a = self._create_server(
            flavor_id=flavor_id, networks='none', host='test_compute0')
        # force the allocation on test_compute1 to 81:00 to make it easy
        # to assert the placement allocation
        self._reserve_placement_resource(
            "test_compute1_0000:81:01.0", self.PCI_RC, 1)
        server_b = self._create_server(
            flavor_id=flavor_id, networks='none', host='test_compute1')

        # the instances should have landed on separate hosts; ensure both hosts
        # have one used PCI device and one free PCI device
        self.assertNotEqual(
            server_a['OS-EXT-SRV-ATTR:host'], server_b['OS-EXT-SRV-ATTR:host'],
        )
        for hostname in ('test_compute0', 'test_compute1'):
            self.assertPCIDeviceCounts(hostname, total=2, free=1)

        test_compute0_placement_pci_view["usages"][
            "0000:81:00.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view["allocations"][
            server_a['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        test_compute1_placement_pci_view[
            "usages"]["0000:81:00.0"][self.PCI_RC] = 1
        test_compute1_placement_pci_view["allocations"][
            server_b['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # remove the resource reservation from test_compute1 to be able to
        # migrate server_a there
        self._reserve_placement_resource(
            "test_compute1_0000:81:01.0", self.PCI_RC, 0)

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
        # on the source host the allocation is now held by the migration UUID
        self._move_server_allocation(
            test_compute0_placement_pci_view["allocations"], server_a['id'])
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        self.assertPCIDeviceCounts('test_compute1', total=2, free=0)
        # sever_a now have allocation on test_compute1 on 81:01
        test_compute1_placement_pci_view["usages"][
            "0000:81:01.0"][self.PCI_RC] = 1
        test_compute1_placement_pci_view["allocations"][
            server_a['id']] = {"0000:81:01.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # now, confirm the migration and check our counts once again
        self._confirm_resize(server_a)

        self.assertPCIDeviceCounts('test_compute0', total=2, free=2)
        # the source host now has no allocations as the migration allocation
        # is removed by confirm resize
        test_compute0_placement_pci_view["usages"] = {
            "0000:81:00.0": {self.PCI_RC: 0},
            "0000:81:01.0": {self.PCI_RC: 0},
        }
        test_compute0_placement_pci_view["allocations"] = {}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        self.assertPCIDeviceCounts('test_compute1', total=2, free=0)
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        self.assert_no_pci_healing("test_compute0")
        self.assert_no_pci_healing("test_compute1")

    def test_request_two_pci_but_host_has_one(self):
        # simulate a single type-PCI device on the host
        self.start_compute(pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))
        self.assertPCIDeviceCounts('compute1', total=1, free=1)

        alias = [jsonutils.dumps(x) for x in (
            {
                'vendor_id': fakelibvirt.PCI_VEND_ID,
                'product_id': fakelibvirt.PCI_PROD_ID,
                'name': 'a1',
            },
            {
                'vendor_id': fakelibvirt.PCI_VEND_ID,
                'product_id': fakelibvirt.PCI_PROD_ID,
                'name': 'a2',
            },
        )]
        self.flags(group='pci', alias=alias)
        # request two PCI devices both are individually matching with the
        # single available device on the host
        extra_spec = {'pci_passthrough:alias': 'a1:1,a2:1'}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        # so we expect that the boot fails with no valid host error as only
        # one of the requested PCI device can be allocated
        server = self._create_server(
            flavor_id=flavor_id, networks="none", expected_state='ERROR')
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

    def _create_two_computes(self):
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1))
        self.assertPCIDeviceCounts('test_compute0', total=1, free=1)
        test_compute0_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        self.start_compute(
            hostname='test_compute1',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=1),
        )
        self.assertPCIDeviceCounts('test_compute1', total=1, free=1)
        test_compute1_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        return (
            test_compute0_placement_pci_view,
            test_compute1_placement_pci_view,
        )

    def _create_two_computes_and_an_instance_on_the_first(self):
        (
            test_compute0_placement_pci_view,
            test_compute1_placement_pci_view,
        ) = self._create_two_computes()

        # boot a VM on test_compute0 with a single PCI dev
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=pci_flavor_id, networks='none', host="test_compute0")

        self.assertPCIDeviceCounts('test_compute0', total=1, free=0)
        test_compute0_placement_pci_view["usages"][
            "0000:81:00.0"][self.PCI_RC] = 1
        test_compute0_placement_pci_view["allocations"][
            server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        return (
            server,
            test_compute0_placement_pci_view,
            test_compute1_placement_pci_view,
        )

    def test_evacuate(self):
        (
            server,
            test_compute0_placement_pci_view,
            test_compute1_placement_pci_view,
        ) = self._create_two_computes_and_an_instance_on_the_first()

        # kill test_compute0 and evacuate the instance
        self.computes['test_compute0'].stop()
        self.api.put_service(
            self.computes["test_compute0"].service_ref.uuid,
            {"forced_down": True},
        )
        self._evacuate_server(server)
        # source allocation should be kept as source is dead but the server
        # now has allocation on both hosts as evacuation does not use migration
        # allocations.
        self.assertPCIDeviceCounts('test_compute0', total=1, free=0)
        self.assert_placement_pci_inventory(
            "test_compute0",
            test_compute0_placement_pci_view["inventories"],
            test_compute0_placement_pci_view["traits"]
        )
        self.assert_placement_pci_usages(
            "test_compute0", test_compute0_placement_pci_view["usages"]
        )
        self.assert_placement_pci_allocations(
            {
                server['id']: {
                    "test_compute0": {
                        "VCPU": 2,
                        "MEMORY_MB": 2048,
                        "DISK_GB": 20,
                    },
                    "test_compute0_0000:81:00.0": {self.PCI_RC: 1},
                    "test_compute1": {
                        "VCPU": 2,
                        "MEMORY_MB": 2048,
                        "DISK_GB": 20,
                    },
                    "test_compute1_0000:81:00.0": {self.PCI_RC: 1},
                },
            }
        )

        # dest allocation should be created
        self.assertPCIDeviceCounts('test_compute1', total=1, free=0)
        test_compute1_placement_pci_view["usages"][
            "0000:81:00.0"][self.PCI_RC] = 1
        test_compute1_placement_pci_view["allocations"][
            server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_inventory(
            "test_compute1",
            test_compute1_placement_pci_view["inventories"],
            test_compute1_placement_pci_view["traits"]
        )
        self.assert_placement_pci_usages(
            "test_compute1", test_compute0_placement_pci_view["usages"]
        )

        # recover test_compute0 and check that it is cleaned
        self.restart_compute_service('test_compute0')

        self.assertPCIDeviceCounts('test_compute0', total=1, free=1)
        test_compute0_placement_pci_view = {
            "inventories": {"0000:81:00.0": {self.PCI_RC: 1}},
            "traits": {"0000:81:00.0": []},
            "usages": {"0000:81:00.0": {self.PCI_RC: 0}},
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        # and test_compute1 is not changes (expect that the instance now has
        # only allocation on this compute)
        self.assertPCIDeviceCounts('test_compute1', total=1, free=0)
        test_compute1_placement_pci_view["usages"][
            "0000:81:00.0"][self.PCI_RC] = 1
        test_compute1_placement_pci_view["allocations"][
            server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        self.assert_no_pci_healing("test_compute0")
        self.assert_no_pci_healing("test_compute1")

    def test_unshelve_after_offload(self):
        (
            server,
            test_compute0_placement_pci_view,
            test_compute1_placement_pci_view,
        ) = self._create_two_computes_and_an_instance_on_the_first()

        # shelve offload the server
        self._shelve_server(server)

        # source allocation should be freed
        self.assertPCIDeviceCounts('test_compute0', total=1, free=1)
        test_compute0_placement_pci_view["usages"][
            "0000:81:00.0"][self.PCI_RC] = 0
        del test_compute0_placement_pci_view["allocations"][server['id']]
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        # test_compute1 should not be touched
        self.assertPCIDeviceCounts('test_compute1', total=1, free=1)
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        # disable test_compute0 and unshelve the instance
        self.api.put_service(
            self.computes["test_compute0"].service_ref.uuid,
            {"status": "disabled"},
        )
        self._unshelve_server(server)

        # test_compute0 should be unchanged
        self.assertPCIDeviceCounts('test_compute0', total=1, free=1)
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        # test_compute1 should be allocated
        self.assertPCIDeviceCounts('test_compute1', total=1, free=0)
        test_compute1_placement_pci_view["usages"][
            "0000:81:00.0"][self.PCI_RC] = 1
        test_compute1_placement_pci_view["allocations"][
            server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(
            "test_compute1", **test_compute1_placement_pci_view)

        self.assert_no_pci_healing("test_compute0")
        self.assert_no_pci_healing("test_compute1")

    def test_reschedule(self):
        (
            test_compute0_placement_pci_view,
            test_compute1_placement_pci_view,
        ) = self._create_two_computes()

        # try to boot a VM with a single device but inject fault on the first
        # compute so that the VM is re-scheduled to the other
        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)

        calls = []
        orig_guest_create = (
            nova.virt.libvirt.driver.LibvirtDriver._create_guest)

        def fake_guest_create(*args, **kwargs):
            if not calls:
                calls.append(1)
                raise fakelibvirt.make_libvirtError(
                    fakelibvirt.libvirtError,
                    "internal error",
                    error_code=fakelibvirt.VIR_ERR_INTERNAL_ERROR,
                )
            else:
                return orig_guest_create(*args, **kwargs)

        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver._create_guest',
            new=fake_guest_create
        ):
            server = self._create_server(
                flavor_id=pci_flavor_id, networks='none')

        compute_pci_view_map = {
            'test_compute0': test_compute0_placement_pci_view,
            'test_compute1': test_compute1_placement_pci_view,
        }
        allocated_compute = server['OS-EXT-SRV-ATTR:host']
        not_allocated_compute = (
            "test_compute0"
            if allocated_compute == "test_compute1"
            else "test_compute1"
        )

        allocated_pci_view = compute_pci_view_map.pop(
            server['OS-EXT-SRV-ATTR:host'])
        not_allocated_pci_view = list(compute_pci_view_map.values())[0]

        self.assertPCIDeviceCounts(allocated_compute, total=1, free=0)
        allocated_pci_view["usages"][
            "0000:81:00.0"][self.PCI_RC] = 1
        allocated_pci_view["allocations"][
            server['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}
        self.assert_placement_pci_view(allocated_compute, **allocated_pci_view)

        self.assertPCIDeviceCounts(not_allocated_compute, total=1, free=1)
        self.assert_placement_pci_view(
            not_allocated_compute, **not_allocated_pci_view)
        self.assert_no_pci_healing("test_compute0")
        self.assert_no_pci_healing("test_compute1")

    def test_multi_create(self):
        self.start_compute(
            hostname='test_compute0',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=3))
        self.assertPCIDeviceCounts('test_compute0', total=3, free=3)
        test_compute0_placement_pci_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
                "0000:81:02.0": {self.PCI_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
                "0000:81:01.0": [],
                "0000:81:02.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
                "0000:81:01.0": {self.PCI_RC: 0},
                "0000:81:02.0": {self.PCI_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        extra_spec = {'pci_passthrough:alias': f'{self.ALIAS_NAME}:1'}
        pci_flavor_id = self._create_flavor(extra_spec=extra_spec)
        body = self._build_server(flavor_id=pci_flavor_id, networks='none')
        body.update(
            {
                "min_count": "2",
            }
        )
        self.api.post_server({'server': body})

        servers = self.api.get_servers(detail=False)
        for server in servers:
            self._wait_for_state_change(server, 'ACTIVE')

        self.assertEqual(2, len(servers))
        self.assertPCIDeviceCounts('test_compute0', total=3, free=1)
        # we have no way to influence which instance takes which device, so
        # we need to look at the nova DB to properly assert the placement
        # allocation
        devices = objects.PciDeviceList.get_by_compute_node(
            self.ctxt,
            objects.ComputeNode.get_by_nodename(self.ctxt, 'test_compute0').id,
        )
        for dev in devices:
            if dev.instance_uuid:
                test_compute0_placement_pci_view["usages"][
                    dev.address][self.PCI_RC] = 1
                test_compute0_placement_pci_view["allocations"][
                    dev.instance_uuid] = {dev.address: {self.PCI_RC: 1}}

        self.assert_placement_pci_view(
            "test_compute0", **test_compute0_placement_pci_view)

        self.assert_no_pci_healing("test_compute0")


class PCIServersWithPreferredNUMATest(_PCIServersTestBase):

    ALIAS_NAME = 'a1'
    PCI_DEVICE_SPEC = [jsonutils.dumps(
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

    def setUp(self):
        super().setUp()
        self.flags(group="pci", report_in_placement=True)
        self.flags(group='filter_scheduler', pci_in_placement=True)

    def test_create_server_with_pci_dev_and_numa(self):
        """Validate behavior of 'preferred' PCI NUMA policy.

        This test ensures that it *is* possible to allocate CPU and memory
        resources from one NUMA node and a PCI device from another *if* PCI
        NUMA policies are in use.
        """

        self.flags(cpu_dedicated_set='0-7', group='compute')

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=1, numa_node=0)
        self.start_compute(pci_info=pci_info)
        compute1_placement_pci_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
            },
            "traits": {
                "0000:81:00.0": [],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_placement_pci_view)

        # boot one instance with no PCI device to "fill up" NUMA node 0
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id)

        self.assert_placement_pci_view(
            "compute1", **compute1_placement_pci_view)

        # now boot one with a PCI device, which should succeed thanks to the
        # use of the PCI policy
        extra_spec['pci_passthrough:alias'] = '%s:1' % self.ALIAS_NAME
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server_with_pci = self._create_server(
            flavor_id=flavor_id, expected_state=self.expected_state)

        if self.expected_state == 'ACTIVE':
            compute1_placement_pci_view["usages"][
                "0000:81:00.0"][self.PCI_RC] = 1
            compute1_placement_pci_view["allocations"][
                server_with_pci['id']] = {"0000:81:00.0": {self.PCI_RC: 1}}

        self.assert_placement_pci_view(
            "compute1", **compute1_placement_pci_view)
        self.assert_no_pci_healing("compute1")


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

    def setUp(self):
        super().setUp()
        self.useFixture(
            fixtures.MockPatch(
                'nova.pci.utils.is_physical_function', return_value=False
            )
        )

    def test_create_server_with_pci_dev_and_numa_placement_conflict(self):
        # fakelibvirt will simulate the devices:
        # * one type-PCI in 81.00 on numa 0
        # * one type-PCI in 81.01 on numa 1
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pci=2)
        # the device_spec will assign different traits to 81.00 than 81.01
        # so the two devices become different from placement perspective
        device_spec = self._to_list_of_json_str(
            [
                {
                    'vendor_id': fakelibvirt.PCI_VEND_ID,
                    'product_id': fakelibvirt.PCI_PROD_ID,
                    "address": "0000:81:00.0",
                    "traits": "green",
                },
                {
                    'vendor_id': fakelibvirt.PCI_VEND_ID,
                    'product_id': fakelibvirt.PCI_PROD_ID,
                    "address": "0000:81:01.0",
                    "traits": "red",
                },
            ]
        )
        self.flags(group='pci', device_spec=device_spec)
        # both numa 0 and numa 1 has 4 PCPUs
        self.flags(cpu_dedicated_set='0-7', group='compute')
        self.start_compute(pci_info=pci_info)
        compute1_placement_pci_view = {
            "inventories": {
                "0000:81:00.0": {self.PCI_RC: 1},
                "0000:81:01.0": {self.PCI_RC: 1},
            },
            "traits": {
                "0000:81:00.0": ["CUSTOM_GREEN"],
                "0000:81:01.0": ["CUSTOM_RED"],
            },
            "usages": {
                "0000:81:00.0": {self.PCI_RC: 0},
                "0000:81:01.0": {self.PCI_RC: 0},
            },
            "allocations": {},
        }
        self.assert_placement_pci_view(
            "compute1", **compute1_placement_pci_view)

        # boot one instance with no PCI device to "fill up" NUMA node 0
        # so we will have PCPUs on numa 0 and we have PCI on both nodes
        extra_spec = {
            'hw:cpu_policy': 'dedicated',
        }
        flavor_id = self._create_flavor(vcpu=4, extra_spec=extra_spec)
        self._create_server(flavor_id=flavor_id)

        pci_alias = {
            "resource_class": self.PCI_RC,
            # this means only 81.00 will match in placement which is on numa 0
            "traits": "green",
            "name": "pci-dev",
            # this forces the scheduler to only accept a solution where the
            # PCI device is on the same numa node as the pinned CPUs
            'numa_policy': fields.PCINUMAAffinityPolicy.REQUIRED,
        }
        self.flags(
            group="pci",
            alias=self._to_list_of_json_str([pci_alias]),
        )

        # Ask for dedicated CPUs, that can only be fulfilled on numa 1.
        # And ask for a PCI alias that can only be fulfilled on numa 0 due to
        # trait request.
        # We expect that this makes the scheduling fail.
        extra_spec = {
            "hw:cpu_policy": "dedicated",
            "pci_passthrough:alias": "pci-dev:1",
        }
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, expected_state="ERROR")

        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])
        self.assert_placement_pci_view(
            "compute1", **compute1_placement_pci_view)
        self.assert_no_pci_healing("compute1")


@ddt.ddt
class PCIServersWithSRIOVAffinityPoliciesTest(_PCIServersTestBase):

    ALIAS_NAME = 'a1'
    PCI_DEVICE_SPEC = [jsonutils.dumps(
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

        # request cpu pinning to create a numa topology and allow the test to
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

        self.flags(
            device_spec=self.PCI_DEVICE_SPEC,
            alias=alias,
            group='pci'
        )

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
    PCI_DEVICE_SPEC = [jsonutils.dumps(x) for x in (
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

        # request cpu pinning to create a numa topology and allow the test to
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

        self.flags(
            device_spec=self.PCI_DEVICE_SPEC,
            alias=alias,
            group='pci'
        )

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


class RemoteManagedServersTest(_PCIServersWithMigrationTestBase):

    ADMIN_API = True
    microversion = 'latest'

    PCI_DEVICE_SPEC = [jsonutils.dumps(x) for x in (
        # A PF with access to physnet4.
        {
            'vendor_id': '15b3',
            'product_id': 'a2dc',
            'physical_network': 'physnet4',
            'remote_managed': 'false',
        },
        # A VF with access to physnet4.
        {
            'vendor_id': '15b3',
            'product_id': '1021',
            'physical_network': 'physnet4',
            'remote_managed': 'true',
        },
        # A PF programmed to forward traffic to an overlay network.
        {
            'vendor_id': '15b3',
            'product_id': 'a2d6',
            'physical_network': None,
            'remote_managed': 'false',
        },
        # A VF programmed to forward traffic to an overlay network.
        {
            'vendor_id': '15b3',
            'product_id': '101e',
            'physical_network': None,
            'remote_managed': 'true',
        },
    )]

    PCI_ALIAS = []

    NUM_PFS = 1
    NUM_VFS = 4
    vf_ratio = NUM_VFS // NUM_PFS

    # Min Libvirt version that supports working with PCI VPD.
    FAKE_LIBVIRT_VERSION = 7_009_000  # 7.9.0
    FAKE_QEMU_VERSION = 5_001_000  # 5.1.0

    def setUp(self):
        super().setUp()
        self.neutron = self.useFixture(base.LibvirtNeutronFixture(self))

        self.useFixture(fixtures.MockPatch(
            'nova.pci.utils.get_vf_num_by_pci_address',
            new=mock.MagicMock(
                side_effect=lambda addr: self._get_pci_function_number(addr))))

        self.useFixture(fixtures.MockPatch(
            'nova.pci.utils.get_mac_by_pci_address',
            new=mock.MagicMock(
                side_effect=(
                    lambda addr: {
                        "0000:80:00.0": "52:54:00:1e:59:42",
                        "0000:81:00.0": "52:54:00:1e:59:01",
                        "0000:82:00.0": "52:54:00:1e:59:02",
                    }.get(addr)
                )
            )
        ))

    @classmethod
    def _get_pci_function_number(cls, pci_addr: str):
        """Get a VF function number based on a PCI address.

        Assume that the PCI ARI capability is enabled (slot bits become a part
        of a function number).
        """
        _, _, slot, function = parse_address(pci_addr)
        # The number of PFs is extracted to get a VF number.
        return int(slot, 16) + int(function, 16) - cls.NUM_PFS

    def start_compute(
        self, hostname='test_compute0', host_info=None, pci_info=None,
        mdev_info=None, vdpa_info=None,
        libvirt_version=None,
        qemu_version=None):

        if not pci_info:
            pci_info = fakelibvirt.HostPCIDevicesInfo(
                num_pci=0, num_pfs=0, num_vfs=0)

            pci_info.add_device(
                dev_type='PF',
                bus=0x81,
                slot=0x0,
                function=0,
                iommu_group=42,
                numa_node=0,
                vf_ratio=self.vf_ratio,
                vend_id='15b3',
                vend_name='Mellanox Technologies',
                prod_id='a2dc',
                prod_name='BlueField-3 integrated ConnectX-7 controller',
                driver_name='mlx5_core',
                vpd_fields={
                    'name': 'MT43244 BlueField-3 integrated ConnectX-7',
                    'readonly': {
                        'serial_number': 'MT0000X00001',
                    },
                }
            )

            for idx in range(self.NUM_VFS):
                pci_info.add_device(
                    dev_type='VF',
                    bus=0x81,
                    slot=0x0,
                    function=idx + 1,
                    iommu_group=idx + 43,
                    numa_node=0,
                    vf_ratio=self.vf_ratio,
                    parent=(0x81, 0x0, 0),
                    vend_id='15b3',
                    vend_name='Mellanox Technologies',
                    prod_id='1021',
                    prod_name='MT2910 Family [ConnectX-7]',
                    driver_name='mlx5_core',
                    vpd_fields={
                        'name': 'MT2910 Family [ConnectX-7]',
                        'readonly': {
                            'serial_number': 'MT0000X00001',
                        },
                    }
                )

            pci_info.add_device(
                dev_type='PF',
                bus=0x82,
                slot=0x0,
                function=0,
                iommu_group=84,
                numa_node=0,
                vf_ratio=self.vf_ratio,
                vend_id='15b3',
                vend_name='Mellanox Technologies',
                prod_id='a2d6',
                prod_name='MT42822 BlueField-2 integrated ConnectX-6',
                driver_name='mlx5_core',
                vpd_fields={
                    'name': 'MT42822 BlueField-2 integrated ConnectX-6',
                    'readonly': {
                        'serial_number': 'MT0000X00002',
                    },
                }
            )

            for idx in range(self.NUM_VFS):
                pci_info.add_device(
                    dev_type='VF',
                    bus=0x82,
                    slot=0x0,
                    function=idx + 1,
                    iommu_group=idx + 85,
                    numa_node=0,
                    vf_ratio=self.vf_ratio,
                    parent=(0x82, 0x0, 0),
                    vend_id='15b3',
                    vend_name='Mellanox Technologies',
                    prod_id='101e',
                    prod_name='ConnectX Family mlx5Gen Virtual Function',
                    driver_name='mlx5_core')

        return super().start_compute(
            hostname=hostname, host_info=host_info, pci_info=pci_info,
            mdev_info=mdev_info, vdpa_info=vdpa_info,
            libvirt_version=libvirt_version or self.FAKE_LIBVIRT_VERSION,
            qemu_version=qemu_version or self.FAKE_QEMU_VERSION)

    def create_remote_managed_tunnel_port(self):
        dpu_tunnel_port = {
            'id': uuids.dpu_tunnel_port,
            'network_id': self.neutron.network_3['id'],
            'status': 'ACTIVE',
            'mac_address': 'fa:16:3e:f0:a4:bb',
            'fixed_ips': [
                {
                    'ip_address': '192.168.2.8',
                    'subnet_id': self.neutron.subnet_3['id']
                }
            ],
            'binding:vif_details': {},
            'binding:vif_type': 'ovs',
            'binding:vnic_type': 'remote-managed',
        }

        self.neutron.create_port({'port': dpu_tunnel_port})
        return dpu_tunnel_port

    def create_remote_managed_physnet_port(self):
        dpu_physnet_port = {
            'id': uuids.dpu_physnet_port,
            'network_id': self.neutron.network_4['id'],
            'status': 'ACTIVE',
            'mac_address': 'd2:0b:fd:99:89:8b',
            'fixed_ips': [
                {
                    'ip_address': '192.168.4.10',
                    'subnet_id': self.neutron.subnet_4['id']
                }
            ],
            'binding:vif_details': {},
            'binding:vif_type': 'ovs',
            'binding:vnic_type': 'remote-managed',
        }

        self.neutron.create_port({'port': dpu_physnet_port})
        return dpu_physnet_port

    def test_create_server_physnet(self):
        """Create an instance with a tunnel remote-managed port."""

        hostname = self.start_compute()
        num_pci = (self.NUM_PFS + self.NUM_VFS) * 2

        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci)

        dpu_port = self.create_remote_managed_physnet_port()

        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertNotIn('binding:profile', port)

        self._create_server(networks=[{'port': dpu_port['id']}])

        # Ensure there is one less VF available and that the PF
        # is no longer usable.
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci - 2)

        # Ensure the binding:profile details sent to Neutron are correct after
        # a port update.
        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertIn('binding:profile', port)
        self.assertEqual({
            'card_serial_number': 'MT0000X00001',
            'pci_slot': '0000:81:00.4',
            'pci_vendor_info': '15b3:1021',
            'pf_mac_address': '52:54:00:1e:59:01',
            'physical_network': 'physnet4',
            'vf_num': 3
        }, port['binding:profile'])

    def test_create_server_tunnel(self):
        """Create an instance with a tunnel remote-managed port."""

        hostname = self.start_compute()
        num_pci = (self.NUM_PFS + self.NUM_VFS) * 2
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci)

        dpu_port = self.create_remote_managed_tunnel_port()
        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertNotIn('binding:profile', port)

        self._create_server(networks=[{'port': dpu_port['id']}])

        # Ensure there is one less VF available and that the PF
        # is no longer usable.
        self.assertPCIDeviceCounts(hostname, total=num_pci, free=num_pci - 2)

        # Ensure the binding:profile details sent to Neutron are correct after
        # a port update.
        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertIn('binding:profile', port)
        self.assertEqual({
            'card_serial_number': 'MT0000X00002',
            'pci_slot': '0000:82:00.4',
            'pci_vendor_info': '15b3:101e',
            'pf_mac_address': '52:54:00:1e:59:02',
            'physical_network': None,
            'vf_num': 3
        }, port['binding:profile'])

    def _test_common(self, op, *args, **kwargs):
        self.start_compute()
        dpu_port = self.create_remote_managed_tunnel_port()
        server = self._create_server(networks=[{'port': dpu_port['id']}])
        op(server, *args, **kwargs)

    def test_attach_interface(self):
        self.start_compute()

        dpu_port = self.create_remote_managed_tunnel_port()
        server = self._create_server(networks='none')

        self._attach_interface(server, dpu_port['id'])

        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '15b3:101e',
                'pci_slot': '0000:82:00.4',
                'physical_network': None,
                'pf_mac_address': '52:54:00:1e:59:02',
                'vf_num': 3,
                'card_serial_number': 'MT0000X00002',
            },
            port['binding:profile'],
        )

    def test_detach_interface(self):
        self._test_common(self._detach_interface, uuids.dpu_tunnel_port)

        port = self.neutron.show_port(uuids.dpu_tunnel_port)['port']
        self.assertIn('binding:profile', port)
        self.assertEqual({}, port['binding:profile'])

    def test_shelve(self):
        self._test_common(self._shelve_server)

        port = self.neutron.show_port(uuids.dpu_tunnel_port)['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '15b3:101e',
                'pci_slot': '0000:82:00.4',
                'physical_network': None,
                'pf_mac_address': '52:54:00:1e:59:02',
                'vf_num': 3,
                'card_serial_number': 'MT0000X00002',
            },
            port['binding:profile'],
        )

    def test_suspend(self):
        self.start_compute()
        dpu_port = self.create_remote_managed_tunnel_port()
        server = self._create_server(networks=[{'port': dpu_port['id']}])
        self._suspend_server(server)
        # TODO(dmitriis): detachDevice does not properly handle hostdevs
        # so full suspend/resume testing is problematic.

    def _test_move_operation_with_neutron(self, move_operation, dpu_port):
        """Test a move operation with a remote-managed port.
        """
        compute1_pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pfs=0, num_vfs=0)

        compute1_pci_info.add_device(
            dev_type='PF',
            bus=0x80,
            slot=0x0,
            function=0,
            iommu_group=84,
            numa_node=1,
            vf_ratio=self.vf_ratio,
            vend_id='15b3',
            vend_name='Mellanox Technologies',
            prod_id='a2d6',
            prod_name='MT42822 BlueField-2 integrated ConnectX-6',
            driver_name='mlx5_core',
            vpd_fields={
                'name': 'MT42822 BlueField-2 integrated ConnectX-6',
                'readonly': {
                    'serial_number': 'MT0000X00042',
                },
            }
        )
        for idx in range(self.NUM_VFS):
            compute1_pci_info.add_device(
                dev_type='VF',
                bus=0x80,
                slot=0x0,
                function=idx + 1,
                iommu_group=idx + 85,
                numa_node=1,
                vf_ratio=self.vf_ratio,
                parent=(0x80, 0x0, 0),
                vend_id='15b3',
                vend_name='Mellanox Technologies',
                prod_id='101e',
                prod_name='ConnectX Family mlx5Gen Virtual Function',
                driver_name='mlx5_core',
                vpd_fields={
                    'name': 'MT42822 BlueField-2 integrated ConnectX-6',
                    'readonly': {
                        'serial_number': 'MT0000X00042',
                    },
                }
            )

        self.start_compute(hostname='test_compute0')
        self.start_compute(hostname='test_compute1',
                           pci_info=compute1_pci_info)

        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertNotIn('binding:profile', port)

        flavor_id = self._create_flavor(vcpu=4)
        server = self._create_server(
            flavor_id=flavor_id,
            networks=[{'port': dpu_port['id']}],
            host='test_compute0',
        )

        self.assertEqual('test_compute0', server['OS-EXT-SRV-ATTR:host'])
        self.assertPCIDeviceCounts('test_compute0', total=10, free=8)
        self.assertPCIDeviceCounts('test_compute1', total=5, free=5)

        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '15b3:101e',
                'pci_slot': '0000:82:00.4',
                'physical_network': None,
                'pf_mac_address': '52:54:00:1e:59:02',
                'vf_num': 3,
                'card_serial_number': 'MT0000X00002',
            },
            port['binding:profile'],
        )

        move_operation(server)

    def test_unshelve_server_with_neutron(self):
        def move_operation(source_server):
            self._shelve_server(source_server)
            # Disable the source compute, to force unshelving on the dest.
            self.api.put_service(
                self.computes['test_compute0'].service_ref.uuid,
                {'status': 'disabled'})
            self._unshelve_server(source_server)

        dpu_port = self.create_remote_managed_tunnel_port()
        self._test_move_operation_with_neutron(move_operation, dpu_port)

        self.assertPCIDeviceCounts('test_compute0', total=10, free=10)
        self.assertPCIDeviceCounts('test_compute1', total=5, free=3)

        # Ensure the binding:profile details got updated, including the
        # fields relevant to remote-managed ports.
        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '15b3:101e',
                'pci_slot': '0000:80:00.4',
                'physical_network': None,
                'pf_mac_address': '52:54:00:1e:59:42',
                'vf_num': 3,
                'card_serial_number': 'MT0000X00042',
            },
            port['binding:profile'],
        )

    def test_cold_migrate_server_with_neutron(self):
        def move_operation(source_server):
            with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                            '.migrate_disk_and_power_off', return_value='{}'):
                server = self._migrate_server(source_server)
                self._confirm_resize(server)

                self.assertPCIDeviceCounts('test_compute0', total=10, free=10)
                self.assertPCIDeviceCounts('test_compute1', total=5, free=3)

                # Ensure the binding:profile details got updated, including the
                # fields relevant to remote-managed ports.
                port = self.neutron.show_port(dpu_port['id'])['port']
                self.assertIn('binding:profile', port)
                self.assertEqual(
                    {
                        'pci_vendor_info': '15b3:101e',
                        'pci_slot': '0000:80:00.4',
                        'physical_network': None,
                        'pf_mac_address': '52:54:00:1e:59:42',
                        'vf_num': 3,
                        'card_serial_number': 'MT0000X00042',
                    },
                    port['binding:profile'],
                )

        dpu_port = self.create_remote_managed_tunnel_port()
        self._test_move_operation_with_neutron(move_operation, dpu_port)

    def test_cold_migrate_server_with_neutron_revert(self):
        def move_operation(source_server):
            with mock.patch('nova.virt.libvirt.driver.LibvirtDriver'
                            '.migrate_disk_and_power_off', return_value='{}'):
                server = self._migrate_server(source_server)

                self.assertPCIDeviceCounts('test_compute0', total=10, free=8)
                self.assertPCIDeviceCounts('test_compute1', total=5, free=3)

                self._revert_resize(server)

                self.assertPCIDeviceCounts('test_compute0', total=10, free=8)
                self.assertPCIDeviceCounts('test_compute1', total=5, free=5)

                port = self.neutron.show_port(dpu_port['id'])['port']
                self.assertIn('binding:profile', port)
                self.assertEqual(
                    {
                        'pci_vendor_info': '15b3:101e',
                        'pci_slot': '0000:82:00.4',
                        'physical_network': None,
                        'pf_mac_address': '52:54:00:1e:59:02',
                        'vf_num': 3,
                        'card_serial_number': 'MT0000X00002',
                    },
                    port['binding:profile'],
                )

        dpu_port = self.create_remote_managed_tunnel_port()
        self._test_move_operation_with_neutron(move_operation, dpu_port)

    def test_evacuate_server_with_neutron(self):
        def move_operation(source_server):
            # Down the source compute to enable the evacuation
            self.api.put_service(
                self.computes['test_compute0'].service_ref.uuid,
                {'forced_down': True})
            self.computes['test_compute0'].stop()
            self._evacuate_server(source_server)

        dpu_port = self.create_remote_managed_tunnel_port()
        self._test_move_operation_with_neutron(move_operation, dpu_port)

        self.assertPCIDeviceCounts('test_compute0', total=10, free=8)
        self.assertPCIDeviceCounts('test_compute1', total=5, free=3)

        # Ensure the binding:profile details got updated, including the
        # fields relevant to remote-managed ports.
        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '15b3:101e',
                'pci_slot': '0000:80:00.4',
                'physical_network': None,
                'pf_mac_address': '52:54:00:1e:59:42',
                'vf_num': 3,
                'card_serial_number': 'MT0000X00042',
            },
            port['binding:profile'],
        )

    def test_live_migrate_server_with_neutron(self):
        """Live migrate an instance using a remote-managed port.

        This should succeed since we support this via detach and attach of the
        PCI device similar to how this is done for SR-IOV ports.
        """
        def move_operation(source_server):
            self._live_migrate(source_server, 'completed')

        dpu_port = self.create_remote_managed_tunnel_port()
        self._test_move_operation_with_neutron(move_operation, dpu_port)

        self.assertPCIDeviceCounts('test_compute0', total=10, free=10)
        self.assertPCIDeviceCounts('test_compute1', total=5, free=3)

        # Ensure the binding:profile details got updated, including the
        # fields relevant to remote-managed ports.
        port = self.neutron.show_port(dpu_port['id'])['port']
        self.assertIn('binding:profile', port)
        self.assertEqual(
            {
                'pci_vendor_info': '15b3:101e',
                'pci_slot': '0000:80:00.4',
                'physical_network': None,
                'pf_mac_address': '52:54:00:1e:59:42',
                'vf_num': 3,
                'card_serial_number': 'MT0000X00042',
            },
            port['binding:profile'],
        )
