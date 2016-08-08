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

"""Tests for compute resource tracking."""

import uuid

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils

from nova.compute import resource_tracker
from nova.compute import vm_states
from nova import context
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova import test
from nova.tests.unit.pci import fakes as pci_fakes
from nova.tests import uuidsentinel
from nova.virt import driver


FAKE_VIRT_MEMORY_MB = 5
FAKE_VIRT_MEMORY_OVERHEAD = 1
FAKE_VIRT_DISK_OVERHEAD = 0
FAKE_VIRT_MEMORY_WITH_OVERHEAD = (
        FAKE_VIRT_MEMORY_MB + FAKE_VIRT_MEMORY_OVERHEAD)
FAKE_VIRT_NUMA_TOPOLOGY = objects.NUMATopology(
        cells=[objects.NUMACell(id=0, cpuset=set([1, 2]), memory=3072,
                                cpu_usage=0, memory_usage=0, mempages=[],
                                siblings=[], pinned_cpus=set([])),
               objects.NUMACell(id=1, cpuset=set([3, 4]), memory=3072,
                                cpu_usage=0, memory_usage=0, mempages=[],
                                siblings=[], pinned_cpus=set([]))])
FAKE_VIRT_NUMA_TOPOLOGY_OVERHEAD = objects.NUMATopologyLimits(
    cpu_allocation_ratio=2, ram_allocation_ratio=2)

ROOT_GB = 5
EPHEMERAL_GB = 1
FAKE_VIRT_LOCAL_GB = ROOT_GB + EPHEMERAL_GB
FAKE_VIRT_VCPUS = 1
CONF = cfg.CONF


class FakeVirtDriver(driver.ComputeDriver):

    def __init__(self, pci_support=False, stats=None,
                 numa_topology=FAKE_VIRT_NUMA_TOPOLOGY):
        super(FakeVirtDriver, self).__init__(None)
        self.memory_mb = FAKE_VIRT_MEMORY_MB
        self.local_gb = FAKE_VIRT_LOCAL_GB
        self.vcpus = FAKE_VIRT_VCPUS
        self.numa_topology = numa_topology

        self.memory_mb_used = 0
        self.local_gb_used = 0
        self.pci_support = pci_support
        self.pci_devices = [
            {
                'label': 'label_8086_0443',
                'dev_type': fields.PciDeviceType.SRIOV_VF,
                'compute_node_id': 1,
                'address': '0000:00:01.1',
                'product_id': '0443',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1',
                'numa_node': 1,
                'parent_addr': '0000:00:01.0',
            },
            {
                'label': 'label_8086_0443',
                'dev_type': fields.PciDeviceType.SRIOV_VF,
                'compute_node_id': 1,
                'address': '0000:00:01.2',
                'product_id': '0443',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1',
                'numa_node': 1,
                'parent_addr': '0000:00:01.0',
            },
            {
                'label': 'label_8086_0443',
                'dev_type': fields.PciDeviceType.SRIOV_PF,
                'compute_node_id': 1,
                'address': '0000:00:01.0',
                'product_id': '0443',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1',
                'numa_node': 1,
            },
            {
                'label': 'label_8086_0123',
                'dev_type': 'type-PCI',
                'compute_node_id': 1,
                'address': '0000:00:01.0',
                'product_id': '0123',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1',
                'numa_node': 1,
            },
            {
                'label': 'label_8086_7891',
                'dev_type': fields.PciDeviceType.SRIOV_VF,
                'compute_node_id': 1,
                'address': '0000:00:01.0',
                'product_id': '7891',
                'vendor_id': '8086',
                'status': 'available',
                'extra_k1': 'v1',
                'numa_node': None,
                'parent_addr': '0000:08:01.0',
            },
        ] if self.pci_support else []
        self.pci_stats = [
            {
                'count': 2,
                'vendor_id': '8086',
                'product_id': '0443',
                'numa_node': 1,
                'dev_type': fields.PciDeviceType.SRIOV_VF
            },
            {
                'count': 1,
                'vendor_id': '8086',
                'product_id': '0443',
                'numa_node': 1,
                'dev_type': fields.PciDeviceType.SRIOV_PF
            },
            {
                'count': 1,
                'vendor_id': '8086',
                'product_id': '7891',
                'numa_node': None,
                'dev_type': fields.PciDeviceType.SRIOV_VF
            },
        ] if self.pci_support else []

    def get_host_ip_addr(self):
        return '127.0.0.1'

    def get_available_resource(self, nodename):
        d = {
            'vcpus': self.vcpus,
            'memory_mb': self.memory_mb,
            'local_gb': self.local_gb,
            'vcpus_used': 0,
            'memory_mb_used': self.memory_mb_used,
            'local_gb_used': self.local_gb_used,
            'hypervisor_type': 'fake',
            'hypervisor_version': 0,
            'hypervisor_hostname': 'fakehost',
            'cpu_info': '',
            'numa_topology': (
                self.numa_topology._to_json() if self.numa_topology else None),
        }
        if self.pci_support:
            d['pci_passthrough_devices'] = jsonutils.dumps(self.pci_devices)
        return d

    def estimate_instance_overhead(self, instance_info):
        instance_info['memory_mb']  # make sure memory value is present
        overhead = {
            'memory_mb': FAKE_VIRT_MEMORY_OVERHEAD,
            'disk_gb': FAKE_VIRT_DISK_OVERHEAD,
        }
        return overhead  # just return a constant value for testing


