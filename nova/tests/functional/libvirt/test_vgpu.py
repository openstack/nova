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

import collections
import os_resource_classes as orc
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import uuidutils
from oslo_utils import versionutils

from nova.compute import instance_actions
import nova.conf
from nova import context
from nova import objects
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class VGPUTestBase(base.ServersTestBase):

    # We want to target some hosts for some created instances
    api_major_version = 'v2.1'
    microversion = 'latest'
    ADMIN_API = True

    FAKE_LIBVIRT_VERSION = 7000000
    FAKE_QEMU_VERSION = 5002000

    # Since we run all computes by a single process, we need to identify which
    # current compute service we use at the moment.
    _current_host = 'host1'

    def setUp(self):
        super(VGPUTestBase, self).setUp()
        libvirt_driver.LibvirtDriver._get_local_gb_info.return_value = {
            'total': 128,
            'used': 44,
            'free': 84,
        }
        # Persistent mdevs in libvirt >= 7.3.0
        if self.FAKE_LIBVIRT_VERSION < versionutils.convert_version_to_int(
                libvirt_driver.MIN_LIBVIRT_PERSISTENT_MDEV):
            create_mdev_str = 'nova.privsep.libvirt.create_mdev'
        else:
            create_mdev_str = (
                'nova.virt.libvirt.driver.LibvirtDriver._create_mdev')
            self._create_mdev = self._create_mdev_7_3
        self.useFixture(
            fixtures.MockPatch(create_mdev_str, side_effect=self._create_mdev))

        # for the sake of resizing, we need to patch the two methods below
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_instance_disk_info',
             return_value=[]))
        self.useFixture(fixtures.MockPatch('os.rename'))

        # Allow non-admins to see instance action events.
        self.policy.set_rules({
            'os_compute_api:os-instance-actions:events': 'rule:admin_or_owner'
        }, overwrite=False)

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

    def _create_mdev_7_3(self, dev_name, mdev_type, uuid=None):
        # We need to fake the newly created sysfs object by adding a new
        # FakeMdevDevice in the existing persisted Connection object so
        # when asking to get the existing mdevs, we would see it.
        if not uuid:
            uuid = uuidutils.generate_uuid()
        mdev_name = libvirt_utils.mdev_uuid2name(uuid)
        # Here, we get the right compute thanks by the self.current_host that
        # was modified just before
        connection = self.computes[
            self._current_host].driver._host.get_connection()
        connection.mdev_info.devices.update(
            {mdev_name: fakelibvirt.FakeMdevDevice(dev_name=mdev_name,
                                                   type_id=mdev_type,
                                                   parent=dev_name)})
        return uuid

    def start_compute_with_vgpu(self, hostname, pci_info=None):
        if not pci_info:
            pci_info = fakelibvirt.HostPCIDevicesInfo(
                num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            )
        hostname = self.start_compute(
            pci_info=pci_info,
            hostname=hostname,
            libvirt_version=self.FAKE_LIBVIRT_VERSION,
            qemu_version=self.FAKE_QEMU_VERSION
        )
        compute = self.computes[hostname]
        rp_uuid = self.compute_rp_uuids[hostname]
        rp_uuids = self._get_all_rp_uuids_in_a_tree(rp_uuid)
        for rp in rp_uuids:
            inventory = self._get_provider_inventory(rp)
            if orc.VGPU in inventory:
                usage = self._get_provider_usages(rp)
                # if multiple types, the inventories are different
                self.assertIn(inventory[orc.VGPU]['total'], [8, 16])
                self.assertEqual(0, usage[orc.VGPU])
        # Since we haven't created any mdevs yet, we shouldn't find them
        self.assertEqual([], compute.driver._get_mediated_devices())
        return compute

    def _confirm_resize(self, server, host='host1'):
        # NOTE(sbauza): Unfortunately, _cleanup_resize() in libvirt checks the
        # host option to know the source hostname but given we have a global
        # CONF, the value will be the hostname of the last compute service that
        # was created, so we need to change it here.
        # TODO(sbauza): Remove the below once we stop using CONF.host in
        # libvirt and rather looking at the compute host value.
        orig_host = CONF.host
        self.flags(host=host)
        super(VGPUTestBase, self)._confirm_resize(server)
        self.flags(host=orig_host)
        self._wait_for_state_change(server, 'ACTIVE')

    def assert_mdev_usage(self, compute, expected_amount, instance=None,
                          expected_rc=orc.VGPU, expected_rp_name=None):
        """Verify the allocations for either a whole compute or just a
           specific instance.

           :param compute: the internal compute object
           :param expected_amount: the expected amount of allocations
           :param instance: if not None, a specific Instance to lookup instead
                            of the whole compute allocations.
           :param expected_rc: the expected resource class
           :param expected_rp_name: the expected resource provider name if an
                                    instance is provided.
        """
        total_usages = collections.defaultdict(int)
        # We only want to get mdevs that are assigned to either all the
        # instances or just one.
        mdevs = compute.driver._get_all_assigned_mediated_devices(instance)
        for mdev in mdevs:
            mdev_name = libvirt_utils.mdev_uuid2name(mdev)
            mdev_info = compute.driver._get_mediated_device_information(
                mdev_name)
            parent_name = mdev_info['parent']
            parent_rp_name = compute.host + '_' + parent_name
            parent_rp_uuid = self._get_provider_uuid_by_name(parent_rp_name)
            parent_usage = self._get_provider_usages(parent_rp_uuid)
            if (expected_rc in parent_usage and
                parent_rp_name not in total_usages
            ):
                # We only set the total amount if we didn't had it already
                total_usages[parent_rp_name] = parent_usage[expected_rc]
            if expected_rp_name and instance is not None:
                # If this is for an instance, all the mdevs should be in the
                # same RP.
                self.assertEqual(expected_rp_name, parent_rp_name)
        self.assertEqual(expected_amount, len(mdevs))
        self.assertEqual(expected_amount,
                         sum(total_usages[k] for k in total_usages))


