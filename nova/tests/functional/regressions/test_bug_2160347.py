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

from nova import objects
from nova.objects import fields
from nova import test
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_pci_sriov_servers as base


class TestPCIMoveClaimAbort(base._PCIServersTestBase):
    """Regression tests for bug https://bugs.launchpad.net/nova/+bug/2160347

    MoveClaim.abort() drops the move claim against self.instance, a copy of
    the instance taken in Claim.__init__ before _move_claim() sets and saves
    instance.migration_context. What the copy then sees depends on whether
    migration_context was already loaded on the instance when the claim was
    created:

    * For evacuation it is loaded (as None), so the copy keeps None. The PCI
      devices claimed on the destination are not freed and stay allocated to
      the instance, which then has allocated pci_devices rows on two hosts
      until the destination's update_available_resource periodic heals it.
    * For resize it is not loaded, so the copy lazy-loads the saved context
      during the abort and the devices are freed.

    In both cases the migration context is left on the instance, because
    drop_migration_context() is also called on the copy.
    """

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

    def _instance_pci_device_ids(self, server):
        # The rows in the pci_devices table owned by the instance.
        devs = objects.PciDeviceList.get_by_instance_uuid(
            self.ctxt, server['id'])
        return sorted(dev.id for dev in devs)

    def test_evacuate_spawn_fails_after_claim(self):
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=1, num_vfs=0)
        self.start_compute(hostname='test_compute0', pci_info=pci_info)
        self.start_compute(hostname='test_compute1', pci_info=pci_info)

        extra_spec = {"pci_passthrough:alias": "%s:1" % self.PFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(
            flavor_id=flavor_id, networks='none', host='test_compute0')
        self.assertPCIDeviceCounts('test_compute0', total=1, free=0)
        self.assertPCIDeviceCounts('test_compute1', total=1, free=1)
        orig_pci_device_ids = self._instance_pci_device_ids(server)
        self.assertEqual(1, len(orig_pci_device_ids))

        self.computes['test_compute0'].stop()
        self.api.put_service(
            self.computes['test_compute0'].service_ref.uuid,
            {'forced_down': True})

        # rebuild_claim() on test_compute1 claims its PF, then spawn fails
        # inside the claim context, so the move claim is aborted.
        with mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver.spawn',
            side_effect=test.TestingException('simulated failure'),
        ):
            self._evacuate_server(
                server, expected_state='ERROR',
                expected_migration_status='failed')

        # FIXME(jomlowe): This is bug 2160347. The PF claimed on the
        # destination is not freed when the move claim is aborted. It stays
        # allocated to the instance, which now has allocated pci_devices rows
        # on both hosts, and the migration context is left on the instance.
        self.assertPCIDeviceCounts('test_compute1', total=1, free=0)
        pci_device_ids = self._instance_pci_device_ids(server)
        self.assertEqual(2, len(pci_device_ids))
        self.assertIn(orig_pci_device_ids[0], pci_device_ids)
        self.assertIsNotNone(
            objects.MigrationContext.get_by_instance_uuid(
                self.ctxt, server['id']))

        # The update_available_resource periodic on the destination frees the
        # leaked PF, as the instance is not on that host and the migration
        # has failed.
        self.computes['test_compute1'].manager.update_available_resource(
            self.ctxt)
        self.assertPCIDeviceCounts('test_compute1', total=1, free=1)
        self.assertEqual(
            orig_pci_device_ids, self._instance_pci_device_ids(server))

    def test_same_host_resize_prep_resize_fails_after_claim(self):
        self.flags(allow_resize_to_same_host=True)
        pci_info = fakelibvirt.HostPCIDevicesInfo(num_pfs=2, num_vfs=0)
        self.start_compute(hostname='test_compute0', pci_info=pci_info)
        self.assertPCIDeviceCounts('test_compute0', total=2, free=2)

        extra_spec = {"pci_passthrough:alias": "%s:1" % self.PFS_ALIAS_NAME}
        flavor_id = self._create_flavor(extra_spec=extra_spec)
        server = self._create_server(flavor_id=flavor_id, networks='none')
        self.assertPCIDeviceCounts('test_compute0', total=2, free=1)
        orig_pci_device_ids = self._instance_pci_device_ids(server)
        self.assertEqual(1, len(orig_pci_device_ids))

        # Resize to a bigger flavor with the same PCI request. resize_claim()
        # on the (same) destination host claims the second PF, then the RPC
        # cast to start the resize fails inside the claim context, so the
        # move claim is aborted.
        new_flavor_id = self._create_flavor(
            memory_mb=4096, extra_spec=extra_spec)
        with mock.patch(
            'nova.compute.rpcapi.ComputeAPI.resize_instance',
            side_effect=test.TestingException('simulated failure'),
        ):
            self.api.post_server_action(
                server['id'], {'resize': {'flavorRef': new_flavor_id}})
            self._wait_for_migration_status(server, ['error'])
            self._wait_for_state_change(server, 'ERROR')

        # The device claimed for the aborted resize is freed and the instance
        # keeps only the device it had before the resize. The copy of the
        # instance used by MoveClaim.abort() lazy-loads the migration context
        # here, which is why resize does not leak the device.
        self.assertPCIDeviceCounts('test_compute0', total=2, free=1)
        self.assertEqual(
            orig_pci_device_ids, self._instance_pci_device_ids(server))
        # FIXME(jomlowe): This is bug 2160347. The migration context is left on
        # the instance after the move claim is aborted.
        self.assertIsNotNone(
            objects.MigrationContext.get_by_instance_uuid(
                self.ctxt, server['id']))

        # The periodic keeps it that way.
        self.computes['test_compute0'].manager.update_available_resource(
            self.ctxt)
        self.assertPCIDeviceCounts('test_compute0', total=2, free=1)
        self.assertEqual(
            orig_pci_device_ids, self._instance_pci_device_ids(server))

        # _delete_server() treats an ERROR server as a failed delete.
        self.api.post_server_action(
            server['id'], {'os-resetState': {'state': 'active'}})
        self._delete_server(server)
        self.assertPCIDeviceCounts('test_compute0', total=2, free=2)
