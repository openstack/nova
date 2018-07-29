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

import mock

from nova import objects
from nova.objects import fields
from nova.scheduler.filters import numa_topology_filter
from nova import test
from nova.tests.unit.scheduler import fakes
from nova.tests import uuidsentinel as uuids


class TestNUMATopologyFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestNUMATopologyFilter, self).setUp()
        self.filt_cls = numa_topology_filter.NUMATopologyFilter()

    def _get_spec_obj(self, numa_topology, network_metadata=None):
        image_meta = objects.ImageMeta(properties=objects.ImageMetaProps())

        spec_obj = objects.RequestSpec(numa_topology=numa_topology,
                                       pci_requests=None,
                                       instance_uuid=uuids.fake,
                                       flavor=objects.Flavor(extra_specs={}),
                                       image=image_meta)

        if network_metadata:
            spec_obj.network_metadata = network_metadata

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

    @mock.patch('nova.objects.instance_numa_topology.InstanceNUMACell'
                '.cpu_pinning_requested',
                return_value=True)
    def _do_test_numa_topology_filter_cpu_policy(
            self, numa_topology, cpu_policy, cpu_thread_policy, passes,
            mock_pinning_requested):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        spec_obj = objects.RequestSpec(numa_topology=instance_topology,
                                       pci_requests=None,
                                       instance_uuid=uuids.fake)

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
            self.assertIsNone(spec_obj.numa_topology.cells[0].cpu_pinning)

    def test_numa_topology_filter_fail_cpu_thread_policy_require(self):
        cpu_policy = fields.CPUAllocationPolicy.DEDICATED
        cpu_thread_policy = fields.CPUThreadAllocationPolicy.REQUIRE
        numa_topology = fakes.NUMA_TOPOLOGY

        self._do_test_numa_topology_filter_cpu_policy(
            numa_topology, cpu_policy, cpu_thread_policy, False)

    def test_numa_topology_filter_pass_cpu_thread_policy_require(self):
        cpu_policy = fields.CPUAllocationPolicy.DEDICATED
        cpu_thread_policy = fields.CPUThreadAllocationPolicy.REQUIRE

        for numa_topology in fakes.NUMA_TOPOLOGIES_W_HT:
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

    def _get_fake_host_state_with_networks(self):
        network_a = objects.NetworkMetadata(physnets=set(['foo', 'bar']),
                                            tunneled=False)
        network_b = objects.NetworkMetadata(physnets=set(), tunneled=True)
        host_topology = objects.NUMATopology(cells=[
            objects.NUMACell(id=1, cpuset=set([1, 2]), memory=2048,
                             cpu_usage=2, memory_usage=2048, mempages=[],
                             siblings=[set([1]), set([2])],
                             pinned_cpus=set([]),
                             network_metadata=network_a),
            objects.NUMACell(id=2, cpuset=set([3, 4]), memory=2048,
                             cpu_usage=2, memory_usage=2048, mempages=[],
                             siblings=[set([3]), set([4])],
                             pinned_cpus=set([]),
                             network_metadata=network_b)])

        return fakes.FakeHostState('host1', 'node1', {
            'numa_topology': host_topology,
            'pci_stats': None,
            'cpu_allocation_ratio': 16.0,
            'ram_allocation_ratio': 1.5})

    def test_numa_topology_filter_pass_networks(self):
        host = self._get_fake_host_state_with_networks()

        instance_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
            objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)])

        network_metadata = objects.NetworkMetadata(
            physnets=set(['foo']), tunneled=False)
        spec_obj = self._get_spec_obj(numa_topology=instance_topology,
                                      network_metadata=network_metadata)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

        # this should pass because while the networks are affined to different
        # host NUMA nodes, our guest itself has multiple NUMA nodes
        network_metadata = objects.NetworkMetadata(
            physnets=set(['foo', 'bar']), tunneled=True)
        spec_obj = self._get_spec_obj(numa_topology=instance_topology,
                                      network_metadata=network_metadata)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_numa_topology_filter_fail_networks(self):
        host = self._get_fake_host_state_with_networks()

        instance_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512)])

        # this should fail because the networks are affined to different host
        # NUMA nodes but our guest only has a single NUMA node
        network_metadata = objects.NetworkMetadata(
            physnets=set(['foo']), tunneled=True)
        spec_obj = self._get_spec_obj(numa_topology=instance_topology,
                                      network_metadata=network_metadata)

        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