class VGPUTests(VGPUTestBase):

    def setUp(self):
        super(VGPUTests, self).setUp()
        extra_spec = {"resources:VGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

        # Start compute1 supporting only nvidia-11
        self.flags(
            enabled_mdev_types=fakelibvirt.NVIDIA_11_VGPU_TYPE,
            group='devices')

        self.compute1 = self.start_compute_with_vgpu('host1')

    def assert_vgpu_usage_for_compute(self, compute, expected):
        self.assert_mdev_usage(compute, expected_amount=expected)

    def test_create_servers_with_vgpu(self):
        self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, host=self.compute1.host,
            networks='auto', expected_state='ACTIVE')
        self.assert_vgpu_usage_for_compute(self.compute1, expected=1)

    def test_resize_servers_with_vgpu(self):
        # Add another compute for the sake of resizing
        self.compute2 = self.start_compute_with_vgpu('host2')
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

    def test_multiple_instance_create(self):
        body = self._build_server(
            name=None, image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', az=None,
            host=self.compute1.host)
        # Asking to multicreate two instances, each of them asking for 1 vGPU
        body['min_count'] = 2
        # Asking to get the reservation ID so we find all the servers from it
        body['return_reservation_id'] = True
        # We ask for two servers but the API only returns the first.
        response = self.api.post_server({'server': body})
        self.assertIn('reservation_id', response)
        reservation_id = response['reservation_id']
        # Lookup servers created by the request
        servers = self.api.get_servers(detail=True,
                search_opts={'reservation_id': reservation_id})
        for server in servers:
            self._wait_for_state_change(server, 'ACTIVE')

        # Let's verify we created two mediated devices and we have a total of
        # 2 vGPUs
        self.assert_vgpu_usage_for_compute(self.compute1, expected=2)

    def test_multiple_instance_create_filling_up_capacity(self):
        # Each pGPU created by fakelibvirt defaults to a capacity of 16 vGPUs.
        # By default, we created a compute service with 2 pGPUs before, so we
        # have a total capacity of 32. In theory, we should be able to find
        # space for two instances asking for 16 vGPUs each.
        extra_spec = {"resources:VGPU": "16"}
        flavor = self._create_flavor(extra_spec=extra_spec)
        body = self._build_server(
            name=None, image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=flavor, networks='auto', az=None,
            host=self.compute1.host)
        # Asking to multicreate two instances, each of them asking for 8 vGPU
        body['min_count'] = 2
        server = self.api.post_server({'server': body})
        # But... we fail miserably because of bug #1874664
        # FIXME(sbauza): Change this once we fix the above bug
        server = self._wait_for_state_change(server, 'ERROR')
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])
        self.assertEqual('', server['hostId'])
        # Assert the "create" instance action exists and is failed.
        actions = self.api.get_instance_actions(server['id'])
        self.assertEqual(1, len(actions), actions)
        action = actions[0]
        self.assertEqual(instance_actions.CREATE, action['action'])
        self.assertEqual('Error', action['message'])
        # Get the events. There should be one with an Error result.
        action = self.api.api_get(
            '/servers/%s/os-instance-actions/%s' %
            (server['id'], action['request_id'])).body['instanceAction']
        events = action['events']
        self.assertEqual(1, len(events), events)
        event = events[0]
        self.assertEqual('conductor_schedule_and_build_instances',
                         event['event'])
        self.assertEqual('Error', event['result'])
        # Normally non-admins cannot see the event traceback but we enabled
        # that via policy in setUp so assert something was recorded.
        self.assertIn('select_destinations', event['traceback'])

    def test_create_server_with_two_vgpus_isolated(self):
        # Let's try to ask for two vGPUs with each of them be in a different
        # physical GPU.
        extra_spec = {"resources1:VGPU": "1", "resources2:VGPU": "1",
                      "group_policy": "isolate"}
        flavor = self._create_flavor(extra_spec=extra_spec)
        self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=flavor, networks='auto', host=self.compute1.host)

        # FIXME(sbauza): Unfortunately, we only accept one allocation per
        # instance by the libvirt driver as you can see in _allocate_mdevs().
        # So, eventually, we only have one vGPU for this instance.
        self.assert_mdev_usage(self.compute1, expected_amount=1)


