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

import fixtures
import re

import os_resource_classes as orc
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import uuidutils

import nova.conf
from nova import context
from nova import objects
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class VGPUTestBase(base.ServersTestBase):

    FAKE_LIBVIRT_VERSION = 5000000
    FAKE_QEMU_VERSION = 3001000

    def setUp(self):
        super(VGPUTestBase, self).setUp()
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_local_gb_info',
            return_value={'total': 128,
                          'used': 44,
                          'free': 84}))
        self.useFixture(fixtures.MockPatch(
            'nova.privsep.libvirt.create_mdev',
            side_effect=self._create_mdev))
        self.context = context.get_admin_context()

    def pci2libvirt_address(self, address):
        return "pci_{}_{}_{}_{}".format(*re.split("[.:]", address))

    def libvirt2pci_address(self, dev_name):
        return "{}:{}:{}.{}".format(*dev_name[4:].split('_'))

    def _create_mdev(self, physical_device, mdev_type, uuid=None):
        # We need to fake the newly created sysfs object by adding a new
        # FakeMdevDevice in the existing persisted Connection object so
        # when asking to get the existing mdevs, we would see it.
        if not uuid:
            uuid = uuidutils.generate_uuid()
        mdev_name = libvirt_utils.mdev_uuid2name(uuid)
        libvirt_parent = self.pci2libvirt_address(physical_device)
        self.fake_connection.mdev_info.devices.update(
            {mdev_name: fakelibvirt.FakeMdevDevice(dev_name=mdev_name,
                                                   type_id=mdev_type,
                                                   parent=libvirt_parent)})
        return uuid

    def _start_compute_service(self, hostname):
        self.fake_connection = self._get_connection(
            host_info=fakelibvirt.HostInfo(cpu_nodes=2, kB_mem=8192),
            # We want to create two pGPUs but no other PCI devices
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=0,
                                                    num_pfs=0,
                                                    num_vfs=0,
                                                    num_mdevcap=2),
            hostname=hostname)

        self.mock_conn.return_value = self.fake_connection
        compute = self.start_service('compute', host=hostname)
        rp_uuid = self._get_provider_uuid_by_name(hostname)
        rp_uuids = self._get_all_rp_uuids_in_a_tree(rp_uuid)
        for rp in rp_uuids:
            inventory = self._get_provider_inventory(rp)
            if orc.VGPU in inventory:
                usage = self._get_provider_usages(rp)
                self.assertEqual(16, inventory[orc.VGPU]['total'])
                self.assertEqual(0, usage[orc.VGPU])
        # Since we haven't created any mdevs yet, we shouldn't find them
        self.assertEqual([], compute.driver._get_mediated_devices())
        return compute


class VGPUTests(VGPUTestBase):

    def setUp(self):
        super(VGPUTests, self).setUp()
        extra_spec = {"resources:VGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

        # Start compute1 supporting only nvidia-11
        self.flags(
            enabled_vgpu_types=fakelibvirt.NVIDIA_11_VGPU_TYPE,
            group='devices')
        self.compute1 = self._start_compute_service('host1')

    def test_create_servers_with_vgpu(self):
        self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, host=self.compute1.host,
            expected_state='ACTIVE')
        # Now we should find a new mdev
        mdevs = self.compute1.driver._get_mediated_devices()
        self.assertEqual(1, len(mdevs))

        # Checking also the allocations for the parent pGPU
        parent_name = mdevs[0]['parent']
        parent_rp_name = self.compute1.host + '_' + parent_name
        parent_rp_uuid = self._get_provider_uuid_by_name(parent_rp_name)
        usage = self._get_provider_usages(parent_rp_uuid)
        self.assertEqual(1, usage[orc.VGPU])


