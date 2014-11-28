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

import mock
from oslo.serialization import jsonutils

from nova import objects
from nova.objects import base as obj_base
from nova.scheduler.filters import numa_topology_filter
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.scheduler import fakes
from nova.virt import hardware


class TestNUMATopologyFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestNUMATopologyFilter, self).setUp()
        self.filt_cls = numa_topology_filter.NUMATopologyFilter()

    def test_numa_topology_filter_pass(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        instance.numa_topology = instance_topology
        filter_properties = {
            'request_spec': {
                'instance_properties': jsonutils.to_primitive(
                    obj_base.obj_to_primitive(instance))}}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_numa_topology_filter_numa_instance_no_numa_host_fail(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        instance.numa_topology = instance_topology

        filter_properties = {
            'request_spec': {
                'instance_properties': jsonutils.to_primitive(
                    obj_base.obj_to_primitive(instance))}}
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_numa_topology_filter_numa_host_no_numa_instance_pass(self):
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        instance.numa_topology = None
        filter_properties = {
            'request_spec': {
                'instance_properties': jsonutils.to_primitive(
                    obj_base.obj_to_primitive(instance))}}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_numa_topology_filter_fail_fit(self):
        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([2]), memory=512),
                   objects.InstanceNUMACell(id=2, cpuset=set([3]), memory=512)
               ])
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        instance.numa_topology = instance_topology
        filter_properties = {
            'request_spec': {
                'instance_properties': jsonutils.to_primitive(
                    obj_base.obj_to_primitive(instance))}}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY})
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_numa_topology_filter_fail_memory(self):
        self.flags(ram_allocation_ratio=1)

        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]),
                                            memory=1024),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        instance.numa_topology = instance_topology
        filter_properties = {
            'request_spec': {
                'instance_properties': jsonutils.to_primitive(
                    obj_base.obj_to_primitive(instance))}}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY})
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_numa_topology_filter_fail_cpu(self):
        self.flags(cpu_allocation_ratio=1)

        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3, 4, 5]),
                                            memory=512)])
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        instance.numa_topology = instance_topology
        filter_properties = {
            'request_spec': {
                'instance_properties': jsonutils.to_primitive(
                    obj_base.obj_to_primitive(instance))}}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY})
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_numa_topology_filter_pass_set_limit(self):
        self.flags(cpu_allocation_ratio=21)
        self.flags(ram_allocation_ratio=1.3)

        instance_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=0, cpuset=set([1]), memory=512),
                   objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=512)
               ])
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx)
        instance.numa_topology = instance_topology
        filter_properties = {
            'request_spec': {
                'instance_properties': jsonutils.to_primitive(
                    obj_base.obj_to_primitive(instance))}}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'numa_topology': fakes.NUMA_TOPOLOGY})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        limits_topology = hardware.VirtNUMALimitTopology.from_json(
                host.limits['numa_topology'])
        self.assertEqual(limits_topology.cells[0].cpu_limit, 42)
        self.assertEqual(limits_topology.cells[1].cpu_limit, 42)
        self.assertEqual(limits_topology.cells[0].memory_limit, 665)
        self.assertEqual(limits_topology.cells[1].memory_limit, 665)
