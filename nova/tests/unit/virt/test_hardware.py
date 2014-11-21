# Copyright 2014 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import uuid

import mock
from oslo.serialization import jsonutils
import six

from nova import context
from nova import exception
from nova import objects
from nova.objects import base as base_obj
from nova import test
from nova.virt import hardware as hw


class InstanceInfoTests(test.NoDBTestCase):

    def test_instance_info_default(self):
        ii = hw.InstanceInfo()
        self.assertIsNone(ii.state)
        self.assertIsNone(ii.id)
        self.assertEqual(0, ii.max_mem_kb)
        self.assertEqual(0, ii.mem_kb)
        self.assertEqual(0, ii.num_cpu)
        self.assertEqual(0, ii.cpu_time_ns)

    def test_instance_info(self):
        ii = hw.InstanceInfo(state='fake-state',
                             max_mem_kb=1,
                             mem_kb=2,
                             num_cpu=3,
                             cpu_time_ns=4,
                             id='fake-id')
        self.assertEqual('fake-state', ii.state)
        self.assertEqual('fake-id', ii.id)
        self.assertEqual(1, ii.max_mem_kb)
        self.assertEqual(2, ii.mem_kb)
        self.assertEqual(3, ii.num_cpu)
        self.assertEqual(4, ii.cpu_time_ns)

    def test_instance_infoi_equals(self):
        ii1 = hw.InstanceInfo(state='fake-state',
                              max_mem_kb=1,
                              mem_kb=2,
                              num_cpu=3,
                              cpu_time_ns=4,
                              id='fake-id')
        ii2 = hw.InstanceInfo(state='fake-state',
                              max_mem_kb=1,
                              mem_kb=2,
                              num_cpu=3,
                              cpu_time_ns=4,
                              id='fake-id')
        ii3 = hw.InstanceInfo(state='fake-estat',
                              max_mem_kb=11,
                              mem_kb=22,
                              num_cpu=33,
                              cpu_time_ns=44,
                              id='fake-di')
        self.assertEqual(ii1, ii2)
        self.assertNotEqual(ii1, ii3)


