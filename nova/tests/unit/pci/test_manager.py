# Copyright (c) 2012 OpenStack Foundation
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
from unittest import mock

from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel

from nova.compute import vm_states
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields
from nova.pci import manager
from nova import test
from nova.tests.unit.pci import fakes as pci_fakes


fake_pci = {
    'compute_node_id': 1,
    'address': '0000:00:00.1',
    'product_id': 'p',
    'vendor_id': 'v',
    'request_id': None,
    'status': fields.PciDeviceStatus.AVAILABLE,
    'dev_type': fields.PciDeviceType.STANDARD,
    'parent_addr': None,
    'numa_node': 0}
fake_pci_1 = dict(fake_pci, address='0000:00:00.2',
                  product_id='p1', vendor_id='v1')
fake_pci_2 = dict(fake_pci, address='0000:00:00.3')

fake_pci_devs = [fake_pci, fake_pci_1, fake_pci_2]

fake_pci_3 = dict(fake_pci, address='0000:00:01.1',
                  dev_type=fields.PciDeviceType.SRIOV_PF,
                  vendor_id='v2', product_id='p2', numa_node=None)
fake_pci_4 = dict(fake_pci, address='0000:00:02.1',
                  dev_type=fields.PciDeviceType.SRIOV_VF,
                  parent_addr='0000:00:01.1',
                  vendor_id='v2', product_id='p2', numa_node=None)
fake_pci_5 = dict(fake_pci, address='0000:00:02.2',
                  dev_type=fields.PciDeviceType.SRIOV_VF,
                  parent_addr='0000:00:01.1',
                  vendor_id='v2', product_id='p2', numa_node=None)
fake_pci_devs_tree = [fake_pci_3, fake_pci_4, fake_pci_5]

fake_db_dev = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 1,
    'uuid': uuidsentinel.pci_device1,
    'compute_node_id': 1,
    'address': '0000:00:00.1',
    'vendor_id': 'v',
    'product_id': 'p',
    'numa_node': 1,
    'dev_type': fields.PciDeviceType.STANDARD,
    'status': fields.PciDeviceStatus.AVAILABLE,
    'dev_id': 'i',
    'label': 'l',
    'instance_uuid': None,
    'extra_info': '{}',
    'request_id': None,
    'parent_addr': None,
    }
fake_db_dev_1 = dict(fake_db_dev, vendor_id='v1',
                     uuid=uuidsentinel.pci_device1,
                     product_id='p1', id=2,
                     address='0000:00:00.2',
                     numa_node=0)
fake_db_dev_2 = dict(fake_db_dev, id=3, address='0000:00:00.3',
                     uuid=uuidsentinel.pci_device2,
                     numa_node=None, parent_addr='0000:00:00.1')
fake_db_devs = [fake_db_dev, fake_db_dev_1, fake_db_dev_2]

fake_db_dev_3 = dict(fake_db_dev, id=4, address='0000:00:01.1',
                     uuid=uuidsentinel.pci_device3,
                     vendor_id='v2', product_id='p2',
                     numa_node=None, dev_type=fields.PciDeviceType.SRIOV_PF)
fake_db_dev_4 = dict(fake_db_dev, id=5, address='0000:00:02.1',
                     uuid=uuidsentinel.pci_device4,
                     numa_node=None, dev_type=fields.PciDeviceType.SRIOV_VF,
                     vendor_id='v2', product_id='p2',
                     parent_addr='0000:00:01.1')
fake_db_dev_5 = dict(fake_db_dev, id=6, address='0000:00:02.2',
                     uuid=uuidsentinel.pci_device5,
                     numa_node=None, dev_type=fields.PciDeviceType.SRIOV_VF,
                     vendor_id='v2', product_id='p2',
                     parent_addr='0000:00:01.1')
fake_db_devs_tree = [fake_db_dev_3, fake_db_dev_4, fake_db_dev_5]

fake_pci_requests = [
    {'count': 1,
     'spec': [{'vendor_id': 'v'}]},
    {'count': 1,
     'spec': [{'vendor_id': 'v1'}]}]


