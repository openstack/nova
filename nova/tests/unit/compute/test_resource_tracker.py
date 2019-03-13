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
import datetime

import mock
from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import units

from nova.compute import claims
from nova.compute.monitors import base as monitor_base
from nova.compute import power_state
from nova.compute import provider_tree
from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import exception as exc
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields as obj_fields
from nova.objects import pci_device
from nova.pci import manager as pci_manager
from nova import rc_fields
from nova import test
from nova.tests.unit import fake_notifier
from nova.tests.unit.objects import test_pci_device as fake_pci_device
from nova.tests import uuidsentinel as uuids
from nova.virt import driver

_HOSTNAME = 'fake-host'
_NODENAME = 'fake-node'
CONF = cfg.CONF

_VIRT_DRIVER_AVAIL_RESOURCES = {
    'vcpus': 4,
    'memory_mb': 512,
    'local_gb': 6,
    'vcpus_used': 0,
    'memory_mb_used': 0,
    'local_gb_used': 0,
    'hypervisor_type': 'fake',
    'hypervisor_version': 0,
    'hypervisor_hostname': _NODENAME,
    'cpu_info': '',
    'numa_topology': None,
}

_COMPUTE_NODE_FIXTURES = [
    objects.ComputeNode(
        id=1,
        uuid=uuids.cn1,
        host=_HOSTNAME,
        vcpus=_VIRT_DRIVER_AVAIL_RESOURCES['vcpus'],
        memory_mb=_VIRT_DRIVER_AVAIL_RESOURCES['memory_mb'],
        local_gb=_VIRT_DRIVER_AVAIL_RESOURCES['local_gb'],
        vcpus_used=_VIRT_DRIVER_AVAIL_RESOURCES['vcpus_used'],
        memory_mb_used=_VIRT_DRIVER_AVAIL_RESOURCES['memory_mb_used'],
        local_gb_used=_VIRT_DRIVER_AVAIL_RESOURCES['local_gb_used'],
        hypervisor_type='fake',
        hypervisor_version=0,
        hypervisor_hostname=_NODENAME,
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
            objects.HVSpec.from_list([
                obj_fields.Architecture.I686,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM])
        ],
        metrics=None,
        pci_device_pools=None,
        extra_resources=None,
        stats={},
        numa_topology=None,
        cpu_allocation_ratio=16.0,
        ram_allocation_ratio=1.5,
        disk_allocation_ratio=1.0,
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
        'deleted': 0,
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
        'deleted': 0,
    },
}


_INSTANCE_TYPE_OBJ_FIXTURES = {
    1: objects.Flavor(id=1, flavorid='fakeid-1', name='fake1.small',
                      memory_mb=128, vcpus=1, root_gb=1,
                      ephemeral_gb=0, swap=0, rxtx_factor=0,
                      vcpu_weight=1, extra_specs={}, deleted=False),
    2: objects.Flavor(id=2, flavorid='fakeid-2', name='fake1.medium',
                      memory_mb=256, vcpus=2, root_gb=5,
                      ephemeral_gb=0, swap=0, rxtx_factor=0,
                      vcpu_weight=1, extra_specs={}, deleted=False),
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
    '2mb*1024': objects.NUMAPagesTopology(size_kb=2048, total=1024, used=0)
}

_NUMA_HOST_TOPOLOGIES = {
    '2mb': objects.NUMATopology(cells=[
        objects.NUMACell(id=0, cpuset=set([1, 2]), memory=_2MB,
                         cpu_usage=0, memory_usage=0,
                         mempages=[_NUMA_PAGE_TOPOLOGIES['2mb*1024']],
                         siblings=[set([1]), set([2])],
                         pinned_cpus=set([])),
        objects.NUMACell(id=1, cpuset=set([3, 4]), memory=_2MB,
                         cpu_usage=0, memory_usage=0,
                         mempages=[_NUMA_PAGE_TOPOLOGIES['2mb*1024']],
                         siblings=[set([3]), set([4])],
                         pinned_cpus=set([]))]),
}


_INSTANCE_FIXTURES = [
    objects.Instance(
        id=1,
        host=_HOSTNAME,
        node=_NODENAME,
        uuid='c17741a5-6f3d-44a8-ade8-773dc8c29124',
        memory_mb=_INSTANCE_TYPE_FIXTURES[1]['memory_mb'],
        vcpus=_INSTANCE_TYPE_FIXTURES[1]['vcpus'],
        root_gb=_INSTANCE_TYPE_FIXTURES[1]['root_gb'],
        ephemeral_gb=_INSTANCE_TYPE_FIXTURES[1]['ephemeral_gb'],
        numa_topology=_INSTANCE_NUMA_TOPOLOGIES['2mb'],
        pci_requests=None,
        pci_devices=None,
        instance_type_id=1,
        vm_state=vm_states.ACTIVE,
        power_state=power_state.RUNNING,
        task_state=None,
        os_type='fake-os',  # Used by the stats collector.
        project_id='fake-project',  # Used by the stats collector.
        user_id=uuids.user_id,
        flavor = _INSTANCE_TYPE_OBJ_FIXTURES[1],
        old_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[1],
        new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[1],
        deleted = False,
    ),
    objects.Instance(
        id=2,
        host=_HOSTNAME,
        node=_NODENAME,
        uuid='33805b54-dea6-47b8-acb2-22aeb1b57919',
        memory_mb=_INSTANCE_TYPE_FIXTURES[2]['memory_mb'],
        vcpus=_INSTANCE_TYPE_FIXTURES[2]['vcpus'],
        root_gb=_INSTANCE_TYPE_FIXTURES[2]['root_gb'],
        ephemeral_gb=_INSTANCE_TYPE_FIXTURES[2]['ephemeral_gb'],
        numa_topology=None,
        pci_requests=None,
        pci_devices=None,
        instance_type_id=2,
        vm_state=vm_states.DELETED,
        power_state=power_state.SHUTDOWN,
        task_state=None,
        os_type='fake-os',
        project_id='fake-project-2',
        user_id=uuids.user_id,
        flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
        old_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
        new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
        deleted = False,
    ),
]

