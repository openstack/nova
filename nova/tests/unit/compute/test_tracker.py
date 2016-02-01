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

import mock
from oslo_utils import units

from nova.compute import arch
from nova.compute import claims
from nova.compute import hv_type
from nova.compute import power_state
from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import vm_mode
from nova.compute import vm_states
from nova import exception as exc
from nova import objects
from nova.objects import base as obj_base
from nova import test

_VIRT_DRIVER_AVAIL_RESOURCES = {
    'vcpus': 4,
    'memory_mb': 512,
    'local_gb': 6,
    'vcpus_used': 0,
    'memory_mb_used': 0,
    'local_gb_used': 0,
    'hypervisor_type': 'fake',
    'hypervisor_version': 0,
    'hypervisor_hostname': 'fakehost',
    'cpu_info': '',
    'numa_topology': None,
}

_COMPUTE_NODE_FIXTURES = [
    objects.ComputeNode(
        id=1,
        host='fake-host',
        vcpus=_VIRT_DRIVER_AVAIL_RESOURCES['vcpus'],
        memory_mb=_VIRT_DRIVER_AVAIL_RESOURCES['memory_mb'],
        local_gb=_VIRT_DRIVER_AVAIL_RESOURCES['local_gb'],
        vcpus_used=_VIRT_DRIVER_AVAIL_RESOURCES['vcpus_used'],
        memory_mb_used=_VIRT_DRIVER_AVAIL_RESOURCES['memory_mb_used'],
        local_gb_used=_VIRT_DRIVER_AVAIL_RESOURCES['local_gb_used'],
        hypervisor_type='fake',
        hypervisor_version=0,
        hypervisor_hostname='fake-host',
        free_ram_mb=(_VIRT_DRIVER_AVAIL_RESOURCES['memory_mb'] -
                     _VIRT_DRIVER_AVAIL_RESOURCES['memory_mb_used']),
        free_disk_gb=(_VIRT_DRIVER_AVAIL_RESOURCES['local_gb'] -
                      _VIRT_DRIVER_AVAIL_RESOURCES['local_gb_used']),
        current_workload=0,
        running_vms=0,
        cpu_info='{}',
        disk_available_least=0,
        host_ip='1.1.1.1',
        supported_hv_specs=[
            objects.HVSpec.from_list([arch.I686, hv_type.KVM, vm_mode.HVM])
        ],
        metrics=None,
        pci_device_pools=None,
        extra_resources=None,
        stats={},
        numa_topology=None,
        cpu_allocation_ratio=16.0,
        ram_allocation_ratio=1.5,
        ),
]

_INSTANCE_TYPE_FIXTURES = {
    1: {
        'id': 1,
        'flavorid': 'fakeid-1',
        'name': 'fake1.small',
        'memory_mb': 128,
        'vcpus': 1,
        'root_gb': 1,
        'ephemeral_gb': 0,
        'swap': 0,
        'rxtx_factor': 0,
        'vcpu_weight': 1,
        'extra_specs': {},
    },
    2: {
        'id': 2,
        'flavorid': 'fakeid-2',
        'name': 'fake1.medium',
        'memory_mb': 256,
        'vcpus': 2,
        'root_gb': 5,
        'ephemeral_gb': 0,
        'swap': 0,
        'rxtx_factor': 0,
        'vcpu_weight': 1,
        'extra_specs': {},
    },
}


_INSTANCE_TYPE_OBJ_FIXTURES = {
    1: objects.Flavor(id=1, flavorid='fakeid-1', name='fake1.small',
                      memory_mb=128, vcpus=1, root_gb=1,
                      ephemeral_gb=0, swap=0, rxtx_factor=0,
                      vcpu_weight=1, extra_specs={}),
    2: objects.Flavor(id=2, flavorid='fakeid-2', name='fake1.medium',
                      memory_mb=256, vcpus=2, root_gb=5,
                      ephemeral_gb=0, swap=0, rxtx_factor=0,
                      vcpu_weight=1, extra_specs={}),
}


_2MB = 2 * units.Mi / units.Ki

_INSTANCE_NUMA_TOPOLOGIES = {
    '2mb': objects.InstanceNUMATopology(cells=[
        objects.InstanceNUMACell(
            id=0, cpuset=set([1]), memory=_2MB, pagesize=0),
        objects.InstanceNUMACell(
            id=1, cpuset=set([3]), memory=_2MB, pagesize=0)]),
}

_NUMA_LIMIT_TOPOLOGIES = {
    '2mb': objects.NUMATopologyLimits(id=0,
                                      cpu_allocation_ratio=1.0,
                                      ram_allocation_ratio=1.0),
}

_NUMA_PAGE_TOPOLOGIES = {
    '2kb*8': objects.NUMAPagesTopology(size_kb=2, total=8, used=0)
}

_NUMA_HOST_TOPOLOGIES = {
    '2mb': objects.NUMATopology(cells=[
        objects.NUMACell(id=0, cpuset=set([1, 2]), memory=_2MB,
                         cpu_usage=0, memory_usage=0,
                         mempages=[_NUMA_PAGE_TOPOLOGIES['2kb*8']],
                         siblings=[], pinned_cpus=set([])),
        objects.NUMACell(id=1, cpuset=set([3, 4]), memory=_2MB,
                         cpu_usage=0, memory_usage=0,
                         mempages=[_NUMA_PAGE_TOPOLOGIES['2kb*8']],
                         siblings=[], pinned_cpus=set([]))]),
}


_INSTANCE_FIXTURES = [
    objects.Instance(
        id=1,
        host=None,  # prevent RT trying to lazy-load this
        node=None,
        uuid='c17741a5-6f3d-44a8-ade8-773dc8c29124',
        memory_mb=_INSTANCE_TYPE_FIXTURES[1]['memory_mb'],
        vcpus=_INSTANCE_TYPE_FIXTURES[1]['vcpus'],
        root_gb=_INSTANCE_TYPE_FIXTURES[1]['root_gb'],
        ephemeral_gb=_INSTANCE_TYPE_FIXTURES[1]['ephemeral_gb'],
        numa_topology=_INSTANCE_NUMA_TOPOLOGIES['2mb'],
        instance_type_id=1,
        vm_state=vm_states.ACTIVE,
        power_state=power_state.RUNNING,
        task_state=None,
        os_type='fake-os',  # Used by the stats collector.
        project_id='fake-project',  # Used by the stats collector.
        flavor = _INSTANCE_TYPE_OBJ_FIXTURES[1],
        old_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[1],
        new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[1],
    ),
    objects.Instance(
        id=2,
        host=None,
        node=None,
        uuid='33805b54-dea6-47b8-acb2-22aeb1b57919',
        memory_mb=_INSTANCE_TYPE_FIXTURES[2]['memory_mb'],
        vcpus=_INSTANCE_TYPE_FIXTURES[2]['vcpus'],
        root_gb=_INSTANCE_TYPE_FIXTURES[2]['root_gb'],
        ephemeral_gb=_INSTANCE_TYPE_FIXTURES[2]['ephemeral_gb'],
        numa_topology=None,
        instance_type_id=2,
        vm_state=vm_states.DELETED,
        power_state=power_state.SHUTDOWN,
        task_state=None,
        os_type='fake-os',
        project_id='fake-project-2',
        flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
        old_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
        new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
    ),
]

