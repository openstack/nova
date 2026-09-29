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

from nova.compute import power_state
from nova import context
from nova import objects
from nova.objects import fields
from nova.policies import base as base_policies
from nova.policies import servers as servers_policies
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.regressions import test_bug_2166786 as pci_base


class TestCrossCellColdMigratePCI(pci_base.TestPCIColdMigrationBase):
    """Reproduce losing PCI requests when copying between cells."""

    NUMBER_OF_CELLS = 2

    def test_cold_migrate_with_missing_destination_pci_devices(self):
        self.policy.set_rules({
            servers_policies.CROSS_CELL_RESIZE: base_policies.RULE_ADMIN_API,
        }, overwrite=False)
        source = self.start_compute(
            hostname='test_compute0', cell_name='cell1',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=0))
        dest = self.start_compute(
            hostname='test_compute1', cell_name='cell2',
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=0))
        flavor = self._create_flavor(extra_spec={
            'pci_passthrough:alias': '%s:1' % self.PFS_ALIAS_NAME,
        })
        server = self._create_server(
            flavor_id=flavor, networks='none', host=source)
        self.assert_pci_inventory(source, total=2, free=1)

        # FIXME(gibi): The cold-migrate API does not load pci_requests. Copying
        # only loaded fields loses them, and Instance.create sets
        # pci_devices=None.
        # Migration fails during destination preparation
        # leaving the server running on the source.
        # This is https://bugs.launchpad.net/nova/+bug/2168874
        self.api.post_server_action(
            server['id'], {'migrate': {'host': dest}})
        self._wait_for_action_fail_completion(
            server, 'migrate', 'conductor_migrate_server')
        self._wait_for_migration_status(server, ['error'])
        server = self.api.get_server(server['id'])
        self.assertEqual(source, server['OS-EXT-SRV-ATTR:host'])
        self.assertEqual(power_state.RUNNING, server['OS-EXT-STS:power_state'])

        with context.target_cell(
            self.ctxt, self.cell_mappings['cell2'],
        ) as ctxt:

            # FIXME(gibi): Unlike a completed claim followed by source failure,
            # this partial claim is not cleaned up by the destination periodic.
            # This is also part of https://bugs.launchpad.net/nova/+bug/2168874
            self.computes[dest].manager.update_available_resource(ctxt)

            devices = objects.PciDeviceList.get_by_instance_uuid(
                ctxt, server['id'])
            self.assertEqual(1, len(devices))
            self.assertEqual(
                fields.PciDeviceStatus.ALLOCATED, devices[0].status)

        self.assert_pci_inventory(source, total=2, free=1)