class VGPUMultipleTypesTests(VGPUTestBase):

    def setUp(self):
        super(VGPUMultipleTypesTests, self).setUp()
        extra_spec = {"resources:VGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

        self.flags(
            enabled_mdev_types=[fakelibvirt.NVIDIA_11_VGPU_TYPE,
                                fakelibvirt.NVIDIA_12_VGPU_TYPE],
            group='devices')
        # we need to call the below again to ensure the updated
        # 'device_addresses' value is read and the new groups created
        nova.conf.devices.register_dynamic_opts(CONF)
        # host1 will have 2 physical GPUs :
        #  - 0000:81:00.0 will only support nvidia-11
        #  - 0000:81:01.0 will only support nvidia-12
        MDEVCAP_DEV1_PCI_ADDR = self.libvirt2pci_address(
            fakelibvirt.MDEVCAP_DEV1_PCI_ADDR)
        MDEVCAP_DEV2_PCI_ADDR = self.libvirt2pci_address(
            fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)
        self.flags(device_addresses=[MDEVCAP_DEV1_PCI_ADDR],
                   group='mdev_nvidia-11')
        self.flags(device_addresses=[MDEVCAP_DEV2_PCI_ADDR],
                   group='mdev_nvidia-12')

        # Prepare traits for later on
        self._create_trait('CUSTOM_NVIDIA_11')
        self._create_trait('CUSTOM_NVIDIA_12')
        self.compute1 = self.start_compute_with_vgpu('host1')

    def test_create_servers_with_vgpu(self):
        self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', host=self.compute1.host)
        mdevs = self.compute1.driver._get_mediated_devices()
        self.assertEqual(1, len(mdevs))

        # We can be deterministic : since 0000:81:01.0 is asked to only support
        # nvidia-12 *BUT* doesn't actually have this type as a PCI capability,
        # we are sure that only 0000:81:00.0 is used.
        parent_name = mdevs[0]['parent']
        self.assertEqual(fakelibvirt.MDEVCAP_DEV1_PCI_ADDR, parent_name)

        # We are also sure that there is no RP for 0000:81:01.0 since there
        # is no inventory for nvidia-12
        root_rp_uuid = self._get_provider_uuid_by_name(self.compute1.host)
        rp_uuids = self._get_all_rp_uuids_in_a_tree(root_rp_uuid)
        # We only have 2 RPs : the root RP and only the pGPU1 RP...
        self.assertEqual(2, len(rp_uuids))
        # ... but we double-check by asking the RP by its expected name
        expected_pgpu2_rp_name = (self.compute1.host + '_' +
                                  fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)
        pgpu2_rp = self.placement.get(
            '/resource_providers?name=' + expected_pgpu2_rp_name).body[
            'resource_providers']
        # See, Placement API returned no RP for this name as it doesn't exist.
        self.assertEqual([], pgpu2_rp)

    def test_create_servers_with_specific_type(self):
        # Regenerate the PCI addresses so both pGPUs now support nvidia-12
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            multiple_gpu_types=True)
        # Make a restart to update the Resource Providers
        self.compute1 = self.restart_compute_service(
            self.compute1.host, pci_info=pci_info, keep_hypervisor_state=False)
        pgpu1_rp_uuid = self._get_provider_uuid_by_name(
            self.compute1.host + '_' + fakelibvirt.MDEVCAP_DEV1_PCI_ADDR)
        pgpu2_rp_uuid = self._get_provider_uuid_by_name(
            self.compute1.host + '_' + fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)

        pgpu1_inventory = self._get_provider_inventory(pgpu1_rp_uuid)
        self.assertEqual(16, pgpu1_inventory[orc.VGPU]['total'])
        pgpu2_inventory = self._get_provider_inventory(pgpu2_rp_uuid)
        self.assertEqual(8, pgpu2_inventory[orc.VGPU]['total'])

        # Attach traits to the pGPU RPs
        self._set_provider_traits(pgpu1_rp_uuid, ['CUSTOM_NVIDIA_11'])
        self._set_provider_traits(pgpu2_rp_uuid, ['CUSTOM_NVIDIA_12'])

        expected = {'CUSTOM_NVIDIA_11': fakelibvirt.MDEVCAP_DEV1_PCI_ADDR,
                    'CUSTOM_NVIDIA_12': fakelibvirt.MDEVCAP_DEV2_PCI_ADDR}

        for trait in expected.keys():
            # Add a trait to the flavor
            extra_spec = {"resources:VGPU": "1",
                          "trait:%s" % trait: "required"}
            flavor = self._create_flavor(extra_spec=extra_spec)

            # Use the new flavor for booting
            server = self._create_server(
                image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
                flavor_id=flavor, networks='auto', host=self.compute1.host)

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