_MIGRATION_FIXTURES = {
    # A migration that has only this compute node as the source host
    'source-only': objects.Migration(
        id=1,
        instance_uuid='f15ecfb0-9bf6-42db-9837-706eb2c4bf08',
        source_compute='fake-host',
        dest_compute='other-host',
        source_node='fake-node',
        dest_node='other-node',
        old_instance_type_id=1,
        new_instance_type_id=2,
        migration_type='resize',
        status='migrating'
    ),
    # A migration that has only this compute node as the dest host
    'dest-only': objects.Migration(
        id=2,
        instance_uuid='f6ed631a-8645-4b12-8e1e-2fff55795765',
        source_compute='other-host',
        dest_compute='fake-host',
        source_node='other-node',
        dest_node='fake-node',
        old_instance_type_id=1,
        new_instance_type_id=2,
        migration_type='resize',
        status='migrating'
    ),
    # A migration that has this compute node as both the source and dest host
    'source-and-dest': objects.Migration(
        id=3,
        instance_uuid='f4f0bfea-fe7e-4264-b598-01cb13ef1997',
        source_compute='fake-host',
        dest_compute='fake-host',
        source_node='fake-node',
        dest_node='fake-node',
        old_instance_type_id=1,
        new_instance_type_id=2,
        migration_type='resize',
        status='migrating'
    ),
    # A migration that has this compute node as destination and is an evac
    'dest-only-evac': objects.Migration(
        id=4,
        instance_uuid='077fb63a-bdc8-4330-90ef-f012082703dc',
        source_compute='other-host',
        dest_compute='fake-host',
        source_node='other-node',
        dest_node='fake-node',
        old_instance_type_id=2,
        new_instance_type_id=None,
        migration_type='evacuation',
        status='pre-migrating'
    ),
}

_MIGRATION_INSTANCE_FIXTURES = {
    # source-only
    'f15ecfb0-9bf6-42db-9837-706eb2c4bf08': objects.Instance(
        id=101,
        host=None,  # prevent RT trying to lazy-load this
        node=None,
        uuid='f15ecfb0-9bf6-42db-9837-706eb2c4bf08',
        memory_mb=_INSTANCE_TYPE_FIXTURES[1]['memory_mb'],
        vcpus=_INSTANCE_TYPE_FIXTURES[1]['vcpus'],
        root_gb=_INSTANCE_TYPE_FIXTURES[1]['root_gb'],
        ephemeral_gb=_INSTANCE_TYPE_FIXTURES[1]['ephemeral_gb'],
        numa_topology=_INSTANCE_NUMA_TOPOLOGIES['2mb'],
        instance_type_id=1,
        vm_state=vm_states.ACTIVE,
        power_state=power_state.RUNNING,
        task_state=task_states.RESIZE_MIGRATING,
        system_metadata={},
        os_type='fake-os',
        project_id='fake-project',
        flavor=_INSTANCE_TYPE_OBJ_FIXTURES[1],
        old_flavor=_INSTANCE_TYPE_OBJ_FIXTURES[1],
        new_flavor=_INSTANCE_TYPE_OBJ_FIXTURES[2],
    ),
    # dest-only
    'f6ed631a-8645-4b12-8e1e-2fff55795765': objects.Instance(
        id=102,
        host=None,  # prevent RT trying to lazy-load this
        node=None,
        uuid='f6ed631a-8645-4b12-8e1e-2fff55795765',
        memory_mb=_INSTANCE_TYPE_FIXTURES[2]['memory_mb'],
        vcpus=_INSTANCE_TYPE_FIXTURES[2]['vcpus'],
        root_gb=_INSTANCE_TYPE_FIXTURES[2]['root_gb'],
        ephemeral_gb=_INSTANCE_TYPE_FIXTURES[2]['ephemeral_gb'],
        numa_topology=None,
        instance_type_id=2,
        vm_state=vm_states.ACTIVE,
        power_state=power_state.RUNNING,
        task_state=task_states.RESIZE_MIGRATING,
        system_metadata={},
        os_type='fake-os',
        project_id='fake-project',
        flavor=_INSTANCE_TYPE_OBJ_FIXTURES[2],
        old_flavor=_INSTANCE_TYPE_OBJ_FIXTURES[1],
        new_flavor=_INSTANCE_TYPE_OBJ_FIXTURES[2],
    ),
    # source-and-dest
    'f4f0bfea-fe7e-4264-b598-01cb13ef1997': objects.Instance(
        id=3,
        host=None,  # prevent RT trying to lazy-load this
        node=None,
        uuid='f4f0bfea-fe7e-4264-b598-01cb13ef1997',
        memory_mb=_INSTANCE_TYPE_FIXTURES[2]['memory_mb'],
        vcpus=_INSTANCE_TYPE_FIXTURES[2]['vcpus'],
        root_gb=_INSTANCE_TYPE_FIXTURES[2]['root_gb'],
        ephemeral_gb=_INSTANCE_TYPE_FIXTURES[2]['ephemeral_gb'],
        numa_topology=None,
        instance_type_id=2,
        vm_state=vm_states.ACTIVE,
        power_state=power_state.RUNNING,
        task_state=task_states.RESIZE_MIGRATING,
        system_metadata={},
        os_type='fake-os',
        project_id='fake-project',
        flavor=_INSTANCE_TYPE_OBJ_FIXTURES[2],
        old_flavor=_INSTANCE_TYPE_OBJ_FIXTURES[1],
        new_flavor=_INSTANCE_TYPE_OBJ_FIXTURES[2],
    ),
    # dest-only-evac
    '077fb63a-bdc8-4330-90ef-f012082703dc': objects.Instance(
        id=102,
        host=None,  # prevent RT trying to lazy-load this
        node=None,
        uuid='077fb63a-bdc8-4330-90ef-f012082703dc',
        memory_mb=_INSTANCE_TYPE_FIXTURES[2]['memory_mb'],
        vcpus=_INSTANCE_TYPE_FIXTURES[2]['vcpus'],
        root_gb=_INSTANCE_TYPE_FIXTURES[2]['root_gb'],
        ephemeral_gb=_INSTANCE_TYPE_FIXTURES[2]['ephemeral_gb'],
        numa_topology=None,
        instance_type_id=2,
        vm_state=vm_states.ACTIVE,
        power_state=power_state.RUNNING,
        task_state=task_states.REBUILDING,
        system_metadata={},
        os_type='fake-os',
        project_id='fake-project',
        flavor=_INSTANCE_TYPE_OBJ_FIXTURES[2],
        old_flavor=_INSTANCE_TYPE_OBJ_FIXTURES[1],
        new_flavor=_INSTANCE_TYPE_OBJ_FIXTURES[2],
    ),
}