class VGPUMultipleTypesTests(VGPUTestBase):

    def setUp(self):
        super(VGPUMultipleTypesTests, self).setUp()
        extra_spec = {"resources:VGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

        self.flags(
            enabled_vgpu_types=[fakelibvirt.NVIDIA_11_VGPU_TYPE,
                                fakelibvirt.NVIDIA_12_VGPU_TYPE],
            group='devices')
        # we need to call the below again to ensure the updated
        # 'device_addresses' value is read and the new groups created
        nova.conf.devices.register_dynamic_opts(CONF)
        # host1 will have 2 physical GPUs :
        #  - 0000:81:00.0 will only support nvidia-11
        #  - 0000:81:01.0 will only support nvidia-12
        pgpu1_pci_addr = self.libvirt2pci_address(fakelibvirt.PGPU1_PCI_ADDR)
        pgpu2_pci_addr = self.libvirt2pci_address(fakelibvirt.PGPU2_PCI_ADDR)
        self.flags(device_addresses=[pgpu1_pci_addr], group='vgpu_nvidia-11')
        self.flags(device_addresses=[pgpu2_pci_addr], group='vgpu_nvidia-12')

        # Prepare traits for later on
        self._create_trait('CUSTOM_NVIDIA_11')
        self._create_trait('CUSTOM_NVIDIA_12')
        self.compute1 = self._start_compute_service('host1')

    def test_create_servers_with_vgpu(self):
        self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, host=self.compute1.host,
            expected_state='ACTIVE')
        mdevs = self.compute1.driver._get_mediated_devices()
        self.assertEqual(1, len(mdevs))

        # We can be deterministic : since 0000:81:01.0 is asked to only support
        # nvidia-12 *BUT* doesn't actually have this type as a PCI capability,
        # we are sure that only 0000:81:00.0 is used.
        parent_name = mdevs[0]['parent']
        self.assertEqual(fakelibvirt.PGPU1_PCI_ADDR, parent_name)

        # We are also sure that there is no RP for 0000:81:01.0 since there
        # is no inventory for nvidia-12
        root_rp_uuid = self._get_provider_uuid_by_name(self.compute1.host)
        rp_uuids = self._get_all_rp_uuids_in_a_tree(root_rp_uuid)
        # We only have 2 RPs : the root RP and only the pGPU1 RP...
        self.assertEqual(2, len(rp_uuids))
        # ... but we double-check by asking the RP by its expected name
        expected_pgpu2_rp_name = (self.compute1.host + '_' +
                                  fakelibvirt.PGPU2_PCI_ADDR)
        pgpu2_rp = self.placement_api.get(
            '/resource_providers?name=' + expected_pgpu2_rp_name).body[
            'resource_providers']
        # See, Placement API returned no RP for this name as it doesn't exist.
        self.assertEqual([], pgpu2_rp)

    def test_create_servers_with_specific_type(self):
        # Regenerate the PCI addresses so both pGPUs now support nvidia-12
        self.fake_connection.pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            multiple_gpu_types=True)
        # Make a restart to update the Resource Providers
        self.compute1 = self.restart_compute_service(self.compute1)
        pgpu1_rp_uuid = self._get_provider_uuid_by_name(
            self.compute1.host + '_' + fakelibvirt.PGPU1_PCI_ADDR)
        pgpu2_rp_uuid = self._get_provider_uuid_by_name(
            self.compute1.host + '_' + fakelibvirt.PGPU2_PCI_ADDR)

        pgpu1_inventory = self._get_provider_inventory(pgpu1_rp_uuid)
        self.assertEqual(16, pgpu1_inventory[orc.VGPU]['total'])
        pgpu2_inventory = self._get_provider_inventory(pgpu2_rp_uuid)
        self.assertEqual(8, pgpu2_inventory[orc.VGPU]['total'])

        # Attach traits to the pGPU RPs
        self._set_provider_traits(pgpu1_rp_uuid, ['CUSTOM_NVIDIA_11'])
        self._set_provider_traits(pgpu2_rp_uuid, ['CUSTOM_NVIDIA_12'])

        expected = {'CUSTOM_NVIDIA_11': fakelibvirt.PGPU1_PCI_ADDR,
                    'CUSTOM_NVIDIA_12': fakelibvirt.PGPU2_PCI_ADDR}

        for trait in expected.keys():
            # Add a trait to the flavor
            extra_spec = {"resources:VGPU": "1",
                          "trait:%s" % trait: "required"}
            flavor = self._create_flavor(extra_spec=extra_spec)

            # Use the new flavor for booting
            server = self._create_server(
                image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
                flavor_id=flavor, host=self.compute1.host,
                expected_state='ACTIVE')

            # Get the instance we just created
            inst = objects.Instance.get_by_uuid(self.context, server['id'])
            # Get the mdevs that were allocated for this instance, we should
            # only have one
            mdevs = self.compute1.driver._get_all_assigned_mediated_devices(
                inst)
            self.assertEqual(1, len(mdevs))

            # It's a dict of mdev_uuid/instance_uuid pairs, we only care about
            # the keys
            mdevs = list(mdevs.keys())
            # Now get the detailed information about this single mdev
            mdev_info = self.compute1.driver._get_mediated_device_information(
                libvirt_utils.mdev_uuid2name(mdevs[0]))

            # We can be deterministic : since we asked for a specific type,
            # we know which pGPU we landed.
            self.assertEqual(expected[trait], mdev_info['parent'])
