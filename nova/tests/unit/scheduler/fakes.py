# Copyright 2011 OpenStack Foundation
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
"""
Fakes For Scheduler tests.
"""

import datetime

from nova import objects
from nova.scheduler import driver
from nova.scheduler import host_manager
from nova.tests import uuidsentinel

NUMA_TOPOLOGY = objects.NUMATopology(
                           cells=[
                             objects.NUMACell(
                               id=0, cpuset=set([1, 2]), memory=512,
                               cpu_usage=0, memory_usage=0, mempages=[
                                 objects.NUMAPagesTopology(size_kb=16,
                                                           total=387184,
                                                           used=0),
                                 objects.NUMAPagesTopology(size_kb=2048,
                                                           total=512, used=0)],
                               siblings=[], pinned_cpus=set([])),
                             objects.NUMACell(
                               id=1, cpuset=set([3, 4]), memory=512,
                               cpu_usage=0, memory_usage=0, mempages=[
                                 objects.NUMAPagesTopology(size_kb=4,
                                                           total=1548736,
                                                           used=0),
                                 objects.NUMAPagesTopology(size_kb=2048,
                                                           total=512, used=0)],
                               siblings=[], pinned_cpus=set([]))])

NUMA_TOPOLOGIES_W_HT = [
    objects.NUMATopology(cells=[
        objects.NUMACell(
            id=0, cpuset=set([1, 2, 5, 6]), memory=512,
            cpu_usage=0, memory_usage=0, mempages=[],
            siblings=[set([1, 5]), set([2, 6])], pinned_cpus=set([])),
        objects.NUMACell(
            id=1, cpuset=set([3, 4, 7, 8]), memory=512,
            cpu_usage=0, memory_usage=0, mempages=[],
            siblings=[set([3, 4]), set([7, 8])], pinned_cpus=set([]))
    ]),
    objects.NUMATopology(cells=[
        objects.NUMACell(
            id=0, cpuset=set([]), memory=512,
            cpu_usage=0, memory_usage=0, mempages=[],
            siblings=[], pinned_cpus=set([])),
        objects.NUMACell(
            id=1, cpuset=set([1, 2, 5, 6]), memory=512,
            cpu_usage=0, memory_usage=0, mempages=[],
            siblings=[set([1, 5]), set([2, 6])], pinned_cpus=set([])),
        objects.NUMACell(
            id=2, cpuset=set([3, 4, 7, 8]), memory=512,
            cpu_usage=0, memory_usage=0, mempages=[],
            siblings=[set([3, 4]), set([7, 8])], pinned_cpus=set([])),
    ]),
]

COMPUTE_NODES = [
        objects.ComputeNode(
            uuid=uuidsentinel.cn1,
            id=1, local_gb=1024, memory_mb=1024, vcpus=1,
            disk_available_least=None, free_ram_mb=512, vcpus_used=1,
            free_disk_gb=512, local_gb_used=0,
            updated_at=datetime.datetime(2015, 11, 11, 11, 0, 0),
            host='host1', hypervisor_hostname='node1', host_ip='127.0.0.1',
            hypervisor_version=0, numa_topology=None,
            hypervisor_type='foo', supported_hv_specs=[],
            pci_device_pools=None, cpu_info=None, stats=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0),
        objects.ComputeNode(
            uuid=uuidsentinel.cn2,
            id=2, local_gb=2048, memory_mb=2048, vcpus=2,
            disk_available_least=1024, free_ram_mb=1024, vcpus_used=2,
            free_disk_gb=1024, local_gb_used=0,
            updated_at=datetime.datetime(2015, 11, 11, 11, 0, 0),
            host='host2', hypervisor_hostname='node2', host_ip='127.0.0.1',
            hypervisor_version=0, numa_topology=None,
            hypervisor_type='foo', supported_hv_specs=[],
            pci_device_pools=None, cpu_info=None, stats=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0),
        objects.ComputeNode(
            uuid=uuidsentinel.cn3,
            id=3, local_gb=4096, memory_mb=4096, vcpus=4,
            disk_available_least=3333, free_ram_mb=3072, vcpus_used=1,
            free_disk_gb=3072, local_gb_used=0,
            updated_at=datetime.datetime(2015, 11, 11, 11, 0, 0),
            host='host3', hypervisor_hostname='node3', host_ip='127.0.0.1',
            hypervisor_version=0, numa_topology=NUMA_TOPOLOGY._to_json(),
            hypervisor_type='foo', supported_hv_specs=[],
            pci_device_pools=None, cpu_info=None, stats=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0),
        objects.ComputeNode(
            uuid=uuidsentinel.cn4,
            id=4, local_gb=8192, memory_mb=8192, vcpus=8,
            disk_available_least=8192, free_ram_mb=8192, vcpus_used=0,
            free_disk_gb=8888, local_gb_used=0,
            updated_at=datetime.datetime(2015, 11, 11, 11, 0, 0),
            host='host4', hypervisor_hostname='node4', host_ip='127.0.0.1',
            hypervisor_version=0, numa_topology=None,
            hypervisor_type='foo', supported_hv_specs=[],
            pci_device_pools=None, cpu_info=None, stats=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0),
        # Broken entry
        objects.ComputeNode(
            uuid=uuidsentinel.cn5,
            id=5, local_gb=1024, memory_mb=1024, vcpus=1,
            host='fake', hypervisor_hostname='fake-hyp'),
]

ALLOC_REQS = [
    {
        'allocations': {
            cn.uuid: {
                'resources': {
                    'VCPU': 1,
                    'MEMORY_MB': 512,
                    'DISK_GB': 512,
                },
            }
        }
    } for cn in COMPUTE_NODES
]

RESOURCE_PROVIDERS = [
    dict(
        uuid=uuidsentinel.rp1,
        name='host1',
        generation=1),
    dict(
        uuid=uuidsentinel.rp2,
        name='host2',
        generation=1),
    dict(
        uuid=uuidsentinel.rp3,
        name='host3',
        generation=1),
    dict(
        uuid=uuidsentinel.rp4,
        name='host4',
        generation=1),
]

SERVICES = [
        objects.Service(host='host1', disabled=False),
        objects.Service(host='host2', disabled=True),
        objects.Service(host='host3', disabled=False),
        objects.Service(host='host4', disabled=False),
]


def get_service_by_host(host):
    services = [service for service in SERVICES if service.host == host]
    return services[0]


class FakeHostState(host_manager.HostState):
    def __init__(self, host, node, attribute_dict, instances=None):
        super(FakeHostState, self).__init__(host, node, None)
        if instances:
            self.instances = {inst.uuid: inst for inst in instances}
        else:
            self.instances = {}
        for (key, val) in attribute_dict.items():
            setattr(self, key, val)


class FakeScheduler(driver.Scheduler):

    def select_destinations(self, context, spec_obj, instance_uuids):
        return []