_MIGRATION_FIXTURES = {
    # A migration that has only this compute node as the source host
    'source-only': objects.Migration(
        id=1,
        instance_uuid='f15ecfb0-9bf6-42db-9837-706eb2c4bf08',
        source_compute=_HOSTNAME,
        dest_compute='other-host',
        source_node=_NODENAME,
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
        dest_compute=_HOSTNAME,
        source_node='other-node',
        dest_node=_NODENAME,
        old_instance_type_id=1,
        new_instance_type_id=2,
        migration_type='resize',
        status='migrating'
    ),
    # A migration that has this compute node as both the source and dest host
    'source-and-dest': objects.Migration(
        id=3,
        instance_uuid='f4f0bfea-fe7e-4264-b598-01cb13ef1997',
        source_compute=_HOSTNAME,
        dest_compute=_HOSTNAME,
        source_node=_NODENAME,
        dest_node=_NODENAME,
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
        dest_compute=_HOSTNAME,
        source_node='other-node',
        dest_node=_NODENAME,
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
        pci_requests=None,
        pci_devices=None,
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
        pci_requests=None,
        pci_devices=None,
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
        pci_requests=None,
        pci_devices=None,
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
        pci_requests=None,
        pci_devices=None,
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
        'memory_mb': 0,
        'disk_gb': 0,
        'vcpus': 0,
    }


def setup_rt(hostname, virt_resources=_VIRT_DRIVER_AVAIL_RESOURCES,
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
    vd = mock.MagicMock(autospec=driver.ComputeDriver)
    # Make sure we don't change any global fixtures during tests
    virt_resources = copy.deepcopy(virt_resources)
    vd.get_available_resource.return_value = virt_resources
    vd.get_inventory.side_effect = NotImplementedError
    vd.update_provider_tree.side_effect = NotImplementedError
    vd.get_host_ip_addr.return_value = _NODENAME
    vd.estimate_instance_overhead.side_effect = estimate_overhead
    vd.rebalances_nodes = False

    with test.nested(
            mock.patch('nova.scheduler.client.SchedulerClient',
                       return_value=sched_client_mock),
            mock.patch('nova.rpc.get_notifier', return_value=notifier_mock)):
        rt = resource_tracker.ResourceTracker(hostname, vd)
    return (rt, sched_client_mock, vd)


def compute_update_usage(resources, flavor, sign=1):
    resources.vcpus_used += sign * flavor.vcpus
    resources.memory_mb_used += sign * flavor.memory_mb
    resources.local_gb_used += sign * (flavor.root_gb + flavor.ephemeral_gb)
    resources.free_ram_mb = resources.memory_mb - resources.memory_mb_used
    resources.free_disk_gb = resources.local_gb - resources.local_gb_used
    return resources


class BaseTestCase(test.NoDBTestCase):

    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.rt = None
        self.flags(my_ip='1.1.1.1',
                   reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0,
                   reserved_host_cpus=0)

    def _setup_rt(self, virt_resources=_VIRT_DRIVER_AVAIL_RESOURCES,
                  estimate_overhead=overhead_zero):
        (self.rt, self.sched_client_mock,
         self.driver_mock) = setup_rt(
                 _HOSTNAME, virt_resources, estimate_overhead)


class TestUpdateAvailableResources(BaseTestCase):

    @mock.patch('nova.objects.Service.get_minimum_version',
                return_value=22)
    def _update_available_resources(self, version_mock):
        # We test RT._update separately, since the complexity
        # of the update_available_resource() function is high enough as
        # it is, we just want to focus here on testing the resources
        # parameter that update_available_resource() eventually passes
        # to _update().
        with mock.patch.object(self.rt, '_update') as update_mock:
            self.rt.update_available_resource(mock.MagicMock(), _NODENAME)
        return update_mock

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_disabled(self, get_mock, migr_mock, get_cn_mock, pci_mock,
            instance_pci_mock):
        self._setup_rt()

        # Set up resource tracker in an enabled state and verify that all is
        # good before simulating a disabled node.
        get_mock.return_value = []
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        # This will call _init_compute_node() and create a ComputeNode object
        # and will also call through to InstanceList.get_by_host_and_node()
        # because the node is available.
        self._update_available_resources()

        self.assertTrue(get_mock.called)

        get_mock.reset_mock()

        # OK, now simulate a node being disabled by the Ironic virt driver.
        vd = self.driver_mock
        vd.node_is_available.return_value = False
        self._update_available_resources()

        self.assertFalse(get_mock.called)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_no_migrations_no_reserved(self, get_mock, migr_mock,
                                                    get_cn_mock, pci_mock,
                                                    instance_pci_mock):
        self._setup_rt()

        get_mock.return_value = []
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        update_mock = self._update_available_resources()

        vd = self.driver_mock
        vd.get_available_resource.assert_called_once_with(_NODENAME)
        get_mock.assert_called_once_with(mock.ANY, _HOSTNAME,
                                         _NODENAME,
                                         expected_attrs=[
                                             'system_metadata',
                                             'numa_topology',
                                             'flavor',
                                             'migration_context'])
        get_cn_mock.assert_called_once_with(mock.ANY, _HOSTNAME,
                                            _NODENAME)
        migr_mock.assert_called_once_with(mock.ANY, _HOSTNAME,
                                          _NODENAME)

        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'free_disk_gb': 6,
            'local_gb': 6,
            'free_ram_mb': 512,
            'memory_mb_used': 0,
            'vcpus_used': 0,
            'local_gb_used': 0,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        }
        _update_compute_node(expected_resources, **vals)
        actual_resources = update_mock.call_args[0][1]
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 actual_resources))
        update_mock.assert_called_once()

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_no_migrations_reserved_disk_ram_and_cpu(
            self, get_mock, migr_mock, get_cn_mock, pci_mock,
            instance_pci_mock):
        self.flags(reserved_host_disk_mb=1024,
                   reserved_host_memory_mb=512,
                   reserved_host_cpus=1)
        self._setup_rt()

        get_mock.return_value = []
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.ANY, _HOSTNAME, _NODENAME)
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'free_disk_gb': 5,  # 6GB avail - 1 GB reserved
            'local_gb': 6,
            'free_ram_mb': 0,  # 512MB avail - 512MB reserved
            'memory_mb_used': 512,  # 0MB used + 512MB reserved
            'vcpus_used': 1,
            'local_gb_used': 1,  # 0GB used + 1 GB reserved
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        }
        _update_compute_node(expected_resources, **vals)
        actual_resources = update_mock.call_args[0][1]
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 actual_resources))
        update_mock.assert_called_once()

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_some_instances_no_migrations(self, get_mock, migr_mock,
                                          get_cn_mock, pci_mock,
                                          instance_pci_mock, bfv_check_mock):
        # Setup virt resources to match used resources to number
        # of defined instances on the hypervisor
        # Note that the usage numbers here correspond to only the first
        # Instance object, because the second instance object fixture is in
        # DELETED state and therefore we should not expect it to be accounted
        # for in the auditing process.
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(vcpus_used=1,
                              memory_mb_used=128,
                              local_gb_used=1)
        self._setup_rt(virt_resources=virt_resources)

        get_mock.return_value = _INSTANCE_FIXTURES
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]
        bfv_check_mock.return_value = False

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.ANY, _HOSTNAME, _NODENAME)
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'free_disk_gb': 5,  # 6 - 1 used
            'local_gb': 6,
            'free_ram_mb': 384,  # 512 - 128 used
            'memory_mb_used': 128,
            'vcpus_used': 1,
            'local_gb_used': 1,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 1  # One active instance
        }
        _update_compute_node(expected_resources, **vals)
        actual_resources = update_mock.call_args[0][1]
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 actual_resources))
        update_mock.assert_called_once()

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_orphaned_instances_no_migrations(self, get_mock, migr_mock,
                                              get_cn_mock, pci_mock,
                                              instance_pci_mock):
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

        get_cn_mock.assert_called_once_with(mock.ANY, _HOSTNAME, _NODENAME)
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'free_disk_gb': 6,
            'local_gb': 6,
            'free_ram_mb': 448,  # 512 - 64 orphaned usage
            'memory_mb_used': 64,
            'vcpus_used': 0,
            'local_gb_used': 0,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            # Yep, for some reason, orphaned instances are not counted
            # as running VMs...
            'running_vms': 0
        }
        _update_compute_node(expected_resources, **vals)
        actual_resources = update_mock.call_args[0][1]
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 actual_resources))
        update_mock.assert_called_once()

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_source_migration(self, get_mock, get_inst_mock,
                                           migr_mock, get_cn_mock, pci_mock,
                                           instance_pci_mock,
                                           mock_is_volume_backed_instance):
        # We test the behavior of update_available_resource() when
        # there is an active migration that involves this compute node
        # as the source host not the destination host, and the resource
        # tracker does not have any instances assigned to it. This is
        # the case when a migration from this compute host to another
        # has been completed, but the user has not confirmed the resize
        # yet, so the resource tracker must continue to keep the resources
        # for the original instance type available on the source compute
        # node in case of a revert of the resize.

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

        get_cn_mock.assert_called_once_with(mock.ANY, _HOSTNAME, _NODENAME)
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'free_disk_gb': 5,
            'local_gb': 6,
            'free_ram_mb': 384,  # 512 total - 128 for possible revert of orig
            'memory_mb_used': 128,  # 128 possible revert amount
            'vcpus_used': 1,
            'local_gb_used': 1,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        }
        _update_compute_node(expected_resources, **vals)
        actual_resources = update_mock.call_args[0][1]
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 actual_resources))
        update_mock.assert_called_once()

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_dest_migration(self, get_mock, get_inst_mock,
                                         migr_mock, get_cn_mock, pci_mock,
                                         instance_pci_mock,
                                         mock_is_volume_backed_instance):
        # We test the behavior of update_available_resource() when
        # there is an active migration that involves this compute node
        # as the destination host not the source host, and the resource
        # tracker does not yet have any instances assigned to it. This is
        # the case when a migration to this compute host from another host
        # is in progress, but the user has not confirmed the resize
        # yet, so the resource tracker must reserve the resources
        # for the possibly-to-be-confirmed instance's instance type
        # node in case of a confirm of the resize.

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

        get_cn_mock.assert_called_once_with(mock.ANY, _HOSTNAME, _NODENAME)
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'free_disk_gb': 1,
            'local_gb': 6,
            'free_ram_mb': 256,  # 512 total - 256 for possible confirm of new
            'memory_mb_used': 256,  # 256 possible confirmed amount
            'vcpus_used': 2,
            'local_gb_used': 5,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        }
        _update_compute_node(expected_resources, **vals)
        actual_resources = update_mock.call_args[0][1]
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 actual_resources))
        update_mock.assert_called_once()

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_no_instances_dest_evacuation(self, get_mock, get_inst_mock,
                                          migr_mock, get_cn_mock, pci_mock,
                                          instance_pci_mock,
                                          mock_is_volume_backed_instance):
        # We test the behavior of update_available_resource() when
        # there is an active evacuation that involves this compute node
        # as the destination host not the source host, and the resource
        # tracker does not yet have any instances assigned to it. This is
        # the case when a migration to this compute host from another host
        # is in progress, but not finished yet.

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
        instance.migration_context.migration_id = migr_obj.id

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.ANY, _HOSTNAME, _NODENAME)
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'free_disk_gb': 1,
            'free_ram_mb': 256,  # 512 total - 256 for possible confirm of new
            'memory_mb_used': 256,  # 256 possible confirmed amount
            'vcpus_used': 2,
            'local_gb_used': 5,
            'memory_mb': 512,
            'current_workload': 0,
            'vcpus': 4,
            'running_vms': 0
        }
        _update_compute_node(expected_resources, **vals)
        actual_resources = update_mock.call_args[0][1]
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 actual_resources))
        update_mock.assert_called_once()

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.MigrationContext.get_by_instance_uuid',
                return_value=None)
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    def test_some_instances_source_and_dest_migration(self, get_mock,
                                                      get_inst_mock, migr_mock,
                                                      get_cn_mock,
                                                      get_mig_ctxt_mock,
                                                      pci_mock,
                                                      instance_pci_mock,
                                                      bfv_check_mock):
        # We test the behavior of update_available_resource() when
        # there is an active migration that involves this compute node
        # as the destination host AND the source host, and the resource
        # tracker has a few instances assigned to it, including the
        # instance that is resizing to this same compute node. The tracking
        # of resource amounts takes into account both the old and new
        # resize instance types as taking up space on the node.

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
        bfv_check_mock.return_value = False

        update_mock = self._update_available_resources()

        get_cn_mock.assert_called_once_with(mock.ANY, _HOSTNAME, _NODENAME)
        expected_resources = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            # 6 total - 1G existing - 5G new flav - 1G old flav
            'free_disk_gb': -1,
            'local_gb': 6,
            # 512 total - 128 existing - 256 new flav - 128 old flav
            'free_ram_mb': 0,
            'memory_mb_used': 512,  # 128 exist + 256 new flav + 128 old flav
            'vcpus_used': 4,
            'local_gb_used': 7,  # 1G existing, 5G new flav + 1 old flav
            'memory_mb': 512,
            'current_workload': 1,  # One migrating instance...
            'vcpus': 4,
            'running_vms': 2
        }
        _update_compute_node(expected_resources, **vals)
        actual_resources = update_mock.call_args[0][1]
        self.assertTrue(obj_base.obj_equal_prims(expected_resources,
                                                 actual_resources))
        update_mock.assert_called_once()


class TestInitComputeNode(BaseTestCase):

    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update')
    def test_no_op_init_compute_node(self, update_mock, get_mock, service_mock,
                                     create_mock, pci_mock):
        self._setup_rt()

        resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        compute_node = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        self.rt.compute_nodes[_NODENAME] = compute_node

        self.rt._init_compute_node(mock.sentinel.ctx, resources)

        self.assertFalse(service_mock.called)
        self.assertFalse(get_mock.called)
        self.assertFalse(create_mock.called)
        self.assertTrue(pci_mock.called)
        self.assertFalse(update_mock.called)

    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update')
    def test_compute_node_loaded(self, update_mock, get_mock, create_mock,
                                 pci_mock):
        self._setup_rt()

        def fake_get_node(_ctx, host, node):
            res = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
            return res

        get_mock.side_effect = fake_get_node
        resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)

        self.rt._init_compute_node(mock.sentinel.ctx, resources)

        get_mock.assert_called_once_with(mock.sentinel.ctx, _HOSTNAME,
                                         _NODENAME)
        self.assertFalse(create_mock.called)
        self.assertFalse(update_mock.called)

    @mock.patch('nova.objects.ComputeNodeList.get_by_hypervisor')
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update')
    def test_compute_node_rebalanced(self, update_mock, get_mock, create_mock,
                                     pci_mock, get_by_hypervisor_mock):
        self._setup_rt()
        self.driver_mock.rebalances_nodes = True
        cn = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        cn.host = "old-host"

        def fake_get_all(_ctx, nodename):
            return [cn]

        get_mock.side_effect = exc.NotFound
        get_by_hypervisor_mock.side_effect = fake_get_all
        resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)

        self.rt._init_compute_node(mock.sentinel.ctx, resources)

        get_mock.assert_called_once_with(mock.sentinel.ctx, _HOSTNAME,
                                         _NODENAME)
        get_by_hypervisor_mock.assert_called_once_with(mock.sentinel.ctx,
                                                     _NODENAME)
        create_mock.assert_not_called()
        update_mock.assert_called_once_with(mock.sentinel.ctx, cn)

        self.assertEqual(_HOSTNAME, self.rt.compute_nodes[_NODENAME].host)

    @mock.patch('nova.objects.ComputeNodeList.get_by_hypervisor')
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList(objects=[]))
    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update')
    def test_compute_node_created_on_empty(self, update_mock, get_mock,
                                           create_mock, pci_tracker_mock,
                                           get_by_hypervisor_mock):
        get_by_hypervisor_mock.return_value = []
        self._test_compute_node_created(update_mock, get_mock, create_mock,
                                        pci_tracker_mock,
                                        get_by_hypervisor_mock)

    @mock.patch('nova.objects.ComputeNodeList.get_by_hypervisor')
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList(objects=[]))
    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update')
    def test_compute_node_created_on_empty_rebalance(self, update_mock,
                                                     get_mock,
                                                     create_mock,
                                                     pci_tracker_mock,
                                                     get_by_hypervisor_mock):
        get_by_hypervisor_mock.return_value = []
        self._test_compute_node_created(update_mock, get_mock, create_mock,
                                        pci_tracker_mock,
                                        get_by_hypervisor_mock,
                                        rebalances_nodes=True)

    @mock.patch('nova.objects.ComputeNodeList.get_by_hypervisor')
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList(objects=[]))
    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update')
    def test_compute_node_created_too_many(self, update_mock, get_mock,
                                           create_mock, pci_tracker_mock,
                                           get_by_hypervisor_mock):
        get_by_hypervisor_mock.return_value = ["fake_node_1", "fake_node_2"]
        self._test_compute_node_created(update_mock, get_mock, create_mock,
                                        pci_tracker_mock,
                                        get_by_hypervisor_mock,
                                        rebalances_nodes=True)

    def _test_compute_node_created(self, update_mock, get_mock,
                                   create_mock, pci_tracker_mock,
                                   get_by_hypervisor_mock,
                                   rebalances_nodes=False):
        self.flags(cpu_allocation_ratio=1.0, ram_allocation_ratio=1.0,
                   disk_allocation_ratio=1.0)
        self._setup_rt()
        self.driver_mock.rebalances_nodes = rebalances_nodes

        get_mock.side_effect = exc.NotFound

        resources = {
            'host_ip': '1.1.1.1',
            'numa_topology': None,
            'metrics': '[]',
            'cpu_info': '',
            'hypervisor_hostname': _NODENAME,
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
            id=42,
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
            host=_HOSTNAME,
            # NOTE(sbauza): ResourceTracker adds CONF allocation ratios
            ram_allocation_ratio=1.0,
            cpu_allocation_ratio=1.0,
            disk_allocation_ratio=1.0,
            stats={'failed_builds': 0},
            pci_device_pools=objects.PciDevicePoolList(objects=[]),
            uuid=uuids.compute_node_uuid
        )

        def set_cn_id():
            # The PCI tracker needs the compute node's ID when starting up, so
            # make sure that we set the ID value so we don't get a Cannot load
            # 'id' in base class error
            cn = self.rt.compute_nodes[_NODENAME]
            cn.id = 42  # Has to be a number, not a mock
            cn.uuid = uuids.compute_node_uuid

        create_mock.side_effect = set_cn_id
        self.rt._init_compute_node(mock.sentinel.ctx, resources)

        cn = self.rt.compute_nodes[_NODENAME]
        get_mock.assert_called_once_with(mock.sentinel.ctx, _HOSTNAME,
                                         _NODENAME)
        if rebalances_nodes:
            get_by_hypervisor_mock.assert_called_once_with(
                mock.sentinel.ctx, _NODENAME)
        else:
            get_by_hypervisor_mock.assert_not_called()
        create_mock.assert_called_once_with()
        self.assertTrue(obj_base.obj_equal_prims(expected_compute, cn))
        pci_tracker_mock.assert_called_once_with(mock.sentinel.ctx,
                                                 42)
        self.assertFalse(update_mock.called)

    @mock.patch('nova.objects.ComputeNodeList.get_by_hypervisor')
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList(objects=[]))
    @mock.patch('nova.objects.ComputeNode.create')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update')
    def test_node_removed(self, update_mock, get_mock,
                          create_mock, pci_tracker_mock,
                          get_by_hypervisor_mock):
        self._test_compute_node_created(update_mock, get_mock, create_mock,
                                        pci_tracker_mock,
                                        get_by_hypervisor_mock)
        self.rt.old_resources[_NODENAME] = mock.sentinel.foo
        self.assertIn(_NODENAME, self.rt.compute_nodes)
        self.assertIn(_NODENAME, self.rt.stats)
        self.assertIn(_NODENAME, self.rt.old_resources)
        self.rt.remove_node(_NODENAME)
        self.assertNotIn(_NODENAME, self.rt.compute_nodes)
        self.assertNotIn(_NODENAME, self.rt.stats)
        self.assertNotIn(_NODENAME, self.rt.old_resources)


