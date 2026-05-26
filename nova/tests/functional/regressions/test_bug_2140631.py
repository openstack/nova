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
"""Regression test for bug 2140631.

When using unified limits, the quota check does NOT include PCI device
resource classes from the flavor's pci_passthrough:alias extra spec,
neutron port bandwidth resources (NET_BW_IGR_KILOBIT_PER_SEC,
NET_BW_EGR_KILOBIT_PER_SEC), or cyborg device profile resources (FPGA).
This is because the RequestSpec used for limits is built from just the
flavor without including these additional resource requests.

https://bugs.launchpad.net/nova/+bug/2140631
"""
from oslo_limit import fixture as limit_fixture

from nova.limit import local as local_limit
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_pci_in_placement
from nova.tests.functional import test_servers
from nova.tests.functional import test_servers_resource_request


class TestBug2140631PCI(test_pci_in_placement.PlacementPCIReportingTests):
    """Regression test for bug 2140631.

    Test that unified limits quota checking includes PCI resource classes
    from the flavor's pci_passthrough:alias extra spec when pci_in_placement
    is enabled.
    """

    PCI_DEVICE_SPEC = []
    PCI_ALIAS = []

    def setUp(self):
        super().setUp()
        # Enable PCI in placement for scheduling
        self.flags(group='filter_scheduler', pci_in_placement=True)
        # Enable unified limits quota driver
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")

    def test_pci_resource_class_limit_not_enforced(self):
        """Test that PCI resource class limits are not enforced.

        Scenario:
        1. Configure 2 PCI devices with resource class CUSTOM_GPU
        2. Set unified limit of 1 for class:CUSTOM_GPU
        3. Create flavor requesting 2 GPUs via pci_passthrough:alias
        4. Attempt to create server

        Expected (when fixed): 403 error mentioning class:CUSTOM_GPU
        Current (buggy): Server succeeds because quota is not checked
        """
        # Configure PCI devices with custom resource class
        device_spec = self._to_list_of_json_str([{
            "vendor_id": fakelibvirt.PCI_VEND_ID,
            "product_id": fakelibvirt.PCI_PROD_ID,
            "resource_class": "CUSTOM_GPU"}])
        self.flags(group='pci', device_spec=device_spec)

        # Configure PCI alias
        pci_alias = self._to_list_of_json_str([{
            "name": "a-gpu",
            "resource_class": "CUSTOM_GPU"}])
        self.flags(group='pci', alias=pci_alias)

        # Create compute with 2 PCI devices
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=2, num_pfs=0, num_vfs=0)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        # Verify PCI devices are in placement
        self.assert_placement_pci_view(
            "compute1",
            inventories={
                "0000:81:00.0": {"CUSTOM_GPU": 1},
                "0000:81:01.0": {"CUSTOM_GPU": 1}},
            traits={
                "0000:81:00.0": [],
                "0000:81:01.0": []},
            usages={
                "0000:81:00.0": {"CUSTOM_GPU": 0},
                "0000:81:01.0": {"CUSTOM_GPU": 0}},
            allocations={})

        # Set up unified limits - limit to 1 GPU per project
        reglimits = {
            local_limit.SERVER_METADATA_ITEMS: 128,
            local_limit.INJECTED_FILES: 5,
            local_limit.INJECTED_FILES_CONTENT: 10 * 1024,
            local_limit.INJECTED_FILES_PATH: 255,
            local_limit.KEY_PAIRS: 100,
            local_limit.SERVER_GROUPS: 10,
            local_limit.SERVER_GROUP_MEMBERS: 10,
            'servers': 10,
            'class:VCPU': 100,
            'class:MEMORY_MB': 100000,
            'class:DISK_GB': 1000,
            'class:CUSTOM_GPU': 1  # Limit to 1 GPU
        }
        self.useFixture(limit_fixture.LimitFixture(reglimits, {}))

        # Create flavor requesting 2 GPUs - exceeds quota
        extra_spec = {"pci_passthrough:alias": "a-gpu:2"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        # BUG: This should fail with 403 (quota exceeded) but succeeds because
        # the unified limits check does not include PCI resource classes.
        server = self._create_server(flavor_id=flavor_id, networks=[])
        self._wait_for_state_change(server, 'ACTIVE')

    def test_pci_resource_class_limit_not_enforced_multi(self):
        """Test PCI limits when multiple instances exceed quota.

        Scenario:
        1. Configure 2 PCI devices with custom resource class
        2. Set project limit of 1 for the PCI resource class
        3. Create first server with 1 PCI device - succeeds
        4. Create second server with 1 PCI device - should fail with 403

        Expected (when fixed): Second server rejected with 403
        Current (buggy): Second server succeeds
        """
        # Configure 2 PCI devices with custom resource class
        device_spec = self._to_list_of_json_str([{
            "vendor_id": fakelibvirt.PCI_VEND_ID,
            "product_id": fakelibvirt.PCI_PROD_ID,
            "resource_class": "CUSTOM_GPU"}])
        self.flags(group='pci', device_spec=device_spec)

        pci_alias = self._to_list_of_json_str([{
            "name": "a-gpu",
            "resource_class": "CUSTOM_GPU"}])
        self.flags(group='pci', alias=pci_alias)

        # Create compute with 2 PCI devices
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=2, num_pfs=0, num_vfs=0)
        self.start_compute(hostname="compute1", pci_info=pci_info)

        # Set project limit to 1 GPU
        reglimits = {
            local_limit.SERVER_METADATA_ITEMS: 128,
            local_limit.INJECTED_FILES: 5,
            local_limit.INJECTED_FILES_CONTENT: 10 * 1024,
            local_limit.INJECTED_FILES_PATH: 255,
            local_limit.KEY_PAIRS: 100,
            local_limit.SERVER_GROUPS: 10,
            local_limit.SERVER_GROUP_MEMBERS: 10,
            'servers': 10,
            'class:VCPU': 100,
            'class:MEMORY_MB': 100000,
            'class:DISK_GB': 1000,
            'class:CUSTOM_GPU': 1
        }
        self.useFixture(limit_fixture.LimitFixture(reglimits, {}))

        # Create flavor requesting 1 PCI device
        extra_spec = {"pci_passthrough:alias": "a-gpu:1"}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        # First server should succeed
        server1 = self._create_server(flavor_id=flavor_id, networks=[])
        self._wait_for_state_change(server1, 'ACTIVE')

        # Verify 1 GPU is now in use
        self.assertPCIDeviceCounts('compute1', total=2, free=1)

        # BUG: Second server should fail with 403 (quota exceeded) but
        # succeeds because the unified limits check does not include PCI
        # resource classes.
        server2 = self._create_server(flavor_id=flavor_id, networks=[])
        self._wait_for_state_change(server2, 'ACTIVE')

        # Both GPUs used - exceeds quota of 1
        self.assertPCIDeviceCounts('compute1', total=2, free=0)


