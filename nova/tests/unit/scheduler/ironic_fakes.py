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

from oslo.serialization import jsonutils


COMPUTE_NODES = [
        dict(id=1, local_gb=10, memory_mb=1024, vcpus=1,
             vcpus_used=0, local_gb_used=0, memory_mb_used=0,
             updated_at=None, cpu_info='baremetal cpu',
             service=dict(host='host1', disabled=False),
             host='host1',
             hypervisor_hostname='node1uuid', host_ip='127.0.0.1',
             hypervisor_version=1, hypervisor_type='ironic',
             stats=jsonutils.dumps(dict(ironic_driver=
                                        "nova.virt.ironic.driver.IronicDriver",
                                        cpu_arch='i386')),
             supported_instances='[["i386", "baremetal", "baremetal"]]',
             free_disk_gb=10, free_ram_mb=1024),
        dict(id=2, local_gb=20, memory_mb=2048, vcpus=1,
             vcpus_used=0, local_gb_used=0, memory_mb_used=0,
             updated_at=None, cpu_info='baremetal cpu',
             service=dict(host='host2', disabled=True),
             host='host2',
             hypervisor_hostname='node2uuid', host_ip='127.0.0.1',
             hypervisor_version=1, hypervisor_type='ironic',
             stats=jsonutils.dumps(dict(ironic_driver=
                                        "nova.virt.ironic.driver.IronicDriver",
                                        cpu_arch='i386')),
             supported_instances='[["i386", "baremetal", "baremetal"]]',
             free_disk_gb=20, free_ram_mb=2048),
        dict(id=3, local_gb=30, memory_mb=3072, vcpus=1,
             vcpus_used=0, local_gb_used=0, memory_mb_used=0,
             updated_at=None, cpu_info='baremetal cpu',
             service=dict(host='host3', disabled=False),
             host='host3',
             hypervisor_hostname='node3uuid', host_ip='127.0.0.1',
             hypervisor_version=1, hypervisor_type='ironic',
             stats=jsonutils.dumps(dict(ironic_driver=
                                        "nova.virt.ironic.driver.IronicDriver",
                                        cpu_arch='i386')),
             supported_instances='[["i386", "baremetal", "baremetal"]]',
             free_disk_gb=30, free_ram_mb=3072),
        dict(id=4, local_gb=40, memory_mb=4096, vcpus=1,
             vcpus_used=0, local_gb_used=0, memory_mb_used=0,
             updated_at=None, cpu_info='baremetal cpu',
             service=dict(host='host4', disabled=False),
             host='host4',
             hypervisor_hostname='node4uuid', host_ip='127.0.0.1',
             hypervisor_version=1, hypervisor_type='ironic',
             stats=jsonutils.dumps(dict(ironic_driver=
                                        "nova.virt.ironic.driver.IronicDriver",
                                        cpu_arch='i386')),
             supported_instances='[["i386", "baremetal", "baremetal"]]',
             free_disk_gb=40, free_ram_mb=4096),
        # Broken entry
        dict(id=5, local_gb=50, memory_mb=5120, vcpus=1, service=None,
             host='fake', cpu_info='baremetal cpu',
             stats=jsonutils.dumps(dict(ironic_driver=
                                        "nova.virt.ironic.driver.IronicDriver",
                                        cpu_arch='i386')),
             supported_instances='[["i386", "baremetal", "baremetal"]]',
             free_disk_gb=50, free_ram_mb=5120),
]