class BaseTestCase(test.TestCase):

    @mock.patch('stevedore.enabled.EnabledExtensionManager')
    def setUp(self, _mock_ext_mgr):
        super(BaseTestCase, self).setUp()

        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        self.context = context.get_admin_context()

        self._set_pci_passthrough_whitelist()

        self._instances = {}
        self._instance_types = {}

        self.stubs.Set(objects.InstanceList, 'get_by_host_and_node',
                       self._fake_instance_get_by_host_and_node)

        self.host = 'fakehost'
        self.compute = self._create_compute_node()
        self.updated = False
        self.update_call_count = 0

    def _set_pci_passthrough_whitelist(self):
        self.flags(pci_passthrough_whitelist=[
            '{"vendor_id": "8086", "product_id": "0443"}',
            '{"vendor_id": "8086", "product_id": "7891"}'])

    def _create_compute_node(self, values=None):
        # This creates a db representation of a compute_node.
        compute = {
            "id": 1,
            "uuid": uuidsentinel.fake_compute_node,
            "service_id": 1,
            "host": "fakehost",
            "vcpus": 1,
            "memory_mb": 1,
            "local_gb": 1,
            "vcpus_used": 1,
            "memory_mb_used": 1,
            "local_gb_used": 1,
            "free_ram_mb": 1,
            "free_disk_gb": 1,
            "current_workload": 1,
            "running_vms": 0,
            "cpu_info": None,
            "numa_topology": None,
            "stats": '{"num_instances": "1"}',
            "hypervisor_hostname": "fakenode",
            'hypervisor_version': 1,
            'hypervisor_type': 'fake-hyp',
            'disk_available_least': None,
            'host_ip': None,
            'metrics': None,
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
            'cpu_allocation_ratio': None,
            'ram_allocation_ratio': None,
            'disk_allocation_ratio': None,
        }
        if values:
            compute.update(values)
        return compute

    def _fake_instance_obj(self, stash=True, flavor=None, **kwargs):

        # Default to an instance ready to resize to or from the same
        # instance_type
        flavor = flavor or self._fake_flavor_create()
        if not isinstance(flavor, objects.Flavor):
            flavor = objects.Flavor(**flavor)

        instance_uuid = str(uuid.uuid1())
        instance = objects.Instance(context=self.context, uuid=instance_uuid,
                                    flavor=flavor)
        instance.update({
            'vm_state': vm_states.RESIZED,
            'task_state': None,
            'ephemeral_key_uuid': None,
            'os_type': 'Linux',
            'project_id': '123456',
            'host': None,
            'node': None,
            'instance_type_id': flavor['id'],
            'memory_mb': flavor['memory_mb'],
            'vcpus': flavor['vcpus'],
            'root_gb': flavor['root_gb'],
            'ephemeral_gb': flavor['ephemeral_gb'],
            'launched_on': None,
            'system_metadata': {},
            'availability_zone': None,
            'vm_mode': None,
            'reservation_id': None,
            'display_name': None,
            'default_swap_device': None,
            'power_state': None,
            'access_ip_v6': None,
            'access_ip_v4': None,
            'key_name': None,
            'updated_at': None,
            'cell_name': None,
            'locked': None,
            'locked_by': None,
            'launch_index': None,
            'architecture': None,
            'auto_disk_config': None,
            'terminated_at': None,
            'ramdisk_id': None,
            'user_data': None,
            'cleaned': None,
            'deleted_at': None,
            'id': 333,
            'disable_terminate': None,
            'hostname': None,
            'display_description': None,
            'key_data': None,
            'deleted': None,
            'default_ephemeral_device': None,
            'progress': None,
            'launched_at': None,
            'config_drive': None,
            'kernel_id': None,
            'user_id': None,
            'shutdown_terminate': None,
            'created_at': None,
            'image_ref': None,
            'root_device_name': None,
        })

        if stash:
            instance.old_flavor = flavor
            instance.new_flavor = flavor

        instance.numa_topology = kwargs.pop('numa_topology', None)

        instance.update(kwargs)

        self._instances[instance_uuid] = instance
        return instance

    def _fake_flavor_create(self, **kwargs):
        instance_type = {
            'id': 1,
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
            'disabled': False,
            'is_public': True,
            'name': 'fakeitype',
            'memory_mb': FAKE_VIRT_MEMORY_MB,
            'vcpus': FAKE_VIRT_VCPUS,
            'root_gb': ROOT_GB,
            'ephemeral_gb': EPHEMERAL_GB,
            'swap': 0,
            'rxtx_factor': 1.0,
            'vcpu_weight': 1,
            'flavorid': 'fakeflavor',
            'extra_specs': {},
        }
        instance_type.update(**kwargs)
        instance_type = objects.Flavor(**instance_type)

        id_ = instance_type['id']
        self._instance_types[id_] = instance_type
        return instance_type

    def _fake_instance_get_by_host_and_node(self, context, host, nodename,
                                            expected_attrs=None):
        return objects.InstanceList(
            objects=[i for i in self._instances.values() if i['host'] == host])

    def _fake_compute_node_update(self, ctx, compute_node_id, values,
            prune_stats=False):
        self.update_call_count += 1
        self.updated = True
        self.compute.update(values)
        return self.compute

    def _driver(self):
        return FakeVirtDriver()

    def _tracker(self, host=None):

        if host is None:
            host = self.host

        node = "fakenode"

        driver = self._driver()

        tracker = resource_tracker.ResourceTracker(host, driver, node)
        return tracker