_MIGRATION_CONTEXT_FIXTURES = {
    'f4f0bfea-fe7e-4264-b598-01cb13ef1997': objects.MigrationContext(
        instance_uuid='f4f0bfea-fe7e-4264-b598-01cb13ef1997',
        migration_id=3,
        new_numa_topology=None,
        old_numa_topology=None),
    'c17741a5-6f3d-44a8-ade8-773dc8c29124': objects.MigrationContext(
        instance_uuid='c17741a5-6f3d-44a8-ade8-773dc8c29124',
        migration_id=3,
        new_numa_topology=None,
        old_numa_topology=None),
    'f15ecfb0-9bf6-42db-9837-706eb2c4bf08': objects.MigrationContext(
        instance_uuid='f15ecfb0-9bf6-42db-9837-706eb2c4bf08',
        migration_id=1,
        new_numa_topology=None,
        old_numa_topology=_INSTANCE_NUMA_TOPOLOGIES['2mb']),
    'f6ed631a-8645-4b12-8e1e-2fff55795765': objects.MigrationContext(
        instance_uuid='f6ed631a-8645-4b12-8e1e-2fff55795765',
        migration_id=2,
        new_numa_topology=_INSTANCE_NUMA_TOPOLOGIES['2mb'],
        old_numa_topology=None),
    '077fb63a-bdc8-4330-90ef-f012082703dc': objects.MigrationContext(
        instance_uuid='077fb63a-bdc8-4330-90ef-f012082703dc',
        migration_id=2,
        new_numa_topology=None,
        old_numa_topology=None),
}


def overhead_zero(instance):
    # Emulate that the driver does not adjust the memory
    # of the instance...
    return {
        'memory_mb': 0
    }


def setup_rt(hostname, nodename, virt_resources=_VIRT_DRIVER_AVAIL_RESOURCES,
             estimate_overhead=overhead_zero):
    """Sets up the resource tracker instance with mock fixtures.

    :param virt_resources: Optional override of the resource representation
                           returned by the virt driver's
                           `get_available_resource()` method.
    :param estimate_overhead: Optional override of a function that should
                              return overhead of memory given an instance
                              object. Defaults to returning zero overhead.
    """
    sched_client_mock = mock.MagicMock()
    notifier_mock = mock.MagicMock()
    vd = mock.MagicMock()
    # Make sure we don't change any global fixtures during tests
    virt_resources = copy.deepcopy(virt_resources)
    vd.get_available_resource.return_value = virt_resources
    vd.estimate_instance_overhead.side_effect = estimate_overhead

    with test.nested(
            mock.patch('nova.scheduler.client.SchedulerClient',
                       return_value=sched_client_mock),
            mock.patch('nova.rpc.get_notifier', return_value=notifier_mock)):
        rt = resource_tracker.ResourceTracker(hostname, vd, nodename)
    return (rt, sched_client_mock, vd)


class BaseTestCase(test.NoDBTestCase):

    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.rt = None
        self.flags(my_ip='1.1.1.1')

    def _setup_rt(self, virt_resources=_VIRT_DRIVER_AVAIL_RESOURCES,
                  estimate_overhead=overhead_zero):
        (self.rt, self.sched_client_mock,
         self.driver_mock) = setup_rt(
                 'fake-host', 'fake-node', virt_resources, estimate_overhead)