class TestUpdateComputeNode(BaseTestCase):

    @mock.patch('nova.objects.ComputeNode.save')
    def test_existing_compute_node_updated_same_resources(self, save_mock):
        self._setup_rt()

        # This is the same set of resources as the fixture, deliberately. We
        # are checking below to see that compute_node.save is not needlessly
        # called when the resources don't actually change.
        orig_compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = orig_compute
        self.rt.old_resources[_NODENAME] = orig_compute

        new_compute = orig_compute.obj_clone()

        self.rt._update(mock.sentinel.ctx, new_compute)
        self.assertFalse(save_mock.called)
        # Even the compute node is not updated, get_inventory still got called.
        # And update_compute_node() is also called when get_inventory() is not
        # implemented.
        self.driver_mock.get_inventory.assert_called_once_with(_NODENAME)
        ucn_mock = self.sched_client_mock.update_compute_node
        ucn_mock.assert_called_once_with(mock.sentinel.ctx, new_compute)

    @mock.patch('nova.objects.ComputeNode.save')
    def test_existing_compute_node_updated_diff_updated_at(self, save_mock):
        # if only updated_at is changed, it won't call compute_node.save()
        self._setup_rt()
        ts1 = timeutils.utcnow()
        ts2 = ts1 + datetime.timedelta(seconds=10)

        orig_compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        orig_compute.updated_at = ts1
        self.rt.compute_nodes[_NODENAME] = orig_compute
        self.rt.old_resources[_NODENAME] = orig_compute

        # Make the new_compute object have a different timestamp
        # from orig_compute.
        new_compute = orig_compute.obj_clone()
        new_compute.updated_at = ts2

        self.rt._update(mock.sentinel.ctx, new_compute)
        self.assertFalse(save_mock.called)

    @mock.patch('nova.compute.resource_tracker.'
                '_normalize_inventory_from_cn_obj')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_existing_compute_node_updated_new_resources(self, save_mock,
                                                         norm_mock):
        self._setup_rt()

        orig_compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = orig_compute
        self.rt.old_resources[_NODENAME] = orig_compute

        # Deliberately changing local_gb_used, vcpus_used, and memory_mb_used
        # below to be different from the compute node fixture's base usages.
        # We want to check that the code paths update the stored compute node
        # usage records with what is supplied to _update().
        new_compute = orig_compute.obj_clone()
        new_compute.memory_mb_used = 128
        new_compute.vcpus_used = 2
        new_compute.local_gb_used = 4

        self.rt._update(mock.sentinel.ctx, new_compute)
        save_mock.assert_called_once_with()
        # The get_inventory() is not implemented, it shouldn't call
        # _normalize_inventory_from_cn_obj but call update_compute_node().
        self.assertFalse(norm_mock.called)
        ucn_mock = self.sched_client_mock.update_compute_node
        ucn_mock.assert_called_once_with(mock.sentinel.ctx, new_compute)

    @mock.patch('nova.compute.resource_tracker.'
                '_normalize_inventory_from_cn_obj')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_existing_node_get_inventory_implemented(self, save_mock,
            norm_mock):
        """The get_inventory() virt driver method is only implemented for some
        virt drivers. This method returns inventory information for a
        node/provider in a way that the placement API better understands, and
        if this method doesn't raise a NotImplementedError, this triggers
        _update() to call the set_inventory_for_provider() method of the
        reporting client instead of the update_compute_node() method.
        """
        self._setup_rt()

        # Emulate a driver that has implemented the newish get_inventory() virt
        # driver method
        self.driver_mock.get_inventory.side_effect = [mock.sentinel.inv_data]

        orig_compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = orig_compute
        self.rt.old_resources[_NODENAME] = orig_compute

        # Deliberately changing local_gb to trigger updating inventory
        new_compute = orig_compute.obj_clone()
        new_compute.local_gb = 210000

        ucn_mock = self.sched_client_mock.update_compute_node
        sifp_mock = self.sched_client_mock.set_inventory_for_provider
        self.rt._update(mock.sentinel.ctx, new_compute)
        save_mock.assert_called_once_with()
        sifp_mock.assert_called_once_with(
            mock.sentinel.ctx,
            new_compute.uuid,
            new_compute.hypervisor_hostname,
            mock.sentinel.inv_data,
        )
        self.assertFalse(ucn_mock.called)

    @mock.patch('nova.objects.ComputeNode.save')
    def test_existing_node_update_provider_tree_implemented(self, save_mock):
        """The update_provider_tree() virt driver method is only implemented
        for some virt drivers. This method returns inventory, trait, and
        aggregate information for resource providers in a tree associated with
        the compute node.  If this method doesn't raise a NotImplementedError,
        it triggers _update() to call the update_from_provider_tree() method of
        the reporting client instead of set_inventory_for_provider() (old) or
        update_compute_node() (older).
        """
        fake_inv = {
            rc_fields.ResourceClass.VCPU: {
                'total': 2,
                'min_unit': 1,
                'max_unit': 2,
                'step_size': 1,
            },
            rc_fields.ResourceClass.MEMORY_MB: {
                'total': 4096,
                'min_unit': 1,
                'max_unit': 4096,
                'step_size': 1,
            },
            rc_fields.ResourceClass.DISK_GB: {
                'total': 500,
                'min_unit': 1,
                'max_unit': 500,
                'step_size': 1,
            },
        }

        def fake_upt(ptree, nodename):
            ptree.update_inventory(nodename, fake_inv)

        # These will get set on ptree by _normalize_inventory_from_cn_obj
        self.flags(reserved_host_disk_mb=1024,
                   reserved_host_memory_mb=512,
                   reserved_host_cpus=1)

        self._setup_rt()

        # Emulate a driver that has implemented the update_from_provider_tree()
        # virt driver method
        self.driver_mock.update_provider_tree.side_effect = fake_upt

        orig_compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        # TODO(efried): These are being overwritten to 0.0 on the global
        # somewhere else in this module. Find and fix that, and remove these:
        orig_compute.cpu_allocation_ratio = 16.0
        orig_compute.ram_allocation_ratio = 1.5
        orig_compute.disk_allocation_ratio = 1.0

        self.rt.compute_nodes[_NODENAME] = orig_compute
        self.rt.old_resources[_NODENAME] = orig_compute

        # Deliberately changing local_gb to trigger updating inventory
        new_compute = orig_compute.obj_clone()
        new_compute.local_gb = 210000

        rc_mock = self.rt.reportclient
        gptaer_mock = rc_mock.get_provider_tree_and_ensure_root
        ptree = provider_tree.ProviderTree()
        ptree.new_root(orig_compute.hypervisor_hostname, orig_compute.uuid)
        gptaer_mock.return_value = ptree

        self.rt._update(mock.sentinel.ctx, new_compute)

        save_mock.assert_called_once_with()
        gptaer_mock.assert_called_once_with(
            mock.sentinel.ctx, new_compute.uuid,
            name=new_compute.hypervisor_hostname)
        self.driver_mock.update_provider_tree.assert_called_once_with(
            ptree, new_compute.hypervisor_hostname)
        rc_mock.update_from_provider_tree.assert_called_once_with(
            mock.sentinel.ctx, ptree)
        self.sched_client_mock.update_compute_node.assert_not_called()
        self.sched_client_mock.set_inventory_for_provider.assert_not_called()
        # _normalize_inventory_from_cn_obj should have set allocation ratios
        # and reserved values
        exp_inv = copy.deepcopy(fake_inv)
        # These ratios come from the compute node fixture
        exp_inv[rc_fields.ResourceClass.VCPU]['allocation_ratio'] = 16.0
        exp_inv[rc_fields.ResourceClass.MEMORY_MB]['allocation_ratio'] = 1.5
        exp_inv[rc_fields.ResourceClass.DISK_GB]['allocation_ratio'] = 1.0
        # and these come from the conf values set above
        exp_inv[rc_fields.ResourceClass.VCPU]['reserved'] = 1
        exp_inv[rc_fields.ResourceClass.MEMORY_MB]['reserved'] = 512
        # 1024MB in GB
        exp_inv[rc_fields.ResourceClass.DISK_GB]['reserved'] = 1
        self.assertEqual(exp_inv, ptree.data(new_compute.uuid).inventory)

    @mock.patch('nova.objects.ComputeNode.save', new=mock.Mock())
    def test_update_retry_success(self):
        self._setup_rt()
        orig_compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = orig_compute
        self.rt.old_resources[_NODENAME] = orig_compute
        # Deliberately changing local_gb to trigger updating inventory
        new_compute = orig_compute.obj_clone()
        new_compute.local_gb = 210000

        # Emulate a driver that has implemented the update_from_provider_tree()
        # virt driver method, so we hit the update_from_provider_tree path.
        self.driver_mock.update_provider_tree.side_effect = lambda *a: None

        ufpt_mock = self.rt.reportclient.update_from_provider_tree
        ufpt_mock.side_effect = (
            exc.ResourceProviderUpdateConflict(
                uuid='uuid', generation=42, error='error'), None)

        self.rt._update(mock.sentinel.ctx, new_compute)

        self.assertEqual(2, ufpt_mock.call_count)

    @mock.patch('nova.objects.ComputeNode.save', new=mock.Mock())
    def test_update_retry_raises(self):
        self._setup_rt()
        orig_compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = orig_compute
        self.rt.old_resources[_NODENAME] = orig_compute
        # Deliberately changing local_gb to trigger updating inventory
        new_compute = orig_compute.obj_clone()
        new_compute.local_gb = 210000

        # Emulate a driver that has implemented the update_from_provider_tree()
        # virt driver method, so we hit the update_from_provider_tree path.
        self.driver_mock.update_provider_tree.side_effect = lambda *a: None

        ufpt_mock = self.rt.reportclient.update_from_provider_tree
        ufpt_mock.side_effect = (
            exc.ResourceProviderUpdateConflict(
                uuid='uuid', generation=42, error='error'))

        self.assertRaises(exc.ResourceProviderUpdateConflict,
                          self.rt._update, mock.sentinel.ctx, new_compute)

        self.assertEqual(4, ufpt_mock.call_count)

    def test_get_node_uuid(self):
        self._setup_rt()
        orig_compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = orig_compute
        uuid = self.rt.get_node_uuid(_NODENAME)
        self.assertEqual(orig_compute.uuid, uuid)

    def test_get_node_uuid_not_found(self):
        self._setup_rt()
        self.assertRaises(exc.ComputeHostNotFound,
                          self.rt.get_node_uuid, 'foo')

    def test_copy_resources_no_update_allocation_ratios(self):
        """Tests that a ComputeNode object's allocation ratio fields are
        not set if the configured allocation ratio values are default 0.0.
        """
        self._setup_rt()
        compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        compute.obj_reset_changes()  # make sure we start clean
        self.rt._copy_resources(
            compute, self.driver_mock.get_available_resource.return_value)
        # Assert that the ComputeNode fields were not changed.
        changes = compute.obj_get_changes()
        for res in ('cpu', 'disk', 'ram'):
            attr_name = '%s_allocation_ratio' % res
            self.assertNotIn(attr_name, changes)

    def test_copy_resources_update_allocation_ratios_from_config(self):
        """Tests that a ComputeNode object's allocation ratio fields are
        set if the configured allocation ratio values are not 0.0.
        """
        # Set explicit ratio config values to 1.0 (the default is 0.0).
        for res in ('cpu', 'disk', 'ram'):
            opt_name = '%s_allocation_ratio' % res
            CONF.set_override(opt_name, 1.0)
        self._setup_rt()
        compute = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        compute.obj_reset_changes()  # make sure we start clean
        self.rt._copy_resources(
            compute, self.driver_mock.get_available_resource.return_value)
        # Assert that the ComputeNode fields were changed.
        changes = compute.obj_get_changes()
        for res in ('cpu', 'disk', 'ram'):
            attr_name = '%s_allocation_ratio' % res
            self.assertIn(attr_name, changes)
            self.assertEqual(1.0, changes[attr_name])