class CpuSetTestCase(test.NoDBTestCase):
    def test_get_vcpu_pin_set(self):
        self.flags(vcpu_pin_set="1-3,5,^2")
        cpuset_ids = hw.get_vcpu_pin_set()
        self.assertEqual(set([1, 3, 5]), cpuset_ids)

    def test_parse_cpu_spec_none_returns_none(self):
        self.flags(vcpu_pin_set=None)
        cpuset_ids = hw.get_vcpu_pin_set()
        self.assertIsNone(cpuset_ids)

    def test_parse_cpu_spec_valid_syntax_works(self):
        cpuset_ids = hw.parse_cpu_spec("1")
        self.assertEqual(set([1]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec("1,2")
        self.assertEqual(set([1, 2]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec(", ,   1 ,  ,,  2,    ,")
        self.assertEqual(set([1, 2]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec("1-1")
        self.assertEqual(set([1]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec(" 1 - 1, 1 - 2 , 1 -3")
        self.assertEqual(set([1, 2, 3]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec("1,^2")
        self.assertEqual(set([1]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec("1-2, ^1")
        self.assertEqual(set([2]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec("1-3,5,^2")
        self.assertEqual(set([1, 3, 5]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec(" 1 -    3        ,   ^2,        5")
        self.assertEqual(set([1, 3, 5]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec(" 1,1, ^1")
        self.assertEqual(set([]), cpuset_ids)

    def test_parse_cpu_spec_invalid_syntax_raises(self):
        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          " -1-3,5,^2")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "1-3-,5,^2")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "-3,5,^2")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "1-,5,^2")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "1-3,5,^2^")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "1-3,5,^2-")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "--13,^^5,^2")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "a-3,5,^2")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "1-a,5,^2")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "1-3,b,^2")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "1-3,5,^c")

        self.assertRaises(exception.Invalid,
                          hw.parse_cpu_spec,
                          "3 - 1, 5 , ^ 2 ")

    def test_format_cpu_spec(self):
        cpus = set([])
        spec = hw.format_cpu_spec(cpus)
        self.assertEqual("", spec)

        cpus = []
        spec = hw.format_cpu_spec(cpus)
        self.assertEqual("", spec)

        cpus = set([1, 3])
        spec = hw.format_cpu_spec(cpus)
        self.assertEqual("1,3", spec)

        cpus = [1, 3]
        spec = hw.format_cpu_spec(cpus)
        self.assertEqual("1,3", spec)

        cpus = set([1, 2, 4, 6])
        spec = hw.format_cpu_spec(cpus)
        self.assertEqual("1-2,4,6", spec)

        cpus = [1, 2, 4, 6]
        spec = hw.format_cpu_spec(cpus)
        self.assertEqual("1-2,4,6", spec)

        cpus = set([10, 11, 13, 14, 15, 16, 19, 20, 40, 42, 48])
        spec = hw.format_cpu_spec(cpus)
        self.assertEqual("10-11,13-16,19-20,40,42,48", spec)

        cpus = [10, 11, 13, 14, 15, 16, 19, 20, 40, 42, 48]
        spec = hw.format_cpu_spec(cpus)
        self.assertEqual("10-11,13-16,19-20,40,42,48", spec)

        cpus = set([1, 2, 4, 6])
        spec = hw.format_cpu_spec(cpus, allow_ranges=False)
        self.assertEqual("1,2,4,6", spec)

        cpus = [1, 2, 4, 6]
        spec = hw.format_cpu_spec(cpus, allow_ranges=False)
        self.assertEqual("1,2,4,6", spec)

        cpus = set([10, 11, 13, 14, 15, 16, 19, 20, 40, 42, 48])
        spec = hw.format_cpu_spec(cpus, allow_ranges=False)
        self.assertEqual("10,11,13,14,15,16,19,20,40,42,48", spec)

        cpus = [10, 11, 13, 14, 15, 16, 19, 20, 40, 42, 48]
        spec = hw.format_cpu_spec(cpus, allow_ranges=False)
        self.assertEqual("10,11,13,14,15,16,19,20,40,42,48", spec)


class VCPUTopologyTest(test.NoDBTestCase):

    def test_validate_config(self):
        testdata = [
            {  # Flavor sets preferred topology only
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "8",
                    "hw:cpu_cores": "2",
                    "hw:cpu_threads": "1",
                }),
                "image": {
                    "properties": {}
                },
                "expect": (
                    8, 2, 1, 65536, 65536, 65536
                )
            },
            {  # Image topology overrides flavor
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "8",
                    "hw:cpu_cores": "2",
                    "hw:cpu_threads": "1",
                    "hw:cpu_max_threads": "2",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_sockets": "4",
                        "hw_cpu_cores": "2",
                        "hw_cpu_threads": "2",
                    }
                },
                "expect": (
                    4, 2, 2, 65536, 65536, 2,
                )
            },
            {  # Partial image topology overrides flavor
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "8",
                    "hw:cpu_cores": "2",
                    "hw:cpu_threads": "1",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_sockets": "2",
                    }
                },
                "expect": (
                    2, -1, -1, 65536, 65536, 65536,
                )
            },
            {  # Restrict use of threads
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_threads": "2",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_max_threads": "1",
                    }
                },
                "expect": (
                    -1, -1, -1, 65536, 65536, 1,
                )
            },
            {  # Force use of at least two sockets
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_cores": "8",
                    "hw:cpu_max_threads": "1",
                }),
                "image": {
                    "properties": {}
                },
                "expect": (
                    -1, -1, -1, 65536, 8, 1
                )
            },
            {  # Image limits reduce flavor
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_cores": "8",
                    "hw:cpu_max_threads": "1",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_max_cores": "4",
                    }
                },
                "expect": (
                    -1, -1, -1, 65536, 4, 1
                )
            },
            {  # Image limits kill flavor preferred
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "2",
                    "hw:cpu_cores": "8",
                    "hw:cpu_threads": "1",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_max_cores": "4",
                    }
                },
                "expect": (
                    -1, -1, -1, 65536, 4, 65536
                )
            },
            {  # Image limits cannot exceed flavor
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_cores": "8",
                    "hw:cpu_max_threads": "1",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_max_cores": "16",
                    }
                },
                "expect": exception.ImageVCPULimitsRangeExceeded,
            },
            {  # Image preferred cannot exceed flavor
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_cores": "8",
                    "hw:cpu_max_threads": "1",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_cores": "16",
                    }
                },
                "expect": exception.ImageVCPUTopologyRangeExceeded,
            },
        ]

        for topo_test in testdata:
            if type(topo_test["expect"]) == tuple:
                (preferred,
                 maximum) = hw._get_cpu_topology_constraints(
                     topo_test["flavor"],
                     topo_test["image"])

                self.assertEqual(topo_test["expect"][0], preferred.sockets)
                self.assertEqual(topo_test["expect"][1], preferred.cores)
                self.assertEqual(topo_test["expect"][2], preferred.threads)
                self.assertEqual(topo_test["expect"][3], maximum.sockets)
                self.assertEqual(topo_test["expect"][4], maximum.cores)
                self.assertEqual(topo_test["expect"][5], maximum.threads)
            else:
                self.assertRaises(topo_test["expect"],
                                  hw._get_cpu_topology_constraints,
                                  topo_test["flavor"],
                                  topo_test["image"])

    def test_possible_topologies(self):
        testdata = [
            {
                "allow_threads": True,
                "vcpus": 8,
                "maxsockets": 8,
                "maxcores": 8,
                "maxthreads": 2,
                "expect": [
                    [8, 1, 1],
                    [4, 2, 1],
                    [2, 4, 1],
                    [1, 8, 1],
                    [4, 1, 2],
                    [2, 2, 2],
                    [1, 4, 2],
                ]
            },
            {
                "allow_threads": False,
                "vcpus": 8,
                "maxsockets": 8,
                "maxcores": 8,
                "maxthreads": 2,
                "expect": [
                    [8, 1, 1],
                    [4, 2, 1],
                    [2, 4, 1],
                    [1, 8, 1],
                ]
            },
            {
                "allow_threads": True,
                "vcpus": 8,
                "maxsockets": 1024,
                "maxcores": 1024,
                "maxthreads": 2,
                "expect": [
                    [8, 1, 1],
                    [4, 2, 1],
                    [2, 4, 1],
                    [1, 8, 1],
                    [4, 1, 2],
                    [2, 2, 2],
                    [1, 4, 2],
                ]
            },
            {
                "allow_threads": True,
                "vcpus": 8,
                "maxsockets": 1024,
                "maxcores": 1,
                "maxthreads": 2,
                "expect": [
                    [8, 1, 1],
                    [4, 1, 2],
                ]
            },
            {
                "allow_threads": True,
                "vcpus": 7,
                "maxsockets": 8,
                "maxcores": 8,
                "maxthreads": 2,
                "expect": [
                    [7, 1, 1],
                    [1, 7, 1],
                ]
            },
            {
                "allow_threads": True,
                "vcpus": 8,
                "maxsockets": 2,
                "maxcores": 1,
                "maxthreads": 1,
                "expect": exception.ImageVCPULimitsRangeImpossible,
            },
            {
                "allow_threads": False,
                "vcpus": 8,
                "maxsockets": 2,
                "maxcores": 1,
                "maxthreads": 4,
                "expect": exception.ImageVCPULimitsRangeImpossible,
            },
        ]

        for topo_test in testdata:
            if type(topo_test["expect"]) == list:
                actual = []
                for topology in hw._get_possible_cpu_topologies(
                        topo_test["vcpus"],
                        objects.VirtCPUTopology(
                                        sockets=topo_test["maxsockets"],
                                        cores=topo_test["maxcores"],
                                        threads=topo_test["maxthreads"]),
                        topo_test["allow_threads"]):
                    actual.append([topology.sockets,
                                   topology.cores,
                                   topology.threads])

                self.assertEqual(topo_test["expect"], actual)
            else:
                self.assertRaises(topo_test["expect"],
                                  hw._get_possible_cpu_topologies,
                                  topo_test["vcpus"],
                                  objects.VirtCPUTopology(
                                      sockets=topo_test["maxsockets"],
                                      cores=topo_test["maxcores"],
                                      threads=topo_test["maxthreads"]),
                                  topo_test["allow_threads"])

    def test_sorting_topologies(self):
        testdata = [
            {
                "allow_threads": True,
                "vcpus": 8,
                "maxsockets": 8,
                "maxcores": 8,
                "maxthreads": 2,
                "sockets": 4,
                "cores": 2,
                "threads": 1,
                "expect": [
                    [4, 2, 1],  # score = 2
                    [8, 1, 1],  # score = 1
                    [2, 4, 1],  # score = 1
                    [1, 8, 1],  # score = 1
                    [4, 1, 2],  # score = 1
                    [2, 2, 2],  # score = 1
                    [1, 4, 2],  # score = 1
                ]
            },
            {
                "allow_threads": True,
                "vcpus": 8,
                "maxsockets": 1024,
                "maxcores": 1024,
                "maxthreads": 2,
                "sockets": -1,
                "cores": 4,
                "threads": -1,
                "expect": [
                    [2, 4, 1],  # score = 1
                    [1, 4, 2],  # score = 1
                    [8, 1, 1],  # score = 0
                    [4, 2, 1],  # score = 0
                    [1, 8, 1],  # score = 0
                    [4, 1, 2],  # score = 0
                    [2, 2, 2],  # score = 0
                ]
            },
            {
                "allow_threads": True,
                "vcpus": 8,
                "maxsockets": 1024,
                "maxcores": 1,
                "maxthreads": 2,
                "sockets": -1,
                "cores": -1,
                "threads": 2,
                "expect": [
                    [4, 1, 2],  # score = 1
                    [8, 1, 1],  # score = 0
                ]
            },
            {
                "allow_threads": False,
                "vcpus": 8,
                "maxsockets": 1024,
                "maxcores": 1,
                "maxthreads": 2,
                "sockets": -1,
                "cores": -1,
                "threads": 2,
                "expect": [
                    [8, 1, 1],  # score = 0
                ]
            },
        ]

        for topo_test in testdata:
            actual = []
            possible = hw._get_possible_cpu_topologies(
                topo_test["vcpus"],
                objects.VirtCPUTopology(sockets=topo_test["maxsockets"],
                                        cores=topo_test["maxcores"],
                                        threads=topo_test["maxthreads"]),
                topo_test["allow_threads"])

            tops = hw._sort_possible_cpu_topologies(
                possible,
                objects.VirtCPUTopology(sockets=topo_test["sockets"],
                                        cores=topo_test["cores"],
                                        threads=topo_test["threads"]))
            for topology in tops:
                actual.append([topology.sockets,
                               topology.cores,
                               topology.threads])

            self.assertEqual(topo_test["expect"], actual)

    def test_best_config(self):
        testdata = [
            {  # Flavor sets preferred topology only
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "8",
                    "hw:cpu_cores": "2",
                    "hw:cpu_threads": "1"
                }),
                "image": {
                    "properties": {}
                },
                "expect": [8, 2, 1],
            },
            {  # Image topology overrides flavor
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "8",
                    "hw:cpu_cores": "2",
                    "hw:cpu_threads": "1",
                    "hw:cpu_maxthreads": "2",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_sockets": "4",
                        "hw_cpu_cores": "2",
                        "hw_cpu_threads": "2",
                    }
                },
                "expect": [4, 2, 2],
            },
            {  # Image topology overrides flavor
                "allow_threads": False,
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "8",
                    "hw:cpu_cores": "2",
                    "hw:cpu_threads": "1",
                    "hw:cpu_maxthreads": "2",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_sockets": "4",
                        "hw_cpu_cores": "2",
                        "hw_cpu_threads": "2",
                    }
                },
                "expect": [8, 2, 1],
            },
            {  # Partial image topology overrides flavor
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "8",
                    "hw:cpu_cores": "2",
                    "hw:cpu_threads": "1"
                }),
                "image": {
                    "properties": {
                        "hw_cpu_sockets": "2"
                    }
                },
                "expect": [2, 8, 1],
            },
            {  # Restrict use of threads
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_threads": "1"
                }),
                "image": {
                    "properties": {}
                },
                "expect": [16, 1, 1]
            },
            {  # Force use of at least two sockets
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_cores": "8",
                    "hw:cpu_max_threads": "1",
                }),
                "image": {
                    "properties": {}
                },
                "expect": [16, 1, 1]
            },
            {  # Image limits reduce flavor
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_sockets": "8",
                    "hw:cpu_max_cores": "8",
                    "hw:cpu_max_threads": "1",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_max_sockets": 4,
                    }
                },
                "expect": [4, 4, 1]
            },
            {  # Image limits kill flavor preferred
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_sockets": "2",
                    "hw:cpu_cores": "8",
                    "hw:cpu_threads": "1",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_max_cores": 4,
                    }
                },
                "expect": [16, 1, 1]
            },
        ]

        for topo_test in testdata:
            topology = hw._get_desirable_cpu_topologies(
                topo_test["flavor"],
                topo_test["image"],
                topo_test["allow_threads"])[0]

            self.assertEqual(topo_test["expect"][0], topology.sockets)
            self.assertEqual(topo_test["expect"][1], topology.cores)
            self.assertEqual(topo_test["expect"][2], topology.threads)