class BaseTrackerTestCase(BaseTestCase):

    def setUp(self):
        # setup plumbing for a working resource tracker with required
        # database models and a compatible compute driver:
        super(BaseTrackerTestCase, self).setUp()

        self.tracker = self._tracker()
        self._migrations = {}
        self._fake_inventories = {}

        self.stub_out('nova.db.compute_node_get_by_host_and_nodename',
                self._fake_compute_node_get_by_host_and_nodename)
        self.stub_out('nova.db.compute_node_get',
                self._fake_compute_node_get)
        self.stub_out('nova.db.compute_node_update',
                self._fake_compute_node_update)
        self.stub_out('nova.db.migration_update',
                self._fake_migration_update)
        self.stub_out('nova.db.migration_get_in_progress_by_host_and_node',
                self._fake_migration_get_in_progress_by_host_and_node)
        self.stub_out('nova.objects.resource_provider._create_inventory_in_db',
                self._fake_inventory_create)
        self.stub_out('nova.objects.resource_provider._create_rp_in_db',
                      self._fake_rp_create)

        # Note that this must be called before the call to _init_tracker()
        patcher = pci_fakes.fake_pci_whitelist()
        self.addCleanup(patcher.stop)

        self._init_tracker()
        self.limits = self._limits()

    def _fake_compute_node_get_by_host_and_nodename(self, ctx, host, nodename):
        self.compute = self._create_compute_node()
        return self.compute

    def _fake_compute_node_get(self, ctx, id):
        return self.compute

    def _fake_compute_node_update(self, ctx, compute_node_id, values,
            prune_stats=False):
        self.update_call_count += 1
        self.updated = True
        self.compute.update(values)
        return self.compute

    def _fake_inventory_create(self, context, updates):
        if self._fake_inventories:
            new_id = max([x for x in self._fake_inventories.keys()])
        else:
            new_id = 1
        updates['id'] = new_id
        self._fake_inventories[new_id] = updates

        legacy = {
            fields.ResourceClass.VCPU: 'vcpus',
            fields.ResourceClass.MEMORY_MB: 'memory_mb',
            fields.ResourceClass.DISK_GB: 'local_gb',
        }
        legacy_key = legacy.get(fields.ResourceClass.from_index(
            updates['resource_class_id']))
        if legacy_key:
            inv_key = 'inv_%s' % legacy_key
            self.compute[inv_key] = updates['total']

        return updates

    def _fake_rp_create(self, context, updates):
        return dict(updates, id=1, name='foo', generation=1)

    def _fake_migration_get_in_progress_by_host_and_node(self, ctxt, host,
                                                         node):
        status = ['confirmed', 'reverted', 'error']
        migrations = []

        for migration in self._migrations.values():
            migration = obj_base.obj_to_primitive(migration)
            if migration['status'] in status:
                continue

            uuid = migration['instance_uuid']
            migration['instance'] = self._instances[uuid]
            migrations.append(migration)

        return migrations

    def _fake_migration_update(self, ctxt, migration_id, values):
        # cheat and assume there's only 1 migration present
        migration = list(self._migrations.values())[0]
        migration.update(values)
        return migration

    def _init_tracker(self):
        self.tracker.update_available_resource(self.context)

    def _limits(self, memory_mb=FAKE_VIRT_MEMORY_WITH_OVERHEAD,
            disk_gb=FAKE_VIRT_LOCAL_GB,
            vcpus=FAKE_VIRT_VCPUS,
            numa_topology=FAKE_VIRT_NUMA_TOPOLOGY_OVERHEAD):
        """Create limits dictionary used for oversubscribing resources."""

        return {
            'memory_mb': memory_mb,
            'disk_gb': disk_gb,
            'vcpu': vcpus,
            'numa_topology': numa_topology,
        }

    def assertEqualNUMAHostTopology(self, expected, got):
        attrs = ('cpuset', 'memory', 'id', 'cpu_usage', 'memory_usage')
        if None in (expected, got):
            if expected != got:
                raise AssertionError("Topologies don't match. Expected: "
                                     "%(expected)s, but got: %(got)s" %
                                     {'expected': expected, 'got': got})
            else:
                return

        if len(expected) != len(got):
            raise AssertionError("Topologies don't match due to different "
                                 "number of cells. Expected: "
                                 "%(expected)s, but got: %(got)s" %
                                 {'expected': expected, 'got': got})
        for exp_cell, got_cell in zip(expected.cells, got.cells):
            for attr in attrs:
                if getattr(exp_cell, attr) != getattr(got_cell, attr):
                    raise AssertionError("Topologies don't match. Expected: "
                                         "%(expected)s, but got: %(got)s" %
                                         {'expected': expected, 'got': got})

    def assertEqualPciDevicePool(self, expected, observed):
        self.assertEqual(expected.product_id, observed.product_id)
        self.assertEqual(expected.vendor_id, observed.vendor_id)
        self.assertEqual(expected.tags, observed.tags)
        self.assertEqual(expected.count, observed.count)

    def _assert(self, value, field, tracker=None):

        if tracker is None:
            tracker = self.tracker

        if field not in tracker.compute_node:
            raise test.TestingException(
                "'%(field)s' not in compute node." % {'field': field})
        x = getattr(tracker.compute_node, field)

        if field == 'numa_topology':
            self.assertEqualNUMAHostTopology(
                    value, objects.NUMATopology.obj_from_db_obj(x))
        else:
            self.assertEqual(value, x)


