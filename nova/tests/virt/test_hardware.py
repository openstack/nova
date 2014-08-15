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

from nova import exception
from nova import test
from nova.tests import matchers
from nova.virt import hardware as hw


class FakeFlavor():
    def __init__(self, vcpus, memory, extra_specs):
        self.vcpus = vcpus
        self.memory_mb = memory
        self.extra_specs = extra_specs

    def __getitem__(self, item):
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item)

    def get(self, item, default=None):
        try:
            return getattr(self, item)
        except AttributeError:
            return default


class CpuSetTestCase(test.NoDBTestCase):
    def test_get_vcpu_pin_set(self):
        self.flags(vcpu_pin_set="1-3,5,^2")
        cpuset_ids = hw.get_vcpu_pin_set()
        self.assertEqual([1, 3, 5], cpuset_ids)

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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                 maximum) = hw.VirtCPUTopology.get_topology_constraints(
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
                                  hw.VirtCPUTopology.get_topology_constraints,
                                  topo_test["flavor"],
                                  topo_test["image"])

    def test_possible_configs(self):
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
                for topology in hw.VirtCPUTopology.get_possible_topologies(
                        topo_test["vcpus"],
                        hw.VirtCPUTopology(topo_test["maxsockets"],
                                           topo_test["maxcores"],
                                           topo_test["maxthreads"]),
                        topo_test["allow_threads"]):
                    actual.append([topology.sockets,
                                   topology.cores,
                                   topology.threads])

                self.assertEqual(topo_test["expect"], actual)
            else:
                self.assertRaises(topo_test["expect"],
                                  hw.VirtCPUTopology.get_possible_topologies,
                                  topo_test["vcpus"],
                                  hw.VirtCPUTopology(topo_test["maxsockets"],
                                                     topo_test["maxcores"],
                                                     topo_test["maxthreads"]),
                                  topo_test["allow_threads"])

    def test_sorting_configs(self):
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
            possible = hw.VirtCPUTopology.get_possible_topologies(
                topo_test["vcpus"],
                hw.VirtCPUTopology(topo_test["maxsockets"],
                                   topo_test["maxcores"],
                                   topo_test["maxthreads"]),
                topo_test["allow_threads"])

            tops = hw.VirtCPUTopology.sort_possible_topologies(
                possible,
                hw.VirtCPUTopology(topo_test["sockets"],
                                   topo_test["cores"],
                                   topo_test["threads"]))
            for topology in tops:
                actual.append([topology.sockets,
                               topology.cores,
                               topology.threads])

            self.assertEqual(topo_test["expect"], actual)

    def test_best_config(self):
        testdata = [
            {  # Flavor sets preferred topology only
                "allow_threads": True,
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
                    "hw:cpu_max_threads": "1"
                }),
                "image": {
                    "properties": {}
                },
                "expect": [16, 1, 1]
            },
            {  # Force use of at least two sockets
                "allow_threads": True,
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
                "flavor": FakeFlavor(16, 2048, {
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
            topology = hw.VirtCPUTopology.get_desirable_configs(
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
                "flavor": FakeFlavor(8, 2048, {
                }),
                "image": {
                },
                "expect": None,
            },
            {
                "flavor": FakeFlavor(8, 2048, {
                    "hw:numa_nodes": 2
                }),
                "image": {
                },
                "expect": hw.VirtNUMAInstanceTopology(
                    [
                        hw.VirtNUMATopologyCell(0, set([0, 1, 2, 3]), 1024),
                        hw.VirtNUMATopologyCell(1, set([4, 5, 6, 7]), 1024),
                    ]),
            },
            {
                # vcpus is not a multiple of nodes, so it
                # is an error to not provide cpu/mem mapping
                "flavor": FakeFlavor(8, 2048, {
                    "hw:numa_nodes": 3
                }),
                "image": {
                },
                "expect": exception.ImageNUMATopologyAsymmetric,
            },
            {
                "flavor": FakeFlavor(8, 2048, {
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
                "expect": hw.VirtNUMAInstanceTopology(
                    [
                        hw.VirtNUMATopologyCell(0, set([0, 1, 2, 3]), 1024),
                        hw.VirtNUMATopologyCell(1, set([4, 6]), 512),
                        hw.VirtNUMATopologyCell(2, set([5, 7]), 512),
                    ]),
            },
            {
                # Request a CPU that is out of range
                # wrt vCPU count
                "flavor": FakeFlavor(8, 2048, {
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
                "flavor": FakeFlavor(8, 2048, {
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
                "flavor": FakeFlavor(8, 2048, {
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
                "flavor": FakeFlavor(8, 2048, {
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
                "flavor": FakeFlavor(8, 2048, {
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
                "flavor": FakeFlavor(8, 2048, {
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
                "flavor": FakeFlavor(8, 2048, {
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
                "flavor": FakeFlavor(8, 2048, {
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
                topology = hw.VirtNUMAInstanceTopology.get_constraints(
                    testitem["flavor"], testitem["image"])
                self.assertIsNone(topology)
            elif type(testitem["expect"]) == type:
                self.assertRaises(testitem["expect"],
                                  hw.VirtNUMAInstanceTopology.get_constraints,
                                  testitem["flavor"],
                                  testitem["image"])
            else:
                topology = hw.VirtNUMAInstanceTopology.get_constraints(
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
        instance1 = hw.VirtNUMAInstanceTopology([
            hw.VirtNUMATopologyCell(0, set([0, 1, 2]), 256),
            hw.VirtNUMATopologyCell(1, set([4]), 256),
        ])
        instance2 = hw.VirtNUMAInstanceTopology([
            hw.VirtNUMATopologyCell(0, set([0, 1]), 256),
            hw.VirtNUMATopologyCell(1, set([5, 7]), 256),
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
        instance1 = hw.VirtNUMAInstanceTopology([
            hw.VirtNUMATopologyCell(0, set([0, 1, 2]), 256),
            hw.VirtNUMATopologyCell(6, set([4]), 256),
        ])
        instance2 = hw.VirtNUMAInstanceTopology([
            hw.VirtNUMATopologyCell(0, set([0, 1]), 256),
            hw.VirtNUMATopologyCell(5, set([5, 7]), 256),
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

    def _test_to_dict(self, cell_or_topo, expected):
        got = cell_or_topo._to_dict()
        self.assertThat(expected, matchers.DictMatches(got))

    def assertNUMACellMatches(self, expected_cell, got_cell):
        attrs = ('cpuset', 'memory', 'id')
        if isinstance(expected_cell, hw.VirtNUMAHostTopology):
            attrs += ('cpu_usage', 'memory_usage')

        for attr in attrs:
            self.assertEqual(getattr(expected_cell, attr),
                             getattr(got_cell, attr))

    def _test_cell_from_dict(self, data_dict, expected_cell):
        cell_class = expected_cell.__class__
        got_cell = cell_class._from_dict(data_dict)
        self.assertNUMACellMatches(expected_cell, got_cell)

    def _test_topo_from_dict(self, data_dict, expected_topo, with_usage=False):
        topology_class = (
                hw.VirtNUMAHostTopology
                if with_usage else hw.VirtNUMAInstanceTopology)
        got_topo = topology_class._from_dict(
                data_dict)
        for got_cell, expected_cell in zip(
                got_topo.cells, expected_topo.cells):
            self.assertNUMACellMatches(expected_cell, got_cell)

    def test_numa_cell_dict(self):
        cell = hw.VirtNUMATopologyCell(1, set([1, 2]), 512)
        cell_dict = {'cpus': '1,2',
                     'mem': {'total': 512},
                     'id': 1}
        self._test_to_dict(cell, cell_dict)
        self._test_cell_from_dict(cell_dict, cell)

    def test_numa_cell_usage_dict(self):
        cell = hw.VirtNUMATopologyCellUsage(1, set([1, 2]), 512)
        cell_dict = {'cpus': '1,2', 'cpu_usage': 0,
                     'mem': {'total': 512, 'used': 0},
                     'id': 1}
        self._test_to_dict(cell, cell_dict)
        self._test_cell_from_dict(cell_dict, cell)

    def test_numa_instance_topo_dict(self):
        topo = hw.VirtNUMAInstanceTopology(
                cells=[
                    hw.VirtNUMATopologyCell(1, set([1, 2]), 1024),
                    hw.VirtNUMATopologyCell(2, set([3, 4]), 1024)])
        topo_dict = {'cells': [
                        {'cpus': '1,2',
                          'mem': {'total': 1024},
                          'id': 1},
                        {'cpus': '3,4',
                          'mem': {'total': 1024},
                          'id': 2}]}
        self._test_to_dict(topo, topo_dict)
        self._test_topo_from_dict(topo_dict, topo, with_usage=False)

    def test_numa_topo_dict_with_usage(self):
        topo = hw.VirtNUMAHostTopology(
                cells=[
                    hw.VirtNUMATopologyCellUsage(
                        1, set([1, 2]), 1024),
                    hw.VirtNUMATopologyCellUsage(
                        2, set([3, 4]), 1024)])
        topo_dict = {'cells': [
                        {'cpus': '1,2', 'cpu_usage': 0,
                          'mem': {'total': 1024, 'used': 0},
                          'id': 1},
                        {'cpus': '3,4', 'cpu_usage': 0,
                          'mem': {'total': 1024, 'used': 0},
                          'id': 2}]}
        self._test_to_dict(topo, topo_dict)
        self._test_topo_from_dict(topo_dict, topo, with_usage=True)

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
