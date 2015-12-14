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

import uuid

from nova import objects
from nova.scheduler.filters import numa_topology_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestNUMATopologyFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestNUMATopologyFilter, self).setUp()
        self.filt_cls = numa_topology_filter.NUMATopologyFilter()

    def test_numa_topology_filter_pass(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        spec_obj = objects.RequestSpec(numa_topology=instance_topology,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY,
                                    'pci_stats': None,
                                    'cpu_allocation_ratio': 16.0,
                                    'ram_allocation_ratio': 1.5})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_numa_instance_no_numa_host_fail(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])

        spec_obj = objects.RequestSpec(numa_topology=instance_topology,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()))
        host = fakes.FakeHostState('host1', 'node1', {'pci_stats': None})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_numa_host_no_numa_instance_pass(self):
        spec_obj = objects.RequestSpec(numa_topology=None,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_fail_fit(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([2]), memory=512),
                   objects.InstanceNUMACell(id=2, cpuset=set([3]), memory=512)
               ])
        spec_obj = objects.RequestSpec(numa_topology=instance_topology,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY,
                                    'pci_stats': None,
                                    'cpu_allocation_ratio': 16.0,
                                    'ram_allocation_ratio': 1.5})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_fail_memory(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]),
                                            memory=1024),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        spec_obj = objects.RequestSpec(numa_topology=instance_topology,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY,
                                    'pci_stats': None,
                                    'cpu_allocation_ratio': 16.0,
                                    'ram_allocation_ratio': 1})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_fail_cpu(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3, 4, 5]),
                                            memory=512)])
        spec_obj = objects.RequestSpec(numa_topology=instance_topology,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY,
                                    'pci_stats': None,
                                    'cpu_allocation_ratio': 1,
                                    'ram_allocation_ratio': 1.5})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_pass_set_limit(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        spec_obj = objects.RequestSpec(numa_topology=instance_topology,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()))
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY,
                                    'pci_stats': None,
                                    'cpu_allocation_ratio': 21,
                                    'ram_allocation_ratio': 1.3})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        limits = host.limits['numa_topology']
        self.assertEqual(limits.cpu_allocation_ratio, 21)
        self.assertEqual(limits.ram_allocation_ratio, 1.3)