class TestNormalizatInventoryFromComputeNode(test.NoDBTestCase):
    def test_normalize_libvirt(self):
        self.flags(reserved_host_disk_mb=100,
                   reserved_host_memory_mb=10,
                   reserved_host_cpus=1)
        vcpus = 24
        memory_mb = 1024
        disk_gb = 200
        cn = objects.ComputeNode(
            mock.sentinel.ctx,
            ram_allocation_ratio=1.5,
            cpu_allocation_ratio=16.0,
            disk_allocation_ratio=1.0,
        )
        # What we get back from libvirt driver, for instance, doesn't contain
        # allocation_ratio or reserved amounts for some resources. Verify that
        # the information on the compute node fills in this information...
        inv = {
            rc_fields.ResourceClass.VCPU: {
                'total': vcpus,
                'min_unit': 1,
                'max_unit': vcpus,
                'step_size': 1,
            },
            rc_fields.ResourceClass.MEMORY_MB: {
                'total': memory_mb,
                'min_unit': 1,
                'max_unit': memory_mb,
                'step_size': 1,
            },
            rc_fields.ResourceClass.DISK_GB: {
                'total': disk_gb,
                'min_unit': 1,
                'max_unit': disk_gb,
                'step_size': 1,
            },
        }
        expected = {
            rc_fields.ResourceClass.VCPU: {
                'total': vcpus,
                'reserved': 1,
                'min_unit': 1,
                'max_unit': vcpus,
                'step_size': 1,
                'allocation_ratio': 16.0,
            },
            rc_fields.ResourceClass.MEMORY_MB: {
                'total': memory_mb,
                'reserved': 10,
                'min_unit': 1,
                'max_unit': memory_mb,
                'step_size': 1,
                'allocation_ratio': 1.5,
            },
            rc_fields.ResourceClass.DISK_GB: {
                'total': disk_gb,
                'reserved': 1,  # Rounded up from CONF.reserved_host_disk_mb
                'min_unit': 1,
                'max_unit': disk_gb,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
        }
        self.assertNotEqual(expected, inv)
        resource_tracker._normalize_inventory_from_cn_obj(inv, cn)
        self.assertEqual(expected, inv)

    def test_normalize_ironic(self):
        """Test that when normalizing the return from Ironic virt driver's
        get_inventory() method, we don't overwrite the information that the
        virt driver gave us.
        """
        self.flags(reserved_host_disk_mb=100,
                   reserved_host_memory_mb=10,
                   reserved_host_cpus=1)
        vcpus = 24
        memory_mb = 1024
        disk_gb = 200
        # We will make sure that these field values do NOT override what the
        # Ironic virt driver sets (which is, for example, that allocation
        # ratios are all 1.0 for Ironic baremetal nodes)
        cn = objects.ComputeNode(
            mock.sentinel.ctx,
            ram_allocation_ratio=1.5,
            cpu_allocation_ratio=16.0,
            disk_allocation_ratio=1.0,
        )
        # What we get back from Ironic driver contains fully-filled-out info
        # blocks for VCPU, MEMORY_MB, DISK_GB and the custom resource class
        # inventory items
        inv = {
            rc_fields.ResourceClass.VCPU: {
                'total': vcpus,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': vcpus,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
            rc_fields.ResourceClass.MEMORY_MB: {
                'total': memory_mb,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': memory_mb,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
            rc_fields.ResourceClass.DISK_GB: {
                'total': disk_gb,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': disk_gb,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
        }
        # We are expecting that NOTHING changes after calling the normalization
        # function
        expected = copy.deepcopy(inv)
        resource_tracker._normalize_inventory_from_cn_obj(inv, cn)
        self.assertEqual(expected, inv)


class TestInstanceClaim(BaseTestCase):

    def setUp(self):
        super(TestInstanceClaim, self).setUp()
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)

        self._setup_rt()
        cn = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = cn

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
        self.rt.compute_nodes = {}
        self.assertTrue(self.rt.disabled(_NODENAME))

        with mock.patch.object(self.instance, 'save'):
            claim = self.rt.instance_claim(mock.sentinel.ctx, self.instance,
                                           _NODENAME, None)

        self.assertEqual(self.rt.host, self.instance.host)
        self.assertEqual(self.rt.host, self.instance.launched_on)
        self.assertEqual(_NODENAME, self.instance.node)
        self.assertIsInstance(claim, claims.NopClaim)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_update_usage_with_claim(self, migr_mock, pci_mock,
                                     check_bfv_mock):
        # Test that RT.update_usage() only changes the compute node
        # resources if there has been a claim first.
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])
        check_bfv_mock.return_value = False

        expected = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        self.rt.update_usage(self.ctx, self.instance, _NODENAME)
        cn = self.rt.compute_nodes[_NODENAME]
        self.assertTrue(obj_base.obj_equal_prims(expected, cn))

        disk_used = self.instance.root_gb + self.instance.ephemeral_gb
        vals = {
            'local_gb_used': disk_used,
            'memory_mb_used': self.instance.memory_mb,
            'free_disk_gb': expected.local_gb - disk_used,
            "free_ram_mb": expected.memory_mb - self.instance.memory_mb,
            'running_vms': 1,
            'vcpus_used': 1,
            'pci_device_pools': objects.PciDevicePoolList(),
            'stats': {
                'io_workload': 0,
                'num_instances': 1,
                'num_task_None': 1,
                'num_os_type_' + self.instance.os_type: 1,
                'num_proj_' + self.instance.project_id: 1,
                'num_vm_' + self.instance.vm_state: 1,
            },
        }
        _update_compute_node(expected, **vals)
        with mock.patch.object(self.rt, '_update') as update_mock:
            with mock.patch.object(self.instance, 'save'):
                self.rt.instance_claim(self.ctx, self.instance, _NODENAME,
                                       None)
            cn = self.rt.compute_nodes[_NODENAME]
            update_mock.assert_called_once_with(self.elevated, cn)
            self.assertTrue(obj_base.obj_equal_prims(expected, cn))

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_update_usage_removed(self, migr_mock, pci_mock, check_bfv_mock):
        # Test that RT.update_usage() removes the instance when update is
        # called in a removed state
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])
        check_bfv_mock.return_value = False

        expected = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        disk_used = self.instance.root_gb + self.instance.ephemeral_gb
        vals = {
            'local_gb_used': disk_used,
            'memory_mb_used': self.instance.memory_mb,
            'free_disk_gb': expected.local_gb - disk_used,
            "free_ram_mb": expected.memory_mb - self.instance.memory_mb,
            'running_vms': 1,
            'vcpus_used': 1,
            'pci_device_pools': objects.PciDevicePoolList(),
            'stats': {
                'io_workload': 0,
                'num_instances': 1,
                'num_task_None': 1,
                'num_os_type_' + self.instance.os_type: 1,
                'num_proj_' + self.instance.project_id: 1,
                'num_vm_' + self.instance.vm_state: 1,
            },
        }
        _update_compute_node(expected, **vals)
        with mock.patch.object(self.rt, '_update') as update_mock:
            with mock.patch.object(self.instance, 'save'):
                self.rt.instance_claim(self.ctx, self.instance, _NODENAME,
                                       None)
            cn = self.rt.compute_nodes[_NODENAME]
            update_mock.assert_called_once_with(self.elevated, cn)
            self.assertTrue(obj_base.obj_equal_prims(expected, cn))

        expected_updated = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'pci_device_pools': objects.PciDevicePoolList(),
            'stats': {
                'io_workload': 0,
                'num_instances': 0,
                'num_task_None': 0,
                'num_os_type_' + self.instance.os_type: 0,
                'num_proj_' + self.instance.project_id: 0,
                'num_vm_' + self.instance.vm_state: 0,
            },
        }
        _update_compute_node(expected_updated, **vals)

        self.instance.vm_state = vm_states.SHELVED_OFFLOADED
        with mock.patch.object(self.rt, '_update') as update_mock:
            self.rt.update_usage(self.ctx, self.instance, _NODENAME)
        cn = self.rt.compute_nodes[_NODENAME]
        self.assertTrue(obj_base.obj_equal_prims(expected_updated, cn))

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_claim(self, migr_mock, pci_mock, check_bfv_mock):
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])
        check_bfv_mock.return_value = False

        disk_used = self.instance.root_gb + self.instance.ephemeral_gb
        expected = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'local_gb_used': disk_used,
            'memory_mb_used': self.instance.memory_mb,
            'free_disk_gb': expected.local_gb - disk_used,
            "free_ram_mb": expected.memory_mb - self.instance.memory_mb,
            'running_vms': 1,
            'vcpus_used': 1,
            'pci_device_pools': objects.PciDevicePoolList(),
            'stats': {
                'io_workload': 0,
                'num_instances': 1,
                'num_task_None': 1,
                'num_os_type_' + self.instance.os_type: 1,
                'num_proj_' + self.instance.project_id: 1,
                'num_vm_' + self.instance.vm_state: 1,
            },
        }
        _update_compute_node(expected, **vals)
        with mock.patch.object(self.rt, '_update') as update_mock:
            with mock.patch.object(self.instance, 'save'):
                self.rt.instance_claim(self.ctx, self.instance, _NODENAME,
                                       None)
            cn = self.rt.compute_nodes[_NODENAME]
            update_mock.assert_called_once_with(self.elevated, cn)
            self.assertTrue(obj_base.obj_equal_prims(expected, cn))

        self.assertEqual(self.rt.host, self.instance.host)
        self.assertEqual(self.rt.host, self.instance.launched_on)
        self.assertEqual(_NODENAME, self.instance.node)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.pci.stats.PciDeviceStats.support_requests',
                return_value=True)
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    def test_claim_with_pci(self, migr_mock, pci_mock, pci_stats_mock,
                            check_bfv_mock):
        # Test that a claim involving PCI requests correctly claims
        # PCI devices on the host and sends an updated pci_device_pools
        # attribute of the ComputeNode object.

        # TODO(jaypipes): Remove once the PCI tracker is always created
        # upon the resource tracker being initialized...
        self.rt.pci_tracker = pci_manager.PciDevTracker(mock.sentinel.ctx)

        pci_dev = pci_device.PciDevice.create(
            None, fake_pci_device.dev_dict)
        pci_devs = [pci_dev]
        self.rt.pci_tracker.pci_devs = objects.PciDeviceList(objects=pci_devs)

        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': 'v', 'product_id': 'p'}])
        pci_requests = objects.InstancePCIRequests(
                requests=[request],
                instance_uuid=self.instance.uuid)
        pci_mock.return_value = pci_requests
        check_bfv_mock.return_value = False

        disk_used = self.instance.root_gb + self.instance.ephemeral_gb
        expected = copy.deepcopy(_COMPUTE_NODE_FIXTURES[0])
        vals = {
            'local_gb_used': disk_used,
            'memory_mb_used': self.instance.memory_mb,
            'free_disk_gb': expected.local_gb - disk_used,
            "free_ram_mb": expected.memory_mb - self.instance.memory_mb,
            'running_vms': 1,
            'vcpus_used': 1,
            'pci_device_pools': objects.PciDevicePoolList(),
            'stats': {
                'io_workload': 0,
                'num_instances': 1,
                'num_task_None': 1,
                'num_os_type_' + self.instance.os_type: 1,
                'num_proj_' + self.instance.project_id: 1,
                'num_vm_' + self.instance.vm_state: 1,
            },
        }
        _update_compute_node(expected, **vals)
        with mock.patch.object(self.rt, '_update') as update_mock:
            with mock.patch.object(self.instance, 'save'):
                self.rt.instance_claim(self.ctx, self.instance, _NODENAME,
                                       None)
            cn = self.rt.compute_nodes[_NODENAME]
            update_mock.assert_called_once_with(self.elevated, cn)
            pci_stats_mock.assert_called_once_with([request])
            self.assertTrue(obj_base.obj_equal_prims(expected, cn))

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_claim_abort_context_manager(self, save_mock, migr_mock, pci_mock,
                                         check_bfv_mock):
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])
        check_bfv_mock.return_value = False

        cn = self.rt.compute_nodes[_NODENAME]
        self.assertEqual(0, cn.local_gb_used)
        self.assertEqual(0, cn.memory_mb_used)
        self.assertEqual(0, cn.running_vms)

        mock_save = mock.MagicMock()
        mock_clear_numa = mock.MagicMock()

        @mock.patch.object(self.instance, 'save', mock_save)
        @mock.patch.object(self.instance, 'clear_numa_topology',
                           mock_clear_numa)
        @mock.patch.object(objects.Instance, 'obj_clone',
                           return_value=self.instance)
        def _doit(mock_clone):
            with self.rt.instance_claim(self.ctx, self.instance, _NODENAME,
                                        None):
                # Raise an exception. Just make sure below that the abort()
                # method of the claim object was called (and the resulting
                # resources reset to the pre-claimed amounts)
                raise test.TestingException()

        self.assertRaises(test.TestingException, _doit)
        self.assertEqual(2, mock_save.call_count)
        mock_clear_numa.assert_called_once_with()
        self.assertIsNone(self.instance.host)
        self.assertIsNone(self.instance.node)

        # Assert that the resources claimed by the Claim() constructor
        # are returned to the resource tracker due to the claim's abort()
        # method being called when triggered by the exception raised above.
        self.assertEqual(0, cn.local_gb_used)
        self.assertEqual(0, cn.memory_mb_used)
        self.assertEqual(0, cn.running_vms)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_claim_abort(self, save_mock, migr_mock, pci_mock, check_bfv_mock):
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])
        check_bfv_mock.return_value = False
        disk_used = self.instance.root_gb + self.instance.ephemeral_gb

        @mock.patch.object(objects.Instance, 'obj_clone',
                           return_value=self.instance)
        @mock.patch.object(self.instance, 'save')
        def _claim(mock_save, mock_clone):
            return self.rt.instance_claim(self.ctx, self.instance, _NODENAME,
                                          None)

        cn = self.rt.compute_nodes[_NODENAME]

        claim = _claim()
        self.assertEqual(disk_used, cn.local_gb_used)
        self.assertEqual(self.instance.memory_mb,
                         cn.memory_mb_used)
        self.assertEqual(1, cn.running_vms)

        mock_save = mock.MagicMock()
        mock_clear_numa = mock.MagicMock()

        @mock.patch.object(self.instance, 'save', mock_save)
        @mock.patch.object(self.instance, 'clear_numa_topology',
                           mock_clear_numa)
        def _abort():
            claim.abort()

        _abort()
        mock_save.assert_called_once_with()
        mock_clear_numa.assert_called_once_with()
        self.assertIsNone(self.instance.host)
        self.assertIsNone(self.instance.node)

        self.assertEqual(0, cn.local_gb_used)
        self.assertEqual(0, cn.memory_mb_used)
        self.assertEqual(0, cn.running_vms)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_claim_limits(self, save_mock, migr_mock, pci_mock):
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])

        good_limits = {
            'memory_mb': _COMPUTE_NODE_FIXTURES[0].memory_mb,
            'disk_gb': _COMPUTE_NODE_FIXTURES[0].local_gb,
            'vcpu': _COMPUTE_NODE_FIXTURES[0].vcpus,
        }
        for key in good_limits.keys():
            bad_limits = copy.deepcopy(good_limits)
            bad_limits[key] = 0

            self.assertRaises(exc.ComputeResourcesUnavailable,
                    self.rt.instance_claim,
                    self.ctx, self.instance, _NODENAME, bad_limits)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_claim_numa(self, save_mock, migr_mock, pci_mock, check_bfv_mock):
        pci_mock.return_value = objects.InstancePCIRequests(requests=[])
        check_bfv_mock.return_value = False
        cn = self.rt.compute_nodes[_NODENAME]

        self.instance.numa_topology = _INSTANCE_NUMA_TOPOLOGIES['2mb']
        host_topology = _NUMA_HOST_TOPOLOGIES['2mb']
        cn.numa_topology = host_topology._to_json()
        limits = {'numa_topology': _NUMA_LIMIT_TOPOLOGIES['2mb']}

        expected_numa = copy.deepcopy(host_topology)
        for cell in expected_numa.cells:
            cell.memory_usage += _2MB
            cell.cpu_usage += 1
        with mock.patch.object(self.rt, '_update') as update_mock:
            with mock.patch.object(self.instance, 'save'):
                self.rt.instance_claim(self.ctx, self.instance, _NODENAME,
                                       limits)
            update_mock.assert_called_once_with(self.ctx.elevated(), cn)
            new_numa = cn.numa_topology
            new_numa = objects.NUMATopology.obj_from_db_obj(new_numa)
            self.assertEqualNUMAHostTopology(expected_numa, new_numa)


