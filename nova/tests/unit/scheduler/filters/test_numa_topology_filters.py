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

import itertools
import uuid

from nova import objects
from nova.objects import fields
from nova.scheduler.filters import numa_topology_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestNUMATopologyFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestNUMATopologyFilter, self).setUp()
        self.filt_cls = numa_topology_filter.NUMATopologyFilter()

    def _get_spec_obj(self, numa_topology):
        image_meta = objects.ImageMeta(properties=objects.ImageMetaProps())
        spec_obj = objects.RequestSpec(numa_topology=numa_topology,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()),
                                       flavor=objects.Flavor(extra_specs={}),
                                       image=image_meta)
        return spec_obj

    def test_numa_topology_filter_pass(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        spec_obj = self._get_spec_obj(numa_topology=instance_topology)
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

        spec_obj = self._get_spec_obj(numa_topology=instance_topology)
        host = fakes.FakeHostState('host1', 'node1', {'pci_stats': None})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_numa_host_no_numa_instance_pass(self):
        spec_obj = self._get_spec_obj(numa_topology=None)
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_fail_fit(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([2]), memory=512),
                   objects.InstanceNUMACell(id=2, cpuset=set([3]), memory=512)
               ])
        spec_obj = self._get_spec_obj(numa_topology=instance_topology)
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
        spec_obj = self._get_spec_obj(numa_topology=instance_topology)
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
        spec_obj = self._get_spec_obj(numa_topology=instance_topology)
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
        spec_obj = self._get_spec_obj(numa_topology=instance_topology)
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY,
                                    'pci_stats': None,
                                    'cpu_allocation_ratio': 21,
                                    'ram_allocation_ratio': 1.3})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        limits = host.limits['numa_topology']
        self.assertEqual(limits.cpu_allocation_ratio, 21)
        self.assertEqual(limits.ram_allocation_ratio, 1.3)

    def _do_test_numa_topology_filter_cpu_policy(
            self, numa_topology, cpu_policy, cpu_thread_policy, passes):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        spec_obj = objects.RequestSpec(numa_topology=instance_topology,
                                       pci_requests=None,
                                       instance_uuid=str(uuid.uuid4()))

        extra_specs = [
            {},
            {
                'hw:cpu_policy': cpu_policy,
                'hw:cpu_thread_policy': cpu_thread_policy,
            }
        ]
        image_props = [
            {},
            {
                'hw_cpu_policy': cpu_policy,
                'hw_cpu_thread_policy': cpu_thread_policy,
            }
        ]
        host = fakes.FakeHostState('host1', 'node1', {
            'numa_topology': numa_topology,
            'pci_stats': None,
            'cpu_allocation_ratio': 1,
            'ram_allocation_ratio': 1.5})
        assertion = self.assertTrue if passes else self.assertFalse

        # test combinations of image properties and extra specs
        for specs, props in itertools.product(extra_specs, image_props):
            # ...except for the one where no policy is specified
            if specs == props == {}:
                continue

            fake_flavor = objects.Flavor(memory_mb=1024, extra_specs=specs)
            fake_image_props = objects.ImageMetaProps(**props)
            fake_image = objects.ImageMeta(properties=fake_image_props)

            spec_obj.image = fake_image
            spec_obj.flavor = fake_flavor

            assertion(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_fail_cpu_thread_policy_require(self):
        cpu_policy = fields.CPUAllocationPolicy.DEDICATED
        cpu_thread_policy = fields.CPUThreadAllocationPolicy.REQUIRE
        numa_topology = fakes.NUMA_TOPOLOGY

        self._do_test_numa_topology_filter_cpu_policy(
            numa_topology, cpu_policy, cpu_thread_policy, False)

    def test_numa_topology_filter_pass_cpu_thread_policy_require(self):
        cpu_policy = fields.CPUAllocationPolicy.DEDICATED
        cpu_thread_policy = fields.CPUThreadAllocationPolicy.REQUIRE
        numa_topology = fakes.NUMA_TOPOLOGY_W_HT

        self._do_test_numa_topology_filter_cpu_policy(
            numa_topology, cpu_policy, cpu_thread_policy, True)

    def test_numa_topology_filter_pass_cpu_thread_policy_others(self):
        cpu_policy = fields.CPUAllocationPolicy.DEDICATED
        cpu_thread_policy = fields.CPUThreadAllocationPolicy.PREFER
        numa_topology = fakes.NUMA_TOPOLOGY

        for cpu_thread_policy in [
                fields.CPUThreadAllocationPolicy.PREFER,
                fields.CPUThreadAllocationPolicy.ISOLATE]:
            self._do_test_numa_topology_filter_cpu_policy(
                numa_topology, cpu_policy, cpu_thread_policy, True)

    def test_numa_topology_filter_pass_mempages(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([3]),
                                            memory=128, pagesize=4),
                   objects.InstanceNUMACell(id=1, cpuset=set([1]),
                                            memory=128, pagesize=16)
            ])
        spec_obj = self._get_spec_obj(numa_topology=instance_topology)
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY,
                                    'pci_stats': None,
                                    'cpu_allocation_ratio': 16.0,
                                    'ram_allocation_ratio': 1.5})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_fail_mempages(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([3]),
                                            memory=128, pagesize=8),
                   objects.InstanceNUMACell(id=1, cpuset=set([1]),
                                            memory=128, pagesize=16)
               ])
        spec_obj = self._get_spec_obj(numa_topology=instance_topology)
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY,
                                    'pci_stats': None,
                                    'cpu_allocation_ratio': 16.0,
                                    'ram_allocation_ratio': 1.5})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
