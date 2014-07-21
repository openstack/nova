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
from nova.virt import hardware as hw


class FakeFlavor():
    def __init__(self, vcpus, extra_specs):
        self.vcpus = vcpus
        self.extra_specs = extra_specs


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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
                    "hw:cpu_max_threads": "1"
                }),
                "image": {
                    "properties": {}
                },
                "expect": [16, 1, 1]
            },
            {  # Force use of at least two sockets
                "allow_threads": True,
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
                "flavor": FakeFlavor(16, {
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