class TestResize(BaseTestCase):
    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.Service.get_minimum_version',
                return_value=22)
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_resize_claim_same_host(self, save_mock, get_mock, migr_mock,
                                    get_cn_mock, pci_mock, instance_pci_mock,
                                    version_mock, is_bfv_mock):
        # Resize an existing instance from its current flavor (instance type
        # 1) to a new flavor (instance type 2) and verify that the compute
        # node's resources are appropriately updated to account for the new
        # flavor's resources. In this scenario, we use an Instance that has not
        # already had its "current" flavor set to the new flavor.
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(vcpus_used=1,
                              memory_mb_used=128,
                              local_gb_used=1)
        self._setup_rt(virt_resources=virt_resources)

        get_mock.return_value = _INSTANCE_FIXTURES
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        instance = _INSTANCE_FIXTURES[0].obj_clone()
        instance.new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]
        # This migration context is fine, it points to the first instance
        # fixture and indicates a source-and-dest resize.
        mig_context_obj = _MIGRATION_CONTEXT_FIXTURES[instance.uuid]
        instance.migration_context = mig_context_obj

        self.rt.update_available_resource(mock.MagicMock(), _NODENAME)

        migration = objects.Migration(
            id=3,
            instance_uuid=instance.uuid,
            source_compute=_HOSTNAME,
            dest_compute=_HOSTNAME,
            source_node=_NODENAME,
            dest_node=_NODENAME,
            old_instance_type_id=1,
            new_instance_type_id=2,
            migration_type='resize',
            status='migrating'
        )
        new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]

        # not using mock.sentinel.ctx because resize_claim calls #elevated
        ctx = mock.MagicMock()

        expected = self.rt.compute_nodes[_NODENAME].obj_clone()
        expected.vcpus_used = (expected.vcpus_used +
                               new_flavor.vcpus)
        expected.memory_mb_used = (expected.memory_mb_used +
                                   new_flavor.memory_mb)
        expected.free_ram_mb = expected.memory_mb - expected.memory_mb_used
        expected.local_gb_used = (expected.local_gb_used +
                                 (new_flavor.root_gb +
                                    new_flavor.ephemeral_gb))
        expected.free_disk_gb = (expected.free_disk_gb -
                                (new_flavor.root_gb +
                                    new_flavor.ephemeral_gb))

        with test.nested(
            mock.patch('nova.compute.resource_tracker.ResourceTracker'
                       '._create_migration',
                       return_value=migration),
            mock.patch('nova.objects.MigrationContext',
                       return_value=mig_context_obj),
            mock.patch('nova.objects.Instance.save'),
        ) as (create_mig_mock, ctxt_mock, inst_save_mock):
            claim = self.rt.resize_claim(ctx, instance, new_flavor, _NODENAME,
                                         None)

        create_mig_mock.assert_called_once_with(
                ctx, instance, new_flavor, _NODENAME,
                None  # move_type is None for resize...
        )
        self.assertIsInstance(claim, claims.MoveClaim)
        cn = self.rt.compute_nodes[_NODENAME]
        self.assertTrue(obj_base.obj_equal_prims(expected, cn))
        self.assertEqual(1, len(self.rt.tracked_migrations))

        # Now abort the resize claim and check that the resources have been set
        # back to their original values.
        with mock.patch('nova.objects.Instance.'
                        'drop_migration_context') as drop_migr_mock:
            claim.abort()
        drop_migr_mock.assert_called_once_with()

        self.assertEqual(1, cn.vcpus_used)
        self.assertEqual(1, cn.local_gb_used)
        self.assertEqual(128, cn.memory_mb_used)
        self.assertEqual(0, len(self.rt.tracked_migrations))

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.Service.get_minimum_version',
                return_value=22)
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename',
                return_value=_COMPUTE_NODE_FIXTURES[0])
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node',
                return_value=[])
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node',
                return_value=[])
    @mock.patch('nova.objects.ComputeNode.save')
    def _test_instance_build_resize(self,
                                    save_mock,
                                    get_by_host_and_node_mock,
                                    get_in_progress_by_host_and_node_mock,
                                    get_by_host_and_nodename_mock,
                                    pci_get_by_compute_node_mock,
                                    pci_get_by_instance_mock,
                                    pci_get_by_instance_uuid_mock,
                                    version_mock,
                                    is_bfv_mock,
                                    revert=False):

        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        self._setup_rt(virt_resources=virt_resources)

        # not using mock.sentinel.ctx because resize_claim calls #elevated
        ctx = mock.MagicMock()

        # Init compute node
        self.rt.update_available_resource(mock.MagicMock(), _NODENAME)
        expected = self.rt.compute_nodes[_NODENAME].obj_clone()

        instance = _INSTANCE_FIXTURES[0].obj_clone()
        old_flavor = instance.flavor
        instance.new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]

        # Build instance
        with mock.patch.object(instance, 'save'):
            self.rt.instance_claim(ctx, instance, _NODENAME, None)

        expected = compute_update_usage(expected, old_flavor, sign=1)
        expected.running_vms = 1
        self.assertTrue(obj_base.obj_equal_prims(
            expected,
            self.rt.compute_nodes[_NODENAME],
            ignore=['stats']
        ))

        # This migration context is fine, it points to the first instance
        # fixture and indicates a source-and-dest resize.
        mig_context_obj = _MIGRATION_CONTEXT_FIXTURES[instance.uuid]
        instance.migration_context = mig_context_obj

        migration = objects.Migration(
            id=3,
            instance_uuid=instance.uuid,
            source_compute=_HOSTNAME,
            dest_compute=_HOSTNAME,
            source_node=_NODENAME,
            dest_node=_NODENAME,
            old_instance_type_id=1,
            new_instance_type_id=2,
            migration_type='resize',
            status='migrating'
        )
        new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]

        # Resize instance
        with test.nested(
            mock.patch('nova.compute.resource_tracker.ResourceTracker'
                       '._create_migration',
                       return_value=migration),
            mock.patch('nova.objects.MigrationContext',
                       return_value=mig_context_obj),
            mock.patch('nova.objects.Instance.save'),
        ) as (create_mig_mock, ctxt_mock, inst_save_mock):
            self.rt.resize_claim(ctx, instance, new_flavor, _NODENAME, None)

        expected = compute_update_usage(expected, new_flavor, sign=1)
        self.assertTrue(obj_base.obj_equal_prims(
            expected,
            self.rt.compute_nodes[_NODENAME],
            ignore=['stats']
        ))
        # Confirm or revert resize
        if revert:
            flavor = new_flavor
            prefix = 'new_'
        else:
            flavor = old_flavor
            prefix = 'old_'

        self.rt.drop_move_claim(ctx, instance, _NODENAME, flavor,
                                prefix=prefix)

        expected = compute_update_usage(expected, flavor, sign=-1)
        self.assertTrue(obj_base.obj_equal_prims(
            expected,
            self.rt.compute_nodes[_NODENAME],
            ignore=['stats']
        ))

    def test_instance_build_resize_revert(self):
        self._test_instance_build_resize(revert=True)

    def test_instance_build_resize_confirm(self):
        self._test_instance_build_resize()

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.Service.get_minimum_version',
                return_value=22)
    @mock.patch('nova.pci.stats.PciDeviceStats.support_requests',
                return_value=True)
    @mock.patch('nova.objects.PciDevice.save')
    @mock.patch('nova.pci.manager.PciDevTracker.claim_instance')
    @mock.patch('nova.pci.request.get_pci_requests_from_flavor')
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_resize_claim_dest_host_with_pci(self, save_mock, get_mock,
            migr_mock, get_cn_mock, pci_mock, pci_req_mock, pci_claim_mock,
            pci_dev_save_mock, pci_supports_mock, version_mock,
            mock_is_volume_backed_instance):
        # Starting from an empty destination compute node, perform a resize
        # operation for an instance containing SR-IOV PCI devices on the
        # original host.
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)
        self._setup_rt()

        # TODO(jaypipes): Remove once the PCI tracker is always created
        # upon the resource tracker being initialized...
        self.rt.pci_tracker = pci_manager.PciDevTracker(mock.sentinel.ctx)

        pci_dev = pci_device.PciDevice.create(
            None, fake_pci_device.dev_dict)
        pci_devs = [pci_dev]
        self.rt.pci_tracker.pci_devs = objects.PciDeviceList(objects=pci_devs)
        pci_claim_mock.return_value = [pci_dev]

        # start with an empty dest compute node. No migrations, no instances
        get_mock.return_value = []
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0]

        self.rt.update_available_resource(mock.MagicMock(), _NODENAME)

        instance = _INSTANCE_FIXTURES[0].obj_clone()
        instance.task_state = task_states.RESIZE_MIGRATING
        instance.new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]

        # A destination-only migration
        migration = objects.Migration(
            id=3,
            instance_uuid=instance.uuid,
            source_compute="other-host",
            dest_compute=_HOSTNAME,
            source_node="other-node",
            dest_node=_NODENAME,
            old_instance_type_id=1,
            new_instance_type_id=2,
            migration_type='resize',
            status='migrating',
            instance=instance,
        )
        mig_context_obj = objects.MigrationContext(
            instance_uuid=instance.uuid,
            migration_id=3,
            new_numa_topology=None,
            old_numa_topology=None,
        )
        instance.migration_context = mig_context_obj
        new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]

        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': 'v', 'product_id': 'p'}])
        pci_requests = objects.InstancePCIRequests(
                requests=[request],
                instance_uuid=instance.uuid,
        )
        instance.pci_requests = pci_requests
        # NOTE(jaypipes): This looks weird, so let me explain. The Instance PCI
        # requests on a resize come from two places. The first is the PCI
        # information from the new flavor. The second is for SR-IOV devices
        # that are directly attached to the migrating instance. The
        # pci_req_mock.return value here is for the flavor PCI device requests
        # (which is nothing). This empty list will be merged with the Instance
        # PCI requests defined directly above.
        pci_req_mock.return_value = objects.InstancePCIRequests(requests=[])

        # not using mock.sentinel.ctx because resize_claim calls elevated
        ctx = mock.MagicMock()

        with test.nested(
            mock.patch('nova.pci.manager.PciDevTracker.allocate_instance'),
            mock.patch('nova.compute.resource_tracker.ResourceTracker'
                       '._create_migration',
                       return_value=migration),
            mock.patch('nova.objects.MigrationContext',
                       return_value=mig_context_obj),
            mock.patch('nova.objects.Instance.save'),
        ) as (alloc_mock, create_mig_mock, ctxt_mock, inst_save_mock):
            self.rt.resize_claim(ctx, instance, new_flavor, _NODENAME, None)

        pci_claim_mock.assert_called_once_with(ctx, pci_req_mock.return_value,
                                               None)
        # Validate that the pci.request.get_pci_request_from_flavor() return
        # value was merged with the instance PCI requests from the Instance
        # itself that represent the SR-IOV devices from the original host.
        pci_req_mock.assert_called_once_with(new_flavor)
        self.assertEqual(1, len(pci_req_mock.return_value.requests))
        self.assertEqual(request, pci_req_mock.return_value.requests[0])
        alloc_mock.assert_called_once_with(instance)

    def test_drop_move_claim_on_revert(self):
        self._setup_rt()
        cn = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = cn

        # TODO(jaypipes): Remove once the PCI tracker is always created
        # upon the resource tracker being initialized...
        self.rt.pci_tracker = pci_manager.PciDevTracker(mock.sentinel.ctx)

        pci_dev = pci_device.PciDevice.create(
            None, fake_pci_device.dev_dict)
        pci_devs = [pci_dev]

        instance = _INSTANCE_FIXTURES[0].obj_clone()
        instance.task_state = task_states.RESIZE_MIGRATING
        instance.flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]
        instance.migration_context = objects.MigrationContext()
        instance.migration_context.new_pci_devices = objects.PciDeviceList(
            objects=pci_devs)

        self.rt.tracked_instances = {
            instance.uuid: obj_base.obj_to_primitive(instance)
        }

        # not using mock.sentinel.ctx because drop_move_claim calls elevated
        ctx = mock.MagicMock()

        with test.nested(
            mock.patch.object(self.rt, '_update'),
            mock.patch.object(self.rt.pci_tracker, 'free_device')
            ) as (update_mock, mock_pci_free_device):
                self.rt.drop_move_claim(ctx, instance, _NODENAME)
                mock_pci_free_device.assert_called_once_with(
                    pci_dev, mock.ANY)

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.Service.get_minimum_version',
                return_value=22)
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_resize_claim_two_instances(self, save_mock, get_mock, migr_mock,
            get_cn_mock, pci_mock, instance_pci_mock, version_mock,
            mock_is_volume_backed_instance):
        # Issue two resize claims against a destination host with no prior
        # instances on it and validate that the accounting for resources is
        # correct.
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)
        self._setup_rt()

        get_mock.return_value = []
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0].obj_clone()

        self.rt.update_available_resource(mock.MagicMock(), _NODENAME)

        # Instance #1 is resizing to instance type 2 which has 2 vCPUs, 256MB
        # RAM and 5GB root disk.
        instance1 = _INSTANCE_FIXTURES[0].obj_clone()
        instance1.id = 1
        instance1.uuid = uuids.instance1
        instance1.task_state = task_states.RESIZE_MIGRATING
        instance1.new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]

        migration1 = objects.Migration(
            id=1,
            instance_uuid=instance1.uuid,
            source_compute="other-host",
            dest_compute=_HOSTNAME,
            source_node="other-node",
            dest_node=_NODENAME,
            old_instance_type_id=1,
            new_instance_type_id=2,
            migration_type='resize',
            status='migrating',
            instance=instance1,
        )
        mig_context_obj1 = objects.MigrationContext(
            instance_uuid=instance1.uuid,
            migration_id=1,
            new_numa_topology=None,
            old_numa_topology=None,
        )
        instance1.migration_context = mig_context_obj1
        flavor1 = _INSTANCE_TYPE_OBJ_FIXTURES[2]

        # Instance #2 is resizing to instance type 1 which has 1 vCPU, 128MB
        # RAM and 1GB root disk.
        instance2 = _INSTANCE_FIXTURES[0].obj_clone()
        instance2.id = 2
        instance2.uuid = uuids.instance2
        instance2.task_state = task_states.RESIZE_MIGRATING
        instance2.old_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2]
        instance2.new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[1]

        migration2 = objects.Migration(
            id=2,
            instance_uuid=instance2.uuid,
            source_compute="other-host",
            dest_compute=_HOSTNAME,
            source_node="other-node",
            dest_node=_NODENAME,
            old_instance_type_id=2,
            new_instance_type_id=1,
            migration_type='resize',
            status='migrating',
            instance=instance1,
        )
        mig_context_obj2 = objects.MigrationContext(
            instance_uuid=instance2.uuid,
            migration_id=2,
            new_numa_topology=None,
            old_numa_topology=None,
        )
        instance2.migration_context = mig_context_obj2
        flavor2 = _INSTANCE_TYPE_OBJ_FIXTURES[1]

        expected = self.rt.compute_nodes[_NODENAME].obj_clone()
        expected.vcpus_used = (expected.vcpus_used +
                               flavor1.vcpus +
                               flavor2.vcpus)
        expected.memory_mb_used = (expected.memory_mb_used +
                                   flavor1.memory_mb +
                                   flavor2.memory_mb)
        expected.free_ram_mb = expected.memory_mb - expected.memory_mb_used
        expected.local_gb_used = (expected.local_gb_used +
                                 (flavor1.root_gb +
                                  flavor1.ephemeral_gb +
                                  flavor2.root_gb +
                                  flavor2.ephemeral_gb))
        expected.free_disk_gb = (expected.free_disk_gb -
                                (flavor1.root_gb +
                                 flavor1.ephemeral_gb +
                                 flavor2.root_gb +
                                 flavor2.ephemeral_gb))

        # not using mock.sentinel.ctx because resize_claim calls #elevated
        ctx = mock.MagicMock()

        with test.nested(
            mock.patch('nova.compute.resource_tracker.ResourceTracker'
                       '._create_migration',
                       side_effect=[migration1, migration2]),
            mock.patch('nova.objects.MigrationContext',
                       side_effect=[mig_context_obj1, mig_context_obj2]),
            mock.patch('nova.objects.Instance.save'),
        ) as (create_mig_mock, ctxt_mock, inst_save_mock):
            self.rt.resize_claim(ctx, instance1, flavor1, _NODENAME, None)
            self.rt.resize_claim(ctx, instance2, flavor2, _NODENAME, None)
        cn = self.rt.compute_nodes[_NODENAME]
        self.assertTrue(obj_base.obj_equal_prims(expected, cn))
        self.assertEqual(2, len(self.rt.tracked_migrations),
                         "Expected 2 tracked migrations but got %s"
                         % self.rt.tracked_migrations)