class NUMATopologyTest(test.NoDBTestCase):

    def test_topology_constraints(self):
        testdata = [
            {
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                }),
                "image": {
                },
                "expect": None,
            },
            {
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={
                    "hw:numa_nodes": 2
                }),
                "image": {
                },
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=1024),
                        objects.InstanceNUMACell(
                            id=1, cpuset=set([4, 5, 6, 7]), memory=1024),
                    ]),
            },
            {
                # vcpus is not a multiple of nodes, so it
                # is an error to not provide cpu/mem mapping
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={
                    "hw:numa_nodes": 3
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyAsymmetric,
            },
            {
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={
                    "hw:numa_nodes": 3,
                    "hw:numa_cpus.0": "0-3",
                    "hw:numa_mem.0": "1024",
                    "hw:numa_cpus.1": "4,6",
                    "hw:numa_mem.1": "512",
                    "hw:numa_cpus.2": "5,7",
                    "hw:numa_mem.2": "512",
                }),
                "image": {
                },
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=1024),
                        objects.InstanceNUMACell(
                            id=1, cpuset=set([4, 6]), memory=512),
                        objects.InstanceNUMACell(
                            id=2, cpuset=set([5, 7]), memory=512),
                    ]),
            },
            {
                # Request a CPU that is out of range
                # wrt vCPU count
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                    "hw:numa_nodes": 1,
                    "hw:numa_cpus.0": "0-16",
                    "hw:numa_mem.0": "2048",
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyCPUOutOfRange,
            },
            {
                # Request the same CPU in two nodes
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                    "hw:numa_nodes": 2,
                    "hw:numa_cpus.0": "0-7",
                    "hw:numa_mem.0": "1024",
                    "hw:numa_cpus.1": "0-7",
                    "hw:numa_mem.1": "1024",
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyCPUDuplicates,
            },
            {
                # Request with some CPUs not assigned
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                    "hw:numa_nodes": 2,
                    "hw:numa_cpus.0": "0-2",
                    "hw:numa_mem.0": "1024",
                    "hw:numa_cpus.1": "3-4",
                    "hw:numa_mem.1": "1024",
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyCPUsUnassigned,
            },
            {
                # Request too little memory vs flavor total
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                    "hw:numa_nodes": 2,
                    "hw:numa_cpus.0": "0-3",
                    "hw:numa_mem.0": "512",
                    "hw:numa_cpus.1": "4-7",
                    "hw:numa_mem.1": "512",
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyMemoryOutOfRange,
            },
            {
                # Request too much memory vs flavor total
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                    "hw:numa_nodes": 2,
                    "hw:numa_cpus.0": "0-3",
                    "hw:numa_mem.0": "1576",
                    "hw:numa_cpus.1": "4-7",
                    "hw:numa_mem.1": "1576",
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyMemoryOutOfRange,
            },
            {
                # Request missing mem.0
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                    "hw:numa_nodes": 2,
                    "hw:numa_cpus.0": "0-3",
                    "hw:numa_mem.1": "1576",
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyIncomplete,
            },
            {
                # Request missing cpu.0
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                    "hw:numa_nodes": 2,
                    "hw:numa_mem.0": "1576",
                    "hw:numa_cpus.1": "4-7",
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyIncomplete,
            },
            {
                # Image attempts to override flavor
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={
                    "hw:numa_nodes": 2,
                }),
                "image": {
                    "hw_numa_nodes": 4,
                },
                "expect": exception.ImageNUMATopologyForbidden,
            },
        ]

        for testitem in testdata:
            if testitem["expect"] is None:
                topology = hw.numa_get_constraints(
                    testitem["flavor"], testitem["image"])
                self.assertIsNone(topology)
            elif type(testitem["expect"]) == type:
                self.assertRaises(testitem["expect"],
                                  hw.numa_get_constraints,
                                  testitem["flavor"],
                                  testitem["image"])
            else:
                topology = hw.numa_get_constraints(
                    testitem["flavor"], testitem["image"])
                self.assertEqual(len(testitem["expect"].cells),
                                 len(topology.cells))
                for i in range(len(topology.cells)):
                    self.assertEqual(testitem["expect"].cells[i].cpuset,
                                     topology.cells[i].cpuset)
                    self.assertEqual(testitem["expect"].cells[i].memory,
                                     topology.cells[i].memory)

    def test_host_usage_contiguous(self):
        hosttopo = hw.VirtNUMAHostTopology([
            hw.VirtNUMATopologyCellUsage(0, set([0, 1, 2, 3]), 1024),
            hw.VirtNUMATopologyCellUsage(1, set([4, 6]), 512),
            hw.VirtNUMATopologyCellUsage(2, set([5, 7]), 512),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1, 2]), memory=256),
            objects.InstanceNUMACell(id=1, cpuset=set([4]), memory=256),
        ])
        instance2 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=256),
            objects.InstanceNUMACell(id=1, cpuset=set([5, 7]), memory=256),
        ])

        hostusage = hw.VirtNUMAHostTopology.usage_from_instances(
            hosttopo, [instance1, instance2])

        self.assertEqual(len(hosttopo), len(hostusage))

        self.assertIsInstance(hostusage.cells[0],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hosttopo.cells[0].cpuset,
                         hostusage.cells[0].cpuset)
        self.assertEqual(hosttopo.cells[0].memory,
                         hostusage.cells[0].memory)
        self.assertEqual(hostusage.cells[0].cpu_usage, 5)
        self.assertEqual(hostusage.cells[0].memory_usage, 512)

        self.assertIsInstance(hostusage.cells[1],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hosttopo.cells[1].cpuset,
                         hostusage.cells[1].cpuset)
        self.assertEqual(hosttopo.cells[1].memory,
                         hostusage.cells[1].memory)
        self.assertEqual(hostusage.cells[1].cpu_usage, 3)
        self.assertEqual(hostusage.cells[1].memory_usage, 512)

        self.assertIsInstance(hostusage.cells[2],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hosttopo.cells[2].cpuset,
                         hostusage.cells[2].cpuset)
        self.assertEqual(hosttopo.cells[2].memory,
                         hostusage.cells[2].memory)
        self.assertEqual(hostusage.cells[2].cpu_usage, 0)
        self.assertEqual(hostusage.cells[2].memory_usage, 0)

    def test_host_usage_sparse(self):
        hosttopo = hw.VirtNUMAHostTopology([
            hw.VirtNUMATopologyCellUsage(0, set([0, 1, 2, 3]), 1024),
            hw.VirtNUMATopologyCellUsage(5, set([4, 6]), 512),
            hw.VirtNUMATopologyCellUsage(6, set([5, 7]), 512),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1, 2]), memory=256),
            objects.InstanceNUMACell(id=6, cpuset=set([4]), memory=256),
        ])
        instance2 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=256),
            objects.InstanceNUMACell(id=5, cpuset=set([5, 7]), memory=256),
        ])

        hostusage = hw.VirtNUMAHostTopology.usage_from_instances(
            hosttopo, [instance1, instance2])

        self.assertEqual(len(hosttopo), len(hostusage))

        self.assertIsInstance(hostusage.cells[0],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hosttopo.cells[0].id,
                         hostusage.cells[0].id)
        self.assertEqual(hosttopo.cells[0].cpuset,
                         hostusage.cells[0].cpuset)
        self.assertEqual(hosttopo.cells[0].memory,
                         hostusage.cells[0].memory)
        self.assertEqual(hostusage.cells[0].cpu_usage, 5)
        self.assertEqual(hostusage.cells[0].memory_usage, 512)

        self.assertIsInstance(hostusage.cells[1],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hosttopo.cells[1].id,
                         hostusage.cells[1].id)
        self.assertEqual(hosttopo.cells[1].cpuset,
                         hostusage.cells[1].cpuset)
        self.assertEqual(hosttopo.cells[1].memory,
                         hostusage.cells[1].memory)
        self.assertEqual(hostusage.cells[1].cpu_usage, 2)
        self.assertEqual(hostusage.cells[1].memory_usage, 256)

        self.assertIsInstance(hostusage.cells[2],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hosttopo.cells[2].cpuset,
                         hostusage.cells[2].cpuset)
        self.assertEqual(hosttopo.cells[2].memory,
                         hostusage.cells[2].memory)
        self.assertEqual(hostusage.cells[2].cpu_usage, 1)
        self.assertEqual(hostusage.cells[2].memory_usage, 256)

    def test_host_usage_culmulative_with_free(self):
        hosttopo = hw.VirtNUMAHostTopology([
            hw.VirtNUMATopologyCellUsage(
                0, set([0, 1, 2, 3]), 1024, cpu_usage=2, memory_usage=512),
            hw.VirtNUMATopologyCellUsage(
                1, set([4, 6]), 512, cpu_usage=1, memory_usage=512),
            hw.VirtNUMATopologyCellUsage(2, set([5, 7]), 256),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1, 2]), memory=512),
            objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=256),
            objects.InstanceNUMACell(id=2, cpuset=set([4]), memory=256)])

        hostusage = hw.VirtNUMAHostTopology.usage_from_instances(
                hosttopo, [instance1])
        self.assertIsInstance(hostusage.cells[0],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hostusage.cells[0].cpu_usage, 5)
        self.assertEqual(hostusage.cells[0].memory_usage, 1024)

        self.assertIsInstance(hostusage.cells[1],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hostusage.cells[1].cpu_usage, 2)
        self.assertEqual(hostusage.cells[1].memory_usage, 768)

        self.assertIsInstance(hostusage.cells[2],
                              hw.VirtNUMATopologyCellUsage)
        self.assertEqual(hostusage.cells[2].cpu_usage, 1)
        self.assertEqual(hostusage.cells[2].memory_usage, 256)

        # Test freeing of resources
        hostusage = hw.VirtNUMAHostTopology.usage_from_instances(
                hostusage, [instance1], free=True)
        self.assertEqual(hostusage.cells[0].cpu_usage, 2)
        self.assertEqual(hostusage.cells[0].memory_usage, 512)

        self.assertEqual(hostusage.cells[1].cpu_usage, 1)
        self.assertEqual(hostusage.cells[1].memory_usage, 512)

        self.assertEqual(hostusage.cells[2].cpu_usage, 0)
        self.assertEqual(hostusage.cells[2].memory_usage, 0)

    def test_topo_usage_none(self):
        hosttopo = hw.VirtNUMAHostTopology([
            hw.VirtNUMATopologyCellUsage(0, set([0, 1]), 512),
            hw.VirtNUMATopologyCellUsage(1, set([2, 3]), 512),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=256),
            objects.InstanceNUMACell(id=2, cpuset=set([2]), memory=256),
        ])

        hostusage = hw.VirtNUMAHostTopology.usage_from_instances(
                None, [instance1])
        self.assertIsNone(hostusage)

        hostusage = hw.VirtNUMAHostTopology.usage_from_instances(
                hosttopo, [])
        self.assertEqual(hostusage.cells[0].cpu_usage, 0)
        self.assertEqual(hostusage.cells[0].memory_usage, 0)
        self.assertEqual(hostusage.cells[1].cpu_usage, 0)
        self.assertEqual(hostusage.cells[1].memory_usage, 0)

        hostusage = hw.VirtNUMAHostTopology.usage_from_instances(
                hosttopo, None)
        self.assertEqual(hostusage.cells[0].cpu_usage, 0)
        self.assertEqual(hostusage.cells[0].memory_usage, 0)
        self.assertEqual(hostusage.cells[1].cpu_usage, 0)
        self.assertEqual(hostusage.cells[1].memory_usage, 0)

    def assertNUMACellMatches(self, expected_cell, got_cell):
        attrs = ('cpuset', 'memory', 'id')
        if isinstance(expected_cell, hw.VirtNUMAHostTopology):
            attrs += ('cpu_usage', 'memory_usage')

        for attr in attrs:
            self.assertEqual(getattr(expected_cell, attr),
                             getattr(got_cell, attr))

    def test_json(self):
        expected = hw.VirtNUMAHostTopology(
                cells=[
                    hw.VirtNUMATopologyCellUsage(
                        1, set([1, 2]), 1024),
                    hw.VirtNUMATopologyCellUsage(
                        2, set([3, 4]), 1024)])
        got = hw.VirtNUMAHostTopology.from_json(expected.to_json())

        for exp_cell, got_cell in zip(expected.cells, got.cells):
            self.assertNUMACellMatches(exp_cell, got_cell)