class PciDevTrackerTestCase(test.NoDBTestCase):
    def _create_fake_instance(self):
        self.inst = objects.Instance()
        self.inst.uuid = uuidsentinel.instance1
        self.inst.pci_devices = objects.PciDeviceList()
        self.inst.vm_state = vm_states.ACTIVE
        self.inst.task_state = None
        self.inst.numa_topology = None

    def _fake_get_pci_devices(self, ctxt, node_id):
        return self.fake_devs

    def _fake_pci_device_update(self, ctxt, node_id, address, value):
        self.update_called += 1
        self.called_values = value
        fake_return = copy.deepcopy(fake_db_dev)
        return fake_return

    def _fake_pci_device_destroy(self, ctxt, node_id, address):
        self.destroy_called += 1

    def _create_pci_requests_object(self, requests,
                                    instance_uuid=None):
        instance_uuid = instance_uuid or uuidsentinel.instance1
        pci_reqs = []
        for request in requests:
            pci_req_obj = objects.InstancePCIRequest(count=request['count'],
                                                     spec=request['spec'])
            pci_reqs.append(pci_req_obj)
        return objects.InstancePCIRequests(
                instance_uuid=instance_uuid,
                requests=pci_reqs)

    def _create_tracker(self, fake_devs):
        self.fake_devs = copy.deepcopy(fake_devs)
        self.tracker = manager.PciDevTracker(
            self.fake_context, objects.ComputeNode(id=1, numa_topology=None))

    def setUp(self):
        super(PciDevTrackerTestCase, self).setUp()
        self.fake_context = context.get_admin_context()
        self.fake_devs = copy.deepcopy(fake_db_devs)
        self.stub_out('nova.db.main.api.pci_device_get_all_by_node',
            self._fake_get_pci_devices)
        # The fake_pci_whitelist must be called before creating the fake
        # devices
        patcher = pci_fakes.fake_pci_whitelist()
        self.addCleanup(patcher.stop)
        self._create_fake_instance()
        self._create_tracker(fake_db_devs)

    def test_pcidev_tracker_create(self):
        self.assertEqual(len(self.tracker.pci_devs), 3)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 3)
        self.assertEqual(list(self.tracker.stale), [])
        self.assertEqual(len(self.tracker.stats.pools), 3)
        self.assertEqual(self.tracker.node_id, 1)
        for dev in self.tracker.pci_devs:
            self.assertIsNone(dev.parent_device)
            self.assertEqual(dev.child_devices, [])

    def test_pcidev_tracker_create_device_tree(self):
        self._create_tracker(fake_db_devs_tree)

        self.assertEqual(len(self.tracker.pci_devs), 3)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 3)
        self.assertEqual(list(self.tracker.stale), [])
        self.assertEqual(len(self.tracker.stats.pools), 2)
        self.assertEqual(self.tracker.node_id, 1)
        pf = [dev for dev in self.tracker.pci_devs
              if dev.dev_type == fields.PciDeviceType.SRIOV_PF].pop()
        vfs = [dev for dev in self.tracker.pci_devs
               if dev.dev_type == fields.PciDeviceType.SRIOV_VF]
        self.assertEqual(2, len(vfs))

        # Assert we build the device tree correctly
        self.assertEqual(vfs, pf.child_devices)
        for vf in vfs:
            self.assertEqual(vf.parent_device, pf)

    def test_pcidev_tracker_create_device_tree_pf_only(self):
        self._create_tracker([fake_db_dev_3])

        self.assertEqual(len(self.tracker.pci_devs), 1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.assertEqual(list(self.tracker.stale), [])
        self.assertEqual(len(self.tracker.stats.pools), 1)
        self.assertEqual(self.tracker.node_id, 1)
        pf = self.tracker.pci_devs[0]
        self.assertIsNone(pf.parent_device)
        self.assertEqual([], pf.child_devices)

    def test_pcidev_tracker_create_device_tree_vf_only(self):
        self._create_tracker([fake_db_dev_4])

        self.assertEqual(len(self.tracker.pci_devs), 1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.assertEqual(list(self.tracker.stale), [])
        self.assertEqual(len(self.tracker.stats.pools), 1)
        self.assertEqual(self.tracker.node_id, 1)
        vf = self.tracker.pci_devs[0]
        self.assertIsNone(vf.parent_device)
        self.assertEqual([], vf.child_devices)

    @mock.patch('nova.pci.whitelist.Whitelist.device_assignable',
                return_value=True)
    def test_update_devices_from_hypervisor_resources(self, _mock_dev_assign):
        fake_pci_devs = [copy.deepcopy(fake_pci_4), copy.deepcopy(fake_pci_5)]
        fake_pci_devs_json = jsonutils.dumps(fake_pci_devs)
        tracker = manager.PciDevTracker(
            self.fake_context, objects.ComputeNode(id=1, numa_topology=None))
        tracker.update_devices_from_hypervisor_resources(fake_pci_devs_json)
        self.assertEqual(5, len(tracker.pci_devs))

    @mock.patch("nova.pci.manager.LOG.debug")
    def test_update_devices_from_hypervisor_resources_32bit_domain(
            self, mock_debug):
        self.flags(
            group='pci',
            device_spec=[
                '{"product_id":"2032", "vendor_id":"8086"}'])
        # There are systems where 32 bit PCI domain is used. See bug 1897528
        # for example. While nova (and qemu) does not support assigning such
        # devices but the existence of such device in the system should not
        # lead to an error.
        fake_pci = {
            'compute_node_id': 1,
            'address': '10000:00:02.0',
            'product_id': '2032',
            'vendor_id': '8086',
            'request_id': None,
            'status': fields.PciDeviceStatus.AVAILABLE,
            'dev_type': fields.PciDeviceType.STANDARD,
            'parent_addr': None,
            'numa_node': 0}

        fake_pci_devs = [fake_pci]
        fake_pci_devs_json = jsonutils.dumps(fake_pci_devs)
        tracker = manager.PciDevTracker(
            self.fake_context, objects.ComputeNode(id=1, numa_topology=None))
        # At this point we should have the original 3 fake devs
        self.assertEqual(3, len(tracker.pci_devs))
        # We expect that the device with 32bit PCI domain is ignored, so we'll
        # still have the same 3 original fake devs.
        tracker.update_devices_from_hypervisor_resources(fake_pci_devs_json)
        self.assertEqual(3, len(tracker.pci_devs))
        mock_debug.assert_called_once_with(
            'Skipping PCI device %s reported by the hypervisor: %s',
            {'address': '10000:00:02.0', 'parent_addr': None},
            'The property domain (10000) is greater than the maximum '
            'allowable value (FFFF).')

    def test_set_hvdev_new_dev(self):
        fake_pci_3 = dict(fake_pci, address='0000:00:00.4', vendor_id='v2')
        fake_pci_devs = [fake_pci, fake_pci_1, fake_pci_2, fake_pci_3]
        self.tracker._set_hvdevs(copy.deepcopy(fake_pci_devs))
        self.assertEqual(len(self.tracker.pci_devs), 4)
        self.assertEqual(set([dev.address for
                              dev in self.tracker.pci_devs]),
                         set(['0000:00:00.1', '0000:00:00.2',
                              '0000:00:00.3', '0000:00:00.4']))
        self.assertEqual(set([dev.vendor_id for
                              dev in self.tracker.pci_devs]),
                         set(['v', 'v1', 'v2']))

    def test_set_hvdev_new_dev_tree_maintained(self):
        # Make sure the device tree is properly maintained when there are new
        # devices reported by the driver
        self._create_tracker(fake_db_devs_tree)

        fake_new_device = dict(fake_pci_5, id=12, address='0000:00:02.3')
        fake_pci_devs = [fake_pci_3, fake_pci_4, fake_pci_5, fake_new_device]
        self.tracker._set_hvdevs(copy.deepcopy(fake_pci_devs))
        self.assertEqual(len(self.tracker.pci_devs), 4)

        pf = [dev for dev in self.tracker.pci_devs
              if dev.dev_type == fields.PciDeviceType.SRIOV_PF].pop()
        vfs = [dev for dev in self.tracker.pci_devs
               if dev.dev_type == fields.PciDeviceType.SRIOV_VF]
        self.assertEqual(3, len(vfs))

        # Assert we build the device tree correctly
        self.assertEqual(vfs, pf.child_devices)
        for vf in vfs:
            self.assertEqual(vf.parent_device, pf)

    def test_set_hvdev_changed(self):
        fake_pci_v2 = dict(fake_pci, address='0000:00:00.2', vendor_id='v1')
        fake_pci_devs = [fake_pci, fake_pci_2, fake_pci_v2]
        self.tracker._set_hvdevs(copy.deepcopy(fake_pci_devs))
        self.assertEqual(set([dev.vendor_id for
                             dev in self.tracker.pci_devs]),
                         set(['v', 'v1']))

    def test_set_hvdev_remove(self):
        self.tracker._set_hvdevs(copy.deepcopy([fake_pci]))
        self.assertEqual(
            len([dev for dev in self.tracker.pci_devs
                 if dev.status == fields.PciDeviceStatus.REMOVED]),
            2)

    def test_set_hvdev_remove_tree_maintained(self):
        # Make sure the device tree is properly maintained when there are
        # devices removed from the system (not reported by the driver but known
        # from previous scans)
        self._create_tracker(fake_db_devs_tree)

        fake_pci_devs = [fake_pci_3, fake_pci_4]
        self.tracker._set_hvdevs(copy.deepcopy(fake_pci_devs))
        self.assertEqual(
            2,
            len([dev for dev in self.tracker.pci_devs
                 if dev.status != fields.PciDeviceStatus.REMOVED]))
        pf = [dev for dev in self.tracker.pci_devs
              if dev.dev_type == fields.PciDeviceType.SRIOV_PF].pop()
        vfs = [dev for dev in self.tracker.pci_devs
               if (dev.dev_type == fields.PciDeviceType.SRIOV_VF and
                   dev.status != fields.PciDeviceStatus.REMOVED)]
        self.assertEqual(1, len(vfs))

        self.assertEqual(vfs, pf.child_devices)
        self.assertEqual(vfs[0].parent_device, pf)

    def test_set_hvdev_remove_tree_maintained_with_allocations(self):
        # Make sure the device tree is properly maintained when there are
        # devices removed from the system that are allocated to vms.

        all_db_devs = fake_db_devs_tree
        all_pci_devs = fake_pci_devs_tree
        self._create_tracker(all_db_devs)
        # we start with 3 devices
        self.assertEqual(
            3,
            len([dev for dev in self.tracker.pci_devs
                 if dev.status != fields.PciDeviceStatus.REMOVED]))
        # we then allocate one device
        pci_requests_obj = self._create_pci_requests_object(
            [{'count': 1, 'spec': [{'vendor_id': 'v2'}]}])
        # NOTE(sean-k-mooney): context, pci request, numa topology
        claimed_dev = self.tracker.claim_instance(
            mock.sentinel.context, pci_requests_obj, None)[0]

        self.tracker._set_hvdevs(copy.deepcopy(all_pci_devs))
        # and assert that no devices were removed
        self.assertEqual(
            0,
            len([dev for dev in self.tracker.pci_devs
                 if dev.status == fields.PciDeviceStatus.REMOVED]))
        # we then try to remove the allocated device from the set reported
        # by the driver.
        fake_pci_devs = [dev for dev in all_pci_devs
                         if dev['address'] != claimed_dev.address]
        with mock.patch("nova.pci.manager.LOG.warning") as log:
            self.tracker._set_hvdevs(copy.deepcopy(fake_pci_devs))
            log.assert_called_once()
            args = log.call_args_list[0][0]  # args of first call
            self.assertIn('Unable to remove device with', args[0])
        # and assert no devices are removed from the tracker
        self.assertEqual(
            0,
            len([dev for dev in self.tracker.pci_devs
                 if dev.status == fields.PciDeviceStatus.REMOVED]))
        # free the device that was allocated and update tracker again
        self.tracker._free_device(claimed_dev)
        self.tracker._set_hvdevs(copy.deepcopy(fake_pci_devs))
        # and assert that one device is removed from the tracker
        self.assertEqual(
            1,
            len([dev for dev in self.tracker.pci_devs
                 if dev.status == fields.PciDeviceStatus.REMOVED]))

    def test_set_hvdev_changed_stal(self):
        pci_requests_obj = self._create_pci_requests_object(
            [{'count': 1, 'spec': [{'vendor_id': 'v1'}]}])
        self.tracker.claim_instance(mock.sentinel.context,
                                    pci_requests_obj, None)
        fake_pci_3 = dict(fake_pci, address='0000:00:00.2', vendor_id='v2')
        fake_pci_devs = [fake_pci, fake_pci_2, fake_pci_3]
        self.tracker._set_hvdevs(copy.deepcopy(fake_pci_devs))
        self.assertEqual(len(self.tracker.stale), 1)
        self.assertEqual(self.tracker.stale['0000:00:00.2']['vendor_id'], 'v2')

    def _get_device_by_address(self, address):
        devs = [dev for dev in self.tracker.pci_devs if dev.address == address]
        if len(devs) == 1:
            return devs[0]
        if devs:
            raise ValueError('ambiguous address', devs)
        else:
            raise ValueError('device not found', address)

    def test_set_hvdevs_unavailable_vf_removed(self):
        # We start with a PF parent and two VF children
        self._create_tracker([fake_db_dev_3, fake_db_dev_4, fake_db_dev_5])
        pci_requests_obj = self._create_pci_requests_object(
            [
                {
                    'count': 1,
                    'spec': [{'dev_type': fields.PciDeviceType.SRIOV_PF}]
                }
            ],
            instance_uuid=uuidsentinel.instance1,
        )
        # then claim and allocate the PF that makes the VFs unavailable
        self.tracker.claim_instance(
            mock.sentinel.context, pci_requests_obj, None)
        self.tracker.allocate_instance({'uuid': uuidsentinel.instance1})

        dev3_pf = self._get_device_by_address(fake_db_dev_3['address'])
        self.assertEqual('allocated', dev3_pf.status)
        self.assertEqual(uuidsentinel.instance1, dev3_pf.instance_uuid)
        dev4_vf = self._get_device_by_address(fake_db_dev_4['address'])
        self.assertEqual('unavailable', dev4_vf.status)
        dev5_vf = self._get_device_by_address(fake_db_dev_5['address'])
        self.assertEqual('unavailable', dev5_vf.status)

        # now simulate that one VF (dev_5) is removed from the hypervisor and
        # the compute is restarted. As the VF is not claimed or allocated we
        # are free to remove it from the tracker.
        self.tracker._set_hvdevs(copy.deepcopy([fake_pci_3, fake_pci_4]))

        dev3_pf = self._get_device_by_address(fake_db_dev_3['address'])
        self.assertEqual('allocated', dev3_pf.status)
        self.assertEqual(uuidsentinel.instance1, dev3_pf.instance_uuid)
        dev4_vf = self._get_device_by_address(fake_db_dev_4['address'])
        self.assertEqual('unavailable', dev4_vf.status)
        dev5_vf = self._get_device_by_address(fake_db_dev_5['address'])
        self.assertEqual('removed', dev5_vf.status)

    def test_set_hvdevs_unavailable_pf_removed(self):
        # We start with one PF parent and one child VF
        self._create_tracker([fake_db_dev_3, fake_db_dev_4])
        pci_requests_obj = self._create_pci_requests_object(
            [
                {
                    'count': 1,
                    'spec': [{'dev_type': fields.PciDeviceType.SRIOV_VF}]
                }
            ],
            instance_uuid=uuidsentinel.instance1,
        )
        # Then we claim and allocate the VF that makes the PF unavailable
        self.tracker.claim_instance(
            mock.sentinel.context, pci_requests_obj, None)
        self.tracker.allocate_instance({'uuid': uuidsentinel.instance1})

        dev3_pf = self._get_device_by_address(fake_db_dev_3['address'])
        self.assertEqual('unavailable', dev3_pf.status)
        dev4_vf = self._get_device_by_address(fake_db_dev_4['address'])
        self.assertEqual('allocated', dev4_vf.status)
        self.assertEqual(uuidsentinel.instance1, dev4_vf.instance_uuid)

        # now simulate that the parent PF is removed from the hypervisor and
        # the compute is restarted. As the PF is not claimed or allocated we
        # are free to remove it from the tracker.
        self.tracker._set_hvdevs(copy.deepcopy([fake_pci_4]))

        dev3_pf = self._get_device_by_address(fake_db_dev_3['address'])
        self.assertEqual('removed', dev3_pf.status)
        dev4_vf = self._get_device_by_address(fake_db_dev_4['address'])
        self.assertEqual('allocated', dev4_vf.status)
        self.assertEqual(uuidsentinel.instance1, dev4_vf.instance_uuid)

    def test_claim_available_pf_while_child_vf_is_unavailable(self):
        # NOTE(gibi): this is bug 1969496. The state created here is
        # inconsistent and should not happen. But it did happen in some cases
        # where we were not able to track down the way how it happened.

        # We start with a PF parent and a VF child. The PF is available and
        # the VF is unavailable.
        pf = copy.deepcopy(fake_db_dev_3)
        vf = copy.deepcopy(fake_db_dev_4)
        vf['status'] = fields.PciDeviceStatus.UNAVAILABLE
        self._create_tracker([pf, vf])

        pf_dev = self._get_device_by_address(pf['address'])
        self.assertEqual('available', pf_dev.status)
        vf_dev = self._get_device_by_address(vf['address'])
        self.assertEqual('unavailable', vf_dev.status)

        pci_requests_obj = self._create_pci_requests_object(
            [
                {
                    'count': 1,
                    'spec': [{'dev_type': fields.PciDeviceType.SRIOV_PF}]
                }
            ],
            instance_uuid=uuidsentinel.instance1,
        )
        # now try to claim and allocate the PF. It should work as it is
        # available
        self.tracker.claim_instance(
            mock.sentinel.context, pci_requests_obj, None)
        self.tracker.allocate_instance({'uuid': uuidsentinel.instance1})

        pf_dev = self._get_device_by_address(pf['address'])
        self.assertEqual('allocated', pf_dev.status)
        vf_dev = self._get_device_by_address(vf['address'])
        self.assertEqual('unavailable', vf_dev.status)

        self.assertIn(
            'Some child device of parent 0000:00:01.1 is in an inconsistent '
            'state. If you can reproduce this warning then please report a '
            'bug at https://bugs.launchpad.net/nova/+filebug with '
            'reproduction steps. Inconsistent children with state: '
            '0000:00:02.1 - unavailable',
            self.stdlog.logger.output
        )

        # Ensure that the claim actually fixes the inconsistency so when the
        # parent if freed the children become available too.
        self.tracker.free_instance(
            mock.sentinel.context,
            {'uuid': uuidsentinel.instance1,
             'pci_devices': [objects.PciDevice(id=pf['id'])]})

        pf_dev = self._get_device_by_address(pf['address'])
        self.assertEqual('available', pf_dev.status)
        vf_dev = self._get_device_by_address(vf['address'])
        self.assertEqual('available', vf_dev.status)

    def test_claim_available_pf_while_children_vfs_are_in_mixed_state(self):
        # We start with a PF parent and two VF children. The PF is available
        # and one of the VF is unavailable while the other is available.
        pf = copy.deepcopy(fake_db_dev_3)
        vf1 = copy.deepcopy(fake_db_dev_4)
        vf1['status'] = fields.PciDeviceStatus.UNAVAILABLE
        vf2 = copy.deepcopy(fake_db_dev_5)
        vf2['status'] = fields.PciDeviceStatus.AVAILABLE
        self._create_tracker([pf, vf1, vf2])

        pf_dev = self._get_device_by_address(pf['address'])
        self.assertEqual('available', pf_dev.status)
        vf1_dev = self._get_device_by_address(vf1['address'])
        self.assertEqual('unavailable', vf1_dev.status)
        vf2_dev = self._get_device_by_address(vf2['address'])
        self.assertEqual('available', vf2_dev.status)

        pci_requests_obj = self._create_pci_requests_object(
            [
                {
                    'count': 1,
                    'spec': [{'dev_type': fields.PciDeviceType.SRIOV_PF}]
                }
            ],
            instance_uuid=uuidsentinel.instance1,
        )
        # now try to claim and allocate the PF. It should work as it is
        # available
        self.tracker.claim_instance(
            mock.sentinel.context, pci_requests_obj, None)
        self.tracker.allocate_instance({'uuid': uuidsentinel.instance1})

        pf_dev = self._get_device_by_address(pf['address'])
        self.assertEqual('allocated', pf_dev.status)
        vf1_dev = self._get_device_by_address(vf1['address'])
        self.assertEqual('unavailable', vf1_dev.status)
        vf2_dev = self._get_device_by_address(vf2['address'])
        self.assertEqual('unavailable', vf2_dev.status)

        self.assertIn(
            'Some child device of parent 0000:00:01.1 is in an inconsistent '
            'state. If you can reproduce this warning then please report a '
            'bug at https://bugs.launchpad.net/nova/+filebug with '
            'reproduction steps. Inconsistent children with state: '
            '0000:00:02.1 - unavailable',
            self.stdlog.logger.output
        )

        # Ensure that the claim actually fixes the inconsistency so when the
        # parent if freed the children become available too.
        self.tracker.free_instance(
            mock.sentinel.context,
            {'uuid': uuidsentinel.instance1,
             'pci_devices': [objects.PciDevice(id=pf['id'])]})

        pf_dev = self._get_device_by_address(pf['address'])
        self.assertEqual('available', pf_dev.status)
        vf1_dev = self._get_device_by_address(vf1['address'])
        self.assertEqual('available', vf1_dev.status)
        vf2_dev = self._get_device_by_address(vf2['address'])
        self.assertEqual('available', vf2_dev.status)

    def test_claim_available_pf_while_a_child_is_used(self):
        pf = copy.deepcopy(fake_db_dev_3)
        vf1 = copy.deepcopy(fake_db_dev_4)
        vf1['status'] = fields.PciDeviceStatus.UNAVAILABLE
        vf2 = copy.deepcopy(fake_db_dev_5)
        vf2['status'] = fields.PciDeviceStatus.CLAIMED
        self._create_tracker([pf, vf1, vf2])

        pf_dev = self._get_device_by_address(pf['address'])
        self.assertEqual('available', pf_dev.status)
        vf1_dev = self._get_device_by_address(vf1['address'])
        self.assertEqual('unavailable', vf1_dev.status)
        vf2_dev = self._get_device_by_address(vf2['address'])
        self.assertEqual('claimed', vf2_dev.status)

        pci_requests_obj = self._create_pci_requests_object(
            [
                {
                    'count': 1,
                    'spec': [{'dev_type': fields.PciDeviceType.SRIOV_PF}]
                }
            ],
            instance_uuid=uuidsentinel.instance1,
        )
        # now try to claim and allocate the PF. The claim should fail as on of
        # the child is used.
        self.assertRaises(
            exception.PciDeviceVFInvalidStatus,
            self.tracker.claim_instance,
            mock.sentinel.context,
            pci_requests_obj,
            None,
        )

        pf_dev = self._get_device_by_address(pf['address'])
        self.assertEqual('available', pf_dev.status)
        vf1_dev = self._get_device_by_address(vf1['address'])
        self.assertEqual('unavailable', vf1_dev.status)
        vf2_dev = self._get_device_by_address(vf2['address'])
        self.assertEqual('claimed', vf2_dev.status)

    def test_update_pci_for_instance_active(self):
        pci_requests_obj = self._create_pci_requests_object(fake_pci_requests)
        self.tracker.claim_instance(mock.sentinel.context,
                                    pci_requests_obj, None)
        self.assertEqual(len(self.tracker.claims[self.inst['uuid']]), 2)
        self.tracker.update_pci_for_instance(None, self.inst, sign=1)
        self.assertEqual(len(self.tracker.allocations[self.inst['uuid']]), 2)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.assertEqual(free_devs[0].vendor_id, 'v')

    def test_update_pci_for_instance_fail(self):
        pci_requests = copy.deepcopy(fake_pci_requests)
        pci_requests[0]['count'] = 4
        pci_requests_obj = self._create_pci_requests_object(pci_requests)
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.tracker.claim_instance,
            mock.sentinel.context,
            pci_requests_obj,
            None
        )
        self.assertEqual(len(self.tracker.claims[self.inst['uuid']]), 0)
        devs = self.tracker.update_pci_for_instance(None,
                                                    self.inst,
                                                    sign=1)
        self.assertEqual(len(self.tracker.allocations[self.inst['uuid']]), 0)
        self.assertIsNone(devs)

    def test_pci_claim_instance_with_numa(self):
        fake_pci_3 = dict(fake_pci_1, address='0000:00:00.4')
        fake_devs_numa = copy.deepcopy(fake_pci_devs)
        fake_devs_numa.append(fake_pci_3)
        self.tracker = manager.PciDevTracker(
            mock.sentinel.context,
            objects.ComputeNode(id=1, numa_topology=None))
        self.tracker._set_hvdevs(copy.deepcopy(fake_devs_numa))
        pci_requests = copy.deepcopy(fake_pci_requests)[:1]
        pci_requests[0]['count'] = 2
        pci_requests_obj = self._create_pci_requests_object(pci_requests)
        self.inst.numa_topology = objects.InstanceNUMATopology(
                    cells=[objects.InstanceNUMACell(
                        id=1, cpuset=set([1, 2]), memory=512)])
        self.tracker.claim_instance(mock.sentinel.context,
                                    pci_requests_obj,
                                    self.inst.numa_topology)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(2, len(free_devs))
        self.assertEqual('v1', free_devs[0].vendor_id)
        self.assertEqual('v1', free_devs[1].vendor_id)

    def test_pci_claim_instance_with_numa_fail(self):
        pci_requests_obj = self._create_pci_requests_object(fake_pci_requests)
        self.inst.numa_topology = objects.InstanceNUMATopology(
                    cells=[objects.InstanceNUMACell(
                        id=1, cpuset=set([1, 2]), memory=512)])
        self.assertRaises(
            exception.PciDeviceRequestFailed,
            self.tracker.claim_instance,
            mock.sentinel.context,
            pci_requests_obj,
            self.inst.numa_topology
        )

    def test_update_pci_for_instance_deleted(self):
        pci_requests_obj = self._create_pci_requests_object(fake_pci_requests)
        self.tracker.claim_instance(mock.sentinel.context,
                                    pci_requests_obj, None)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.inst.vm_state = vm_states.DELETED
        self.tracker.update_pci_for_instance(None, self.inst, -1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 3)
        self.assertEqual(set([dev.vendor_id for
                              dev in self.tracker.pci_devs]),
                         set(['v', 'v1']))

    @mock.patch.object(objects.PciDevice, 'should_migrate_data',
                       return_value=False)
    def test_save(self, migrate_mock):
        self.stub_out(
                'nova.db.main.api.pci_device_update',
                self._fake_pci_device_update)
        fake_pci_v3 = dict(fake_pci, address='0000:00:00.2', vendor_id='v3')
        fake_pci_devs = [fake_pci, fake_pci_2, fake_pci_v3]
        self.tracker._set_hvdevs(copy.deepcopy(fake_pci_devs))
        self.update_called = 0
        self.tracker.save(self.fake_context)
        self.assertEqual(self.update_called, 3)

    def test_save_removed(self):
        self.stub_out(
                'nova.db.main.api.pci_device_update',
                self._fake_pci_device_update)
        self.stub_out(
                'nova.db.main.api.pci_device_destroy',
                self._fake_pci_device_destroy)
        self.destroy_called = 0
        self.assertEqual(len(self.tracker.pci_devs), 3)
        dev = self.tracker.pci_devs[0]
        self.update_called = 0
        dev.remove()
        self.tracker.save(self.fake_context)
        self.assertEqual(len(self.tracker.pci_devs), 2)
        self.assertEqual(self.destroy_called, 1)

    def test_clean_usage(self):
        inst_2 = copy.copy(self.inst)
        inst_2.uuid = uuidsentinel.instance2
        migr = objects.Migration(
            instance_uuid='uuid2',
            vm_state=vm_states.BUILDING,
        )

        pci_requests_obj = self._create_pci_requests_object(
            [{'count': 1, 'spec': [{'vendor_id': 'v'}]}])
        self.tracker.claim_instance(mock.sentinel.context,
                                    pci_requests_obj, None)
        self.tracker.update_pci_for_instance(None, self.inst, sign=1)
        pci_requests_obj = self._create_pci_requests_object(
            [{'count': 1, 'spec': [{'vendor_id': 'v1'}]}],
            instance_uuid=inst_2.uuid)
        self.tracker.claim_instance(mock.sentinel.context,
                                    pci_requests_obj, None)
        self.tracker.update_pci_for_instance(None, inst_2, sign=1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.assertEqual(free_devs[0].vendor_id, 'v')

        self.tracker.clean_usage([self.inst], [migr])
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 2)
        self.assertEqual(
            set([dev.vendor_id for dev in free_devs]),
            set(['v', 'v1']))

    def test_clean_usage_no_request_match_no_claims(self):
        # Tests the case that there is no match for the request so the
        # claims mapping is set to None for the instance when the tracker
        # calls clean_usage.
        self.tracker.update_pci_for_instance(None, self.inst, sign=1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(3, len(free_devs))
        self.tracker.clean_usage([], [])
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(3, len(free_devs))
        self.assertEqual(
            set([dev.address for dev in free_devs]),
            set(['0000:00:00.1', '0000:00:00.2', '0000:00:00.3']))

    def test_free_devices(self):
        pci_requests_obj = self._create_pci_requests_object(
            [{'count': 1, 'spec': [{'vendor_id': 'v'}]}])
        self.tracker.claim_instance(mock.sentinel.context,
                                    pci_requests_obj, None)
        self.tracker.update_pci_for_instance(None, self.inst, sign=1)

        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 2)

        self.tracker.free_instance(None, self.inst)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 3)

    def test_free_device(self):
        pci_requests_obj = self._create_pci_requests_object(
            [{'count': 1, 'spec': [{'vendor_id': 'v'}]}])
        self.tracker.claim_instance(mock.sentinel.context,
                                    pci_requests_obj, None)
        self.tracker.update_pci_for_instance(None, self.inst, sign=1)
        free_pci_device_ids = (
            [dev.id for dev in self.tracker.pci_stats.get_free_devs()])
        self.assertEqual(2, len(free_pci_device_ids))
        allocated_devs = self.inst.get_pci_devices()
        pci_device = allocated_devs[0]
        self.assertNotIn(pci_device.id, free_pci_device_ids)
        instance_uuid = self.inst['uuid']
        self.assertIn(pci_device, self.tracker.allocations[instance_uuid])
        self.tracker.free_device(pci_device, self.inst)
        free_pci_device_ids = (
            [dev.id for dev in self.tracker.pci_stats.get_free_devs()])
        self.assertEqual(3, len(free_pci_device_ids))
        self.assertIn(pci_device.id, free_pci_device_ids)
        self.assertIsNone(self.tracker.allocations.get(instance_uuid))

    def test_free_instance_claims(self):
        # Create an InstancePCIRequest object
        pci_requests_obj = self._create_pci_requests_object(
            [{'count': 1, 'spec': [{'vendor_id': 'v'}]}])

        # Claim a single PCI device
        claimed_devs = self.tracker.claim_instance(mock.sentinel.context,
                                                   pci_requests_obj, None)

        # Assert we have exactly one claimed device for the given instance.
        claimed_dev = claimed_devs[0]
        instance_uuid = self.inst['uuid']
        self.assertEqual(1, len(self.tracker.claims.get(instance_uuid)))
        self.assertIn(claimed_dev.id,
                      [pci_dev.id for pci_dev in
                       self.tracker.claims.get(instance_uuid)])
        self.assertIsNone(self.tracker.allocations.get(instance_uuid))

        # Free instance claims
        self.tracker.free_instance_claims(mock.sentinel.context, self.inst)

        # Assert no claims for instance and all PCI devices are free
        self.assertIsNone(self.tracker.claims.get(instance_uuid))
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(fake_db_devs), len(free_devs))

    def test_free_instance_allocations(self):
        # Create an InstancePCIRequest object
        pci_requests_obj = self._create_pci_requests_object(
            [{'count': 1, 'spec': [{'vendor_id': 'v'}]}])
        # Allocate a single PCI device
        allocated_devs = self.tracker.claim_instance(mock.sentinel.context,
                                                     pci_requests_obj, None)
        self.tracker.allocate_instance(self.inst)

        # Assert we have exactly one allocated device for the given instance.
        allocated_dev = allocated_devs[0]
        instance_uuid = self.inst['uuid']
        self.assertIsNone(self.tracker.claims.get(instance_uuid))
        self.assertEqual(1, len(self.tracker.allocations.get(instance_uuid)))
        self.assertIn(allocated_dev.id,
                      [pci_dev.id for pci_dev in
                       self.tracker.allocations.get(instance_uuid)])

        # Free instance allocations and assert claims did not change
        self.tracker.free_instance_allocations(mock.sentinel.context,
                                               self.inst)
        # Assert all PCI devices are free.
        self.assertIsNone(self.tracker.allocations.get(instance_uuid))
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(fake_db_devs), len(free_devs))
