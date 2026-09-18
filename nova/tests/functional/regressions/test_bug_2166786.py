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
from unittest import mock

from oslo_serialization import jsonutils

from nova import exception
from nova import objects
from nova.objects import fields
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_pci_sriov_servers as base


class TestPCIColdMigrationBase(base._PCIServersTestBase):
    microversion = 'latest'
    ADMIN_API = True
    CAST_AS_CALL = False

    PFS_ALIAS_NAME = 'pfs'

    PCI_DEVICE_SPEC = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PF_PROD_ID,
        },
    )]
    PCI_ALIAS = [jsonutils.dumps(x) for x in (
        {
            'vendor_id': fakelibvirt.PCI_VEND_ID,
            'product_id': fakelibvirt.PF_PROD_ID,
            'device_type': fields.PciDeviceType.SRIOV_PF,
            'name': PFS_ALIAS_NAME,
        },
    )]

    def assert_pci_pool_free_count(self, hostname, free):
        node = objects.ComputeNode.get_by_nodename(self.ctxt, hostname)
        self.assertEqual(
            free, sum(pool.count for pool in node.pci_device_pools))

    def assert_pci_inventory(self, hostname, total, free):
        self.assertPCIDeviceCounts(hostname, total=total, free=free)
        self.assert_pci_pool_free_count(hostname, free=free)


class TestPCIColdMigrationFailureRevert(TestPCIColdMigrationBase):
    """Regression test for bug https://bugs.launchpad.net/nova/+bug/2166786
    """

    def test_cold_migrate_server_with_PF(self):
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=0)
        comp0 = self.start_compute(
            hostname='test_compute0',
            pci_info=pci_info)
        comp1 = self.start_compute(
            hostname='test_compute1',
            pci_info=pci_info)

        self.assert_pci_inventory(comp0, total=2, free=2)
        self.assert_pci_inventory(comp1, total=2, free=2)

        # create a server
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.PFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, networks='none', host='test_compute0')

        self.assert_pci_inventory(comp0, total=2, free=1)
        self.assert_pci_inventory(comp1, total=2, free=2)

        # NOTE(gibi): we are simulating an ssh failure during migration
        # when the libvirt driver tries to create the instance dir on the
        # destination host via remotefs / ssh.
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            side_effect=exception.InstanceFaultRollback(
                exception.ResizeError(reason="simulated ssh failure"))
        ):
            self._migrate_server(server, expected_state="ACTIVE")
            self._wait_for_migration_status(server, ['error'])
            self._wait_for_state_change(server, 'ACTIVE')
            self.notifier.wait_for_versioned_notifications('compute.exception')

        self.assert_pci_inventory(comp0, total=2, free=1)
        # NOTE(gibi): This is bug https://bugs.launchpad.net/nova/+bug/2166786
        # as after the migration failed and reverted
        # the PCI allocation on the destination compute is not cleaned.
        self.assert_pci_inventory(comp1, total=2, free=1)

        # The periodic now detects and cleans such leaks
        self._run_periodics()
        self.assert_pci_inventory(comp0, total=2, free=1)
        self.assert_pci_inventory(comp1, total=2, free=2)

        # NOTE(gibi): This is also the same bug, the migration context is not
        # cleaned up on the instance after the migration failed and reverted.
        inst = objects.Instance.get_by_uuid(self.ctxt, server['id'])
        self.assertIsNotNone(inst.migration_context)

        self._delete_server(server)
        self.assert_pci_inventory(comp0, total=2, free=2)
        self.assert_pci_inventory(comp1, total=2, free=2)