class VirtNUMATopologyCellUsageTestCase(test.NoDBTestCase):
    def test_fit_instance_cell_success_no_limit(self):
        host_cell = hw.VirtNUMATopologyCellUsage(4, set([1, 2]), 1024)
        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2]), memory=1024)
        fitted_cell = host_cell.fit_instance_cell(host_cell, instance_cell)
        self.assertIsInstance(fitted_cell, objects.InstanceNUMACell)
        self.assertEqual(host_cell.id, fitted_cell.id)

    def test_fit_instance_cell_success_w_limit(self):
        host_cell = hw.VirtNUMATopologyCellUsage(4, set([1, 2]), 1024,
                                                 cpu_usage=2,
                                                 memory_usage=1024)
        limit_cell = hw.VirtNUMATopologyCellLimit(
                        4, set([1, 2]), 1024,
                        cpu_limit=4, memory_limit=2048)
        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2]), memory=1024)
        fitted_cell = host_cell.fit_instance_cell(
                host_cell, instance_cell, limit_cell=limit_cell)
        self.assertIsInstance(fitted_cell, objects.InstanceNUMACell)
        self.assertEqual(host_cell.id, fitted_cell.id)

    def test_fit_instance_cell_self_overcommit(self):
        host_cell = hw.VirtNUMATopologyCellUsage(4, set([1, 2]), 1024)
        limit_cell = hw.VirtNUMATopologyCellLimit(
                        4, set([1, 2]), 1024,
                        cpu_limit=4, memory_limit=2048)
        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2, 3]), memory=4096)
        fitted_cell = host_cell.fit_instance_cell(
                host_cell, instance_cell, limit_cell=limit_cell)
        self.assertIsNone(fitted_cell)

    def test_fit_instance_cell_fail_w_limit(self):
        host_cell = hw.VirtNUMATopologyCellUsage(4, set([1, 2]), 1024,
                                                 cpu_usage=2,
                                                 memory_usage=1024)
        limit_cell = hw.VirtNUMATopologyCellLimit(
                        4, set([1, 2]), 1024,
                        cpu_limit=4, memory_limit=2048)
        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2]), memory=4096)
        fitted_cell = host_cell.fit_instance_cell(
                host_cell, instance_cell, limit_cell=limit_cell)
        self.assertIsNone(fitted_cell)

        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2, 3, 4, 5]), memory=1024)
        fitted_cell = host_cell.fit_instance_cell(
                host_cell, instance_cell, limit_cell=limit_cell)
        self.assertIsNone(fitted_cell)


class VirtNUMAHostTopologyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VirtNUMAHostTopologyTestCase, self).setUp()

        self.host = hw.VirtNUMAHostTopology(
                cells=[
                    hw.VirtNUMATopologyCellUsage(
                        1, set([1, 2]), 2048,
                        cpu_usage=2, memory_usage=2048),
                    hw.VirtNUMATopologyCellUsage(
                        2, set([3, 4]), 2048,
                        cpu_usage=2, memory_usage=2048)])

        self.limits = hw.VirtNUMALimitTopology(
                cells=[
                    hw.VirtNUMATopologyCellLimit(
                        1, set([1, 2]), 2048,
                        cpu_limit=4, memory_limit=4096),
                    hw.VirtNUMATopologyCellLimit(
                        2, set([3, 4]), 2048,
                        cpu_limit=4, memory_limit=3072)])

        self.instance1 = objects.InstanceNUMATopology(
                cells=[
                    objects.InstanceNUMACell(
                        id=0, cpuset=set([1, 2]), memory=2048)])
        self.instance2 = objects.InstanceNUMATopology(
                cells=[
                    objects.InstanceNUMACell(
                        id=0, cpuset=set([1, 2, 3, 4]), memory=1024)])
        self.instance3 = objects.InstanceNUMATopology(
                cells=[
                    objects.InstanceNUMACell(
                        id=0, cpuset=set([1, 2]), memory=1024)])

    def test_get_fitting_success_no_limits(self):
        fitted_instance1 = hw.VirtNUMAHostTopology.fit_instance_to_host(
                self.host, self.instance1)
        self.assertIsInstance(fitted_instance1, objects.InstanceNUMATopology)
        self.host = hw.VirtNUMAHostTopology.usage_from_instances(self.host,
                [fitted_instance1])
        fitted_instance2 = hw.VirtNUMAHostTopology.fit_instance_to_host(
                self.host, self.instance3)
        self.assertIsInstance(fitted_instance2, objects.InstanceNUMATopology)

    def test_get_fitting_success_limits(self):
        fitted_instance = hw.VirtNUMAHostTopology.fit_instance_to_host(
                self.host, self.instance3, self.limits)
        self.assertIsInstance(fitted_instance, objects.InstanceNUMATopology)
        self.assertEqual(1, fitted_instance.cells[0].id)

    def test_get_fitting_fails_no_limits(self):
        fitted_instance = hw.VirtNUMAHostTopology.fit_instance_to_host(
                self.host, self.instance2, self.limits)
        self.assertIsNone(fitted_instance)

    def test_get_fitting_culmulative_fails_limits(self):
        fitted_instance1 = hw.VirtNUMAHostTopology.fit_instance_to_host(
                self.host, self.instance1, self.limits)
        self.assertIsInstance(fitted_instance1, objects.InstanceNUMATopology)
        self.assertEqual(1, fitted_instance1.cells[0].id)
        self.host = hw.VirtNUMAHostTopology.usage_from_instances(self.host,
                [fitted_instance1])
        fitted_instance2 = hw.VirtNUMAHostTopology.fit_instance_to_host(
                self.host, self.instance1, self.limits)
        self.assertIsNone(fitted_instance2)

    def test_get_fitting_culmulative_success_limits(self):
        fitted_instance1 = hw.VirtNUMAHostTopology.fit_instance_to_host(
                self.host, self.instance1, self.limits)
        self.assertIsInstance(fitted_instance1, objects.InstanceNUMATopology)
        self.assertEqual(1, fitted_instance1.cells[0].id)
        self.host = hw.VirtNUMAHostTopology.usage_from_instances(self.host,
                [fitted_instance1])
        fitted_instance2 = hw.VirtNUMAHostTopology.fit_instance_to_host(
                self.host, self.instance3, self.limits)
        self.assertIsInstance(fitted_instance2, objects.InstanceNUMATopology)
        self.assertEqual(2, fitted_instance2.cells[0].id)