class VGPULimitMultipleTypesTests(VGPUTestBase):

    def setUp(self):
        super(VGPULimitMultipleTypesTests, self).setUp()
        extra_spec = {"resources:VGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

        self.flags(
            enabled_mdev_types=[fakelibvirt.NVIDIA_11_VGPU_TYPE,
                                fakelibvirt.NVIDIA_12_VGPU_TYPE],
            group='devices')
        # we need to call the below again to ensure the updated
        # 'device_addresses' value is read and the new groups created
        nova.conf.devices.register_dynamic_opts(CONF)
        # host1 will have 2 physical GPUs :
        #  - 0000:81:00.0 will only support nvidia-11
        #  - 0000:81:01.0 will only support nvidia-12
        MDEVCAP_DEV1_PCI_ADDR = self.libvirt2pci_address(
            fakelibvirt.MDEVCAP_DEV1_PCI_ADDR)
        MDEVCAP_DEV2_PCI_ADDR = self.libvirt2pci_address(
            fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)
        self.flags(device_addresses=[MDEVCAP_DEV1_PCI_ADDR],
                   group='mdev_nvidia-11')
        self.flags(device_addresses=[MDEVCAP_DEV2_PCI_ADDR],
                   group='mdev_nvidia-12')

        # Start the compute by supporting both types
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            multiple_gpu_types=True)
        self.compute1 = self.start_compute_with_vgpu('host1', pci_info)

    def test_create_servers_with_vgpu(self):
        physdev1_rp_uuid = self._get_provider_uuid_by_name(
            self.compute1.host + '_' + fakelibvirt.MDEVCAP_DEV1_PCI_ADDR)
        physdev2_rp_uuid = self._get_provider_uuid_by_name(
            self.compute1.host + '_' + fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)

        # Just for asserting the inventories we currently have.
        physdev1_inventory = self._get_provider_inventory(physdev1_rp_uuid)
        self.assertEqual(16, physdev1_inventory[orc.VGPU]['total'])
        physdev2_inventory = self._get_provider_inventory(physdev2_rp_uuid)
        self.assertEqual(8, physdev2_inventory[orc.VGPU]['total'])

        # Now, let's limit the capacity for the first type to 2
        self.flags(max_instances=2, group='mdev_nvidia-11')
        # Make a restart to update the Resource Providers
        self.compute2 = self.restart_compute_service('host1')
        # Make sure we can still create an instance
        server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', host=self.compute1.host)
        mdevs = self.compute1.driver._get_mediated_devices()
        self.assertEqual(1, len(mdevs))

        # ... but actually looking at Placement, only now the 2nd GPU can be
        # used because nvidia-11 was limited to 2 while the GPU supporting it
        # was having a 8th capacity.
        physdev2_inventory = self._get_provider_inventory(physdev2_rp_uuid)
        self.assertEqual(8, physdev2_inventory[orc.VGPU]['total'])

        # Get the instance we just created
        inst = objects.Instance.get_by_uuid(self.context, server['id'])
        expected_rp_name = (self.compute1.host + '_' +
                            fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)
        # Yes, indeed we use the 2nd GPU
        self.assert_mdev_usage(self.compute1, expected_amount=1,
                                   expected_rc=orc.VGPU, instance=inst,
                                   expected_rp_name=expected_rp_name)
        # ... and what happened to the first GPU inventory ? Well, the whole
        # Resource Provider disappeared !
        provider = self._get_resource_provider_by_uuid(physdev1_rp_uuid)
        self.assertEqual(404, provider['errors'][0]['status'])
        self.assertIn(
            "No resource provider with uuid %s found" % physdev1_rp_uuid,
            provider['errors'][0]['detail'])