class TestPCIColdMigrationLeakHealedByPeriodic(TestPCIColdMigrationBase):
    """Regression test for bug https://bugs.launchpad.net/nova/+bug/2166786

    This simulates a leak that happened before the fix that drops the move
    claim on the destination was deployed, and asserts that the periodic
    update_available_resource job on the destination is able to heal it.
    """

    def test_cold_migrate_server_with_PF(self):
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=0)
        comp0 = self.start_compute(
            hostname='test_compute0',
            pci_info=pci_info)
        comp1 = self.start_compute(
            hostname='test_compute1',
            pci_info=pci_info)

        self.assert_pci_inventory(comp0, total=2, free=2)
        self.assert_pci_inventory(comp1, total=2, free=2)

        # create a server
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.PFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, networks='none', host='test_compute0')

        self.assert_pci_inventory(comp0, total=2, free=1)
        self.assert_pci_inventory(comp1, total=2, free=2)

        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            side_effect=exception.InstanceFaultRollback(
                exception.ResizeError(reason="simulated ssh failure"))
        ):
            self._migrate_server(server, expected_state="ACTIVE")
            self._wait_for_migration_status(server, ['error'])
            self._wait_for_state_change(server, 'ACTIVE')
            self.notifier.wait_for_versioned_notifications('compute.exception')

        self.assert_pci_inventory(comp0, total=2, free=1)
        # The migration failed and reverted but, the PCI device claimed on
        # the destination during prep_resize is leaked.
        self.assert_pci_inventory(comp1, total=2, free=1)

        # The migration is still in error state and holds the leaked claim.
        migration = self._wait_for_migration_status(server, ['error'])

        # The periodic on the destination detects the leaked move claim of the
        # failed migration and releases it.
        self._run_periodics()
        self.assert_pci_inventory(comp0, total=2, free=1)
        self.assert_pci_inventory(comp1, total=2, free=2)

        # The migration is marked as failed so that it is reconciled only once
        # and no longer processed by later periodic runs.
        migration = objects.Migration.get_by_id(self.ctxt, migration['id'])
        self.assertEqual('failed', migration.status)

        # Running it again is a no-op, the leak stays healed.
        self._run_periodics()
        self.assert_pci_inventory(comp0, total=2, free=1)
        self.assert_pci_inventory(comp1, total=2, free=2)

        self._delete_server(server)
        self.assert_pci_inventory(comp0, total=2, free=2)
        self.assert_pci_inventory(comp1, total=2, free=2)


class TestPCIColdMigrationFailureRevertPciInPlacement(
    TestPCIColdMigrationBase
):
    """Regression test for bug https://bugs.launchpad.net/nova/+bug/2166786
    in case report_in_placement and pci_in_placement are enabled.
    """

    def test_cold_migrate_server_with_PF(self):
        self.flags(report_in_placement=True, group='pci')
        self.flags(pci_in_placement=True, group='filter_scheduler')

        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=0)
        comp0 = self.start_compute(
            hostname='test_compute0',
            pci_info=pci_info)
        comp1 = self.start_compute(
            hostname='test_compute1',
            pci_info=pci_info)

        self.assertPCIDeviceCounts(comp0, total=1, free=1)
        self.assertPCIDeviceCounts(comp1, total=1, free=1)

        self.assert_placement_pci_view(
            comp0,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 0}})
        self.assert_placement_pci_view(
            comp1,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 0}})

        # create a server
        extra_spec = {"pci_passthrough:alias": "%s:1" % self.PFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, networks='none', host='test_compute0')

        self.assertPCIDeviceCounts(comp0, total=1, free=0)
        self.assertPCIDeviceCounts(comp1, total=1, free=1)

        self.assert_placement_pci_view(
            comp0,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            allocations={server['id']: {
                "0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}}})
        self.assert_placement_pci_view(
            comp1,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 0}})

        # NOTE(gibi): we are simulating an ssh failure during migration
        # when the libvirt driver tries to create the instance dir on the
        # destination host via remotefs / ssh.
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver'
            '.migrate_disk_and_power_off',
            side_effect=exception.InstanceFaultRollback(
                exception.ResizeError(reason="simulated ssh failure"))
        ):
            self._migrate_server(server, expected_state="ACTIVE")
            self._wait_for_migration_status(server, ['error'])
            self._wait_for_state_change(server, 'ACTIVE')
            self.notifier.wait_for_versioned_notifications('compute.exception')

        self.assertPCIDeviceCounts(comp0, total=1, free=0)
        # NOTE(gibi): This is bug https://bugs.launchpad.net/nova/+bug/2166786
        # as after the migration failed and revert
        # the PCI allocation on the destination compute is not cleaned.
        self.assertPCIDeviceCounts(comp1, total=1, free=0)

        # NOTE(gibi): but Placement allocation is correct.
        self.assert_placement_pci_view(
            comp0,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            allocations={server['id']: {
                "0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}}})
        self.assert_placement_pci_view(
            comp1,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 0}})

        # The periodic now detects and cleans such leaks
        self._run_periodics()
        self.assertPCIDeviceCounts(comp0, total=1, free=0)
        self.assertPCIDeviceCounts(comp1, total=1, free=1)
        self.assert_placement_pci_view(
            comp0,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            allocations={server['id']: {
                "0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}}})
        self.assert_placement_pci_view(
            comp1,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 0}})

        self._delete_server(server)
        self.assertPCIDeviceCounts(comp0, total=1, free=1)
        self.assertPCIDeviceCounts(comp1, total=1, free=1)

        self.assert_placement_pci_view(
            comp0,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 0}})
        self.assert_placement_pci_view(
            comp1,
            inventories={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 1}},
            traits={"0000:81:00.0": []},
            usages={"0000:81:00.0": {'CUSTOM_PCI_8086_1528': 0}})