class NumberOfSerialPortsTest(test.NoDBTestCase):
    def test_flavor(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048,
                                extra_specs={"hw:serial_port_count": 3})
        num_ports = hw.get_number_of_serial_ports(flavor, None)
        self.assertEqual(3, num_ports)

    def test_image_meta(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={})
        image_meta = {"properties": {"hw_serial_port_count": 2}}
        num_ports = hw.get_number_of_serial_ports(flavor, image_meta)
        self.assertEqual(2, num_ports)

    def test_flavor_invalid_value(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048,
                                extra_specs={"hw:serial_port_count": 'foo'})
        image_meta = {"properties": {}}
        self.assertRaises(exception.ImageSerialPortNumberInvalid,
                          hw.get_number_of_serial_ports,
                          flavor, image_meta)

    def test_image_meta_invalid_value(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={})
        image_meta = {"properties": {"hw_serial_port_count": 'bar'}}
        self.assertRaises(exception.ImageSerialPortNumberInvalid,
                          hw.get_number_of_serial_ports,
                          flavor, image_meta)

    def test_image_meta_smaller_than_flavor(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048,
                                extra_specs={"hw:serial_port_count": 3})
        image_meta = {"properties": {"hw_serial_port_count": 2}}
        num_ports = hw.get_number_of_serial_ports(flavor, image_meta)
        self.assertEqual(2, num_ports)

    def test_flavor_smaller_than_image_meta(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048,
                                extra_specs={"hw:serial_port_count": 3})
        image_meta = {"properties": {"hw_serial_port_count": 4}}
        self.assertRaises(exception.ImageSerialPortNumberExceedFlavorValue,
                          hw.get_number_of_serial_ports,
                          flavor, image_meta)


class HelperMethodsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(HelperMethodsTestCase, self).setUp()
        self.hosttopo = hw.VirtNUMAHostTopology([
            hw.VirtNUMATopologyCellUsage(0, set([0, 1]), 512),
            hw.VirtNUMATopologyCellUsage(1, set([2, 3]), 512),
        ])
        self.instancetopo = objects.InstanceNUMATopology(
            instance_uuid='fake-uuid',
            cells=[
                objects.InstanceNUMACell(
                    id=0, cpuset=set([0, 1]), memory=256, pagesize=2048),
                objects.InstanceNUMACell(
                    id=1, cpuset=set([2]), memory=256, pagesize=2048),
        ])
        self.context = context.RequestContext('fake-user',
                                              'fake-project')

    def _check_usage(self, host_usage):
        self.assertEqual(2, host_usage.cells[0].cpu_usage)
        self.assertEqual(256, host_usage.cells[0].memory_usage)
        self.assertEqual(1, host_usage.cells[1].cpu_usage)
        self.assertEqual(256, host_usage.cells[1].memory_usage)

    def test_dicts_json(self):
        host = {'numa_topology': self.hosttopo.to_json()}
        instance = {'numa_topology': self.instancetopo._to_json()}

        res = hw.get_host_numa_usage_from_instance(host, instance)
        self.assertIsInstance(res, six.string_types)
        self._check_usage(hw.VirtNUMAHostTopology.from_json(res))

    def test_dicts_instance_json(self):
        host = {'numa_topology': self.hosttopo}
        instance = {'numa_topology': self.instancetopo._to_json()}

        res = hw.get_host_numa_usage_from_instance(host, instance)
        self.assertIsInstance(res, hw.VirtNUMAHostTopology)
        self._check_usage(res)

    def test_dicts_instance_json_old(self):
        host = {'numa_topology': self.hosttopo}
        instance = {'numa_topology':
                    jsonutils.dumps(self.instancetopo._to_dict())}

        res = hw.get_host_numa_usage_from_instance(host, instance)
        self.assertIsInstance(res, hw.VirtNUMAHostTopology)
        self._check_usage(res)

    def test_dicts_host_json(self):
        host = {'numa_topology': self.hosttopo.to_json()}
        instance = {'numa_topology': self.instancetopo}

        res = hw.get_host_numa_usage_from_instance(host, instance)
        self.assertIsInstance(res, six.string_types)
        self._check_usage(hw.VirtNUMAHostTopology.from_json(res))

    def test_object_host_instance_json(self):
        host = objects.ComputeNode(numa_topology=self.hosttopo.to_json())
        instance = {'numa_topology': self.instancetopo._to_json()}

        res = hw.get_host_numa_usage_from_instance(host, instance)
        self.assertIsInstance(res, six.string_types)
        self._check_usage(hw.VirtNUMAHostTopology.from_json(res))

    def test_object_host_instance(self):
        host = objects.ComputeNode(numa_topology=self.hosttopo.to_json())
        instance = {'numa_topology': self.instancetopo}

        res = hw.get_host_numa_usage_from_instance(host, instance)
        self.assertIsInstance(res, six.string_types)
        self._check_usage(hw.VirtNUMAHostTopology.from_json(res))

    def test_instance_with_fetch(self):
        host = objects.ComputeNode(numa_topology=self.hosttopo.to_json())
        fake_uuid = str(uuid.uuid4())
        instance = {'uuid': fake_uuid}

        with mock.patch.object(objects.InstanceNUMATopology,
                'get_by_instance_uuid', return_value=None) as get_mock:
            res = hw.get_host_numa_usage_from_instance(host, instance)
            self.assertIsInstance(res, six.string_types)
            self.assertTrue(get_mock.called)

    def test_object_instance_with_load(self):
        host = objects.ComputeNode(numa_topology=self.hosttopo.to_json())
        fake_uuid = str(uuid.uuid4())
        instance = objects.Instance(context=self.context, uuid=fake_uuid)

        with mock.patch.object(objects.InstanceNUMATopology,
                'get_by_instance_uuid', return_value=None) as get_mock:
            res = hw.get_host_numa_usage_from_instance(host, instance)
            self.assertIsInstance(res, six.string_types)
            self.assertTrue(get_mock.called)

    def test_instance_serialized_by_build_request_spec(self):
        host = objects.ComputeNode(numa_topology=self.hosttopo.to_json())
        fake_uuid = str(uuid.uuid4())
        instance = objects.Instance(context=self.context, id=1, uuid=fake_uuid,
                numa_topology=self.instancetopo)
        # NOTE (ndipanov): This emulates scheduler.utils.build_request_spec
        # We can remove this test once we no longer use that method.
        instance_raw = jsonutils.to_primitive(
                base_obj.obj_to_primitive(instance))
        res = hw.get_host_numa_usage_from_instance(host, instance_raw)
        self.assertIsInstance(res, six.string_types)
        self._check_usage(hw.VirtNUMAHostTopology.from_json(res))

    def test_attr_host(self):
        class Host(object):
            def __init__(obj):
                obj.numa_topology = self.hosttopo.to_json()

        host = Host()
        instance = {'numa_topology': self.instancetopo._to_json()}

        res = hw.get_host_numa_usage_from_instance(host, instance)
        self.assertIsInstance(res, six.string_types)
        self._check_usage(hw.VirtNUMAHostTopology.from_json(res))

    def test_never_serialize_result(self):
        host = {'numa_topology': self.hosttopo.to_json()}
        instance = {'numa_topology': self.instancetopo}

        res = hw.get_host_numa_usage_from_instance(host, instance,
                                                  never_serialize_result=True)
        self.assertIsInstance(res, hw.VirtNUMAHostTopology)
        self._check_usage(res)


class VirtMemoryPagesTestCase(test.NoDBTestCase):
    def test_virt_pages_topology(self):
        pages = hw.VirtPagesTopology(4, 1024, 512)
        self.assertEqual(4, pages.size_kb)
        self.assertEqual(1024, pages.total)
        self.assertEqual(512, pages.used)

    def test_cell_instance_pagesize(self):
        cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024, pagesize=2048)

        self.assertEqual(0, cell.id)
        self.assertEqual(set([0]), cell.cpuset)
        self.assertEqual(1024, cell.memory)
        self.assertEqual(2048, cell.pagesize)