class TestRebuild(BaseTestCase):
    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.objects.Service.get_minimum_version',
                return_value=22)
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance',
                return_value=objects.InstancePCIRequests(requests=[]))
    @mock.patch('nova.objects.PciDeviceList.get_by_compute_node',
                return_value=objects.PciDeviceList())
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename')
    @mock.patch('nova.objects.MigrationList.get_in_progress_by_host_and_node')
    @mock.patch('nova.objects.InstanceList.get_by_host_and_node')
    @mock.patch('nova.objects.ComputeNode.save')
    def test_rebuild_claim(self, save_mock, get_mock, migr_mock, get_cn_mock,
            pci_mock, instance_pci_mock, version_mock, bfv_check_mock):
        # Rebuild an instance, emulating an evacuate command issued against the
        # original instance. The rebuild operation uses the resource tracker's
        # _move_claim() method, but unlike with resize_claim(), rebuild_claim()
        # passes in a pre-created Migration object from the destination compute
        # manager.
        self.flags(reserved_host_disk_mb=0,
                   reserved_host_memory_mb=0)

        # Starting state for the destination node of the rebuild claim is the
        # normal compute node fixture containing a single active running VM
        # having instance type #1.
        virt_resources = copy.deepcopy(_VIRT_DRIVER_AVAIL_RESOURCES)
        virt_resources.update(vcpus_used=1,
                              memory_mb_used=128,
                              local_gb_used=1)
        self._setup_rt(virt_resources=virt_resources)

        get_mock.return_value = _INSTANCE_FIXTURES
        migr_mock.return_value = []
        get_cn_mock.return_value = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        bfv_check_mock.return_value = False

        ctx = mock.MagicMock()
        self.rt.update_available_resource(ctx, _NODENAME)

        # Now emulate the evacuate command by calling rebuild_claim() on the
        # resource tracker as the compute manager does, supplying a Migration
        # object that corresponds to the evacuation.
        migration = objects.Migration(
            mock.sentinel.ctx,
            id=1,
            instance_uuid=uuids.rebuilding_instance,
            source_compute='fake-other-compute',
            source_node='fake-other-node',
            status='accepted',
            migration_type='evacuation'
        )
        instance = objects.Instance(
            id=1,
            host=None,
            node=None,
            uuid='abef5b54-dea6-47b8-acb2-22aeb1b57919',
            memory_mb=_INSTANCE_TYPE_FIXTURES[2]['memory_mb'],
            vcpus=_INSTANCE_TYPE_FIXTURES[2]['vcpus'],
            root_gb=_INSTANCE_TYPE_FIXTURES[2]['root_gb'],
            ephemeral_gb=_INSTANCE_TYPE_FIXTURES[2]['ephemeral_gb'],
            numa_topology=None,
            pci_requests=None,
            pci_devices=None,
            instance_type_id=2,
            vm_state=vm_states.ACTIVE,
            power_state=power_state.RUNNING,
            task_state=task_states.REBUILDING,
            os_type='fake-os',
            project_id='fake-project',
            flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
            old_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
            new_flavor = _INSTANCE_TYPE_OBJ_FIXTURES[2],
        )

        # not using mock.sentinel.ctx because resize_claim calls #elevated
        ctx = mock.MagicMock()

        with test.nested(
            mock.patch('nova.objects.Migration.save'),
            mock.patch('nova.objects.Instance.save'),
        ) as (mig_save_mock, inst_save_mock):
            self.rt.rebuild_claim(ctx, instance, _NODENAME,
                                  migration=migration)

        self.assertEqual(_HOSTNAME, migration.dest_compute)
        self.assertEqual(_NODENAME, migration.dest_node)
        self.assertEqual("pre-migrating", migration.status)
        self.assertEqual(1, len(self.rt.tracked_migrations))
        mig_save_mock.assert_called_once_with()
        inst_save_mock.assert_called_once_with()


class TestUpdateUsageFromMigration(test.NoDBTestCase):
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_get_instance_type')
    def test_unsupported_move_type(self, get_mock):
        rt = resource_tracker.ResourceTracker(mock.sentinel.virt_driver,
                                              _HOSTNAME)
        migration = objects.Migration(migration_type='live-migration')
        # For same-node migrations, the RT's _get_instance_type() method is
        # called if there is a migration that is trackable. Here, we want to
        # ensure that this method isn't called for live-migration migrations.
        rt._update_usage_from_migration(mock.sentinel.ctx,
                                        mock.sentinel.instance,
                                        migration,
                                        _NODENAME)
        self.assertFalse(get_mock.called)