class TestUpdateAvailableResources(BaseTestCase):

    def _update_available_resources(self):
        # We test RT._update separately, since the complexity
        # of the update_available_resource() function is high enough as
        # it is, we just want to focus here on testing the resources
        # parameter that update_available_resource() eventually passes
        # to _update().
        with mock.patch.object(self.rt, '_update') as update_mock:
            self.rt.update_available_resource(mock.sentinel.ctx)
        return update_mock

    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_no_migrations_no_reserved(self, get_mock, migr_mock,
                                                    get_cn_mock):
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)
        self._setup_rt()

        get_mock.return_value = []
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        update_mock = self._update_available_resources()

        vd = self.driver_mock
        vd.get_available_resource.assert_called_once_with('fake-node')
        get_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                         'fake-node',
                                         expected_attrs=[
                                             'system_metadata',
                                             'numa_topology',
                                             'flavor',
                                             'migration_context'])
        get_cn_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                            'fake-node')
        migr_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                          'fake-node')

        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected_resources.update({
            # host is added in update_available_resources()
            # before calling _update()
            'host': 'fake-host',
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            'free_disk_gb': 6,
            'hypervisor_version': 0,
            'local_gb': 6,
            'free_ram_mb': 512,
            'memory_mb_used': 0,
            'pci_device_pools': objects.PciDevicePoolList(),
            'vcpus_used': 0,
            'hypervisor_type': 'fake',
            'local_gb_used': 0,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        })
        update_mock.assert_called_once_with(mock.sentinel.ctx)
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 self.rt.compute_node))

    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_no_migrations_reserved_disk_and_ram(
            self, get_mock, migr_mock, get_cn_mock):
        self.flags(reserved_host_disk_mb=1024,
                   reserved_host_memory_mb=512)
        self._setup_rt()

        get_mock.return_value = []
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                            'fake-node')
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected_resources.update({
            # host is added in update_available_resources()
            # before calling _update()
            'host': 'fake-host',
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            'free_disk_gb': 5,  # 6GB avail - 1 GB reserved
            'hypervisor_version': 0,
            'local_gb': 6,
            'free_ram_mb': 0,  # 512MB avail - 512MB reserved
            'memory_mb_used': 512,  # 0MB used + 512MB reserved
            'pci_device_pools': objects.PciDevicePoolList(),
            'vcpus_used': 0,
            'hypervisor_type': 'fake',
            'local_gb_used': 1,  # 0GB used + 1 GB reserved
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        })
        update_mock.assert_called_once_with(mock.sentinel.ctx)
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 self.rt.compute_node))

    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_some_instances_no_migrations(self, get_mock, migr_mock,
                                          get_cn_mock):
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        # Setup virt resources to match used resources to number
        # of defined instances on the hypervisor
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(vcpus_used=1,
                              memory_mb_used=128,
                              local_gb_used=1)
        self._setup_rt(virt_resources=virt_resources)

        get_mock.return_value = _INSTANCE_FIXTURES
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                            'fake-node')
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected_resources.update({
            # host is added in update_available_resources()
            # before calling _update()
            'host': 'fake-host',
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            'free_disk_gb': 5,  # 6 - 1 used
            'hypervisor_version': 0,
            'local_gb': 6,
            'free_ram_mb': 384,  # 512 - 128 used
            'memory_mb_used': 128,
            'pci_device_pools': objects.PciDevicePoolList(),
            'vcpus_used': 1,
            'hypervisor_type': 'fake',
            'local_gb_used': 1,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 1  # One active instance
        })
        update_mock.assert_called_once_with(mock.sentinel.ctx)
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 self.rt.compute_node))

    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_orphaned_instances_no_migrations(self, get_mock, migr_mock,
                                              get_cn_mock):
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        # Setup virt resources to match used resources to number
        # of defined instances on the hypervisor
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(memory_mb_used=64)
        self._setup_rt(virt_resources=virt_resources)

        get_mock.return_value = []
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        # Orphaned instances are those that the virt driver has on
        # record as consuming resources on the compute node, but the
        # Nova database has no record of the instance being active
        # on the host. For some reason, the resource tracker only
        # considers orphaned instance's memory usage in its calculations
        # of free resources...
        orphaned_usages = {
            '71ed7ef6-9d2e-4c65-9f4e-90bb6b76261d': {
                # Yes, the return result format of get_per_instance_usage
                # is indeed this stupid and redundant. Also note that the
                # libvirt driver just returns an empty dict always for this
                # method and so who the heck knows whether this stuff
                # actually works.
                'uuid': '71ed7ef6-9d2e-4c65-9f4e-90bb6b76261d',
                'memory_mb': 64
            }
        }
        vd = self.driver_mock
        vd.get_per_instance_usage.return_value = orphaned_usages

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                            'fake-node')
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected_resources.update({
            # host is added in update_available_resources()
            # before calling _update()
            'host': 'fake-host',
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            'free_disk_gb': 6,
            'hypervisor_version': 0,
            'local_gb': 6,
            'free_ram_mb': 448,  # 512 - 64 orphaned usage
            'memory_mb_used': 64,
            'pci_device_pools': objects.PciDevicePoolList(),
            'vcpus_used': 0,
            'hypervisor_type': 'fake',
            'local_gb_used': 0,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            # Yep, for some reason, orphaned instances are not counted
            # as running VMs...
            'running_vms': 0
        })
        update_mock.assert_called_once_with(mock.sentinel.ctx)
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 self.rt.compute_node))

    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_source_migration(self, get_mock, get_inst_mock,
                                           migr_mock, get_cn_mock):
        # We test the behavior of update_available_resource() when
        # there is an active migration that involves this compute node
        # as the source host not the destination host, and the resource
        # tracker does not have any instances assigned to it. This is
        # the case when a migration from this compute host to another
        # has been completed, but the user has not confirmed the resize
        # yet, so the resource tracker must continue to keep the resources
        # for the original instance type available on the source compute
        # node in case of a revert of the resize.
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        # Setup virt resources to match used resources to number
        # of defined instances on the hypervisor
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(vcpus_used=4,
                              memory_mb_used=128,
                              local_gb_used=1)
        self._setup_rt(virt_resources=virt_resources)

        get_mock.return_value = []
        migr_obj = _MIGRATION_FIXTURES['source-only']
        migr_mock.return_value = [migr_obj]
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]
        # Migration.instance property is accessed in the migration
        # processing code, and this property calls
        # objects.Instance.get_by_uuid, so we have the migration return
        inst_uuid = migr_obj.instance_uuid
        instance = _MIGRATION_INSTANCE_FIXTURES[inst_uuid].obj_clone()
        get_inst_mock.return_value = instance
        instance.migration_context = _MIGRATION_CONTEXT_FIXTURES[inst_uuid]

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                            'fake-node')
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected_resources.update({
            # host is added in update_available_resources()
            # before calling _update()
            'host': 'fake-host',
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            'free_disk_gb': 5,
            'hypervisor_version': 0,
            'local_gb': 6,
            'free_ram_mb': 384,  # 512 total - 128 for possible revert of orig
            'memory_mb_used': 128,  # 128 possible revert amount
            'pci_device_pools': objects.PciDevicePoolList(),
            'vcpus_used': 1,
            'hypervisor_type': 'fake',
            'local_gb_used': 1,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        })
        update_mock.assert_called_once_with(mock.sentinel.ctx)
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 self.rt.compute_node))

    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_dest_migration(self, get_mock, get_inst_mock,
                                         migr_mock, get_cn_mock):
        # We test the behavior of update_available_resource() when
        # there is an active migration that involves this compute node
        # as the destination host not the source host, and the resource
        # tracker does not yet have any instances assigned to it. This is
        # the case when a migration to this compute host from another host
        # is in progress, but the user has not confirmed the resize
        # yet, so the resource tracker must reserve the resources
        # for the possibly-to-be-confirmed instance's instance type
        # node in case of a confirm of the resize.
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        # Setup virt resources to match used resources to number
        # of defined instances on the hypervisor
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(vcpus_used=2,
                              memory_mb_used=256,
                              local_gb_used=5)
        self._setup_rt(virt_resources=virt_resources)

        get_mock.return_value = []
        migr_obj = _MIGRATION_FIXTURES['dest-only']
        migr_mock.return_value = [migr_obj]
        inst_uuid = migr_obj.instance_uuid
        instance = _MIGRATION_INSTANCE_FIXTURES[inst_uuid].obj_clone()
        get_inst_mock.return_value = instance
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]
        instance.migration_context = _MIGRATION_CONTEXT_FIXTURES[inst_uuid]

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                            'fake-node')
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected_resources.update({
            # host is added in update_available_resources()
            # before calling _update()
            'host': 'fake-host',
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            'free_disk_gb': 1,
            'hypervisor_version': 0,
            'local_gb': 6,
            'free_ram_mb': 256,  # 512 total - 256 for possible confirm of new
            'memory_mb_used': 256,  # 256 possible confirmed amount
            'pci_device_pools': objects.PciDevicePoolList(),
            'vcpus_used': 2,
            'hypervisor_type': 'fake',
            'local_gb_used': 5,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        })
        update_mock.assert_called_once_with(mock.sentinel.ctx)
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 self.rt.compute_node))

    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_dest_evacuation(self, get_mock, get_inst_mock,
                                          migr_mock, get_cn_mock):
        # We test the behavior of update_available_resource() when
        # there is an active evacuation that involves this compute node
        # as the destination host not the source host, and the resource
        # tracker does not yet have any instances assigned to it. This is
        # the case when a migration to this compute host from another host
        # is in progress, but not finished yet.
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        # Setup virt resources to match used resources to number
        # of defined instances on the hypervisor
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(vcpus_used=2,
                              memory_mb_used=256,
                              local_gb_used=5)
        self._setup_rt(virt_resources=virt_resources)

        get_mock.return_value = []
        migr_obj = _MIGRATION_FIXTURES['dest-only-evac']
        migr_mock.return_value = [migr_obj]
        inst_uuid = migr_obj.instance_uuid
        instance = _MIGRATION_INSTANCE_FIXTURES[inst_uuid].obj_clone()
        get_inst_mock.return_value = instance
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]
        instance.migration_context = _MIGRATION_CONTEXT_FIXTURES[inst_uuid]

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                            'fake-node')
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected_resources.update({
            # host is added in update_available_resources()
            # before calling _update()
            'host': 'fake-host',
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            'free_disk_gb': 1,
            'hypervisor_version': 0,
            'local_gb': 6,
            'free_ram_mb': 256,  # 512 total - 256 for possible confirm of new
            'memory_mb_used': 256,  # 256 possible confirmed amount
            'pci_device_pools': objects.PciDevicePoolList(),
            'vcpus_used': 2,
            'hypervisor_type': 'fake',
            'local_gb_used': 5,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        })
        update_mock.assert_called_once_with(mock.sentinel.ctx)
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 self.rt.compute_node))

    @mock.patch('nova.objects.MigrationContext.get_by_instance_uuid',
                return_value=None)
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_some_instances_source_and_dest_migration(self, get_mock,
                                                      get_inst_mock, migr_mock,
                                                      get_cn_mock,
                                                      get_mig_ctxt_mock):
        # We test the behavior of update_available_resource() when
        # there is an active migration that involves this compute node
        # as the destination host AND the source host, and the resource
        # tracker has a few instances assigned to it, including the
        # instance that is resizing to this same compute node. The tracking
        # of resource amounts takes into account both the old and new
        # resize instance types as taking up space on the node.
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        # Setup virt resources to match used resources to number
        # of defined instances on the hypervisor
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(vcpus_used=4,
                              memory_mb_used=512,
                              local_gb_used=7)
        self._setup_rt(virt_resources=virt_resources)

        migr_obj = _MIGRATION_FIXTURES['source-and-dest']
        migr_mock.return_value = [migr_obj]
        inst_uuid = migr_obj.instance_uuid
        # The resizing instance has already had its instance type
        # changed to the *new* instance type (the bigger one, instance type 2)
        resizing_instance = _MIGRATION_INSTANCE_FIXTURES[inst_uuid].obj_clone()
        resizing_instance.migration_context = (
            _MIGRATION_CONTEXT_FIXTURES[resizing_instance.uuid])
        all_instances = _INSTANCE_FIXTURES + [resizing_instance]
        get_mock.return_value = all_instances
        get_inst_mock.return_value = resizing_instance
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                            'fake-node')
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected_resources.update({
            # host is added in update_available_resources()
            # before calling _update()
            'host': 'fake-host',
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            # 6 total - 1G existing - 5G new flav - 1G old flav
            'free_disk_gb': -1,
            'hypervisor_version': 0,
            'local_gb': 6,
            # 512 total - 128 existing - 256 new flav - 128 old flav
            'free_ram_mb': 0,
            'memory_mb_used': 512,  # 128 exist + 256 new flav + 128 old flav
            'pci_device_pools': objects.PciDevicePoolList(),
            'vcpus_used': 4,
            'hypervisor_type': 'fake',
            'local_gb_used': 7,  # 1G existing, 5G new flav + 1 old flav
            'memory_mb': 512,
            'current_workload': 1,  # One migrating instance...
            'vcpus': 4,
            'running_vms': 2
        })
        update_mock.assert_called_once_with(mock.sentinel.ctx)
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 self.rt.compute_node))


