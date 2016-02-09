# Copyright 2014 OpenStack Foundation
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
Fake nodes for Ironic host manager tests.
"""

from nova import objects


COMPUTE_NODES = [
        objects.ComputeNode(
            id=1, local_gb=10, memory_mb=1024, vcpus=1,
            vcpus_used=0, local_gb_used=0, memory_mb_used=0,
            updated_at=None, cpu_info='baremetal cpu',
            host='host1',
            hypervisor_hostname='node1uuid', host_ip='127.0.0.1',
            hypervisor_version=1, hypervisor_type='ironic',
            stats=dict(ironic_driver=
                       "nova.virt.ironic.driver.IronicDriver",
                       cpu_arch='i386'),
            supported_hv_specs=[objects.HVSpec.from_list(
                ["i386", "baremetal", "baremetal"])],
            free_disk_gb=10, free_ram_mb=1024,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0),
        objects.ComputeNode(
            id=2, local_gb=20, memory_mb=2048, vcpus=1,
            vcpus_used=0, local_gb_used=0, memory_mb_used=0,
            updated_at=None, cpu_info='baremetal cpu',
            host='host2',
            hypervisor_hostname='node2uuid', host_ip='127.0.0.1',
            hypervisor_version=1, hypervisor_type='ironic',
            stats=dict(ironic_driver=
                       "nova.virt.ironic.driver.IronicDriver",
                       cpu_arch='i386'),
            supported_hv_specs=[objects.HVSpec.from_list(
                ["i386", "baremetal", "baremetal"])],
            free_disk_gb=20, free_ram_mb=2048,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0),
        objects.ComputeNode(
            id=3, local_gb=30, memory_mb=3072, vcpus=1,
            vcpus_used=0, local_gb_used=0, memory_mb_used=0,
            updated_at=None, cpu_info='baremetal cpu',
            host='host3',
            hypervisor_hostname='node3uuid', host_ip='127.0.0.1',
            hypervisor_version=1, hypervisor_type='ironic',
            stats=dict(ironic_driver=
                       "nova.virt.ironic.driver.IronicDriver",
                       cpu_arch='i386'),
            supported_hv_specs=[objects.HVSpec.from_list(
                ["i386", "baremetal", "baremetal"])],
            free_disk_gb=30, free_ram_mb=3072,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0),
        objects.ComputeNode(
            id=4, local_gb=40, memory_mb=4096, vcpus=1,
            vcpus_used=0, local_gb_used=0, memory_mb_used=0,
            updated_at=None, cpu_info='baremetal cpu',
            host='host4',
            hypervisor_hostname='node4uuid', host_ip='127.0.0.1',
            hypervisor_version=1, hypervisor_type='ironic',
            stats=dict(ironic_driver=
                       "nova.virt.ironic.driver.IronicDriver",
                       cpu_arch='i386'),
            supported_hv_specs=[objects.HVSpec.from_list(
                ["i386", "baremetal", "baremetal"])],
            free_disk_gb=40, free_ram_mb=4096,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0),
        # Broken entry
        objects.ComputeNode(
            id=5, local_gb=50, memory_mb=5120, vcpus=1,
            host='fake', cpu_info='baremetal cpu',
            stats=dict(ironic_driver=
                       "nova.virt.ironic.driver.IronicDriver",
                       cpu_arch='i386'),
            supported_hv_specs=[objects.HVSpec.from_list(
                ["i386", "baremetal", "baremetal"])],
            free_disk_gb=50, free_ram_mb=5120,
            hypervisor_hostname='fake-hyp'),
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
