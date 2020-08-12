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

import io
import mock

from oslo_config import cfg
from oslo_log import log as logging

from nova import context
from nova import objects
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt import utils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class VGPUReshapeTests(base.ServersTestBase):

    @mock.patch('nova.virt.libvirt.LibvirtDriver._get_local_gb_info',
                return_value={'total': 128,
                              'used': 44,
                              'free': 84})
    @mock.patch('nova.virt.libvirt.driver.libvirt_utils.is_valid_hostname',
                return_value=True)
    @mock.patch('nova.virt.libvirt.driver.libvirt_utils.file_open',
                side_effect=[io.BytesIO(b''), io.BytesIO(b''),
                             io.BytesIO(b'')])
    def test_create_servers_with_vgpu(
            self, mock_file_open, mock_valid_hostname, mock_get_fs_info):
        """Verify that vgpu reshape works with libvirt driver

        1) create two servers with an old tree where the VGPU resource is on
           the compute provider
        2) trigger a reshape
        3) check that the allocations of the servers are still valid
        4) create another server now against the new tree
        """

        # NOTE(gibi): We cannot simply ask the virt driver to create an old
        # RP tree with vgpu on the root RP as that code path does not exist
        # any more. So we have to hack a "bit". We will create a compute
        # service without vgpu support to have the compute RP ready then we
        # manually add the VGPU resources to that RP in placement. Also we make
        # sure that during the instance claim the virt driver does not detect
        # the old tree as that would be a bad time for reshape. Later when the
        # compute service is restarted the driver will do the reshape.

        mdevs = {
            'mdev_4b20d080_1b54_4048_85b3_a6a62d165c01':
                fakelibvirt.FakeMdevDevice(
                    dev_name='mdev_4b20d080_1b54_4048_85b3_a6a62d165c01',
                    type_id=fakelibvirt.NVIDIA_11_VGPU_TYPE,
                    parent=fakelibvirt.PGPU1_PCI_ADDR),
            'mdev_4b20d080_1b54_4048_85b3_a6a62d165c02':
                fakelibvirt.FakeMdevDevice(
                    dev_name='mdev_4b20d080_1b54_4048_85b3_a6a62d165c02',
                    type_id=fakelibvirt.NVIDIA_11_VGPU_TYPE,
                    parent=fakelibvirt.PGPU2_PCI_ADDR),
            'mdev_4b20d080_1b54_4048_85b3_a6a62d165c03':
                fakelibvirt.FakeMdevDevice(
                    dev_name='mdev_4b20d080_1b54_4048_85b3_a6a62d165c03',
                    type_id=fakelibvirt.NVIDIA_11_VGPU_TYPE,
                    parent=fakelibvirt.PGPU3_PCI_ADDR),
        }

        # start a compute with vgpu support disabled so the driver will
        # ignore the content of the above HostMdevDeviceInfo
        self.flags(enabled_vgpu_types='', group='devices')

        hostname = self.start_compute(
            hostname='compute1',
            mdev_info=fakelibvirt.HostMdevDevicesInfo(devices=mdevs),
        )
        self.compute = self.computes[hostname]

        # create the VGPU resource in placement manually
        compute_rp_uuid = self.placement.get(
            '/resource_providers?name=compute1').body[
            'resource_providers'][0]['uuid']
        inventories = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body
        inventories['inventories']['VGPU'] = {
            'allocation_ratio': 1.0,
            'max_unit': 3,
            'min_unit': 1,
            'reserved': 0,
            'step_size': 1,
            'total': 3}
        self.placement.put(
            '/resource_providers/%s/inventories' % compute_rp_uuid,
            inventories)

        # enabled vgpu support
        self.flags(
            enabled_vgpu_types=fakelibvirt.NVIDIA_11_VGPU_TYPE,
            group='devices')
        # We don't want to restart the compute service or it would call for
        # a reshape but we still want to accept some vGPU types so we call
        # directly the needed method
        self.compute.driver.supported_vgpu_types = (
            self.compute.driver._get_supported_vgpu_types())

        # now we boot two servers with vgpu
        extra_spec = {"resources:VGPU": 1}
        flavor_id = self._create_flavor(extra_spec=extra_spec)

        server_req = self._build_server(flavor_id=flavor_id)

        # NOTE(gibi): during instance_claim() there is a
        # driver.update_provider_tree() call that would detect the old tree and
        # would fail as this is not a good time to reshape. To avoid that we
        # temporarily mock update_provider_tree here.
        with mock.patch('nova.virt.libvirt.driver.LibvirtDriver.'
                        'update_provider_tree'):
            created_server1 = self.api.post_server({'server': server_req})
            server1 = self._wait_for_state_change(created_server1, 'ACTIVE')
            created_server2 = self.api.post_server({'server': server_req})
            server2 = self._wait_for_state_change(created_server2, 'ACTIVE')

        # Determine which device is associated with which instance
        # { inst.uuid: pgpu_name }
        inst_to_pgpu = {}
        ctx = context.get_admin_context()
        for server in (server1, server2):
            inst = objects.Instance.get_by_uuid(ctx, server['id'])
            mdevs = list(
                self.compute.driver._get_all_assigned_mediated_devices(inst))
            self.assertEqual(1, len(mdevs))
            mdev_uuid = mdevs[0]
            mdev_info = self.compute.driver._get_mediated_device_information(
                utils.mdev_uuid2name(mdev_uuid))
            inst_to_pgpu[inst.uuid] = mdev_info['parent']
        # The VGPUs should have come from different pGPUs
        self.assertNotEqual(*list(inst_to_pgpu.values()))

        # verify that the inventory, usages and allocation are correct before
        # the reshape
        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
            'inventories']
        self.assertEqual(3, compute_inventory['VGPU']['total'])
        compute_usages = self.placement.get(
            '/resource_providers/%s/usages' % compute_rp_uuid).body[
            'usages']
        self.assertEqual(2, compute_usages['VGPU'])

        for server in (server1, server2):
            allocations = self.placement.get(
                '/allocations/%s' % server['id']).body['allocations']
            # the flavor has disk=10 and ephemeral=10
            self.assertEqual(
                {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2, 'VGPU': 1},
                allocations[compute_rp_uuid]['resources'])

        # restart compute which will trigger a reshape
        self.compute = self.restart_compute_service(self.compute)

        # verify that the inventory, usages and allocation are correct after
        # the reshape
        compute_inventory = self.placement.get(
            '/resource_providers/%s/inventories' % compute_rp_uuid).body[
            'inventories']
        self.assertNotIn('VGPU', compute_inventory)

        # NOTE(sbauza): The two instances will use two different pGPUs
        # That said, we need to check all the pGPU inventories for knowing
        # which ones are used.
        usages = {}
        pgpu_uuid_to_name = {}
        for pci_device in [fakelibvirt.PGPU1_PCI_ADDR,
                           fakelibvirt.PGPU2_PCI_ADDR,
                           fakelibvirt.PGPU3_PCI_ADDR]:
            gpu_rp_uuid = self.placement.get(
                '/resource_providers?name=compute1_%s' % pci_device).body[
                'resource_providers'][0]['uuid']
            pgpu_uuid_to_name[gpu_rp_uuid] = pci_device
            gpu_inventory = self.placement.get(
                '/resource_providers/%s/inventories' % gpu_rp_uuid).body[
                'inventories']
            self.assertEqual(1, gpu_inventory['VGPU']['total'])

            gpu_usages = self.placement.get(
                '/resource_providers/%s/usages' % gpu_rp_uuid).body[
                'usages']
            usages[pci_device] = gpu_usages['VGPU']
        # Make sure that both instances are using different pGPUs
        used_devices = [dev for dev, usage in usages.items() if usage == 1]
        avail_devices = list(set(usages.keys()) - set(used_devices))
        self.assertEqual(2, len(used_devices))
        # Make sure that both instances are using the correct pGPUs
        for server in [server1, server2]:
            allocations = self.placement.get(
                '/allocations/%s' % server['id']).body[
                'allocations']
            self.assertEqual(
                {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2},
                allocations[compute_rp_uuid]['resources'])
            rp_uuids = list(allocations.keys())
            # We only have two RPs, the compute RP (the root) and the child
            # pGPU RP
            gpu_rp_uuid = (rp_uuids[1] if rp_uuids[0] == compute_rp_uuid
                           else rp_uuids[0])
            self.assertEqual(
                {'VGPU': 1},
                allocations[gpu_rp_uuid]['resources'])
            # The pGPU's RP name contains the pGPU name
            self.assertIn(inst_to_pgpu[server['id']],
                          pgpu_uuid_to_name[gpu_rp_uuid])

        # now create one more instance with vgpu against the reshaped tree
        created_server = self.api.post_server({'server': server_req})
        server3 = self._wait_for_state_change(created_server, 'ACTIVE')

        # find the pGPU that wasn't used before we created the third instance
        # It should have taken the previously available pGPU
        device = avail_devices[0]
        gpu_rp_uuid = self.placement.get(
            '/resource_providers?name=compute1_%s' % device).body[
            'resource_providers'][0]['uuid']
        gpu_usages = self.placement.get(
            '/resource_providers/%s/usages' % gpu_rp_uuid).body[
            'usages']
        self.assertEqual(1, gpu_usages['VGPU'])

        allocations = self.placement.get(
            '/allocations/%s' % server3['id']).body[
            'allocations']
        self.assertEqual(
            {'DISK_GB': 20, 'MEMORY_MB': 2048, 'VCPU': 2},
            allocations[compute_rp_uuid]['resources'])
        self.assertEqual(
            {'VGPU': 1},
            allocations[gpu_rp_uuid]['resources'])