class TestInitComputeNode(BaseTestCase):

    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    def test_no_op_init_compute_node(self, get_mock, service_mock,
                                     create_mock):
        self._setup_rt()

        resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        compute_node = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        self.rt.compute_node = compute_node

        self.rt._init_compute_node(mock.sentinel.ctx, resources)

        self.assertFalse(service_mock.called)
        self.assertFalse(get_mock.called)
        self.assertFalse(create_mock.called)
        self.assertFalse(self.rt.disabled)

    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    def test_compute_node_loaded(self, get_mock, create_mock):
        self._setup_rt()

        def fake_get_node(_ctx, host, node):
            res = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
            return res

        get_mock.side_effect = fake_get_node
        resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)

        self.rt._init_compute_node(mock.sentinel.ctx, resources)

        get_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                         'fake-node')
        self.assertFalse(create_mock.called)
        self.assertFalse(self.rt.disabled)

    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    def test_compute_node_created_on_empty(self, get_mock, create_mock):
        self._setup_rt()

        get_mock.side_effect = exc.NotFound
        cpu_alloc_ratio = 1.0
        ram_alloc_ratio = 1.0

        resources = {
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': 'fakehost',
            'free_disk_gb': 6,
            'hypervisor_version': 0,
            'local_gb': 6,
            'free_ram_mb': 512,
            'memory_mb_used': 0,
            'pci_device_pools': [],
            'vcpus_used': 0,
            'hypervisor_type': 'fake',
            'local_gb_used': 0,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0,
            'pci_passthrough_devices': '[]'
        }
        # The expected compute represents the initial values used
        # when creating a compute node.
        expected_compute = objects.ComputeNode(
            host_ip=resources['host_ip'],
            vcpus=resources['vcpus'],
            memory_mb=resources['memory_mb'],
            local_gb=resources['local_gb'],
            cpu_info=resources['cpu_info'],
            vcpus_used=resources['vcpus_used'],
            memory_mb_used=resources['memory_mb_used'],
            local_gb_used=resources['local_gb_used'],
            numa_topology=resources['numa_topology'],
            hypervisor_type=resources['hypervisor_type'],
            hypervisor_version=resources['hypervisor_version'],
            hypervisor_hostname=resources['hypervisor_hostname'],
            # NOTE(sbauza): ResourceTracker adds host field
            host='fake-host',
            # NOTE(sbauza): ResourceTracker adds CONF allocation ratios
            ram_allocation_ratio=ram_alloc_ratio,
            cpu_allocation_ratio=cpu_alloc_ratio,
        )

        # Forcing the flags to the values we know
        self.rt.ram_allocation_ratio = ram_alloc_ratio
        self.rt.cpu_allocation_ratio = cpu_alloc_ratio

        self.rt._init_compute_node(mock.sentinel.ctx, resources)

        self.assertFalse(self.rt.disabled)
        get_mock.assert_called_once_with(mock.sentinel.ctx, 'fake-host',
                                         'fake-node')
        create_mock.assert_called_once_with()
        self.assertTrue(obj_base.obj_equal_prims(expected_compute,
                                                 self.rt.compute_node))

    def test_copy_resources_adds_allocation_ratios(self):
        self.flags(cpu_allocation_ratio=4.0, ram_allocation_ratio=3.0)
        self._setup_rt()

        resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        compute_node = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        self.rt.compute_node = compute_node

        self.rt._copy_resources(resources)
        self.assertEqual(4.0, self.rt.compute_node.cpu_allocation_ratio)
        self.assertEqual(3.0, self.rt.compute_node.ram_allocation_ratio)


class TestUpdateComputeNode(BaseTestCase):

    @mock.patch('nova.objects.Service.get_by_compute_host')
    def test_existing_compute_node_updated_same_resources(self, service_mock):
        self._setup_rt()

        # This is the same set of resources as the fixture, deliberately. We
        # are checking below to see that update_resource_stats() is not
        # needlessly called when the resources don't actually change.
        compute = objects.ComputeNode(
            host_ip='1.1.1.1',
            numa_topology=None,
            metrics='[]',
            cpu_info='',
            hypervisor_hostname='fakehost',
            free_disk_gb=6,
            hypervisor_version=0,
            local_gb=6,
            free_ram_mb=512,
            memory_mb_used=0,
            pci_device_pools=objects.PciDevicePoolList(),
            vcpus_used=0,
            hypervisor_type='fake',
            local_gb_used=0,
            memory_mb=512,
            current_workload=0,
            vcpus=4,
            running_vms=0,
            cpu_allocation_ratio=16.0,
            ram_allocation_ratio=1.5,
        )
        self.rt.compute_node = compute
        self.rt._update(mock.sentinel.ctx)

        self.assertFalse(self.rt.disabled)
        self.assertFalse(service_mock.called)

        # The above call to _update() will populate the
        # RT.old_resources collection with the resources. Here, we check that
        # if we call _update() again with the same resources, that
        # the scheduler client won't be called again to update those
        # (unchanged) resources for the compute node
        self.sched_client_mock.reset_mock()
        urs_mock = self.sched_client_mock.update_resource_stats
        self.rt._update(mock.sentinel.ctx)
        self.assertFalse(urs_mock.called)

    @mock.patch('nova.objects.Service.get_by_compute_host')
    def test_existing_compute_node_updated_new_resources(self, service_mock):
        self._setup_rt()

        # Deliberately changing local_gb_used, vcpus_used, and memory_mb_used
        # below to be different from the compute node fixture's base usages.
        # We want to check that the code paths update the stored compute node
        # usage records with what is supplied to _update().
        compute = objects.ComputeNode(
            host='fake-host',
            host_ip='1.1.1.1',
            numa_topology=None,
            metrics='[]',
            cpu_info='',
            hypervisor_hostname='fakehost',
            free_disk_gb=2,
            hypervisor_version=0,
            local_gb=6,
            free_ram_mb=384,
            memory_mb_used=128,
            pci_device_pools=objects.PciDevicePoolList(),
            vcpus_used=2,
            hypervisor_type='fake',
            local_gb_used=4,
            memory_mb=512,
            current_workload=0,
            vcpus=4,
            running_vms=0,
            cpu_allocation_ratio=16.0,
            ram_allocation_ratio=1.5,
        )
        self.rt.compute_node = compute
        self.rt._update(mock.sentinel.ctx)

        self.assertFalse(self.rt.disabled)
        self.assertFalse(service_mock.called)
        urs_mock = self.sched_client_mock.update_resource_stats
        urs_mock.assert_called_once_with(self.rt.compute_node)