class _MoveClaimTestCase(BaseTrackerTestCase):

    def setUp(self):
        super(_MoveClaimTestCase, self).setUp()

        self.instance = self._fake_instance_obj()
        self.instance_type = self._fake_flavor_create()
        self.claim_method = self.tracker._move_claim

    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    def test_additive_claims(self, mock_get, mock_save):

        limits = self._limits(
              2 * FAKE_VIRT_MEMORY_WITH_OVERHEAD,
              2 * FAKE_VIRT_LOCAL_GB,
              2 * FAKE_VIRT_VCPUS)
        self.claim_method(
            self.context, self.instance, self.instance_type, limits=limits)
        mock_save.assert_called_once_with()
        mock_save.reset_mock()
        instance2 = self._fake_instance_obj()
        self.claim_method(
            self.context, instance2, self.instance_type, limits=limits)
        mock_save.assert_called_once_with()

        self._assert(2 * FAKE_VIRT_MEMORY_WITH_OVERHEAD, 'memory_mb_used')
        self._assert(2 * FAKE_VIRT_LOCAL_GB, 'local_gb_used')
        self._assert(2 * FAKE_VIRT_VCPUS, 'vcpus_used')


class ResizeClaimTestCase(_MoveClaimTestCase):
    def setUp(self):
        super(ResizeClaimTestCase, self).setUp()

        self.claim_method = self.tracker.resize_claim