class VGPULiveMigrationTests(base.LibvirtMigrationMixin, VGPUTestBase):

    # Use the right minimum versions for live-migration
    FAKE_LIBVIRT_VERSION = 8006000
    FAKE_QEMU_VERSION = 8001000

    def setUp(self):
        # Prepares two computes (src and dst), each of them having two GPUs
        # (81:00.0 and 81:01.0) with two types but where the operator only
        # wants to supports nvidia-11 by 81:00.0 and nvidia-12 by 81:01.0
        super(VGPULiveMigrationTests, self).setUp()

        # Let's set the configuration correctly.
        self.flags(
            enabled_mdev_types=[fakelibvirt.NVIDIA_11_VGPU_TYPE,
                                fakelibvirt.NVIDIA_12_VGPU_TYPE],
            group='devices')
        # we need to call the below again to ensure the updated
        # 'device_addresses' value is read and the new groups created
        nova.conf.devices.register_dynamic_opts(CONF)
        MDEVCAP_DEV1_PCI_ADDR = self.libvirt2pci_address(
            fakelibvirt.MDEVCAP_DEV1_PCI_ADDR)
        MDEVCAP_DEV2_PCI_ADDR = self.libvirt2pci_address(
            fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)
        self.flags(device_addresses=[MDEVCAP_DEV1_PCI_ADDR],
                   group='mdev_nvidia-11')
        self.flags(device_addresses=[MDEVCAP_DEV2_PCI_ADDR],
                   group='mdev_nvidia-12')

        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            multiple_gpu_types=True)
        self.src = self.start_compute_with_vgpu('src', pci_info=pci_info)
        self.dest = self.start_compute_with_vgpu('dest', pci_info=pci_info)

        # Add the custom traits to the 4 resource providers (two per host as
        # we have two pGPUs)
        self._create_trait('CUSTOM_NVIDIA_11')
        self._create_trait('CUSTOM_NVIDIA_12')
        for host in [self.src.host, self.dest.host]:
            nvidia11_rp_uuid = self._get_provider_uuid_by_name(
                host + '_' + fakelibvirt.MDEVCAP_DEV1_PCI_ADDR)
            nvidia12_rp_uuid = self._get_provider_uuid_by_name(
                host + '_' + fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)
            self._set_provider_traits(nvidia11_rp_uuid, ['CUSTOM_NVIDIA_11'])
            self._set_provider_traits(nvidia12_rp_uuid, ['CUSTOM_NVIDIA_12'])

        # We will test to live-migrate an instance using nvidia-11 type.
        extra_spec = {"resources:VGPU": "1",
                      "trait:CUSTOM_NVIDIA_11": "required"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

    def test_live_migration_fails_on_old_source(self):
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            multiple_gpu_types=True)
        self.src = self.restart_compute_service(
            self.src.host,
            pci_info=pci_info,
            keep_hypervisor_state=False,
            qemu_version=8000000,
            libvirt_version=8005000)
        server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', host=self.src.host)
        # now live migrate that server
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._live_migrate,
            server, 'completed')

        self.assertEqual(500, ex.response.status_code)
        self.assertIn('NoValidHost', str(ex))
        log_out = self.stdlog.logger.output
        self.assertIn('Migration pre-check error: Unable to migrate %s: '
                      'Either libvirt or QEMU version for compute service '
                      'source are too old than the supported ones '
                      '' % server['id'], log_out)

    def test_live_migration_fails_on_old_destination(self):
        # For the fact to testing that we look at the dest object, we need to
        # skip the verification for whether the destination HV version is older
        self.flags(skip_hypervisor_version_check_on_lm=True,
                   group='workarounds')
        pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            multiple_gpu_types=True)
        self.dest = self.restart_compute_service(
            self.dest.host,
            pci_info=pci_info,
            keep_hypervisor_state=False,
            qemu_version=8000000,
            libvirt_version=8005000)
        server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', host=self.src.host)
        # now live migrate that server
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._live_migrate,
            server, 'completed')

        self.assertEqual(500, ex.response.status_code)
        self.assertIn('NoValidHost', str(ex))
        log_out = self.stdlog.logger.output
        self.assertIn('Migration pre-check error: Unable to migrate %s: '
                      'Either libvirt or QEMU version for compute service '
                      'target are too old than the supported ones '
                      '' % server['id'],
                      log_out)

    def test_live_migration_fails_due_to_non_supported_mdev_types(self):
        self.flags(
            enabled_mdev_types=[fakelibvirt.NVIDIA_11_VGPU_TYPE],
            group='devices')
        self.src = self.restart_compute_service(self.src.host)
        self.flags(
            enabled_mdev_types=[fakelibvirt.NVIDIA_12_VGPU_TYPE],
            group='devices')
        self.dest = self.restart_compute_service(self.dest.host)
        # Force a periodic run in order to make sure all service resources
        # are changed before we call create_service()
        self._run_periodics()
        self.server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', host=self.src.host)
        # now live migrate that server
        ex = self.assertRaises(
            client.OpenStackApiException,
            self._live_migrate,
            self.server, 'completed')
        self.assertEqual(500, ex.response.status_code)
        self.assertIn('NoValidHost', str(ex))
        log_out = self.stdlog.logger.output
        # The log is fully JSON-serialized, so just check the phrase.
        self.assertIn('Unable to migrate %s: ' % self.server['id'], log_out)
        self.assertIn('Source mdev types ', log_out)
        self.assertIn('are not supported by this compute : ', log_out)

    def test_live_migrate_server(self):
        self.server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', host=self.src.host)
        inst = objects.Instance.get_by_uuid(self.context, self.server['id'])
        mdevs = self.src.driver._get_all_assigned_mediated_devices(inst)
        self.assertEqual(1, len(mdevs))
        self._live_migrate(self.server, 'completed')
        # Now the destination XML is updated, so the destination mdev is
        # correctly used.
        self.assert_mdev_usage(self.dest, 1)