class TestInstanceClaim(BaseTestCase):

    def setUp(self):
        super(TestInstanceClaim, self).setUp()
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)

        self._setup_rt()
        self.rt.compute_node = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])

        # not using mock.sentinel.ctx because instance_claim calls #elevated
        self.ctx = mock.MagicMock()
        self.elevated = mock.MagicMock()
        self.ctx.elevated.return_value = self.elevated

        self.instance = _INSTANCE_FIXTURES[0].obj_clone()

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

    def test_claim_disabled(self):
        self.rt.compute_node = None
        self.assertTrue(self.rt.disabled)

        with mock.patch.object(self.instance, 'save'):
            claim = self.rt.instance_claim(mock.sentinel.ctx, self.instance,
                                           None)

        self.assertEqual(self.rt.host, self.instance.host)
        self.assertEqual(self.rt.host, self.instance.launched_on)
        self.assertEqual(self.rt.nodename, self.instance.node)
        self.assertIsInstance(claim, claims.NopClaim)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_update_usage_with_claim(self, migr_mock, pci_mock):
        # Test that RT.update_usage() only changes the compute node
        # resources if there has been a claim first.
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])

        expected = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        self.rt.update_usage(self.ctx, self.instance)
        self.assertTrue(obj_base.obj_equal_prims(expected,
                                                 self.rt.compute_node))

        disk_used = self.instance.root_gb + self.instance.ephemeral_gb
        expected.update({
            'local_gb_used': disk_used,
            'memory_mb_used': self.instance.memory_mb,
            'free_disk_gb': expected['local_gb'] - disk_used,
            "free_ram_mb": expected['memory_mb'] - self.instance.memory_mb,
            'running_vms': 1,
            'vcpus_used': 1,
            'pci_device_pools': objects.PciDevicePoolList(),
        })
        with mock.patch.object(self.rt, '_update') as update_mock:
            with mock.patch.object(self.instance, 'save'):
                self.rt.instance_claim(self.ctx, self.instance, None)
            update_mock.assert_called_once_with(self.elevated)
            self.assertTrue(obj_base.obj_equal_prims(expected,
                                                     self.rt.compute_node))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_claim(self, migr_mock, pci_mock):
        self.assertFalse(self.rt.disabled)

        pci_mock.return_value = objects.InstancePCIRequests(requests=[])

        disk_used = self.instance.root_gb + self.instance.ephemeral_gb
        expected = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        expected.update({
            'local_gb_used': disk_used,
            'memory_mb_used': self.instance.memory_mb,
            'free_disk_gb': expected['local_gb'] - disk_used,
            "free_ram_mb": expected['memory_mb'] - self.instance.memory_mb,
            'running_vms': 1,
            'vcpus_used': 1,
            'pci_device_pools': objects.PciDevicePoolList(),
        })
        with mock.patch.object(self.rt, '_update') as update_mock:
            with mock.patch.object(self.instance, 'save'):
                self.rt.instance_claim(self.ctx, self.instance, None)
            update_mock.assert_called_once_with(self.elevated)
            self.assertTrue(obj_base.obj_equal_prims(expected,
                                                     self.rt.compute_node))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_claim_abort_context_manager(self, migr_mock, pci_mock):
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])

        self.assertEqual(0, self.rt.compute_node.local_gb_used)
        self.assertEqual(0, self.rt.compute_node.memory_mb_used)
        self.assertEqual(0, self.rt.compute_node.running_vms)

        @mock.patch.object(self.instance, 'save')
        def _doit(mock_save):
            with self.rt.instance_claim(self.ctx, self.instance, None):
                # Raise an exception. Just make sure below that the abort()
                # method of the claim object was called (and the resulting
                # resources reset to the pre-claimed amounts)
                raise test.TestingException()

        self.assertRaises(test.TestingException, _doit)

        # Assert that the resources claimed by the Claim() constructor
        # are returned to the resource tracker due to the claim's abort()
        # method being called when triggered by the exception raised above.
        self.assertEqual(0, self.rt.compute_node.local_gb_used)
        self.assertEqual(0, self.rt.compute_node.memory_mb_used)
        self.assertEqual(0, self.rt.compute_node.running_vms)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_claim_abort(self, migr_mock, pci_mock):
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])
        disk_used = self.instance.root_gb + self.instance.ephemeral_gb

        with mock.patch.object(self.instance, 'save'):
            claim = self.rt.instance_claim(self.ctx, self.instance, None)

        self.assertEqual(disk_used, self.rt.compute_node.local_gb_used)
        self.assertEqual(self.instance.memory_mb,
                         self.rt.compute_node.memory_mb_used)
        self.assertEqual(1, self.rt.compute_node.running_vms)

        claim.abort()

        self.assertEqual(0, self.rt.compute_node.local_gb_used)
        self.assertEqual(0, self.rt.compute_node.memory_mb_used)
        self.assertEqual(0, self.rt.compute_node.running_vms)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_claim_limits(self, migr_mock, pci_mock):
        self.assertFalse(self.rt.disabled)

        pci_mock.return_value = objects.InstancePCIRequests(requests=[])

        good_limits = {
            'memory_mb': _COMPUTE_NODE_FIXTURES[0]['memory_mb'],
            'disk_gb': _COMPUTE_NODE_FIXTURES[0]['local_gb'],
            'vcpu': _COMPUTE_NODE_FIXTURES[0]['vcpus'],
        }
        for key in good_limits.keys():
            bad_limits = copy.deepcopy(good_limits)
            bad_limits[key] = 0

            self.assertRaises(exc.ComputeResourcesUnavailable,
                    self.rt.instance_claim,
                    self.ctx, self.instance, bad_limits)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_claim_numa(self, migr_mock, pci_mock):
        self.assertFalse(self.rt.disabled)

        pci_mock.return_value = objects.InstancePCIRequests(requests=[])

        self.instance.numa_topology = _INSTANCE_NUMA_TOPOLOGIES['2mb']
        host_topology = _NUMA_HOST_TOPOLOGIES['2mb']
        self.rt.compute_node['numa_topology'] = host_topology._to_json()
        limits = {'numa_topology': _NUMA_LIMIT_TOPOLOGIES['2mb']}

        expected_numa = copy.deepcopy(host_topology)
        for cell in expected_numa.cells:
            cell.memory_usage += _2MB
            cell.cpu_usage += 1
        with mock.patch.object(self.rt, '_update') as update_mock:
            with mock.patch.object(self.instance, 'save'):
                self.rt.instance_claim(self.ctx, self.instance, limits)
            update_mock.assert_called_once_with(self.ctx.elevated())
            updated_compute_node = self.rt.compute_node
            new_numa = updated_compute_node['numa_topology']
            new_numa = objects.NUMATopology.obj_from_db_obj(new_numa)
            self.assertEqualNUMAHostTopology(expected_numa, new_numa)


