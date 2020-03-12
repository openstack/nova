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

import mock
import os_resource_classes as orc
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import uuidutils

import nova.conf
from nova import context
from nova import objects
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


_DEFAULT_HOST = 'host1'


class VGPUTestBase(base.ServersTestBase):

    FAKE_LIBVIRT_VERSION = 5000000
    FAKE_QEMU_VERSION = 3001000

    # Since we run all computes by a single process, we need to identify which
    # current compute service we use at the moment.
    _current_host = _DEFAULT_HOST

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

        # NOTE(sbauza): Since the fake create_mdev doesn't know which compute
        # was called, we need to look at a value that can be provided just
        # before the driver calls create_mdev. That's why we fake the below
        # method for having the LibvirtDriver instance so we could modify
        # the self.current_host value.
        orig_get_vgpu_type_per_pgpu = (
            libvirt_driver.LibvirtDriver._get_vgpu_type_per_pgpu)

        def fake_get_vgpu_type_per_pgpu(_self, *args):
            # See, here we look at the hostname from the virt driver...
            self._current_host = _self._host.get_hostname()
            # ... and then we call the original method
            return orig_get_vgpu_type_per_pgpu(_self, *args)

        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_vgpu_type_per_pgpu',
             new=fake_get_vgpu_type_per_pgpu))

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
        # Here, we get the right compute thanks by the self.current_host that
        # was modified just before
        connection = self.computes[
            self._current_host].driver._host.get_connection()
        connection.mdev_info.devices.update(
            {mdev_name: fakelibvirt.FakeMdevDevice(dev_name=mdev_name,
                                                   type_id=mdev_type,
                                                   parent=libvirt_parent)})
        return uuid

    def _start_compute_service(self, hostname):
        fake_connection = self._get_connection(
            host_info=fakelibvirt.HostInfo(cpu_nodes=2, kB_mem=8192),
            # We want to create two pGPUs but no other PCI devices
            pci_info=fakelibvirt.HostPCIDevicesInfo(num_pci=0,
                                                    num_pfs=0,
                                                    num_vfs=0,
                                                    num_mdevcap=2),
            hostname=hostname)
        with mock.patch('nova.virt.libvirt.host.Host.get_connection',
                        return_value=fake_connection):
            # this method will update a self.computes dict keyed by hostname
            compute = self._start_compute(hostname)
            compute.driver._host.get_connection = lambda: fake_connection
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

    # We want to target some hosts for some created instances
    api_major_version = 'v2.1'
    ADMIN_API = True
    microversion = 'latest'

    def setUp(self):
        super(VGPUTests, self).setUp()
        extra_spec = {"resources:VGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

        # Start compute1 supporting only nvidia-11
        self.flags(
            enabled_vgpu_types=fakelibvirt.NVIDIA_11_VGPU_TYPE,
            group='devices')

        # for the sake of resizing, we need to patch the two methods below
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_instance_disk_info',
             return_value=[]))
        self.useFixture(fixtures.MockPatch('os.rename'))

        self.compute1 = self._start_compute_service(_DEFAULT_HOST)

    def assert_vgpu_usage_for_compute(self, compute, expected):
        total_usage = 0
        # We only want to get mdevs that are assigned to instances
        mdevs = compute.driver._get_all_assigned_mediated_devices()
        for mdev in mdevs:
            mdev_name = libvirt_utils.mdev_uuid2name(mdev)
            mdev_info = compute.driver._get_mediated_device_information(
                mdev_name)
            parent_name = mdev_info['parent']
            parent_rp_name = compute.host + '_' + parent_name
            parent_rp_uuid = self._get_provider_uuid_by_name(parent_rp_name)
            parent_usage = self._get_provider_usages(parent_rp_uuid)
            if orc.VGPU in parent_usage:
                total_usage += parent_usage[orc.VGPU]
        self.assertEqual(expected, len(mdevs))
        self.assertEqual(expected, total_usage)

    def test_create_servers_with_vgpu(self):
        self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, host=self.compute1.host,
            networks='auto', expected_state='ACTIVE')
        self.assert_vgpu_usage_for_compute(self.compute1, expected=1)

    def _confirm_resize(self, server, host='host1'):
        # NOTE(sbauza): Unfortunately, _cleanup_resize() in libvirt checks the
        # host option to know the source hostname but given we have a global
        # CONF, the value will be the hostname of the last compute service that
        # was created, so we need to change it here.
        # TODO(sbauza): Remove the below once we stop using CONF.host in
        # libvirt and rather looking at the compute host value.
        orig_host = CONF.host
        self.flags(host=host)
        super(VGPUTests, self)._confirm_resize(server)
        self.flags(host=orig_host)
        self._wait_for_state_change(server, 'ACTIVE')

    def test_resize_servers_with_vgpu(self):
        # Add another compute for the sake of resizing
        self.compute2 = self._start_compute_service('host2')
        server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, host=self.compute1.host,
            networks='auto', expected_state='ACTIVE')
        # Make sure we only have 1 vGPU for compute1
        self.assert_vgpu_usage_for_compute(self.compute1, expected=1)
        self.assert_vgpu_usage_for_compute(self.compute2, expected=0)

        extra_spec = {"resources:VGPU": "1"}
        new_flavor = self._create_flavor(memory_mb=4096,
                                         extra_spec=extra_spec)
        # First, resize and then revert.
        self._resize_server(server, new_flavor)
        # After resizing, we then have two vGPUs, both for each compute
        self.assert_vgpu_usage_for_compute(self.compute1, expected=1)
        self.assert_vgpu_usage_for_compute(self.compute2, expected=1)

        self._revert_resize(server)
        # We're back to the original resources usage
        self.assert_vgpu_usage_for_compute(self.compute1, expected=1)
        self.assert_vgpu_usage_for_compute(self.compute2, expected=0)

        # Now resize and then confirm it.
        self._resize_server(server, new_flavor)
        self.assert_vgpu_usage_for_compute(self.compute1, expected=1)
        self.assert_vgpu_usage_for_compute(self.compute2, expected=1)

        self._confirm_resize(server)
        # In the last case, the source guest disappeared so we only have 1 vGPU
        self.assert_vgpu_usage_for_compute(self.compute1, expected=0)
        self.assert_vgpu_usage_for_compute(self.compute2, expected=1)


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
        connection = self.computes[
            self.compute1.host].driver._host.get_connection()
        connection.pci_info = fakelibvirt.HostPCIDevicesInfo(
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