class VGPULiveMigrationTestsLMFailed(VGPULiveMigrationTests):
    """Tests that expect the live migration to fail, and exist to test the
    rollback code. Stubs out fakelibvirt's migrateToURI3() with a stub that
    "fails" the migration.
    """

    def _migrate_stub(self, domain, destination, params, flags):
        """Designed to stub fakelibvirt's migrateToURI3 and "fail" the
        live migration by monkeypatching jobStats() to return an error.
        """

        # During the migration, we reserved a mdev in the dest
        self.assert_mdev_usage(self.src, 1)
        self.assert_mdev_usage(self.dest, 1)

        # The resource update periodic task should not change the consumed
        # mdevs, as the migration is still happening. As usual, running
        # periodics is not necessary to make the test pass, but it's good to
        # make sure it does the right thing.
        self._run_periodics()
        self.assert_mdev_usage(self.src, 1)
        self.assert_mdev_usage(self.dest, 1)

        source = self.computes['src']
        conn = source.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        dom.fail_job()
        self.migrate_stub_ran = True

    def test_live_migrate_server(self):
        self.server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', host=self.src.host)
        inst = objects.Instance.get_by_uuid(self.context, self.server['id'])
        mdevs = self.src.driver._get_all_assigned_mediated_devices(inst)
        self.assertEqual(1, len(mdevs))

        self._live_migrate(self.server, 'failed')

        # We released the reserved mdev after the migration failed.
        self.assert_mdev_usage(self.src, 1)
        self.assert_mdev_usage(self.dest, 0)