class TestBug2140631Bandwidth(
    test_servers_resource_request.PortResourceRequestBasedSchedulingTestBase
):
    """Regression test for bug 2140631 - bandwidth resources.

    Test that unified limits quota checking includes neutron port bandwidth
    resources (NET_BW_IGR_KILOBIT_PER_SEC, NET_BW_EGR_KILOBIT_PER_SEC) from
    ports with resource_request.
    """

    def setUp(self):
        super().setUp()
        # Enable unified limits quota driver
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")

    def test_bandwidth_resource_limit_not_enforced(self):
        """Test that bandwidth resource limits are not enforced.

        Scenario:
        1. The base class sets up SRIOV networking RPs with bandwidth
           inventory (10000 each)
        2. Set unified limit of 1 for NET_BW_IGR_KILOBIT_PER_SEC and
           NET_BW_EGR_KILOBIT_PER_SEC
        3. Create server with SRIOV port requesting 10000 each
        4. Server succeeds despite exceeding the quota

        Expected (when fixed): 403 error
        Current (buggy): Server succeeds
        """
        # Set up unified limits - bandwidth set very low
        reglimits = {
            local_limit.SERVER_METADATA_ITEMS: 128,
            local_limit.INJECTED_FILES: 5,
            local_limit.INJECTED_FILES_CONTENT: 10 * 1024,
            local_limit.INJECTED_FILES_PATH: 255,
            local_limit.KEY_PAIRS: 100,
            local_limit.SERVER_GROUPS: 10,
            local_limit.SERVER_GROUP_MEMBERS: 10,
            'servers': 10,
            'class:VCPU': 100,
            'class:MEMORY_MB': 100000,
            'class:DISK_GB': 1000,
            # Port requests 10000 each but limit is 1
            'class:NET_BW_IGR_KILOBIT_PER_SEC': 1,
            'class:NET_BW_EGR_KILOBIT_PER_SEC': 1
        }
        self.useFixture(limit_fixture.LimitFixture(reglimits, {}))

        sriov_port = self.neutron.port_with_sriov_resource_request

        # BUG: This should fail with 403 (quota exceeded) but succeeds because
        # the unified limits check does not include port bandwidth resources.
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[{'port': sriov_port['id']}])
        self._wait_for_state_change(server, 'ACTIVE')


class TestBug2140631Cyborg(test_servers.AcceleratorServerBase):
    """Regression test for bug 2140631 - cyborg resources.

    Test that unified limits quota checking includes cyborg device profile
    resources (FPGA) from the flavor's accel:device_profile extra spec.
    """

    def setUp(self):
        super().setUp()
        # Enable unified limits quota driver
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")

    def test_cyborg_resource_limit_not_enforced(self):
        """Test that cyborg resource limits are not enforced.

        Scenario:
        1. The base class sets up a device RP with FPGA inventory (total=2)
           and CUSTOM_FAKE_DEVICE trait
        2. Set unified limit of 1 for class:FPGA
        3. Create first server with 1 FPGA - succeeds
        4. Create second server with 1 FPGA - should fail with 403 but
           succeeds (bug)

        Expected (when fixed): Second server rejected with 403
        Current (buggy): Second server succeeds
        """
        # Set up unified limits - FPGA limit is 1
        reglimits = {
            local_limit.SERVER_METADATA_ITEMS: 128,
            local_limit.INJECTED_FILES: 5,
            local_limit.INJECTED_FILES_CONTENT: 10 * 1024,
            local_limit.INJECTED_FILES_PATH: 255,
            local_limit.KEY_PAIRS: 100,
            local_limit.SERVER_GROUPS: 10,
            local_limit.SERVER_GROUP_MEMBERS: 10,
            'servers': 10,
            'class:VCPU': 100,
            'class:MEMORY_MB': 100000,
            'class:DISK_GB': 1000,
            # Device profile requests 1 FPGA, limit is 1
            'class:FPGA': 1
        }
        self.useFixture(limit_fixture.LimitFixture(reglimits, {}))

        # Create flavor with accelerator device profile
        flavor_id = self._create_acc_flavor()

        # First server succeeds
        server1 = self._create_server(
            'accel_server1', flavor_id=flavor_id,
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none', expected_state='ACTIVE')
        self.assertEqual('ACTIVE', server1['status'])

        # BUG: Second server should fail with 403 (quota exceeded) but
        # succeeds because the unified limits check does not include cyborg
        # resources.
        server2 = self._create_server(
            'accel_server2', flavor_id=flavor_id,
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none', expected_state='ACTIVE')
        self.assertEqual('ACTIVE', server2['status'])