class TestUpdateUsageFromMigrations(BaseTestCase):
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update_usage_from_migration')
    def test_no_migrations(self, mock_update_usage):
        migrations = []
        self._setup_rt()
        self.rt._update_usage_from_migrations(mock.sentinel.ctx, migrations,
                                              _NODENAME)
        self.assertFalse(mock_update_usage.called)

    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update_usage_from_migration')
    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    def test_instance_not_found(self, mock_get_instance, mock_update_usage):
        mock_get_instance.side_effect = exc.InstanceNotFound(
            instance_id='some_id',
        )
        migration = objects.Migration(
            context=mock.sentinel.ctx,
            instance_uuid='some_uuid',
        )
        self._setup_rt()
        self.rt._update_usage_from_migrations(mock.sentinel.ctx, [migration],
                                              _NODENAME)
        mock_get_instance.assert_called_once_with(mock.sentinel.ctx,
                                                  'some_uuid')
        self.assertFalse(mock_update_usage.called)

    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update_usage_from_migration')
    def test_duplicate_migrations_filtered(self, upd_mock):
        # The wrapper function _update_usage_from_migrations() looks at the
        # list of migration objects returned from
        # MigrationList.get_in_progress_by_host_and_node() and ensures that
        # only the most recent migration record for an instance is used in
        # determining the usage records. Here we pass multiple migration
        # objects for a single instance and ensure that we only call the
        # _update_usage_from_migration() (note: not migration*s*...) once with
        # the migration object with greatest updated_at value. We also pass
        # some None values for various updated_at attributes to exercise some
        # of the code paths in the filtering logic.
        self._setup_rt()

        instance = objects.Instance(vm_state=vm_states.RESIZED,
                                    task_state=None)
        ts1 = timeutils.utcnow()
        ts0 = ts1 - datetime.timedelta(seconds=10)
        ts2 = ts1 + datetime.timedelta(seconds=10)

        migrations = [
            objects.Migration(source_compute=_HOSTNAME,
                              source_node=_NODENAME,
                              dest_compute=_HOSTNAME,
                              dest_node=_NODENAME,
                              instance_uuid=uuids.instance,
                              created_at=ts0,
                              updated_at=ts1,
                              id=1,
                              instance=instance),
            objects.Migration(source_compute=_HOSTNAME,
                              source_node=_NODENAME,
                              dest_compute=_HOSTNAME,
                              dest_node=_NODENAME,
                              instance_uuid=uuids.instance,
                              created_at=ts0,
                              updated_at=ts2,
                              id=2,
                              instance=instance)
        ]
        mig1, mig2 = migrations
        mig_list = objects.MigrationList(objects=migrations)
        instance.migration_context = objects.MigrationContext(
            migration_id=mig2.id)
        self.rt._update_usage_from_migrations(mock.sentinel.ctx, mig_list,
                                              _NODENAME)
        upd_mock.assert_called_once_with(mock.sentinel.ctx, instance, mig2,
                                         _NODENAME)

        upd_mock.reset_mock()
        mig2.updated_at = None
        instance.migration_context.migration_id = mig1.id
        self.rt._update_usage_from_migrations(mock.sentinel.ctx, mig_list,
                _NODENAME)
        upd_mock.assert_called_once_with(mock.sentinel.ctx, instance, mig1,
                _NODENAME)

    @mock.patch('nova.objects.migration.Migration.save')
    @mock.patch.object(resource_tracker.ResourceTracker,
                       '_update_usage_from_migration')
    def test_ignore_stale_migration(self, upd_mock, save_mock):
        # In _update_usage_from_migrations() we want to only look at
        # migrations where the migration id matches the migration ID that is
        # stored in the instance migration context.  The problem scenario is
        # that the instance is migrating on host B, but we run the resource
        # audit on host A and there is a stale migration in the DB for the
        # same instance involving host A.
        self._setup_rt()
        # Create an instance which is migrating with a migration id of 2
        migration_context = objects.MigrationContext(migration_id=2)
        instance = objects.Instance(vm_state=vm_states.RESIZED,
                                    task_state=None,
                                    migration_context=migration_context)
        # Create a stale migration object with id of 1
        mig1 = objects.Migration(source_compute=_HOSTNAME,
                              source_node=_NODENAME,
                              dest_compute=_HOSTNAME,
                              dest_node=_NODENAME,
                              instance_uuid=uuids.instance,
                              updated_at=timeutils.utcnow(),
                              id=1,
                              instance=instance)
        mig_list = objects.MigrationList(objects=[mig1])
        self.rt._update_usage_from_migrations(mock.sentinel.ctx, mig_list,
                                              _NODENAME)
        self.assertFalse(upd_mock.called)
        self.assertEqual(mig1.status, "error")

    @mock.patch('nova.objects.migration.Migration.save')
    @mock.patch.object(resource_tracker.ResourceTracker,
                       '_update_usage_from_migration')
    def test_evacuate_and_resizing_states(self, mock_update_usage, mock_save):
        self._setup_rt()
        migration_context = objects.MigrationContext(migration_id=1)
        instance = objects.Instance(
            vm_state=vm_states.STOPPED, task_state=None,
            migration_context=migration_context)
        migration = objects.Migration(
            source_compute='other-host', source_node='other-node',
            dest_compute=_HOSTNAME, dest_node=_NODENAME,
            instance_uuid=uuids.instance, id=1, instance=instance)
        for state in task_states.rebuild_states + task_states.resizing_states:
            instance.task_state = state
            self.rt._update_usage_from_migrations(
                mock.sentinel.ctx, [migration], _NODENAME)
            mock_update_usage.assert_called_once_with(
                mock.sentinel.ctx, instance, migration, _NODENAME)
            mock_update_usage.reset_mock()