@mock.patch('nova.objects.Instance.save')
@mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
@mock.patch('nova.objects.Instance.get_by_uuid')
@mock.patch('nova.objects.InstanceList.get_by_host_and_node')
@mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
class TestMoveClaim(BaseTestCase):
    def setUp(self):
        super(TestMoveClaim, self).setUp()

        self._setup_rt()
        self.rt.compute_node = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])

        self.instance = _INSTANCE_FIXTURES[0].obj_clone()
        self.flavor = _INSTANCE_TYPE_OBJ_FIXTURES[1]
        self.limits = {}

        # not using mock.sentinel.ctx because resize_claim calls #elevated
        self.ctx = mock.MagicMock()
        self.elevated = mock.MagicMock()
        self.ctx.elevated.return_value = self.elevated

        # Initialise extensible resource trackers
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        with test.nested(
            mock.patch('nova.objects.InstanceList.get_by_host_and_node'),
            mock.patch('nova.objects.MigrationList.'
                       'get_in_progress_by_host_and_node')
        ) as (inst_list_mock, migr_mock):
            inst_list_mock.return_value = objects.InstanceList(objects=[])
            migr_mock.return_value = objects.MigrationList(objects=[])
            self.rt.update_available_resource(self.ctx)

    def register_mocks(self, pci_mock, inst_list_mock, inst_by_uuid,
            migr_mock, inst_save_mock):
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])
        self.inst_list_mock = inst_list_mock
        self.inst_by_uuid = inst_by_uuid
        self.migr_mock = migr_mock
        self.inst_save_mock = inst_save_mock

    def audit(self, rt, instances, migrations, migr_inst):
        self.inst_list_mock.return_value = \
                objects.InstanceList(objects=instances)
        self.migr_mock.return_value = \
                objects.MigrationList(objects=migrations)
        self.inst_by_uuid.return_value = migr_inst
        rt.update_available_resource(self.ctx)

    def assertEqual(self, expected, actual):
        if type(expected) != dict or type(actual) != dict:
            super(TestMoveClaim, self).assertEqual(expected, actual)
            return
        fail = False
        for k, e in expected.items():
            a = actual[k]
            if e != a:
                print("%s: %s != %s" % (k, e, a))
                fail = True
        if fail:
            self.fail()

    def adjust_expected(self, expected, flavor):
        disk_used = flavor['root_gb'] + flavor['ephemeral_gb']
        expected.free_disk_gb -= disk_used
        expected.local_gb_used += disk_used
        expected.free_ram_mb -= flavor['memory_mb']
        expected.memory_mb_used += flavor['memory_mb']
        expected.vcpus_used += flavor['vcpus']

    @mock.patch('nova.objects.Flavor.get_by_id')
    def test_claim(self, flavor_mock, pci_mock, inst_list_mock, inst_by_uuid,
            migr_mock, inst_save_mock):
        """Resize self.instance and check that the expected quantities of each
        resource have been consumed.
        """

        self.register_mocks(pci_mock, inst_list_mock, inst_by_uuid, migr_mock,
                            inst_save_mock)
        self.driver_mock.get_host_ip_addr.return_value = "fake-ip"
        flavor_mock.return_value = objects.Flavor(**self.flavor)
        mig_context_obj = _MIGRATION_CONTEXT_FIXTURES[self.instance.uuid]
        self.instance.migration_context = mig_context_obj

        expected = copy.deepcopy(self.rt.compute_node)
        self.adjust_expected(expected, self.flavor)

        create_mig_mock = mock.patch.object(self.rt, '_create_migration')
        mig_ctxt_mock = mock.patch('nova.objects.MigrationContext',
                                   return_value=mig_context_obj)
        with create_mig_mock as migr_mock, mig_ctxt_mock as ctxt_mock:
            migr_mock.return_value = _MIGRATION_FIXTURES['source-only']
            claim = self.rt.resize_claim(
                self.ctx, self.instance, self.flavor, None)
            self.assertEqual(1, ctxt_mock.call_count)

        self.assertIsInstance(claim, claims.MoveClaim)
        inst_save_mock.assert_called_once_with()
        self.assertTrue(obj_base.obj_equal_prims(expected,
                                                 self.rt.compute_node))

    def test_claim_abort(self, pci_mock, inst_list_mock,
            inst_by_uuid, migr_mock, inst_save_mock):
        # Resize self.instance and check that the expected quantities of each
        # resource have been consumed. The abort the resize claim and check
        # that the resources have been set back to their original values.
        self.register_mocks(pci_mock, inst_list_mock, inst_by_uuid, migr_mock,
                            inst_save_mock)
        self.driver_mock.get_host_ip_addr.return_value = "fake-host"
        migr_obj = _MIGRATION_FIXTURES['dest-only']
        self.instance = _MIGRATION_INSTANCE_FIXTURES[migr_obj['instance_uuid']]
        mig_context_obj = _MIGRATION_CONTEXT_FIXTURES[self.instance.uuid]
        self.instance.migration_context = mig_context_obj
        self.flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]

        with mock.patch.object(self.rt, '_create_migration') as migr_mock:
            migr_mock.return_value = migr_obj
            claim = self.rt.resize_claim(
                self.ctx, self.instance, self.flavor, None)

        self.assertIsInstance(claim, claims.MoveClaim)
        self.assertEqual(5, self.rt.compute_node.local_gb_used)
        self.assertEqual(256, self.rt.compute_node.memory_mb_used)
        self.assertEqual(1, len(self.rt.tracked_migrations))

        with mock.patch('nova.objects.Instance.'
                        'drop_migration_context') as drop_migr_mock:
            claim.abort()
            drop_migr_mock.assert_called_once_with()

        self.assertEqual(0, self.rt.compute_node.local_gb_used)
        self.assertEqual(0, self.rt.compute_node.memory_mb_used)
        self.assertEqual(0, len(self.rt.tracked_migrations))

    def test_same_host(self, pci_mock, inst_list_mock, inst_by_uuid,
            migr_mock, inst_save_mock):
        """Resize self.instance to the same host but with a different flavor.
        Then abort the claim. Check that the same amount of resources are
        available afterwards as we started with.
        """

        self.register_mocks(pci_mock, inst_list_mock, inst_by_uuid, migr_mock,
                            inst_save_mock)
        migr_obj = _MIGRATION_FIXTURES['source-and-dest']
        self.instance = _MIGRATION_INSTANCE_FIXTURES[migr_obj['instance_uuid']]
        self.instance._context = self.ctx
        mig_context_obj = _MIGRATION_CONTEXT_FIXTURES[self.instance.uuid]
        self.instance.migration_context = mig_context_obj

        with mock.patch.object(self.instance, 'save'):
            self.rt.instance_claim(self.ctx, self.instance, None)
        expected = copy.deepcopy(self.rt.compute_node)

        create_mig_mock = mock.patch.object(self.rt, '_create_migration')
        mig_ctxt_mock = mock.patch('nova.objects.MigrationContext',
                                   return_value=mig_context_obj)

        with create_mig_mock as migr_mock, mig_ctxt_mock as ctxt_mock:
            migr_mock.return_value = migr_obj
            claim = self.rt.resize_claim(self.ctx, self.instance,
                    _INSTANCE_TYPE_OBJ_FIXTURES[1], None)
            self.assertEqual(1, ctxt_mock.call_count)

        self.audit(self.rt, [self.instance], [migr_obj], self.instance)
        inst_save_mock.assert_called_once_with()
        self.assertNotEqual(expected, self.rt.compute_node)

        claim.instance.migration_context = mig_context_obj
        with mock.patch('nova.objects.MigrationContext._destroy') as destroy_m:
            claim.abort()
            self.assertTrue(obj_base.obj_equal_prims(expected,
                                                     self.rt.compute_node))
            destroy_m.assert_called_once_with(self.ctx, claim.instance.uuid)

    def test_revert_reserve_source(
            self, pci_mock, inst_list_mock, inst_by_uuid, migr_mock,
            inst_save_mock):
        """Check that the source node of an instance migration reserves
        resources until the migration has completed, even if the migration is
        reverted.
        """

        self.register_mocks(pci_mock, inst_list_mock, inst_by_uuid, migr_mock,
                            inst_save_mock)

        # Get our migrations, instances and itypes in a row
        src_migr = _MIGRATION_FIXTURES['source-only']
        src_instance = (
            _MIGRATION_INSTANCE_FIXTURES[src_migr['instance_uuid']].obj_clone()
        )
        src_instance.migration_context = (
            _MIGRATION_CONTEXT_FIXTURES[src_instance.uuid])
        old_itype = _INSTANCE_TYPE_FIXTURES[src_migr['old_instance_type_id']]
        dst_migr = _MIGRATION_FIXTURES['dest-only']
        dst_instance = (
            _MIGRATION_INSTANCE_FIXTURES[dst_migr['instance_uuid']].obj_clone()
        )
        new_itype = _INSTANCE_TYPE_FIXTURES[dst_migr['new_instance_type_id']]
        dst_instance.migration_context = (
            _MIGRATION_CONTEXT_FIXTURES[dst_instance.uuid])

        # Set up the destination resource tracker
        # update_available_resource to initialise extensible resource trackers
        src_rt = self.rt
        (dst_rt, _, _) = setup_rt("other-host", "other-node")
        dst_rt.compute_node = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        inst_list_mock.return_value = objects.InstanceList(objects=[])
        dst_rt.update_available_resource(self.ctx)

        # Register the instance with dst_rt
        expected = copy.deepcopy(dst_rt.compute_node)
        with mock.patch.object(dst_instance, 'save'):
            dst_rt.instance_claim(self.ctx, dst_instance)
        self.adjust_expected(expected, new_itype)
        expected.stats = {'num_task_resize_migrating': 1,
                             'io_workload': 1,
                             'num_instances': 1,
                             'num_proj_fake-project': 1,
                             'num_vm_active': 1,
                             'num_os_type_fake-os': 1}
        expected.current_workload = 1
        expected.running_vms = 1
        self.assertTrue(obj_base.obj_equal_prims(expected,
                                                 dst_rt.compute_node))

        # Provide the migration via a mock, then audit dst_rt to check that
        # the instance + migration resources are not double-counted
        self.audit(dst_rt, [dst_instance], [dst_migr], dst_instance)
        self.assertTrue(obj_base.obj_equal_prims(expected,
                                                 dst_rt.compute_node))

        # Audit src_rt with src_migr
        expected = copy.deepcopy(src_rt.compute_node)
        self.adjust_expected(expected, old_itype)
        self.audit(src_rt, [], [src_migr], src_instance)
        self.assertTrue(obj_base.obj_equal_prims(expected,
                                                 src_rt.compute_node))

        # Flag the instance as reverting and re-audit
        src_instance['vm_state'] = vm_states.RESIZED
        src_instance['task_state'] = task_states.RESIZE_REVERTING
        self.audit(src_rt, [], [src_migr], src_instance)
        self.assertTrue(obj_base.obj_equal_prims(expected,
                                                 src_rt.compute_node))

    def test_update_available_resources_migration_no_context(self, pci_mock,
            inst_list_mock, inst_by_uuid, migr_mock, inst_save_mock):
        """When migrating onto older nodes - it is possible for the
        migration_context record to be missing. Confirm resource audit works
        regardless.
        """
        self.register_mocks(pci_mock, inst_list_mock, inst_by_uuid, migr_mock,
                            inst_save_mock)
        migr_obj = _MIGRATION_FIXTURES['source-and-dest']
        self.instance = _MIGRATION_INSTANCE_FIXTURES[migr_obj['instance_uuid']]
        self.instance.migration_context = None

        expected = copy.deepcopy(self.rt.compute_node)
        self.adjust_expected(expected, self.flavor)

        self.audit(self.rt, [], [migr_obj], self.instance)
        self.assertTrue(obj_base.obj_equal_prims(expected,
                                                 self.rt.compute_node))

    def test_dupe_filter(self, pci_mock, inst_list_mock, inst_by_uuid,
            migr_mock, inst_save_mock):
        self.register_mocks(pci_mock, inst_list_mock, inst_by_uuid, migr_mock,
                            inst_save_mock)

        migr_obj = _MIGRATION_FIXTURES['source-and-dest']
        # This is good enough to prevent a lazy-load; value is unimportant
        migr_obj['updated_at'] = None
        self.instance = _MIGRATION_INSTANCE_FIXTURES[migr_obj['instance_uuid']]
        self.instance.migration_context = (
            _MIGRATION_CONTEXT_FIXTURES[self.instance.uuid])
        self.audit(self.rt, [], [migr_obj, migr_obj], self.instance)
        self.assertEqual(1, len(self.rt.tracked_migrations))


class TestInstanceInResizeState(test.NoDBTestCase):
    def test_active_suspending(self):
        instance = objects.Instance(vm_state=vm_states.ACTIVE,
                                    task_state=task_states.SUSPENDING)
        self.assertFalse(resource_tracker._instance_in_resize_state(instance))

    def test_resized_suspending(self):
        instance = objects.Instance(vm_state=vm_states.RESIZED,
                                    task_state=task_states.SUSPENDING)
        self.assertTrue(resource_tracker._instance_in_resize_state(instance))

    def test_resized_resize_migrating(self):
        instance = objects.Instance(vm_state=vm_states.RESIZED,
                                    task_state=task_states.RESIZE_MIGRATING)
        self.assertTrue(resource_tracker._instance_in_resize_state(instance))

    def test_resized_resize_finish(self):
        instance = objects.Instance(vm_state=vm_states.RESIZED,
                                    task_state=task_states.RESIZE_FINISH)
        self.assertTrue(resource_tracker._instance_in_resize_state(instance))