class DifferentMdevClassesTests(VGPUTestBase):

    def setUp(self):
        super(DifferentMdevClassesTests, self).setUp()
        self.extra_spec = {"resources:CUSTOM_NOTVGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=self.extra_spec)

        self.flags(
            enabled_mdev_types=[fakelibvirt.MLX5_CORE_TYPE,
                                fakelibvirt.NVIDIA_12_VGPU_TYPE],
            group='devices')
        # we need to call the below again to ensure the updated
        # 'device_addresses' value is read and the new groups created
        nova.conf.devices.register_dynamic_opts(CONF)
        # host1 will have 2 physical devices :
        #  - 0000:81:00.0 will only support mlx5_core
        #  - 0000:81:01.0 will only support nvidia-12
        MDEVCAP_DEV1_PCI_ADDR = self.libvirt2pci_address(
            fakelibvirt.MDEVCAP_DEV1_PCI_ADDR)
        MDEVCAP_DEV2_PCI_ADDR = self.libvirt2pci_address(
            fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)
        self.flags(device_addresses=[MDEVCAP_DEV1_PCI_ADDR],
                   group='mdev_mlx5_core')
        self.flags(device_addresses=[MDEVCAP_DEV2_PCI_ADDR],
                   group='mdev_nvidia-12')
        self.flags(mdev_class='CUSTOM_NOTVGPU', group='mdev_mlx5_core')

        self.compute1 = self.start_compute_with_vgpu('host1')
        # Regenerate the PCI addresses so they can support both mlx5 and
        # nvidia-12 types
        connection = self.computes[
            self.compute1.host].driver._host.get_connection()
        connection.pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            generic_types=True)
        # Make a restart to update the Resource Providers
        self.compute1 = self.restart_compute_service('host1')

    def test_create_servers_with_different_mdev_classes(self):
        physdev1_rp_uuid = self._get_provider_uuid_by_name(
            self.compute1.host + '_' + fakelibvirt.MDEVCAP_DEV1_PCI_ADDR)
        physdev2_rp_uuid = self._get_provider_uuid_by_name(
            self.compute1.host + '_' + fakelibvirt.MDEVCAP_DEV2_PCI_ADDR)

        # Remember, we asked to create 1st device inventory to use a
        # CUSTOM_NOTVGPU RC.
        physdev1_inventory = self._get_provider_inventory(physdev1_rp_uuid)
        self.assertEqual(16, physdev1_inventory['CUSTOM_NOTVGPU']['total'])
        # But, we didn't ask for the second device inventory...
        physdev2_inventory = self._get_provider_inventory(physdev2_rp_uuid)
        self.assertEqual(8, physdev2_inventory[orc.VGPU]['total'])

        expected = {'CUSTOM_NOTVGPU': fakelibvirt.MDEVCAP_DEV1_PCI_ADDR,
                    orc.VGPU: fakelibvirt.MDEVCAP_DEV2_PCI_ADDR}

        for mdev_rc in expected.keys():
            # Use a specific mdev resource class for the flavor
            extra_spec = {"resources:%s" % mdev_rc: "1"}
            flavor = self._create_flavor(extra_spec=extra_spec)

            # Use the new flavor for booting
            server = self._create_server(
                image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
                flavor_id=flavor, networks='auto', host=self.compute1.host)

            # Get the instance we just created
            inst = objects.Instance.get_by_uuid(self.context, server['id'])
            expected_rp_name = self.compute1.host + '_' + expected[mdev_rc]
            self.assert_mdev_usage(self.compute1, expected_amount=1,
                                   expected_rc=mdev_rc, instance=inst,
                                   expected_rp_name=expected_rp_name)

    def test_resize_servers_with_mlx5(self):
        # Add another compute for the sake of resizing
        self.compute2 = self.start_compute_with_vgpu('host2')
        # Regenerate the PCI addresses so they can support both mlx5 and
        # nvidia-12 types
        connection = self.computes[
            self.compute2.host].driver._host.get_connection()
        connection.pci_info = fakelibvirt.HostPCIDevicesInfo(
            num_pci=0, num_pfs=0, num_vfs=0, num_mdevcap=2,
            generic_types=True)
        # Make a restart to update the Resource Providers
        self.compute2 = self.restart_compute_service('host2')

        # Use the new flavor for booting
        server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, networks='auto', host=self.compute1.host)

        # Make sure we only have 1 mdev for compute1
        self.assert_mdev_usage(self.compute1, expected_amount=1,
                               expected_rc='CUSTOM_NOTVGPU')
        self.assert_mdev_usage(self.compute2, expected_amount=0,
                               expected_rc='CUSTOM_NOTVGPU')

        new_flavor = self._create_flavor(memory_mb=4096,
                                         extra_spec=self.extra_spec)
        # First, resize and then revert.
        self._resize_server(server, new_flavor)
        # After resizing, we then have two mdevs, both for each compute
        self.assert_mdev_usage(self.compute1, expected_amount=1,
                               expected_rc='CUSTOM_NOTVGPU')
        self.assert_mdev_usage(self.compute2, expected_amount=1,
                               expected_rc='CUSTOM_NOTVGPU')

        self._revert_resize(server)
        # We're back to the original resources usage
        self.assert_mdev_usage(self.compute1, expected_amount=1,
                               expected_rc='CUSTOM_NOTVGPU')
        self.assert_mdev_usage(self.compute2, expected_amount=0,
                               expected_rc='CUSTOM_NOTVGPU')

        # Now resize and then confirm it.
        self._resize_server(server, new_flavor)
        self.assert_mdev_usage(self.compute1, expected_amount=1,
                               expected_rc='CUSTOM_NOTVGPU')
        self.assert_mdev_usage(self.compute2, expected_amount=1,
                               expected_rc='CUSTOM_NOTVGPU')

        self._confirm_resize(server)
        # In the last case, the source guest disappeared so we only have 1 mdev
        self.assert_mdev_usage(self.compute1, expected_amount=0,
                               expected_rc='CUSTOM_NOTVGPU')
        self.assert_mdev_usage(self.compute2, expected_amount=1,
                               expected_rc='CUSTOM_NOTVGPU')


class VGPUTestsLibvirt7_3(VGPUTests):

    # Minimum version supporting persistent mdevs is 7.3.0.
    # https://libvirt.org/drvnodedev.html#mediated-devices-mdevs
    FAKE_LIBVIRT_VERSION = 7003000