class TestUpdateUsageFromInstance(BaseTestCase):

    def setUp(self):
        super(TestUpdateUsageFromInstance, self).setUp()
        self._setup_rt()
        cn = _COMPUTE_NODE_FIXTURES[0].obj_clone()
        self.rt.compute_nodes[_NODENAME] = cn
        self.instance = _INSTANCE_FIXTURES[0].obj_clone()

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    def test_get_usage_dict_return_0_root_gb_for_bfv_instance(
            self, mock_check_bfv):
        mock_check_bfv.return_value = True
        # Make sure the cache is empty.
        self.assertNotIn(self.instance.uuid, self.rt.is_bfv)
        result = self.rt._get_usage_dict(self.instance, self.instance)
        self.assertEqual(0, result['root_gb'])
        mock_check_bfv.assert_called_once_with(
            self.instance._context, self.instance)
        # Make sure we updated the cache.
        self.assertIn(self.instance.uuid, self.rt.is_bfv)
        self.assertTrue(self.rt.is_bfv[self.instance.uuid])
        # Now run _get_usage_dict again to make sure we don't call
        # is_volume_backed_instance.
        mock_check_bfv.reset_mock()
        result = self.rt._get_usage_dict(self.instance, self.instance)
        self.assertEqual(0, result['root_gb'])
        mock_check_bfv.assert_not_called()

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    def test_get_usage_dict_include_swap(
            self, mock_check_bfv):
        mock_check_bfv.return_value = False
        instance_with_swap = self.instance.obj_clone()
        instance_with_swap.flavor.swap = 10
        result = self.rt._get_usage_dict(
            instance_with_swap, instance_with_swap)
        self.assertEqual(10, result['swap'])

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update_usage')
    def test_building(self, mock_update_usage, mock_check_bfv):
        mock_check_bfv.return_value = False
        self.instance.vm_state = vm_states.BUILDING
        self.rt._update_usage_from_instance(mock.sentinel.ctx, self.instance,
                                            _NODENAME)

        mock_update_usage.assert_called_once_with(
            self.rt._get_usage_dict(self.instance, self.instance),
            _NODENAME, sign=1)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update_usage')
    def test_shelve_offloading(self, mock_update_usage, mock_check_bfv):
        mock_check_bfv.return_value = False
        self.instance.vm_state = vm_states.SHELVED_OFFLOADED
        # Stub out the is_bfv cache to make sure we remove the instance
        # from it after updating usage.
        self.rt.is_bfv[self.instance.uuid] = False
        self.rt.tracked_instances = {
            self.instance.uuid: obj_base.obj_to_primitive(self.instance)
        }
        self.rt._update_usage_from_instance(mock.sentinel.ctx, self.instance,
                                            _NODENAME)
        # The instance should have been removed from the is_bfv cache.
        self.assertNotIn(self.instance.uuid, self.rt.is_bfv)
        mock_update_usage.assert_called_once_with(
            self.rt._get_usage_dict(self.instance, self.instance),
            _NODENAME, sign=-1)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update_usage')
    def test_unshelving(self, mock_update_usage, mock_check_bfv):
        mock_check_bfv.return_value = False
        self.instance.vm_state = vm_states.SHELVED_OFFLOADED
        self.rt._update_usage_from_instance(mock.sentinel.ctx, self.instance,
                                            _NODENAME)

        mock_update_usage.assert_called_once_with(
            self.rt._get_usage_dict(self.instance, self.instance),
            _NODENAME, sign=1)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                '_update_usage')
    def test_deleted(self, mock_update_usage, mock_check_bfv):
        mock_check_bfv.return_value = False
        self.instance.vm_state = vm_states.DELETED
        self.rt.tracked_instances = {
                self.instance.uuid: obj_base.obj_to_primitive(self.instance)
        }
        self.rt._update_usage_from_instance(mock.sentinel.ctx,
                                            self.instance, _NODENAME, True)

        mock_update_usage.assert_called_once_with(
            self.rt._get_usage_dict(self.instance, self.instance),
            _NODENAME, sign=-1)

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_remove_deleted_instances_allocations_deleted_instance(self,
            mock_inst_get):
        rc = self.rt.reportclient
        self.rt.tracked_instances = {}
        allocs = {uuids.deleted: "fake_deleted_instance"}
        rc.get_allocations_for_resource_provider = mock.MagicMock(
            return_value=allocs)
        rc.delete_allocation_for_instance = mock.MagicMock()
        mock_inst_get.return_value = objects.Instance(
            uuid=uuids.deleted, deleted=True)
        cn = self.rt.compute_nodes[_NODENAME]
        ctx = mock.MagicMock()
        # Call the method.
        self.rt._remove_deleted_instances_allocations(ctx, cn, [], {})
        # Only one call should be made to delete allocations, and that should
        # be for the first instance created above
        rc.delete_allocation_for_instance.assert_called_once_with(
            ctx, uuids.deleted)
        mock_inst_get.assert_called_once_with(
            ctx.elevated.return_value,
            uuids.deleted,
            expected_attrs=[])
        ctx.elevated.assert_called_once_with(read_deleted='yes')

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_remove_deleted_instances_allocations_building_instance(self,
            mock_inst_get):
        rc = self.rt.reportclient
        self.rt.tracked_instances = {}
        allocs = {uuids.deleted: "fake_deleted_instance"}
        rc.get_allocations_for_resource_provider = mock.MagicMock(
            return_value=allocs)
        rc.delete_allocation_for_instance = mock.MagicMock()
        mock_inst_get.side_effect = exc.InstanceNotFound(
            instance_id=uuids.deleted)
        cn = self.rt.compute_nodes[_NODENAME]
        ctx = mock.MagicMock()
        # Call the method.
        self.rt._remove_deleted_instances_allocations(ctx, cn, [], {})
        # Instance wasn't found in the database at all, so the allocation
        # should not have been deleted
        self.assertFalse(rc.delete_allocation_for_instance.called)

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_remove_deleted_instances_allocations_ignores_migrations(self,
            mock_inst_get):
        rc = self.rt.reportclient
        self.rt.tracked_instances = {}
        allocs = {uuids.deleted: "fake_deleted_instance",
                  uuids.migration: "fake_migration"}
        mig = objects.Migration(uuid=uuids.migration)
        rc.get_allocations_for_resource_provider = mock.MagicMock(
            return_value=allocs)
        rc.delete_allocation_for_instance = mock.MagicMock()
        mock_inst_get.return_value = objects.Instance(
            uuid=uuids.deleted, deleted=True)
        cn = self.rt.compute_nodes[_NODENAME]
        ctx = mock.MagicMock()
        # Call the method.
        self.rt._remove_deleted_instances_allocations(
            ctx, cn, [mig], {uuids.migration:
                             objects.Instance(uuid=uuids.imigration)})
        # Only one call should be made to delete allocations, and that should
        # be for the first instance created above
        rc.delete_allocation_for_instance.assert_called_once_with(
            ctx, uuids.deleted)

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_remove_deleted_instances_allocations_scheduled_instance(self,
            mock_inst_get):
        rc = self.rt.reportclient
        self.rt.tracked_instances = {}
        allocs = {uuids.scheduled: "fake_scheduled_instance"}
        rc.get_allocations_for_resource_provider = mock.MagicMock(
            return_value=allocs)
        rc.delete_allocation_for_instance = mock.MagicMock()
        instance_by_uuid = {uuids.scheduled:
                            objects.Instance(uuid=uuids.scheduled,
                                             deleted=False, host=None)}
        cn = self.rt.compute_nodes[_NODENAME]
        ctx = mock.MagicMock()
        # Call the method.
        self.rt._remove_deleted_instances_allocations(ctx, cn, [],
                                                      instance_by_uuid)
        # Scheduled instances should not have their allocations removed
        rc.delete_allocation_for_instance.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocations_for_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete_allocation_for_instance')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_remove_deleted_instances_allocations_move_ops(self, mock_get,
            mock_delete_allocs, mock_get_allocs):
        """Test that we do NOT delete allocations for instances that are
        currently undergoing move operations.
        """
        self.rt.tracked_instances = {}
        # Create 1 instance
        instance = _INSTANCE_FIXTURES[0].obj_clone()
        instance.uuid = uuids.moving_instance
        instance.host = uuids.destination
        # Instances in resizing/move will be ACTIVE or STOPPED
        instance.vm_state = vm_states.ACTIVE
        # Mock out the allocation call
        allocs = {uuids.inst0: mock.sentinel.moving_instance}
        mock_get_allocs.return_value = allocs
        mock_get.return_value = instance

        cn = self.rt.compute_nodes[_NODENAME]
        ctx = mock.MagicMock()
        self.rt._remove_deleted_instances_allocations(ctx, cn, [], mock.ANY)
        mock_delete_allocs.assert_not_called()

    def test_remove_deleted_instances_allocations_known_instance(self):
        """Tests the case that actively tracked instances for the
        given node do not have their allocations removed.
        """
        rc = self.rt.reportclient
        self.rt.tracked_instances = {
            uuids.known: objects.Instance(uuid=uuids.known)}
        allocs = {
            uuids.known: {
                'resources': {
                    'VCPU': 1,
                    'MEMORY_MB': 2048,
                    'DISK_GB': 20
                }
            }
        }
        rc.get_allocations_for_resource_provider = mock.MagicMock(
            return_value=allocs)
        rc.delete_allocation_for_instance = mock.MagicMock()
        cn = self.rt.compute_nodes[_NODENAME]
        ctx = mock.MagicMock()
        # Call the method.
        self.rt._remove_deleted_instances_allocations(ctx, cn, [],
            self.rt.tracked_instances)
        # We don't delete the allocation because the node is tracking the
        # instance and has allocations for it.
        rc.delete_allocation_for_instance.assert_not_called()

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_remove_deleted_instances_allocations_unknown_instance(
            self, mock_inst_get):
        """Tests the case that an instance is found with allocations for
        this host/node but is not in the dict of tracked instances. The
        allocations are not removed for the instance since we don't know
        how this happened or what to do.
        """
        instance = _INSTANCE_FIXTURES[0]
        mock_inst_get.return_value = instance
        rc = self.rt.reportclient
        # No tracked instances on this node.
        self.rt.tracked_instances = {}
        # But there is an allocation for an instance on this node.
        allocs = {
            instance.uuid: {
                'resources': {
                    'VCPU': 1,
                    'MEMORY_MB': 2048,
                    'DISK_GB': 20
                }
            }
        }
        rc.get_allocations_for_resource_provider = mock.MagicMock(
            return_value=allocs)
        rc.delete_allocation_for_instance = mock.MagicMock()
        cn = self.rt.compute_nodes[_NODENAME]
        ctx = mock.MagicMock()
        # Call the method.
        self.rt._remove_deleted_instances_allocations(
            ctx, cn, [], self.rt.tracked_instances)
        # We don't delete the allocation because we're not sure what to do.
        # NOTE(mriedem): This is not actually the behavior we want. This is
        # testing the current behavior but in the future when we get smart
        # and figure things out, this should actually be an error.
        rc.delete_allocation_for_instance.assert_not_called()

    def test_delete_allocation_for_shelve_offloaded_instance(self):
        instance = _INSTANCE_FIXTURES[0].obj_clone()
        instance.uuid = uuids.inst0

        self.rt.delete_allocation_for_shelve_offloaded_instance(
            mock.sentinel.ctx, instance)

        rc = self.rt.reportclient
        mock_remove_allocation = rc.delete_allocation_for_instance
        mock_remove_allocation.assert_called_once_with(
            mock.sentinel.ctx, instance.uuid)

    def test_update_usage_from_instances_goes_negative(self):
        # NOTE(danms): The resource tracker _should_ report negative resources
        # for things like free_ram_mb if overcommit is being used. This test
        # ensures that we don't collapse negative values to zero.
        self.flags(reserved_host_memory_mb=2048)
        self.flags(reserved_host_disk_mb=(11 * 1024))
        cn = objects.ComputeNode(memory_mb=1024, local_gb=10)
        self.rt.compute_nodes['foo'] = cn

        @mock.patch.object(self.rt,
                           '_remove_deleted_instances_allocations')
        @mock.patch.object(self.rt, '_update_usage_from_instance')
        @mock.patch('nova.objects.Service.get_minimum_version',
                    return_value=22)
        def test(version_mock, uufi, rdia):
            self.rt._update_usage_from_instances('ctxt', [], 'foo')

        test()

        self.assertEqual(-1024, cn.free_ram_mb)
        self.assertEqual(-1, cn.free_disk_gb)

    def test_update_usage_from_instances_refreshes_ironic(self):
        self.rt.driver.requires_allocation_refresh = True

        @mock.patch.object(self.rt,
                           '_remove_deleted_instances_allocations')
        @mock.patch.object(self.rt, '_update_usage_from_instance')
        @mock.patch('nova.objects.Service.get_minimum_version',
                    return_value=22)
        def test(version_mock, uufi, rdia):
            self.rt._update_usage_from_instances('ctxt', [self.instance],
                                                 _NODENAME)

            uufi.assert_called_once_with('ctxt', self.instance, _NODENAME,
                                         require_allocation_refresh=True)

        test()

    def test_update_usage_from_instances_no_refresh(self):
        self.rt.driver.requires_allocation_refresh = False

        @mock.patch.object(self.rt,
                           '_remove_deleted_instances_allocations')
        @mock.patch.object(self.rt, '_update_usage_from_instance')
        @mock.patch('nova.objects.Service.get_minimum_version',
                    return_value=22)
        def test(version_mock, uufi, rdia):
            self.rt._update_usage_from_instances('ctxt', [self.instance],
                                                 _NODENAME)

            uufi.assert_called_once_with('ctxt', self.instance, _NODENAME,
                                         require_allocation_refresh=False)

        test()

    @mock.patch('nova.scheduler.utils.resources_from_flavor')
    def test_delete_allocation_for_evacuated_instance(
            self, mock_resource_from_flavor):
        mock_resource = mock.Mock()
        mock_resource_from_flavor.return_value = mock_resource
        instance = _INSTANCE_FIXTURES[0].obj_clone()
        instance.uuid = uuids.inst0
        ctxt = context.get_admin_context()

        self.rt.delete_allocation_for_evacuated_instance(
            ctxt, instance, _NODENAME)

        rc = self.rt.reportclient
        mock_remove_allocation = rc.remove_provider_from_instance_allocation
        mock_remove_allocation.assert_called_once_with(
            ctxt, instance.uuid, self.rt.compute_nodes[_NODENAME].uuid,
            instance.user_id, instance.project_id, mock_resource)


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


class TestSetInstanceHostAndNode(BaseTestCase):

    def setUp(self):
        super(TestSetInstanceHostAndNode, self).setUp()
        self._setup_rt()

    @mock.patch('nova.objects.Instance.save')
    def test_set_instance_host_and_node(self, save_mock):
        inst = objects.Instance()
        self.rt._set_instance_host_and_node(inst, _NODENAME)
        save_mock.assert_called_once_with()
        self.assertEqual(self.rt.host, inst.host)
        self.assertEqual(_NODENAME, inst.node)
        self.assertEqual(self.rt.host, inst.launched_on)

    @mock.patch('nova.objects.Instance.save')
    def test_unset_instance_host_and_node(self, save_mock):
        inst = objects.Instance()
        self.rt._set_instance_host_and_node(inst, _NODENAME)
        self.rt._unset_instance_host_and_node(inst)
        self.assertEqual(2, save_mock.call_count)
        self.assertIsNone(inst.host)
        self.assertIsNone(inst.node)
        self.assertEqual(self.rt.host, inst.launched_on)


def _update_compute_node(node, **kwargs):
    for key, value in kwargs.items():
        setattr(node, key, value)


class ComputeMonitorTestCase(BaseTestCase):
    def setUp(self):
        super(ComputeMonitorTestCase, self).setUp()
        self._setup_rt()
        self.info = {}
        self.context = context.RequestContext(mock.sentinel.user_id,
                                              mock.sentinel.project_id)

    def test_get_host_metrics_none(self):
        self.rt.monitors = []
        metrics = self.rt._get_host_metrics(self.context, _NODENAME)
        self.assertEqual(len(metrics), 0)

    @mock.patch.object(resource_tracker.LOG, 'warning')
    def test_get_host_metrics_exception(self, mock_LOG_warning):
        monitor = mock.MagicMock()
        monitor.populate_metrics.side_effect = Exception
        self.rt.monitors = [monitor]
        metrics = self.rt._get_host_metrics(self.context, _NODENAME)
        mock_LOG_warning.assert_called_once_with(
            u'Cannot get the metrics from %(mon)s; error: %(exc)s', mock.ANY)
        self.assertEqual(0, len(metrics))

    @mock.patch('nova.compute.utils.notify_about_metrics_update')
    def test_get_host_metrics(self, mock_notify):
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        class FakeCPUMonitor(monitor_base.MonitorBase):

            NOW_TS = timeutils.utcnow()

            def __init__(self, *args):
                super(FakeCPUMonitor, self).__init__(*args)
                self.source = 'FakeCPUMonitor'

            def get_metric_names(self):
                return set(["cpu.frequency"])

            def populate_metrics(self, monitor_list):
                metric_object = objects.MonitorMetric()
                metric_object.name = 'cpu.frequency'
                metric_object.value = 100
                metric_object.timestamp = self.NOW_TS
                metric_object.source = self.source
                monitor_list.objects.append(metric_object)

        self.rt.monitors = [FakeCPUMonitor(None)]

        metrics = self.rt._get_host_metrics(self.context, _NODENAME)

        mock_notify.assert_called_once_with(
            self.context, _HOSTNAME, '1.1.1.1', _NODENAME,
            test.MatchType(objects.MonitorMetricList))

        expected_metrics = [
            {
                'timestamp': FakeCPUMonitor.NOW_TS.isoformat(),
                'name': 'cpu.frequency',
                'value': 100,
                'source': 'FakeCPUMonitor'
            },
        ]

        payload = {
            'metrics': expected_metrics,
            'host': _HOSTNAME,
            'host_ip': '1.1.1.1',
            'nodename': _NODENAME,
        }

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('compute.metrics.update', msg.event_type)
        for p_key in payload:
            if p_key == 'metrics':
                self.assertIn(p_key, msg.payload)
                self.assertEqual(1, len(msg.payload['metrics']))
                # make sure the expected metrics match the actual metrics
                self.assertDictEqual(expected_metrics[0],
                                     msg.payload['metrics'][0])
            else:
                self.assertEqual(payload[p_key], msg.payload[p_key])

        self.assertEqual(metrics, expected_metrics)


class TestIsTrackableMigration(test.NoDBTestCase):
    def test_true(self):
        mig = objects.Migration()
        for mig_type in ('resize', 'migration', 'evacuation'):
            mig.migration_type = mig_type

            self.assertTrue(resource_tracker._is_trackable_migration(mig))

    def test_false(self):
        mig = objects.Migration()
        for mig_type in ('live-migration',):
            mig.migration_type = mig_type

            self.assertFalse(resource_tracker._is_trackable_migration(mig))


class OverCommitTestCase(BaseTestCase):
    def test_cpu_allocation_ratio_none_negative(self):
        self.assertRaises(ValueError,
                          CONF.set_default, 'cpu_allocation_ratio', -1.0)

    def test_ram_allocation_ratio_none_negative(self):
        self.assertRaises(ValueError,
                          CONF.set_default, 'ram_allocation_ratio', -1.0)

    def test_disk_allocation_ratio_none_negative(self):
        self.assertRaises(ValueError,
                          CONF.set_default, 'disk_allocation_ratio', -1.0)
