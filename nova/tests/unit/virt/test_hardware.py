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

import collections
import copy
import ddt

import mock
import testtools

from nova import exception
from nova import objects
from nova.objects import fields
from nova.pci import stats
from nova import test
from nova.tests.unit import fake_pci_device_pools as fake_pci
from nova.tests.unit.image.fake import fake_image_obj
from nova.virt import hardware as hw


class InstanceInfoTests(test.NoDBTestCase):

    def test_instance_info_default(self):
        ii = hw.InstanceInfo('fake-state')
        self.assertEqual('fake-state', ii.state)
        self.assertIsNone(ii.internal_id)

    def test_instance_info(self):
        ii = hw.InstanceInfo(state='fake-state',
                             internal_id='fake-id')
        self.assertEqual('fake-state', ii.state)
        self.assertEqual('fake-id', ii.internal_id)

    def test_instance_info_equals(self):
        ii1 = hw.InstanceInfo(state='fake-state',
                              internal_id='fake-id')
        ii2 = hw.InstanceInfo(state='fake-state',
                              internal_id='fake-id')
        ii3 = hw.InstanceInfo(state='fake-estat',
                              internal_id='fake-di')
        self.assertEqual(ii1, ii2)
        self.assertNotEqual(ii1, ii3)


class CPUSetTestCase(test.NoDBTestCase):
    def test_get_vcpu_pin_set(self):
        self.flags(vcpu_pin_set="1-3,5,^2")
        cpuset_ids = hw.get_vcpu_pin_set()
        self.assertEqual(set([1, 3, 5]), cpuset_ids)

    def test_get_vcpu_pin_set__unset(self):
        self.flags(vcpu_pin_set=None)
        cpuset_ids = hw.get_vcpu_pin_set()
        self.assertIsNone(cpuset_ids)

    def test_get_vcpu_pin_set__invalid(self):
        self.flags(vcpu_pin_set='0-1,^0,^1')
        self.assertRaises(exception.Invalid, hw.get_vcpu_pin_set)

    def test_get_cpu_shared_set(self):
        self.flags(cpu_shared_set='0-5,6,^2', group='compute')
        cpuset_ids = hw.get_cpu_shared_set()
        self.assertEqual(set([0, 1, 3, 4, 5, 6]), cpuset_ids)

    def test_get_cpu_shared_set__unset(self):
        self.flags(cpu_shared_set=None, group='compute')
        cpuset_ids = hw.get_cpu_shared_set()
        self.assertIsNone(cpuset_ids)

    def test_get_cpu_shared_set__error(self):
        self.flags(cpu_shared_set="0-1,^0,^1", group='compute')
        self.assertRaises(exception.Invalid, hw.get_cpu_shared_set)

    def test_get_cpu_dedicated_set(self):
        self.flags(cpu_dedicated_set='0-5,6,^2', group='compute')
        cpuset_ids = hw.get_cpu_dedicated_set()
        self.assertEqual(set([0, 1, 3, 4, 5, 6]), cpuset_ids)

    def test_get_cpu_dedicated_set__unset(self):
        self.flags(cpu_dedicated_set=None, group='compute')
        cpuset_ids = hw.get_cpu_dedicated_set()
        self.assertIsNone(cpuset_ids)

    def test_get_cpu_dedicated_set__error(self):
        self.flags(cpu_dedicated_set="0-1,^0,^1", group='compute')
        self.assertRaises(exception.Invalid, hw.get_cpu_dedicated_set)

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

        cpuset_ids = hw.parse_cpu_spec("^0-1")
        self.assertEqual(set([]), cpuset_ids)

        cpuset_ids = hw.parse_cpu_spec("0-3,^1-2")
        self.assertEqual(set([0, 3]), cpuset_ids)

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
                    2, 0, 0, 65536, 65536, 65536,
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
                    0, 0, 0, 65536, 65536, 1,
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
                    0, 0, 0, 65536, 8, 1
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
                    0, 0, 0, 65536, 4, 1
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
                    0, 0, 0, 65536, 4, 65536
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
            image_meta = objects.ImageMeta.from_dict(topo_test["image"])
            if type(topo_test["expect"]) == tuple:
                (preferred,
                 maximum) = hw.get_cpu_topology_constraints(
                     topo_test["flavor"], image_meta)

                self.assertEqual(topo_test["expect"][0], preferred.sockets)
                self.assertEqual(topo_test["expect"][1], preferred.cores)
                self.assertEqual(topo_test["expect"][2], preferred.threads)
                self.assertEqual(topo_test["expect"][3], maximum.sockets)
                self.assertEqual(topo_test["expect"][4], maximum.cores)
                self.assertEqual(topo_test["expect"][5], maximum.threads)
            else:
                self.assertRaises(topo_test["expect"],
                                  hw.get_cpu_topology_constraints,
                                  topo_test["flavor"],
                                  image_meta)

    def test_invalid_flavor_values(self):
        extra_specs = {
                    # test non-integer value of these extra specs
                    "hw:cpu_sockets": "8",
                    "hw:cpu_cores": "2",
                    "hw:cpu_threads": "1",
                    "hw:cpu_max_sockets": "8",
                    "hw:cpu_max_cores": "2",
                    "hw:cpu_max_threads": "1",
            }
        image_meta = objects.ImageMeta.from_dict({"properties": {}})

        for key in extra_specs:
            extra_specs_invalid = extra_specs.copy()
            extra_specs_invalid[key] = 'foo'
            flavor = objects.Flavor(vcpus=16, memory_mb=2048,
                                     extra_specs=extra_specs_invalid)
            self.assertRaises(exception.InvalidRequest,
                              hw.get_cpu_topology_constraints,
                              flavor,
                              image_meta)

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
            {  # NUMA needs threads, only cores requested by flavor
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_cores": "2",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_max_cores": 2,
                    }
                },
                "numa_topology": objects.InstanceNUMATopology(
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1]), memory=1024,
                            cpu_topology=objects.VirtCPUTopology(
                                sockets=1, cores=1, threads=2)),
                        objects.InstanceNUMACell(
                            id=1, cpuset=set([2, 3]), memory=1024)]),
                "expect": [1, 2, 2]
            },
            {  # NUMA needs threads, but more than requested by flavor - the
               # least amount of threads wins
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_threads": "2",
                }),
                "image": {
                    "properties": {}
                },
                "numa_topology": objects.InstanceNUMATopology(
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_topology=objects.VirtCPUTopology(
                                sockets=1, cores=1, threads=4))]),
                "expect": [2, 1, 2]
            },
            {  # NUMA needs threads, but more than limit in flavor - the
               # least amount of threads which divides into the vcpu
               # count wins. So with desired 4, max of 3, and
               # vcpu count of 4, we should get 2 threads.
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_max_sockets": "5",
                    "hw:cpu_max_cores": "2",
                    "hw:cpu_max_threads": "3",
                }),
                "image": {
                    "properties": {}
                },
                "numa_topology": objects.InstanceNUMATopology(
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_topology=objects.VirtCPUTopology(
                                sockets=1, cores=1, threads=4))]),
                "expect": [2, 1, 2]
            },
            {  # NUMA needs threads, but thread count does not
               # divide into flavor vcpu count, so we must
               # reduce thread count to closest divisor
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=6, memory_mb=2048,
                                         extra_specs={
                }),
                "image": {
                    "properties": {}
                },
                "numa_topology": objects.InstanceNUMATopology(
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_topology=objects.VirtCPUTopology(
                                sockets=1, cores=1, threads=4))]),
                "expect": [2, 1, 3]
            },
            {  # NUMA needs different number of threads per cell - the least
               # amount of threads wins
                "allow_threads": True,
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048,
                                         extra_specs={}),
                "image": {
                    "properties": {}
                },
                "numa_topology": objects.InstanceNUMATopology(
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=1024,
                            cpu_topology=objects.VirtCPUTopology(
                                sockets=1, cores=2, threads=2)),
                        objects.InstanceNUMACell(
                            id=1, cpuset=set([4, 5, 6, 7]), memory=1024,
                            cpu_topology=objects.VirtCPUTopology(
                                sockets=1, cores=1, threads=4))]),
                "expect": [4, 1, 2]
            },
        ]

        for topo_test in testdata:
            image_meta = objects.ImageMeta.from_dict(topo_test["image"])
            topology = hw._get_desirable_cpu_topologies(
                topo_test["flavor"],
                image_meta,
                topo_test["allow_threads"],
                topo_test.get("numa_topology"))[0]

            self.assertEqual(topo_test["expect"][0], topology.sockets)
            self.assertEqual(topo_test["expect"][1], topology.cores)
            self.assertEqual(topo_test["expect"][2], topology.threads)


class NUMATopologyTest(test.NoDBTestCase):

    def test_cpu_policy_constraint(self):
        testdata = [
            {
                "flavor": objects.Flavor(extra_specs={
                    "hw:cpu_policy": "dedicated"
                }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": "dedicated"
                    }
                },
                "expect": fields.CPUAllocationPolicy.DEDICATED
            },
            {
                "flavor": objects.Flavor(extra_specs={
                    "hw:cpu_policy": "dedicated"
                }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": "shared"
                    }
                },
                "expect": fields.CPUAllocationPolicy.DEDICATED
            },
            {
                "flavor": objects.Flavor(extra_specs={
                    "hw:cpu_policy": "dedicated"
                }),
                "image": {
                    "properties": {
                    }
                },
                "expect": fields.CPUAllocationPolicy.DEDICATED
            },
            {
                "flavor": objects.Flavor(extra_specs={
                    "hw:cpu_policy": "shared"
                }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": "dedicated"
                    }
                },
                "expect": exception.ImageCPUPinningForbidden
            },
            {
                "flavor": objects.Flavor(extra_specs={
                    "hw:cpu_policy": "shared"
                }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": "shared"
                    }
                },
                "expect": fields.CPUAllocationPolicy.SHARED
            },
            {
                "flavor": objects.Flavor(extra_specs={
                    "hw:cpu_policy": "shared"
                }),
                "image": {
                    "properties": {
                    }
                },
                "expect": fields.CPUAllocationPolicy.SHARED
            },
            {
                "flavor": objects.Flavor(),
                "image": {
                    "properties": {
                        "hw_cpu_policy": "dedicated"
                    }
                },
                "expect": fields.CPUAllocationPolicy.DEDICATED
            },
            {
                "flavor": objects.Flavor(),
                "image": {
                    "properties": {
                        "hw_cpu_policy": "shared"
                    }
                },
                "expect": fields.CPUAllocationPolicy.SHARED
            },
            {
                "flavor": objects.Flavor(),
                "image": {
                    "properties": {
                    }
                },
                "expect": None
            },
            {
                "flavor": objects.Flavor(extra_specs={
                    "hw:cpu_policy": "invalid"
                }),
                "image": {
                    "properties": {
                    }
                },
                "expect": exception.InvalidCPUAllocationPolicy
            },
        ]

        for testitem in testdata:
            image_meta = objects.ImageMeta.from_dict(testitem["image"])
            if testitem["expect"] is None:
                cpu_policy = hw.get_cpu_policy_constraint(
                    testitem["flavor"], image_meta)
                self.assertIsNone(cpu_policy)
            elif type(testitem["expect"]) == type:
                self.assertRaises(testitem["expect"],
                                  hw.get_cpu_policy_constraint,
                                  testitem["flavor"],
                                  image_meta)
            else:
                cpu_policy = hw.get_cpu_policy_constraint(
                    testitem["flavor"], image_meta)
                self.assertIsNotNone(cpu_policy)
                self.assertEqual(testitem["expect"], cpu_policy)

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
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={
                    "hw:mem_page_size": 2048
                }),
                "image": {
                },
                "expect": objects.InstanceNUMATopology(cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
                            memory=2048, pagesize=2048)
                    ]),
            },
            {
                # a nodes number of zero should lead to an
                # exception
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={
                    "hw:numa_nodes": 0
                }),
                "image": {
                },
                "expect": exception.InvalidNUMANodesNumber,
            },
            {
                # a negative nodes number should lead to an
                # exception
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={
                    "hw:numa_nodes": -1
                }),
                "image": {
                },
                "expect": exception.InvalidNUMANodesNumber,
            },
            {
                # a nodes number not numeric should lead to an
                # exception
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={
                    "hw:numa_nodes": 'x'
                }),
                "image": {
                },
                "expect": exception.InvalidNUMANodesNumber,
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
                            id=2, cpuset=set([5, 7]), memory=512)
                    ]),
            },
            {
                "flavor": objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={
                }),
                "image": {
                    "properties": {
                        "hw_numa_nodes": 3,
                        "hw_numa_cpus.0": "0-3",
                        "hw_numa_mem.0": "1024",
                        "hw_numa_cpus.1": "4,6",
                        "hw_numa_mem.1": "512",
                        "hw_numa_cpus.2": "5,7",
                        "hw_numa_mem.2": "512",
                    },
                },
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=1024),
                        objects.InstanceNUMACell(
                            id=1, cpuset=set([4, 6]), memory=512),
                        objects.InstanceNUMACell(
                            id=2, cpuset=set([5, 7]), memory=512)
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
                    "properties": {
                        "hw_numa_nodes": 4}
                },
                "expect": exception.ImageNUMATopologyForbidden,
            },
            {
                # NUMA + CPU pinning requested in the flavor
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                     "hw:numa_nodes": 2,
                     "hw:cpu_policy": fields.CPUAllocationPolicy.DEDICATED
                }),
                "image": {
                },
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1]), memory=1024,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
                        objects.InstanceNUMACell(
                            id=1, cpuset=set([2, 3]), memory=1024,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
            },
            {
                # no NUMA + CPU pinning requested in the flavor
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                         "hw:cpu_policy": fields.CPUAllocationPolicy.DEDICATED
                }),
                "image": {
                },
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
            },
            {
                # NUMA + CPU pinning requested in the image
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                         "hw:numa_nodes": 2
                }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": fields.CPUAllocationPolicy.DEDICATED
                        }},
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1]), memory=1024,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
                        objects.InstanceNUMACell(
                            id=1, cpuset=set([2, 3]), memory=1024,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
            },
            {
                # no NUMA + CPU pinning requested in the image
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={}),
                "image": {
                    "properties": {
                        "hw_cpu_policy": fields.CPUAllocationPolicy.DEDICATED
                    }},
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
            },
            {
                # Invalid CPU pinning override
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                     "hw:numa_nodes": 2,
                     "hw:cpu_policy": fields.CPUAllocationPolicy.SHARED
                }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": fields.CPUAllocationPolicy.DEDICATED}
                },
                "expect": exception.ImageCPUPinningForbidden,
            },
            {
                # Invalid CPU pinning policy with realtime
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                         "hw:cpu_policy": fields.CPUAllocationPolicy.SHARED,
                         "hw:cpu_realtime": "yes",
                }),
                "image": {
                    "properties": {}
                },
                "expect": exception.RealtimeConfigurationInvalid,
            },
            {
                # Invalid CPU thread pinning override
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                         "hw:numa_nodes": 2,
                         "hw:cpu_policy": fields.CPUAllocationPolicy.DEDICATED,
                         "hw:cpu_thread_policy":
                             fields.CPUThreadAllocationPolicy.ISOLATE,
                }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": fields.CPUAllocationPolicy.DEDICATED,
                        "hw_cpu_thread_policy":
                            fields.CPUThreadAllocationPolicy.REQUIRE,
                        }
                },
                "expect": exception.ImageCPUThreadPolicyForbidden,
            },
            {
                # CPU thread pinning override set to default value
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                         "hw:numa_nodes": 1,
                         "hw:cpu_policy": fields.CPUAllocationPolicy.DEDICATED,
                         "hw:cpu_thread_policy":
                             fields.CPUThreadAllocationPolicy.PREFER,
                }),
                "image": {},
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                            cpu_thread_policy=
                                fields.CPUThreadAllocationPolicy.PREFER)])
            },
            {
                # Invalid CPU pinning policy with CPU thread pinning
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                         "hw:cpu_policy": fields.CPUAllocationPolicy.SHARED,
                         "hw:cpu_thread_policy":
                             fields.CPUThreadAllocationPolicy.ISOLATE,
                }),
                "image": {
                    "properties": {}
                },
                "expect": exception.CPUThreadPolicyConfigurationInvalid,
            },
            {
                # Invalid vCPUs mask with realtime
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                                             "hw:cpu_policy": "dedicated",
                                             "hw:cpu_realtime": "yes",
                                         }),
                "image": {
                    "properties": {}
                },
                "expect": exception.RealtimeMaskNotFoundOrInvalid,
            },
            {   # We pass an invalid option
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:emulator_threads_policy": "foo",
                }),
                "image": {
                    "properties": {}
                },
                "expect": exception.InvalidEmulatorThreadsPolicy,
            },
            {   # We request emulator threads option without numa topology
                "flavor": objects.Flavor(vcpus=16, memory_mb=2048,
                                         extra_specs={
                    "hw:emulator_threads_policy": "isolate",
                }),
                "image": {
                    "properties": {}
                },
                "expect": exception.BadRequirementEmulatorThreadsPolicy,
            },
            {   # We request a valid emulator threads options with
                # cpu_policy based from flavor
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:emulator_threads_policy": "isolate",
                    "hw:cpu_policy": "dedicated",
                }),
                "image": {
                    "properties": {}
                },
                "expect": objects.InstanceNUMATopology(
                    emulator_threads_policy=
                      fields.CPUEmulatorThreadsPolicy.ISOLATE,
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                        )]),
            },
            {   # We request a valid emulator threads options with cpu
                # policy based from image
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:emulator_threads_policy": "isolate",
                }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": "dedicated",
                    }
                },
                "expect": objects.InstanceNUMATopology(
                    emulator_threads_policy=
                      fields.CPUEmulatorThreadsPolicy.ISOLATE,
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                        )]),
            },
            {
                # Invalid CPU pinning policy
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_policy": "foo",
                }),
                "image": {
                    "properties": {}
                },
                "expect": exception.InvalidCPUAllocationPolicy,
            },
            {
                # Invalid CPU thread pinning
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_policy": fields.CPUAllocationPolicy.DEDICATED,
                    "hw:cpu_thread_policy": "foo",
                }),
                "image": {
                    "properties": {}
                },
                "expect": exception.InvalidCPUThreadAllocationPolicy,
            },
            {
                # Invalid CPU thread pinning in image
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_policy": fields.CPUAllocationPolicy.SHARED,
                 }),
                "image": {
                    "properties": {
                        "hw_cpu_policy": fields.CPUAllocationPolicy.DEDICATED,
                    }
                },
                "expect": exception.ImageCPUPinningForbidden,
            },
            {
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048, extra_specs={
                    "hw:pmem": '2GB'}),
                "image": {},
                "expect": objects.InstanceNUMATopology(cells=
                    [
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048),
                    ]),
            },
            {
                # We request PCPUs explicitly
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "resources:PCPU": "4",
                }),
                "image": {
                    "properties": {}
                },
                "expect": objects.InstanceNUMATopology(
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                        )]),
            },
            {
                # We request the HW_CPU_HYPERTHREADING trait explicitly
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "resources:PCPU": "4",
                    "trait:HW_CPU_HYPERTHREADING": "forbidden",
                }),
                "image": {
                    "properties": {}
                },
                "expect": objects.InstanceNUMATopology(
                    cells=[
                        objects.InstanceNUMACell(
                            id=0, cpuset=set([0, 1, 2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                            cpu_thread_policy=
                                fields.CPUThreadAllocationPolicy.ISOLATE,
                        )]),
            },
            {
                # Requesting both implicit and explicit PCPUs
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_policy": fields.CPUAllocationPolicy.DEDICATED,
                    "resources:PCPU": "4",
                }),
                "image": {"properties": {}},
                "expect": exception.InvalidRequest,
            },
            {
                # Requesting both PCPUs and VCPUs
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "resources:PCPU": "2",
                    "resources:VCPU": "2",
                }),
                "image": {"properties": {}},
                "expect": exception.InvalidRequest,
            },
            {
                # Mismatch between PCPU requests and flavor.vcpus
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "resources:PCPU": "5",
                }),
                "image": {"properties": {}},
                "expect": exception.InvalidRequest,
            },
            {
                # Mismatch between PCPU requests and flavor.vcpus with
                # 'isolate' emulator thread policy
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:emulator_threads_policy": "isolate",
                    "resources:PCPU": "4",
                }),
                "image": {"properties": {}},
                "expect": exception.InvalidRequest,
            },
            {
                # Mismatch between implicit and explicit HW_CPU_HYPERTHREADING
                # trait (flavor)
                "flavor": objects.Flavor(vcpus=4, memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_thread_policy":
                        fields.CPUThreadAllocationPolicy.ISOLATE,
                    "trait:HW_CPU_HYPERTHREADING": "required",
                }),
                "image": {"properties": {}},
                "expect": exception.InvalidRequest,
            },
            {
                # Mismatch between implicit and explicit HW_CPU_HYPERTHREADING
                # trait (image)
                "flavor": objects.Flavor(vcpus=4, name='foo', memory_mb=2048,
                                         extra_specs={
                    "hw:cpu_policy": fields.CPUAllocationPolicy.DEDICATED,
                    "hw:cpu_thread_policy":
                        fields.CPUThreadAllocationPolicy.ISOLATE,
                }),
                "image": {
                    "properties": {
                        "trait:HW_CPU_HYPERTHREADING": "required",
                    }
                },
                "expect": exception.InvalidRequest,
            },
        ]

        for testitem in testdata:
            image_meta = objects.ImageMeta.from_dict(testitem["image"])
            if testitem["expect"] is None:
                topology = hw.numa_get_constraints(
                    testitem["flavor"], image_meta)
                self.assertIsNone(topology)
            elif type(testitem["expect"]) == type:
                self.assertRaises(testitem["expect"],
                                  hw.numa_get_constraints,
                                  testitem["flavor"],
                                  image_meta)
            else:
                topology = hw.numa_get_constraints(
                    testitem["flavor"], image_meta)
                self.assertIsNotNone(topology)
                self.assertEqual(len(testitem["expect"].cells),
                                 len(topology.cells))
                self.assertEqual(
                    testitem["expect"].emulator_threads_isolated,
                    topology.emulator_threads_isolated)

                for i in range(len(topology.cells)):
                    self.assertEqual(testitem["expect"].cells[i].id,
                                     topology.cells[i].id)
                    self.assertEqual(testitem["expect"].cells[i].cpuset,
                                     topology.cells[i].cpuset)
                    self.assertEqual(testitem["expect"].cells[i].memory,
                                     topology.cells[i].memory)
                    self.assertEqual(testitem["expect"].cells[i].pagesize,
                                     topology.cells[i].pagesize)
                    self.assertEqual(testitem["expect"].cells[i].cpu_pinning,
                                     topology.cells[i].cpu_pinning)

    def test_host_usage_contiguous(self):
        hosttopo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1, 2, 3]),
                pcpuset=set(),
                memory=256,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=32768, used=0),
                    objects.NUMAPagesTopology(size_kb=2048, total=64, used=32)
                ],
                siblings=[set([0]), set([1]), set([2]), set([3])]),
            objects.NUMACell(
                id=1,
                cpuset=set([4, 6]),
                pcpuset=set(),
                memory=256,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=32768, used=64),
                    objects.NUMAPagesTopology(size_kb=2048, total=64, used=62)
                ],
                siblings=[set([4]), set([6])]),
            objects.NUMACell(
                id=2,
                cpuset=set([5, 7]),
                pcpuset=set(),
                memory=2,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=512, used=16)],
                siblings=[set([5]), set([7])]),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1, 2]), memory=32),
            objects.InstanceNUMACell(id=1, cpuset=set([4]), memory=16),
        ])
        instance2 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=64),
            objects.InstanceNUMACell(id=1, cpuset=set([2, 3]), memory=32),
        ])
        instance3 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=4,
                                     pagesize=2048),
            objects.InstanceNUMACell(id=1, cpuset=set([2, 3]), memory=4,
                                     pagesize=2048),
        ])

        hostusage = hw.numa_usage_from_instance_numa(hosttopo, instance1)
        hostusage = hw.numa_usage_from_instance_numa(hostusage, instance2)
        hostusage = hw.numa_usage_from_instance_numa(hostusage, instance3)

        self.assertEqual(len(hosttopo), len(hostusage))

        # Host NUMA node 0
        self.assertIsInstance(hostusage.cells[0], objects.NUMACell)
        self.assertEqual(hosttopo.cells[0].cpuset,
                         hostusage.cells[0].cpuset)
        self.assertEqual(hosttopo.cells[0].memory,
                         hostusage.cells[0].memory)
        self.assertEqual(hostusage.cells[0].cpu_usage, 7)
        self.assertEqual(hostusage.cells[0].memory_usage, 100)
        # instance1, instance2 consume 96MiB of small pages
        self.assertEqual(4, hostusage.cells[0].mempages[0].size_kb)
        self.assertEqual(24576, hostusage.cells[0].mempages[0].used)
        # instance3 consumes 4MiB of large pages
        self.assertEqual(2048, hostusage.cells[0].mempages[1].size_kb)
        self.assertEqual(34, hostusage.cells[0].mempages[1].used)

        # Host NUMA node 1
        self.assertIsInstance(hostusage.cells[1], objects.NUMACell)
        self.assertEqual(hosttopo.cells[1].cpuset,
                         hostusage.cells[1].cpuset)
        self.assertEqual(hosttopo.cells[1].memory,
                         hostusage.cells[1].memory)
        self.assertEqual(hostusage.cells[1].cpu_usage, 5)
        self.assertEqual(hostusage.cells[1].memory_usage, 52)
        # instance1, instance2 consume 48MiB of small pages and 64
        # pages already used
        self.assertEqual(4, hostusage.cells[1].mempages[0].size_kb)
        self.assertEqual(12352, hostusage.cells[1].mempages[0].used)
        # instance3 consumes 4MiB of large pages
        self.assertEqual(2048, hostusage.cells[1].mempages[1].size_kb)
        self.assertEqual(64, hostusage.cells[1].mempages[1].used)

        # Host NUMA node 2
        self.assertIsInstance(hostusage.cells[2], objects.NUMACell)
        self.assertEqual(hosttopo.cells[2].cpuset,
                         hostusage.cells[2].cpuset)
        self.assertEqual(hosttopo.cells[2].memory,
                         hostusage.cells[2].memory)
        self.assertEqual(hostusage.cells[2].cpu_usage, 0)
        self.assertEqual(hostusage.cells[2].memory_usage, 0)
        self.assertEqual(4, hostusage.cells[2].mempages[0].size_kb)
        self.assertEqual(16, hostusage.cells[2].mempages[0].used)

    def test_host_usage_contiguous_pages_compute(self):
        hosttopo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1, 2, 3]),
                pcpuset=set(),
                memory=160,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=32768, used=32),
                    objects.NUMAPagesTopology(size_kb=2048, total=16, used=2)],
                siblings=[set([0]), set([1]), set([2]), set([3])])])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1, 2]), memory=64,
                                     pagesize=4),
        ])
        instance2 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=32,
                                     pagesize=4),
        ])
        instance3 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=16,
                                     pagesize=2048),
        ])

        hostusage = hw.numa_usage_from_instance_numa(hosttopo, instance1)
        hostusage = hw.numa_usage_from_instance_numa(hostusage, instance2)
        hostusage = hw.numa_usage_from_instance_numa(hostusage, instance3)

        # instance1, instance2 are consuming 96MiB smallpages which
        # means 96*1024/4 = 24576, plus 32 pages already used.
        self.assertEqual(4, hostusage.cells[0].mempages[0].size_kb)
        self.assertEqual(24608, hostusage.cells[0].mempages[0].used)
        # instance3 is consuming 16MiB largepages plus 2 pages already
        # used.
        self.assertEqual(2048, hostusage.cells[0].mempages[1].size_kb)
        self.assertEqual(10, hostusage.cells[0].mempages[1].used)

    def test_host_usage_sparse(self):
        hosttopo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1, 2, 3]),
                pcpuset=set(),
                memory=1024,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=512, used=0)],
                siblings=[set([0]), set([1]), set([2]), set([3])]),
            objects.NUMACell(
                id=5,
                cpuset=set([4, 6]),
                pcpuset=set(),
                memory=512,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=512, used=0)],
                siblings=[set([4]), set([6])]),
            objects.NUMACell(
                id=6,
                cpuset=set([5, 7]),
                pcpuset=set(),
                memory=512,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=512, used=0)],
                siblings=[set([5]), set([7])]),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1, 2]), memory=256),
            objects.InstanceNUMACell(id=6, cpuset=set([4]), memory=256),
        ])
        instance2 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=256,
                                     cpu_usage=0, memory_usage=0, mempages=[
                                     objects.NUMAPagesTopology(
                                        size_kb=4, total=512, used=0)]),
            objects.InstanceNUMACell(id=5, cpuset=set([5, 7]), memory=256,
                                     cpu_usage=0, memory_usage=0, mempages=[
                                     objects.NUMAPagesTopology(
                                        size_kb=4, total=512, used=0)]),
        ])

        hostusage = hw.numa_usage_from_instance_numa(hosttopo, instance1)
        hostusage = hw.numa_usage_from_instance_numa(hostusage, instance2)

        self.assertEqual(len(hosttopo), len(hostusage))

        self.assertIsInstance(hostusage.cells[0], objects.NUMACell)
        self.assertEqual(hosttopo.cells[0].id,
                         hostusage.cells[0].id)
        self.assertEqual(hosttopo.cells[0].cpuset,
                         hostusage.cells[0].cpuset)
        self.assertEqual(hosttopo.cells[0].memory,
                         hostusage.cells[0].memory)
        self.assertEqual(hostusage.cells[0].cpu_usage, 5)
        self.assertEqual(hostusage.cells[0].memory_usage, 512)

        self.assertIsInstance(hostusage.cells[1], objects.NUMACell)
        self.assertEqual(hosttopo.cells[1].id,
                         hostusage.cells[1].id)
        self.assertEqual(hosttopo.cells[1].cpuset,
                         hostusage.cells[1].cpuset)
        self.assertEqual(hosttopo.cells[1].memory,
                         hostusage.cells[1].memory)
        self.assertEqual(hostusage.cells[1].cpu_usage, 2)
        self.assertEqual(hostusage.cells[1].memory_usage, 256)

        self.assertIsInstance(hostusage.cells[2], objects.NUMACell)
        self.assertEqual(hosttopo.cells[2].cpuset,
                         hostusage.cells[2].cpuset)
        self.assertEqual(hosttopo.cells[2].memory,
                         hostusage.cells[2].memory)
        self.assertEqual(hostusage.cells[2].cpu_usage, 1)
        self.assertEqual(hostusage.cells[2].memory_usage, 256)

    def test_host_usage_culmulative_with_free(self):
        hosttopo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1, 2, 3]),
                pcpuset=set(),
                memory=1024,
                cpu_usage=2,
                memory_usage=512,
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=512, used=0)],
                siblings=[set([0]), set([1]), set([2]), set([3])],
                pinned_cpus=set()),
            objects.NUMACell(
                id=1,
                cpuset=set([4, 6]),
                pcpuset=set(),
                memory=512,
                cpu_usage=1,
                memory_usage=512,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=512, used=0)],
                siblings=[set([4]), set([6])]),
            objects.NUMACell(
                id=2,
                cpuset=set([5, 7]),
                pcpuset=set(),
                memory=256,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[
                    objects.NUMAPagesTopology(size_kb=4, total=512, used=0)],
                siblings=[set([5]), set([7])]),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1, 2]), memory=512),
            objects.InstanceNUMACell(id=1, cpuset=set([3]), memory=256),
            objects.InstanceNUMACell(id=2, cpuset=set([4]), memory=256)])

        hostusage = hw.numa_usage_from_instance_numa(hosttopo, instance1)

        self.assertIsInstance(hostusage.cells[0], objects.NUMACell)
        self.assertEqual(hostusage.cells[0].cpu_usage, 5)
        self.assertEqual(hostusage.cells[0].memory_usage, 1024)

        self.assertIsInstance(hostusage.cells[1], objects.NUMACell)
        self.assertEqual(hostusage.cells[1].cpu_usage, 2)
        self.assertEqual(hostusage.cells[1].memory_usage, 768)

        self.assertIsInstance(hostusage.cells[2], objects.NUMACell)
        self.assertEqual(hostusage.cells[2].cpu_usage, 1)
        self.assertEqual(hostusage.cells[2].memory_usage, 256)

        # Test freeing of resources
        hostusage = hw.numa_usage_from_instance_numa(hostusage, instance1,
                                                     free=True)

        self.assertEqual(hostusage.cells[0].cpu_usage, 2)
        self.assertEqual(hostusage.cells[0].memory_usage, 512)

        self.assertEqual(hostusage.cells[1].cpu_usage, 1)
        self.assertEqual(hostusage.cells[1].memory_usage, 512)

        self.assertEqual(hostusage.cells[2].cpu_usage, 0)
        self.assertEqual(hostusage.cells[2].memory_usage, 0)

    def _topo_usage_reserved_page_size(self):
        reserved = hw.numa_get_reserved_huge_pages()
        hosttopo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1]),
                memory=512,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=2048, total=512, used=128,
                    reserved=reserved[0][2048])],
                siblings=[set([0]), set([1])]),
            objects.NUMACell(
                id=1,
                cpuset=set([2, 3]),
                memory=512,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=1048576, total=5, used=2,
                    reserved=reserved[1][1048576])],
                siblings=[set([2]), set([3])]),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(
                id=0, cpuset=set([0, 1]), memory=256, pagesize=2048),
            objects.InstanceNUMACell(
                id=1, cpuset=set([2, 3]), memory=1024, pagesize=1048576),
        ])
        return hosttopo, instance1

    def test_numa_get_reserved_huge_pages(self):
        reserved = hw.numa_get_reserved_huge_pages()
        self.assertEqual({}, reserved)
        self.flags(reserved_huge_pages=[
            {'node': 3, 'size': 2048, 'count': 128},
            {'node': 3, 'size': '1GB', 'count': 4},
            {'node': 6, 'size': '2MB', 'count': 64},
            {'node': 9, 'size': '1GB', 'count': 1}])
        reserved = hw.numa_get_reserved_huge_pages()
        self.assertEqual({2048: 128, 1048576: 4}, reserved[3])
        self.assertEqual({2048: 64}, reserved[6])
        self.assertEqual({1048576: 1}, reserved[9])

    def test_reserved_hugepgaes_success(self):
        self.flags(reserved_huge_pages=[
            {'node': 0, 'size': 2048, 'count': 128},
            {'node': 1, 'size': 1048576, 'count': 1}])
        hosttopo, instance1 = self._topo_usage_reserved_page_size()

        hostusage = hw.numa_usage_from_instance_numa(hosttopo, instance1)

        self.assertEqual(hostusage.cells[0].mempages[0].size_kb, 2048)
        self.assertEqual(hostusage.cells[0].mempages[0].total, 512)
        self.assertEqual(hostusage.cells[0].mempages[0].used, 256)
        # 128 already used + 128 used by instance + 128 reserved
        self.assertEqual(hostusage.cells[0].mempages[0].free, 128)

        self.assertEqual(hostusage.cells[1].mempages[0].size_kb, 1048576)
        self.assertEqual(hostusage.cells[1].mempages[0].total, 5)
        self.assertEqual(hostusage.cells[1].mempages[0].used, 3)
        # 2 already used + 1 used by instance + 1 reserved
        self.assertEqual(hostusage.cells[1].mempages[0].free, 1)

    def test_reserved_huge_pages_invalid_format(self):
        self.flags(reserved_huge_pages=[{'node': 0, 'size': 2048}])
        self.assertRaises(
            exception.InvalidReservedMemoryPagesOption,
            self._topo_usage_reserved_page_size)

    def test_reserved_huge_pages_invalid_value(self):
        self.flags(reserved_huge_pages=["0:foo:bar"])
        self.assertRaises(
            exception.InvalidReservedMemoryPagesOption,
            self._topo_usage_reserved_page_size)

    def test_topo_usage_none(self):
        hosttopo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1]),
                memory=512,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=512, used=0)],
                siblings=[set([0]), set([1])]),
            objects.NUMACell(
                id=1,
                cpuset=set([2, 3]),
                memory=512,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=512, used=0)],
                siblings=[set([2]), set([3])]),
        ])
        instance1 = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0, 1]), memory=256),
            objects.InstanceNUMACell(id=2, cpuset=set([2]), memory=256),
        ])

        hostusage = hw.numa_usage_from_instance_numa(None, instance1)
        self.assertIsNone(hostusage)

        hostusage = hw.numa_usage_from_instance_numa(hosttopo, None)
        self.assertEqual(hostusage.cells[0].cpu_usage, 0)
        self.assertEqual(hostusage.cells[0].memory_usage, 0)
        self.assertEqual(hostusage.cells[1].cpu_usage, 0)
        self.assertEqual(hostusage.cells[1].memory_usage, 0)

    def test_topo_usage_with_network_metadata(self):
        r"""Validate behavior with network_metadata.

        Ensure we handle ``NUMACell``\ s that have ``network_metadata`` set
        along with those where this is unset.
        """

        topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                siblings=[set([0, 2]), set([1, 3])],
                mempages=[],
                pinned_cpus=set(),
                network_metadata=objects.NetworkMetadata(
                    physnets=set(['foo', 'bar']), tunneled=True)),
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                siblings=[set([0, 2]), set([1, 3])],
                mempages=[],
                pinned_cpus=set()),
            ])

        new_topo = hw.numa_usage_from_instance_numa(topo, None)
        self.assertIn('network_metadata', new_topo.cells[0])
        self.assertNotIn('network_metadata', new_topo.cells[1])

    def assertNUMACellMatches(self, expected_cell, got_cell):
        attrs = ('cpuset', 'memory', 'id')
        if isinstance(expected_cell, objects.NUMATopology):
            attrs += ('cpu_usage', 'memory_usage')

        for attr in attrs:
            self.assertEqual(getattr(expected_cell, attr),
                             getattr(got_cell, attr))

    def test_json(self):
        expected = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=1,
                cpuset=set([1, 2]),
                memory=1024,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=512, used=0)],
                siblings=[set([1]), set([2])]),
            objects.NUMACell(
                id=2,
                cpuset=set([3, 4]),
                memory=1024,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=512, used=0)],
                siblings=[set([3]), set([4])])])
        got = objects.NUMATopology.obj_from_db_obj(expected._to_json())

        for exp_cell, got_cell in zip(expected.cells, got.cells):
            self.assertNUMACellMatches(exp_cell, got_cell)


class VirtNUMATopologyCellUsageTestCase(test.NoDBTestCase):
    def test_fit_instance_cell_success_no_limit(self):
        host_cell = objects.NUMACell(
            id=4,
            cpuset=set([1, 2]),
            memory=1024,
            cpu_usage=0,
            memory_usage=0,
            pinned_cpus=set(),
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)],
            siblings=[set([1]), set([2])])
        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2]), memory=1024)
        fitted_cell = hw._numa_fit_instance_cell(host_cell, instance_cell)
        self.assertIsInstance(fitted_cell, objects.InstanceNUMACell)
        self.assertEqual(host_cell.id, fitted_cell.id)

    def test_fit_instance_cell_success_w_limit(self):
        host_cell = objects.NUMACell(
            id=4,
            cpuset=set([1, 2]),
            memory=1024,
            cpu_usage=2,
            memory_usage=1024,
            pinned_cpus=set(),
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)],
            siblings=[set([1]), set([2])])
        limit_cell = objects.NUMATopologyLimits(
            cpu_allocation_ratio=2, ram_allocation_ratio=2)
        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2]), memory=1024)
        fitted_cell = hw._numa_fit_instance_cell(
                host_cell, instance_cell, limit_cell=limit_cell)
        self.assertIsInstance(fitted_cell, objects.InstanceNUMACell)
        self.assertEqual(host_cell.id, fitted_cell.id)

    def test_fit_instance_cell_self_overcommit(self):
        host_cell = objects.NUMACell(
            id=4,
            cpuset=set([1, 2]),
            memory=1024,
            cpu_usage=0,
            memory_usage=0,
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)],
            siblings=[set([1]), set([2])],
            pinned_cpus=set())
        limit_cell = objects.NUMATopologyLimits(
            cpu_allocation_ratio=2, ram_allocation_ratio=2)
        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2, 3]), memory=4096)
        fitted_cell = hw._numa_fit_instance_cell(
                host_cell, instance_cell, limit_cell=limit_cell)
        self.assertIsNone(fitted_cell)

    def test_fit_instance_cell_fail_w_limit(self):
        host_cell = objects.NUMACell(
            id=4,
            cpuset=set([1, 2]),
            memory=1024,
            cpu_usage=2,
            memory_usage=1024,
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)],
            siblings=[set([1]), set([2])],
            pinned_cpus=set())
        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2]), memory=4096)
        limit_cell = objects.NUMATopologyLimits(
            cpu_allocation_ratio=2, ram_allocation_ratio=2)
        fitted_cell = hw._numa_fit_instance_cell(
                host_cell, instance_cell, limit_cell=limit_cell)
        self.assertIsNone(fitted_cell)

        instance_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([1, 2, 3, 4, 5]), memory=1024)
        fitted_cell = hw._numa_fit_instance_cell(
                host_cell, instance_cell, limit_cell=limit_cell)
        self.assertIsNone(fitted_cell)


class VirtNUMAHostTopologyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VirtNUMAHostTopologyTestCase, self).setUp()

        self.host = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=1,
                cpuset=set([1, 2]),
                pcpuset=set(),
                memory=2048,
                cpu_usage=2,
                memory_usage=2048,
                pinned_cpus=set(),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)],
                siblings=[set([1]), set([2])]),
            objects.NUMACell(id=2,
                cpuset=set([3, 4]),
                pcpuset=set(),
                memory=2048,
                cpu_usage=2,
                memory_usage=2048,
                pinned_cpus=set(),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)],
                siblings=[set([3]), set([4])])])

        self.limits = objects.NUMATopologyLimits(
            cpu_allocation_ratio=2, ram_allocation_ratio=2)
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
        fitted_instance1 = hw.numa_fit_instance_to_host(
                self.host, self.instance1)
        self.assertIsInstance(fitted_instance1, objects.InstanceNUMATopology)
        self.host = hw.numa_usage_from_instance_numa(
                self.host, fitted_instance1)
        fitted_instance2 = hw.numa_fit_instance_to_host(
                self.host, self.instance3)
        self.assertIsInstance(fitted_instance2, objects.InstanceNUMATopology)

    def test_get_fitting_success_limits(self):
        fitted_instance = hw.numa_fit_instance_to_host(
                self.host, self.instance3, self.limits)
        self.assertIsInstance(fitted_instance, objects.InstanceNUMATopology)
        self.assertEqual(1, fitted_instance.cells[0].id)

    def test_get_fitting_fails_no_limits(self):
        fitted_instance = hw.numa_fit_instance_to_host(
                self.host, self.instance2, self.limits)
        self.assertIsNone(fitted_instance)

    def test_get_fitting_culmulative_fails_limits(self):
        fitted_instance1 = hw.numa_fit_instance_to_host(
                self.host, self.instance1, self.limits)
        self.assertIsInstance(fitted_instance1, objects.InstanceNUMATopology)
        self.assertEqual(1, fitted_instance1.cells[0].id)
        self.host = hw.numa_usage_from_instance_numa(
                self.host, fitted_instance1)
        fitted_instance2 = hw.numa_fit_instance_to_host(
                self.host, self.instance2, self.limits)
        self.assertIsNone(fitted_instance2)

    def test_get_fitting_culmulative_success_limits(self):
        fitted_instance1 = hw.numa_fit_instance_to_host(
                self.host, self.instance1, self.limits)
        self.assertIsInstance(fitted_instance1, objects.InstanceNUMATopology)
        self.assertEqual(1, fitted_instance1.cells[0].id)
        self.host = hw.numa_usage_from_instance_numa(
                self.host, fitted_instance1)
        fitted_instance2 = hw.numa_fit_instance_to_host(
                self.host, self.instance3, self.limits)
        self.assertIsInstance(fitted_instance2, objects.InstanceNUMATopology)
        self.assertEqual(2, fitted_instance2.cells[0].id)

    @mock.patch.object(hw, '_numa_cells_support_network_metadata',
                       return_value=True)
    def test_get_fitting_success_limits_with_networks(self, mock_supports):
        network_metadata = objects.NetworkMetadata(
            physnets=set(), tunneled=False)
        limits = objects.NUMATopologyLimits(
            cpu_allocation_ratio=2.0,
            ram_allocation_ratio=2.0,
            network_metadata=network_metadata)

        fitted_instance = hw.numa_fit_instance_to_host(
            self.host, self.instance1, limits=limits)

        self.assertIsInstance(fitted_instance, objects.InstanceNUMATopology)
        mock_supports.assert_called_once_with(
            self.host, [self.host.cells[0]], network_metadata)

    @mock.patch.object(hw, '_numa_cells_support_network_metadata',
                       return_value=False)
    def test_get_fitting_fails_limits_with_networks(self, mock_supports):
        network_metadata = objects.NetworkMetadata(
            physnets=set(), tunneled=False)
        limits = objects.NUMATopologyLimits(
            cpu_allocation_ratio=2.0,
            ram_allocation_ratio=2.0,
            network_metadata=network_metadata)

        fitted_instance = hw.numa_fit_instance_to_host(
            self.host, self.instance1, limits=limits)

        self.assertIsNone(fitted_instance)
        mock_supports.assert_has_calls([
            mock.call(self.host, [self.host.cells[0]], network_metadata),
            mock.call(self.host, [self.host.cells[1]], network_metadata),
        ])

    def test_get_fitting_pci_success(self):
        pci_request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': '8086'}])
        pci_reqs = [pci_request]
        pci_stats = stats.PciDeviceStats()
        with mock.patch.object(stats.PciDeviceStats,
                'support_requests', return_value= True):
            fitted_instance1 = hw.numa_fit_instance_to_host(self.host,
                                                        self.instance1,
                                                        pci_requests=pci_reqs,
                                                        pci_stats=pci_stats)
            self.assertIsInstance(fitted_instance1,
                                  objects.InstanceNUMATopology)

    def test_get_fitting_pci_fail(self):
        pci_request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': '8086'}])
        pci_reqs = [pci_request]
        pci_stats = stats.PciDeviceStats()
        with mock.patch.object(stats.PciDeviceStats,
                'support_requests', return_value= False):
            fitted_instance1 = hw.numa_fit_instance_to_host(
                                                        self.host,
                                                        self.instance1,
                                                        pci_requests=pci_reqs,
                                                        pci_stats=pci_stats)
            self.assertIsNone(fitted_instance1)

    def test_get_fitting_pci_avoided(self):

        def _create_pci_stats(node):
            test_dict = copy.copy(fake_pci.fake_pool_dict)
            test_dict['numa_node'] = node
            return stats.PciDeviceStats(
                [objects.PciDevicePool.from_dict(test_dict)])

        # the PCI device is found on host cell 1
        pci_stats = _create_pci_stats(1)

        # ...threfore an instance without a PCI device should get host cell 2
        instance_topology = hw.numa_fit_instance_to_host(
                self.host, self.instance1, pci_stats=pci_stats)
        self.assertIsInstance(instance_topology, objects.InstanceNUMATopology)
        # TODO(sfinucan): We should be comparing this against the HOST cell
        self.assertEqual(2, instance_topology.cells[0].id)

        # the PCI device is now found on host cell 2
        pci_stats = _create_pci_stats(2)

        # ...threfore an instance without a PCI device should get host cell 1
        instance_topology = hw.numa_fit_instance_to_host(
                self.host, self.instance1, pci_stats=pci_stats)
        self.assertIsInstance(instance_topology, objects.InstanceNUMATopology)
        self.assertEqual(1, instance_topology.cells[0].id)


class NumberOfSerialPortsTest(test.NoDBTestCase):
    def test_flavor(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048,
                                extra_specs={"hw:serial_port_count": 3})
        image_meta = objects.ImageMeta.from_dict({})
        num_ports = hw.get_number_of_serial_ports(flavor, image_meta)
        self.assertEqual(3, num_ports)

    def test_image_meta(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048, extra_specs={})
        image_meta = objects.ImageMeta.from_dict(
            {"properties": {"hw_serial_port_count": 2}})
        num_ports = hw.get_number_of_serial_ports(flavor, image_meta)
        self.assertEqual(2, num_ports)

    def test_flavor_invalid_value(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048,
                                extra_specs={"hw:serial_port_count": 'foo'})
        image_meta = objects.ImageMeta.from_dict({})
        self.assertRaises(exception.ImageSerialPortNumberInvalid,
                          hw.get_number_of_serial_ports,
                          flavor, image_meta)

    def test_image_meta_smaller_than_flavor(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048,
                                extra_specs={"hw:serial_port_count": 3})
        image_meta = objects.ImageMeta.from_dict(
            {"properties": {"hw_serial_port_count": 2}})
        num_ports = hw.get_number_of_serial_ports(flavor, image_meta)
        self.assertEqual(2, num_ports)

    def test_flavor_smaller_than_image_meta(self):
        flavor = objects.Flavor(vcpus=8, memory_mb=2048,
                                extra_specs={"hw:serial_port_count": 3})
        image_meta = objects.ImageMeta.from_dict(
            {"properties": {"hw_serial_port_count": 4}})
        self.assertRaises(exception.ImageSerialPortNumberExceedFlavorValue,
                          hw.get_number_of_serial_ports,
                          flavor, image_meta)


class VirtMemoryPagesTestCase(test.NoDBTestCase):
    def test_cell_instance_pagesize(self):
        cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024, pagesize=2048)

        self.assertEqual(0, cell.id)
        self.assertEqual(set([0]), cell.cpuset)
        self.assertEqual(1024, cell.memory)
        self.assertEqual(2048, cell.pagesize)

    def test_numa_pagesize_usage_from_cell(self):
        hostcell = objects.NUMACell(
            id=0,
            cpuset=set([0]),
            pcpuset=set(),
            memory=1024,
            cpu_usage=0,
            memory_usage=0,
            pinned_cpus=set(),
            mempages=[objects.NUMAPagesTopology(
                size_kb=2048, total=512, used=0)],
            siblings=[set([0])])
        instcell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=512, pagesize=2048)

        topo = hw._numa_pagesize_usage_from_cell(hostcell, instcell, 1)
        self.assertEqual(2048, topo[0].size_kb)
        self.assertEqual(512, topo[0].total)
        self.assertEqual(256, topo[0].used)

    def _test_get_requested_mempages_pagesize(self, spec=None, props=None):
        flavor = objects.Flavor(vcpus=16, memory_mb=2048,
                                extra_specs=spec or {})
        image_meta = objects.ImageMeta.from_dict({"properties": props or {}})
        return hw._get_numa_pagesize_constraint(flavor, image_meta)

    def test_get_requested_mempages_pagesize_from_flavor_swipe(self):
        self.assertEqual(
            hw.MEMPAGES_SMALL, self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "small"}))

        self.assertEqual(
            hw.MEMPAGES_LARGE, self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "large"}))

        self.assertEqual(
            hw.MEMPAGES_ANY, self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "any"}))

    def test_get_requested_mempages_pagesize_from_flavor_specific(self):
        self.assertEqual(
            2048,
            self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "2048"}))

    def test_get_requested_mempages_pagesize_from_flavor_invalid(self):
        ex = self.assertRaises(
            exception.MemoryPageSizeInvalid,
            self._test_get_requested_mempages_pagesize,
            {"hw:mem_page_size": "foo"})
        self.assertIn("foo", str(ex))

        ex = self.assertRaises(
            exception.MemoryPageSizeInvalid,
            self._test_get_requested_mempages_pagesize,
            {"hw:mem_page_size": "-42"})
        self.assertIn("-42", str(ex))

        ex = self.assertRaises(
            exception.MemoryPageSizeInvalid,
            self._test_get_requested_mempages_pagesize,
            {"hw:mem_page_size": "2M"})
        self.assertIn("2M", str(ex))

    def test_get_requested_mempages_pagesizes_from_flavor_suffix_sweep(self):
        self.assertEqual(
            2048,
            self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "2048KB"}))

        self.assertEqual(
            2048,
            self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "2MB"}))

        self.assertEqual(
            1048576,
            self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "1GB"}))

    def test_get_requested_mempages_pagesize_from_image_flavor_any(self):
        self.assertEqual(
            2048,
            self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "any"},
                props={"hw_mem_page_size": "2048"}))

    def test_get_requested_mempages_pagesize_from_image_flavor_large(self):
        self.assertEqual(
            2048,
            self._test_get_requested_mempages_pagesize(
                spec={"hw:mem_page_size": "large"},
                props={"hw_mem_page_size": "2048"}))

    def test_get_requested_mempages_pagesize_from_image_forbidden(self):
        self.assertRaises(
            exception.MemoryPageSizeForbidden,
            self._test_get_requested_mempages_pagesize,
            {"hw:mem_page_size": "small"},
            {"hw_mem_page_size": "2048"})

    def test_get_requested_mempages_pagesize_from_image_forbidden2(self):
        self.assertRaises(
            exception.MemoryPageSizeForbidden,
            self._test_get_requested_mempages_pagesize,
            {}, {"hw_mem_page_size": "2048"})

    def test_cell_accepts_request_wipe(self):
        host_cell = objects.NUMACell(
            id=0,
            cpuset=set([0]),
            memory=1024,
            mempages=[
                objects.NUMAPagesTopology(size_kb=4, total=262144, used=0),
            ],
            siblings=[set([0])],
            pinned_cpus=set())

        inst_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024, pagesize=hw.MEMPAGES_SMALL)
        self.assertEqual(
            4,
            hw._numa_cell_supports_pagesize_request(host_cell, inst_cell))

        inst_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024, pagesize=hw.MEMPAGES_ANY)
        self.assertEqual(
            4,
            hw._numa_cell_supports_pagesize_request(host_cell, inst_cell))

        inst_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024, pagesize=hw.MEMPAGES_LARGE)
        self.assertIsNone(hw._numa_cell_supports_pagesize_request(
            host_cell, inst_cell))

    def test_cell_accepts_request_large_pass(self):
        inst_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024, pagesize=hw.MEMPAGES_LARGE)
        host_cell = objects.NUMACell(
            id=0,
            cpuset=set([0]),
            memory=1024,
            mempages=[
                objects.NUMAPagesTopology(size_kb=4, total=256, used=0),
                objects.NUMAPagesTopology(size_kb=2048, total=512, used=0)
            ],
            siblings=[set([0])],
            pinned_cpus=set())

        self.assertEqual(
            2048,
            hw._numa_cell_supports_pagesize_request(host_cell, inst_cell))

    def test_cell_accepts_request_custom_pass(self):
        inst_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024, pagesize=2048)
        host_cell = objects.NUMACell(
            id=0,
            cpuset=set([0]),
            memory=1024,
            mempages=[
                objects.NUMAPagesTopology(size_kb=4, total=256, used=0),
                objects.NUMAPagesTopology(size_kb=2048, total=512, used=0)
            ],
            siblings=[set([0])],
            pinned_cpus=set())

        self.assertEqual(
            2048,
            hw._numa_cell_supports_pagesize_request(host_cell, inst_cell))

    def test_cell_accepts_request_remainder_memory(self):
        # Test memory can't be divided with no rem by mempage's size_kb
        inst_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024 + 1, pagesize=2048)
        host_cell = objects.NUMACell(
            id=0,
            cpuset=set([0]),
            memory=1024,
            mempages=[
                objects.NUMAPagesTopology(size_kb=4, total=256, used=0),
                objects.NUMAPagesTopology(size_kb=2048, total=512, used=0)
            ],
            siblings=[set([0])],
            pinned_cpus=set())
        self.assertIsNone(hw._numa_cell_supports_pagesize_request(
            host_cell, inst_cell))

    def test_cell_accepts_request_host_mempages(self):
        # Test pagesize not in host's mempages
        inst_cell = objects.InstanceNUMACell(
            id=0, cpuset=set([0]), memory=1024, pagesize=4096)
        host_cell = objects.NUMACell(
            id=0,
            cpuset=set([0]),
            memory=1024,
            mempages=[
                objects.NUMAPagesTopology(size_kb=4, total=256, used=0),
                objects.NUMAPagesTopology(size_kb=2048, total=512, used=0)
            ],
            siblings=[set([0])],
            pinned_cpus=set())
        self.assertRaises(exception.MemoryPageSizeNotSupported,
                          hw._numa_cell_supports_pagesize_request,
                          host_cell, inst_cell)


class _CPUPinningTestCaseBase(object):
    def assertEqualTopology(self, expected, got):
        for attr in ('sockets', 'cores', 'threads'):
            self.assertEqual(getattr(expected, attr), getattr(got, attr),
                             "Mismatch on %s" % attr)

    def assertInstanceCellPinned(self, instance_cell, cell_ids=None):
        default_cell_id = 0

        self.assertIsNotNone(instance_cell)
        if cell_ids is None:
            self.assertEqual(default_cell_id, instance_cell.id)
        else:
            self.assertIn(instance_cell.id, cell_ids)

        self.assertEqual(len(instance_cell.cpuset),
                         len(instance_cell.cpu_pinning))

    def assertPinningPreferThreads(self, instance_cell, host_cell):
        """Make sure we are preferring threads.

        We do this by assessing that at least 2 CPUs went to the same core
        if that was even possible to begin with.
        """
        max_free_siblings = max(map(len, host_cell.free_siblings))
        if len(instance_cell) > 1 and max_free_siblings > 1:
            cpu_to_sib = {}
            for sib in host_cell.free_siblings:
                for cpu in sib:
                    cpu_to_sib[cpu] = tuple(sorted(sib))
            pins_per_sib = collections.defaultdict(int)
            for inst_p, host_p in instance_cell.cpu_pinning.items():
                pins_per_sib[cpu_to_sib[host_p]] += 1
            self.assertGreater(max(pins_per_sib.values()), 1,
                               "Seems threads were not preferred by the "
                               "pinning logic.")


class CPUPinningCellTestCase(test.NoDBTestCase, _CPUPinningTestCaseBase):
    def test_get_pinning_inst_too_large_cpu(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2]),
            memory=2048,
            memory_usage=0,
            pinned_cpus=set(),
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)],
            siblings=[set([0]), set([1]), set([2])])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                            memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertIsNone(inst_pin)

    def test_get_pinning_inst_too_large_mem(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2]),
            memory=2048,
            memory_usage=1024,
            pinned_cpus=set(),
            mempages=[],
            siblings=[set([0]), set([1]), set([2])])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2]),
                                            memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertIsNone(inst_pin)

    def test_get_pinning_inst_not_avail(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3]),
            memory=2048,
            memory_usage=0,
            pinned_cpus=set([0]),
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)],
            siblings=[set([0]), set([1]), set([2]), set([3])])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                            memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertIsNone(inst_pin)

    def test_get_pinning_no_sibling_fits_empty(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2]),
            memory=2048,
            memory_usage=0,
            pinned_cpus=set(),
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)],
            siblings=[set([0]), set([1]), set([2])])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2]), memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=3, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)
        got_pinning = {x: x for x in range(0, 3)}
        self.assertEqual(got_pinning, inst_pin.cpu_pinning)

    def test_get_pinning_no_sibling_fits_w_usage(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3]),
            memory=2048,
            memory_usage=0,
            pinned_cpus=set([1]),
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)],
            siblings=[set([0]), set([1]), set([2]), set([3])])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2]), memory=1024)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_pinning = {0: 0, 1: 2, 2: 3}
        self.assertEqual(got_pinning, inst_pin.cpu_pinning)

    def test_get_pinning_instance_siblings_fits(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3]),
            memory=2048,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0]), set([1]), set([2]), set([3])],
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]), memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=4, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)
        got_pinning = {x: x for x in range(0, 4)}
        self.assertEqual(got_pinning, inst_pin.cpu_pinning)

    def test_get_pinning_instance_siblings_host_siblings_fits_empty(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3]),
            memory=2048,
            memory_usage=0,
            siblings=[set([0, 1]), set([2, 3])],
            pinned_cpus=set(),
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]), memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=2)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)
        got_pinning = {x: x for x in range(0, 4)}
        self.assertEqual(got_pinning, inst_pin.cpu_pinning)

    def test_get_pinning_instance_siblings_host_siblings_fits_empty_2(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0, 1]), set([2, 3]), set([4, 5]), set([6, 7])],
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3, 4, 5, 6, 7]), memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=4, threads=2)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)
        got_pinning = {x: x for x in range(0, 8)}
        self.assertEqual(got_pinning, inst_pin.cpu_pinning)

    def test_get_pinning_instance_siblings_host_siblings_fits_w_usage(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([1, 2, 5, 6]),
            siblings=[set([0, 1, 2, 3]), set([4, 5, 6, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]), memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=2)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)
        got_pinning = {0: 0, 1: 3, 2: 4, 3: 7}
        self.assertEqual(got_pinning, inst_pin.cpu_pinning)

    def test_get_pinning_host_siblings_fit_single_core(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0, 1, 2, 3]), set([4, 5, 6, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                            memory=2048)

        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=1, threads=4)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)
        got_pinning = {x: x for x in range(0, 4)}
        self.assertEqual(got_pinning, inst_pin.cpu_pinning)

    def test_get_pinning_host_siblings_fit(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0, 1]), set([2, 3])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                            memory=2048)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=2)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)
        got_pinning = {x: x for x in range(0, 4)}
        self.assertEqual(got_pinning, inst_pin.cpu_pinning)

    def test_get_pinning_require_policy_no_siblings(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set(range(0, 8)),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([x]) for x in range(0, 8)],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.REQUIRE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertIsNone(inst_pin)

    def test_get_pinning_require_policy_too_few_siblings(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([0, 1, 2]),
            siblings=[set([0, 4]), set([1, 5]), set([2, 6]), set([3, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.REQUIRE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertIsNone(inst_pin)

    def test_get_pinning_require_policy_fits(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0, 1]), set([2, 3])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.REQUIRE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=2)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    def test_get_pinning_require_policy_fits_w_usage(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([0, 1]),
            siblings=[set([0, 4]), set([1, 5]), set([2, 6]), set([3, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1, 2, 3]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.REQUIRE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=2)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    def test_get_pinning_host_siblings_instance_odd_fit(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0, 1]), set([2, 3]), set([4, 5]), set([6, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3, 4]),
                                            memory=2048)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=5, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    def test_get_pinning_host_siblings_instance_fit_optimize_threads(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0, 1, 2, 3]), set([4, 5, 6, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3, 4, 5]),
                                            memory=2048)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=3, threads=2)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    def test_get_pinning_host_siblings_instance_odd_fit_w_usage(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([0, 2, 5]),
            siblings=[set([0, 1]), set([2, 3]), set([4, 5]), set([6, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2]),
                                            memory=2048)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=3, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    def test_get_pinning_host_siblings_instance_mixed_siblings(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([0, 1, 2, 5]),
            siblings=[set([0, 1]), set([2, 3]), set([4, 5]), set([6, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                            memory=2048)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=4, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    def test_get_pinning_host_siblings_instance_odd_fit_orphan_only(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([0, 2, 5, 6]),
            siblings=[set([0, 1]), set([2, 3]), set([4, 5]), set([6, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3]),
                                            memory=2048)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=4, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    def test_get_pinning_host_siblings_large_instance_odd_fit(self):
        host_pin = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                         15]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0, 8]), set([1, 9]), set([2, 10]), set([3, 11]),
                      set([4, 12]), set([5, 13]), set([6, 14]), set([7, 15])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(cpuset=set([0, 1, 2, 3, 4]),
                                            memory=2048)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        self.assertPinningPreferThreads(inst_pin, host_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=5, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    def test_get_pinning_isolate_policy_too_few_fully_free_cores(self):
        host_pin = objects.NUMACell(
            id=0,
            # Simulate a legacy host with vcpu_pin_set configuration,
            # meaning cpuset == pcpuset
            cpuset=set([0, 1, 2, 3]),
            pcpuset=set([0, 1, 2, 3]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([1]),
            siblings=[set([0, 1]), set([2, 3])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertIsNone(inst_pin)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    def test_get_pinning_isolate_policy_no_fully_free_cores(self):
        host_pin = objects.NUMACell(
            id=0,
            # Simulate a legacy host with vcpu_pin_set configuration,
            # meaning cpuset == pcpuset
            cpuset=set([0, 1, 2, 3]),
            pcpuset=set([0, 1, 2, 3]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([1, 2]),
            siblings=[set([0, 1]), set([2, 3])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertIsNone(inst_pin)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    def test_get_pinning_isolate_policy_fits(self):
        host_pin = objects.NUMACell(
            id=0,
            # Simulate a legacy host with vcpu_pin_set configuration,
            # meaning cpuset == pcpuset
            cpuset=set([0, 1, 2, 3]),
            pcpuset=set([0, 1, 2, 3]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0]), set([1]), set([2]), set([3])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    def test_get_pinning_isolate_policy_fits_ht_host(self):
        host_pin = objects.NUMACell(
            id=0,
            # Simulate a legacy host with vcpu_pin_set configuration,
            # meaning cpuset == pcpuset
            cpuset=set([0, 1, 2, 3]),
            pcpuset=set([0, 1, 2, 3]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0, 1]), set([2, 3])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    def test_get_pinning_isolate_policy_fits_w_usage(self):
        host_pin = objects.NUMACell(
            id=0,
            # Simulate a legacy host with vcpu_pin_set configuration,
            # meaning cpuset == pcpuset
            cpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            pcpuset=set([0, 1, 2, 3, 4, 5, 6, 7]),
            memory=4096,
            memory_usage=0,
            pinned_cpus=set([0, 1]),
            siblings=[set([0, 4]), set([1, 5]), set([2, 6]), set([3, 7])],
            mempages=[])
        inst_pin = objects.InstanceNUMACell(
                cpuset=set([0, 1]),
                memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE)
        inst_pin = hw._numa_fit_instance_cell_with_pinning(host_pin, inst_pin)
        self.assertInstanceCellPinned(inst_pin)
        got_topo = objects.VirtCPUTopology(sockets=1, cores=2, threads=1)
        self.assertEqualTopology(got_topo, inst_pin.cpu_topology)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    @mock.patch.object(hw, 'LOG')
    def test_get_pinning_isolate_policy_bug_1889633(self, mock_log):
        host_pin = objects.NUMACell(
            id=0,
            cpuset={0, 1, 4, 5},
            pcpuset={2, 3, 6, 7},
            memory=4096,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[{0, 4}, {1, 5}, {2, 6}, {3, 7}],
            mempages=[],
        )
        inst_pin = objects.InstanceNUMACell(
            cpuset=set(),
            pcpuset={0, 1},
            memory=2048,
            cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
            cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE,
        )
        limits = objects.NUMATopologyLimits(
            cpu_allocation_ratio=2, ram_allocation_ratio=2,
        )

        # host has hyperthreads, which means no NUMA topology should be built
        inst_topo = hw._numa_fit_instance_cell(host_pin, inst_pin, limits)
        self.assertIsNone(inst_topo)
        self.assertIn(
            'Host supports hyperthreads, but instance requested no',
            mock_log.warning.call_args[0][0],
        )


class CPUPinningTestCase(test.NoDBTestCase, _CPUPinningTestCaseBase):
    def test_host_numa_fit_instance_to_host_single_cell(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([0]), set([1])]),
            objects.NUMACell(
                id=1,
                cpuset=set(),
                pcpuset=set([2, 3]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([2]), set([3])])
        ])
        inst_topo = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    cpuset=set([0, 1]), memory=2048,
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)

        for cell in inst_topo.cells:
            self.assertInstanceCellPinned(cell, cell_ids=(0, 1))

    # TODO(stephenfin): Remove in U
    def test_host_numa_fit_instance_to_host_legacy_object(self):
        """Check that we're able to fit an instance NUMA topology to a legacy
        host NUMA topology that doesn't have the 'pcpuset' field present.
        """
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set([0, 1]),
                # we are explicitly not setting pcpuset here
                memory=2048,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([0]), set([1])]),
            objects.NUMACell(
                id=1,
                cpuset=set([2, 3]),
                # we are explicitly not setting pcpuset here
                memory=2048,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([2]), set([3])])
        ])
        inst_topo = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(
                cpuset=set([0, 1]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)

        for cell in inst_topo.cells:
            self.assertInstanceCellPinned(cell, cell_ids=(0, 1))

    def test_host_numa_fit_instance_to_host_single_cell_w_usage(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set([0]),
                mempages=[],
                siblings=[set([0]), set([1])]),
            objects.NUMACell(
                id=1,
                cpuset=set(),
                pcpuset=set([2, 3]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([2]), set([3])])
        ])
        inst_topo = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    cpuset=set([0, 1]), memory=2048,
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)

        for cell in inst_topo.cells:
            self.assertInstanceCellPinned(cell, cell_ids=(1,))

    def test_host_numa_fit_instance_to_host_single_cell_fail(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set([0]),
                mempages=[],
                siblings=[set([0]), set([1])]),
            objects.NUMACell(
                id=1,
                cpuset=set(),
                pcpuset=set([2, 3]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set([2]),
                mempages=[],
                siblings=[set([2]), set([3])])
        ])
        inst_topo = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    cpuset=set([0, 1]), memory=2048,
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertIsNone(inst_topo)

    def test_host_numa_fit_instance_to_host_fit(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([0]), set([1]), set([2]), set([3])]),
            objects.NUMACell(
                id=1,
                cpuset=set(),
                pcpuset=set([4, 5, 6, 7]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([4]), set([5]), set([6]), set([7])])
        ])
        inst_topo = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                            cpuset=set([0, 1]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
                       objects.InstanceNUMACell(
                            cpuset=set([2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)

        for cell in inst_topo.cells:
            self.assertInstanceCellPinned(cell, cell_ids=(0, 1))

    def test_host_numa_fit_instance_to_host_barely_fit(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set([0]),
                mempages=[],
                siblings=[set([0]), set([1]), set([2]), set([3])]),
            objects.NUMACell(
                id=1,
                cpuset=set(),
                pcpuset=set([4, 5, 6, 7]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set([4, 5, 6]),
                mempages=[],
                siblings=[set([4]), set([5]), set([6]), set([7])]),
            objects.NUMACell(
                id=2,
                cpuset=set(),
                pcpuset=set([8, 9, 10, 11]),
                memory=2048,
                memory_usage=0,
                pinned_cpus=set([10, 11]),
                mempages=[],
                siblings=[set([8]), set([9]), set([10]), set([11])])
        ])

        inst_topo = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                            cpuset=set([0, 1]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
                       objects.InstanceNUMACell(
                            cpuset=set([2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)

        for cell in inst_topo.cells:
            self.assertInstanceCellPinned(cell, cell_ids=(0, 2))

    def test_host_numa_fit_instance_to_host_fail_capacity(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                memory_usage=0,
                pinned_cpus=set([0]),
                mempages=[],
                siblings=[set([0]), set([1]), set([2]), set([3])]),
            objects.NUMACell(
                id=1,
                cpuset=set(),
                pcpuset=set([4, 5, 6, 7]),
                memory=4096,
                memory_usage=0,
                pinned_cpus=set([4, 5, 6]),
                mempages=[],
                siblings=[set([4]), set([5]), set([6]), set([7])])
        ])
        inst_topo = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                            cpuset=set([0, 1]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
                       objects.InstanceNUMACell(
                            cpuset=set([2, 3]), memory=2048,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertIsNone(inst_topo)

    def test_host_numa_fit_instance_to_host_fail_topology(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([0]), set([1]), set([2]), set([3])]),
            objects.NUMACell(
                id=1,
                cpuset=set(),
                pcpuset=set([4, 5, 6, 7]),
                memory=4096,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([4]), set([5]), set([6]), set([7])])
        ])
        inst_topo = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                            cpuset=set([0, 1]), memory=1024,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
                       objects.InstanceNUMACell(
                            cpuset=set([2, 3]), memory=1024,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
                       objects.InstanceNUMACell(
                            cpuset=set([4, 5]), memory=1024,
                            cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertIsNone(inst_topo)

    def test_cpu_pinning_usage_from_instances(self):
        host_pin = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([0]), set([1]), set([2]), set([3])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_pin_1 = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    cpuset=set([0, 1]), id=0, memory=2048,
                    cpu_pinning={0: 0, 1: 3},
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
        inst_pin_2 = objects.InstanceNUMATopology(
                cells = [objects.InstanceNUMACell(
                    cpuset=set([0, 1]), id=0, memory=2048,
                    cpu_pinning={0: 1, 1: 2},
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        host_pin = hw.numa_usage_from_instance_numa(host_pin, inst_pin_1)
        host_pin = hw.numa_usage_from_instance_numa(host_pin, inst_pin_2)
        self.assertEqual(set([0, 1, 2, 3]),
                         host_pin.cells[0].pinned_cpus)

    def test_cpu_pinning_usage_from_instances_free(self):
        host_pin = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set([0, 1, 3]),
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)],
                siblings=[set([0]), set([1]), set([2]), set([3])])])
        inst_pin_1 = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(
                cpuset=set([0]), memory=1024, cpu_pinning={0: 1}, id=0,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
        inst_pin_2 = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(
                cpuset=set([0, 1]), memory=1024, id=0,
                cpu_pinning={0: 0, 1: 3},
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
        host_pin = hw.numa_usage_from_instance_numa(host_pin, inst_pin_1,
                                                    free=True)
        host_pin = hw.numa_usage_from_instance_numa(host_pin, inst_pin_2,
                                                    free=True)
        self.assertEqual(set(), host_pin.cells[0].pinned_cpus)

    def test_host_usage_from_instances_fail(self):
        host_pin = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([0]), set([1]), set([2]), set([3])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_pin_1 = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    cpuset=set([0, 1]), memory=2048, id=0,
                    cpu_pinning={0: 0, 1: 3},
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])
        inst_pin_2 = objects.InstanceNUMATopology(
                cells = [objects.InstanceNUMACell(
                    cpuset=set([0, 1]), id=0, memory=2048,
                    cpu_pinning={0: 0, 1: 2},
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        host_pin = hw.numa_usage_from_instance_numa(host_pin, inst_pin_1)
        self.assertRaises(exception.CPUPinningInvalid,
                hw.numa_usage_from_instance_numa, host_pin, inst_pin_2)

    def test_host_usage_from_instances_isolate(self):
        host_pin = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([0, 2]), set([1, 3])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_pin_1 = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    cpuset=set([0, 1]), memory=2048, id=0,
                    cpu_pinning={0: 0, 1: 1},
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                    cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE
                    )])

        new_cell = hw.numa_usage_from_instance_numa(host_pin, inst_pin_1)
        self.assertEqual(host_pin.cells[0].pcpuset,
                         new_cell.cells[0].pinned_cpus)
        self.assertEqual(0, new_cell.cells[0].cpu_usage)

    def test_host_usage_from_instances_isolate_free(self):
        host_pin = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set([0, 1, 2, 3]),
                siblings=[set([0, 2]), set([1, 3])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_pin_1 = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    cpuset=set([0, 1]), memory=2048, id=0,
                    cpu_pinning={0: 0, 1: 1},
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                    cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE
                    )])

        new_cell = hw.numa_usage_from_instance_numa(host_pin, inst_pin_1,
                                                   free=True)
        self.assertEqual(set([]), new_cell.cells[0].pinned_cpus)
        self.assertEqual(0, new_cell.cells[0].cpu_usage)

    def test_host_usage_from_instances_isolated_without_siblings(self):
        host_pin = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([0]), set([1]), set([2]), set([3])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_pin = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(
                cpuset=set([0, 1, 2]), memory=2048, id=0,
                cpu_pinning={0: 0, 1: 1, 2: 2},
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE
            )])

        new_cell = hw.numa_usage_from_instance_numa(host_pin, inst_pin)
        self.assertEqual(inst_pin.cells[0].cpuset,
                         new_cell.cells[0].pinned_cpus)
        self.assertEqual(0, new_cell.cells[0].cpu_usage)

    def test_host_usage_from_instances_isolated_without_siblings_free(self):
        host_pin = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1, 2, 3]),
                memory=4096,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set([0, 1, 2, 3]),
                siblings=[set([0]), set([1]), set([2]), set([3])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_pin = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    cpuset=set([0, 1, 3]), memory=2048, id=0,
                    cpu_pinning={0: 0, 1: 1, 2: 2},
                    cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                    cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE
                )])

        new_cell = hw.numa_usage_from_instance_numa(host_pin, inst_pin,
                                                    free=True)
        self.assertEqual(set([3]), new_cell.cells[0].pinned_cpus)
        self.assertEqual(0, new_cell.cells[0].cpu_usage)


class CPUSReservedCellTestCase(test.NoDBTestCase):
    def _test_reserved(self, reserved):
        host_cell = objects.NUMACell(
            id=0,
            cpuset=set(),
            pcpuset=set([0, 1, 2]),
            memory=2048,
            memory_usage=0,
            pinned_cpus=set(),
            siblings=[set([0]), set([1]), set([2])],
            mempages=[objects.NUMAPagesTopology(
                size_kb=4, total=524288, used=0)])
        inst_cell = objects.InstanceNUMACell(cpuset=set([0, 1]), memory=2048)
        return hw._numa_fit_instance_cell_with_pinning(
            host_cell, inst_cell, reserved)

    def test_no_reserved(self):
        inst_cell = self._test_reserved(reserved=0)
        self.assertEqual(set([0, 1]), inst_cell.cpuset)
        self.assertIsNone(inst_cell.cpuset_reserved)

    def test_reserved(self):
        inst_cell = self._test_reserved(reserved=1)
        self.assertEqual(set([0, 1]), inst_cell.cpuset)
        self.assertEqual(set([2]), inst_cell.cpuset_reserved)

    def test_reserved_exceeded(self):
        inst_cell = self._test_reserved(reserved=2)
        self.assertIsNone(inst_cell)


class CPURealtimeTestCase(test.NoDBTestCase):
    def test_success_flavor(self):
        flavor = objects.Flavor(vcpus=3, memory_mb=2048,
                                extra_specs={"hw:cpu_realtime_mask": "^1"})
        image = objects.ImageMeta.from_dict({})
        rt = hw.vcpus_realtime_topology(flavor, image)
        self.assertEqual(set([0, 2]), rt)

    def test_success_image(self):
        flavor = objects.Flavor(vcpus=3, memory_mb=2048,
                                extra_specs={"hw:cpu_realtime_mask": "^1"})
        image = objects.ImageMeta.from_dict(
            {"properties": {"hw_cpu_realtime_mask": "^0-1"}})
        rt = hw.vcpus_realtime_topology(flavor, image)
        self.assertEqual(set([2]), rt)

    def test_no_mask_configured(self):
        flavor = objects.Flavor(vcpus=3, memory_mb=2048,
                                extra_specs={})
        image = objects.ImageMeta.from_dict({"properties": {}})
        self.assertRaises(
            exception.RealtimeMaskNotFoundOrInvalid,
            hw.vcpus_realtime_topology, flavor, image)

    def test_mask_badly_configured(self):
        flavor = objects.Flavor(vcpus=3, memory_mb=2048,
                                extra_specs={"hw:cpu_realtime_mask": "^0-2"})
        image = objects.ImageMeta.from_dict({"properties": {}})
        self.assertRaises(
            exception.RealtimeMaskNotFoundOrInvalid,
            hw.vcpus_realtime_topology, flavor, image)


class EmulatorThreadsTestCase(test.NoDBTestCase):

    @staticmethod
    def _host_topology():
        return objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([0, 1]),
                memory=2048,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([0]), set([1])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)]),
            objects.NUMACell(
                id=1,
                cpuset=set(),
                pcpuset=set([2, 3]),
                memory=2048,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([2]), set([3])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])

    def test_single_node_not_defined(self):
        host_topo = self._host_topology()
        inst_topo = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertEqual({0: 0}, inst_topo.cells[0].cpu_pinning)
        self.assertIsNone(inst_topo.cells[0].cpuset_reserved)

    def test_single_node_shared(self):
        host_topo = self._host_topology()
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.SHARE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertEqual({0: 0}, inst_topo.cells[0].cpu_pinning)
        self.assertIsNone(inst_topo.cells[0].cpuset_reserved)

    def test_single_node_isolate(self):
        host_topo = self._host_topology()
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertEqual({0: 0}, inst_topo.cells[0].cpu_pinning)
        self.assertEqual(set([1]), inst_topo.cells[0].cpuset_reserved)

    def test_single_node_isolate_exceeded(self):
        host_topo = self._host_topology()
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0, 1, 2, 4]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertIsNone(inst_topo)

    def test_multi_nodes_isolate(self):
        host_topo = self._host_topology()
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
            objects.InstanceNUMACell(
                id=1,
                cpuset=set([1]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertEqual({0: 0}, inst_topo.cells[0].cpu_pinning)
        self.assertEqual(set([1]), inst_topo.cells[0].cpuset_reserved)
        self.assertEqual({1: 2}, inst_topo.cells[1].cpu_pinning)
        self.assertIsNone(inst_topo.cells[1].cpuset_reserved)

    def test_multi_nodes_isolate_exceeded(self):
        host_topo = self._host_topology()
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0, 1]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
            objects.InstanceNUMACell(
                id=1,
                cpuset=set([2]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        # The guest NUMA node 0 is requesting 2pCPUs + 1 additional
        # pCPU for emulator threads, the host can't handle the
        # request.
        self.assertIsNone(inst_topo)

    def test_multi_nodes_isolate_full_usage(self):
        host_topo = self._host_topology()
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED),
            objects.InstanceNUMACell(
                id=1,
                cpuset=set([1, 2]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertEqual({0: 0}, inst_topo.cells[0].cpu_pinning)
        self.assertEqual(set([1]), inst_topo.cells[0].cpuset_reserved)
        self.assertEqual({1: 2, 2: 3}, inst_topo.cells[1].cpu_pinning)
        self.assertIsNone(inst_topo.cells[1].cpuset_reserved)

    def test_isolate_usage(self):
        host_topo = self._host_topology()
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_pinning={0: 0},
                cpuset_reserved=set([1]))])

        host_topo = hw.numa_usage_from_instance_numa(host_topo, inst_topo)

        self.assertEqual(set([0, 1]), host_topo.cells[0].pinned_cpus)
        self.assertEqual(set([]), host_topo.cells[1].pinned_cpus)

    def test_isolate_full_usage(self):
        host_topo = self._host_topology()
        inst_topo1 = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_pinning={0: 0},
                cpuset_reserved=set([1]))])
        inst_topo2 = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=1,
                cpuset=set([0]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_pinning={0: 2},
                cpuset_reserved=set([3]))])

        host_topo = hw.numa_usage_from_instance_numa(host_topo, inst_topo1)
        host_topo = hw.numa_usage_from_instance_numa(host_topo, inst_topo2)

        self.assertEqual(set([0, 1]), host_topo.cells[0].pinned_cpus)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    def test_isolate_w_isolate_thread_alloc(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                # Simulate a legacy host with vcpu_pin_set configuration,
                # meaning cpuset == pcpuset
                cpuset=set([0, 1, 2, 3, 4, 5]),
                pcpuset=set([0, 1, 2, 3, 4, 5]),
                memory=2048,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([0, 1]), set([2, 3]), set([4, 5])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0, 1]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE
                )])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertEqual({0: 0, 1: 2}, inst_topo.cells[0].cpu_pinning)
        self.assertEqual(set([4]), inst_topo.cells[0].cpuset_reserved)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    def test_isolate_w_isolate_thread_alloc_usage(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                # Simulate a legacy host with vcpu_pin_set configuration,
                # meaning cpuset == pcpuset
                cpuset=set([0, 1, 2, 3, 4, 5]),
                pcpuset=set([0, 1, 2, 3, 4, 5]),
                memory=2048,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set([0]),
                siblings=[set([0, 1]), set([2, 3]), set([4, 5])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0, 1]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE
                )])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)

        self.assertEqual({0: 2, 1: 4}, inst_topo.cells[0].cpu_pinning)
        self.assertEqual(set([1]), inst_topo.cells[0].cpuset_reserved)

    def test_asymmetric_host(self):
        """Validate behavior with an asymmetric host topology.

        The host has three cores, two of which are siblings, and the guest
        requires all three of these - two for vCPUs and one for emulator
        threads. Ensure that the sibling-ness of the cores is ignored if
        necessary.
        """
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                cpuset=set(),
                pcpuset=set([1, 2, 3]),
                memory=2048,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([1]), set([2, 3])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=(
                fields.CPUEmulatorThreadsPolicy.ISOLATE),
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0, 1]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED)])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)
        self.assertEqual({0: 2, 1: 3}, inst_topo.cells[0].cpu_pinning)
        self.assertEqual(set([1]), inst_topo.cells[0].cpuset_reserved)

    # TODO(stephenfin): Remove when we drop support for vcpu_pin_set
    def test_asymmetric_host_w_isolate_thread_alloc(self):
        host_topo = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=0,
                # Simulate a legacy host with vcpu_pin_set configuration,
                # meaning cpuset == pcpuset
                cpuset=set([1, 2, 3, 4, 5]),
                pcpuset=set([1, 2, 3, 4, 5]),
                memory=2048,
                cpu_usage=0,
                memory_usage=0,
                pinned_cpus=set(),
                siblings=[set([1]), set([2, 3]), set([4, 5])],
                mempages=[objects.NUMAPagesTopology(
                    size_kb=4, total=524288, used=0)])])
        inst_topo = objects.InstanceNUMATopology(
            emulator_threads_policy=fields.CPUEmulatorThreadsPolicy.ISOLATE,
            cells=[objects.InstanceNUMACell(
                id=0,
                cpuset=set([0, 1]), memory=2048,
                cpu_policy=fields.CPUAllocationPolicy.DEDICATED,
                cpu_thread_policy=fields.CPUThreadAllocationPolicy.ISOLATE
                )])

        inst_topo = hw.numa_fit_instance_to_host(host_topo, inst_topo)

        self.assertEqual({0: 2, 1: 4}, inst_topo.cells[0].cpu_pinning)
        self.assertEqual(set([1]), inst_topo.cells[0].cpuset_reserved)


class NetworkRequestSupportTestCase(test.NoDBTestCase):
    """Validate behavior of '_numa_cells_support_network_metadata'."""

    def setUp(self):
        super(NetworkRequestSupportTestCase, self).setUp()

        self.network_a = objects.NetworkMetadata(
            physnets=set(['foo', 'bar']), tunneled=False)
        self.network_b = objects.NetworkMetadata(
            physnets=set(), tunneled=True)

        self.host = objects.NUMATopology(cells=[
            objects.NUMACell(
                id=1,
                cpuset=set([1, 2]),
                memory=4096,
                cpu_usage=2,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([1]), set([2])],
                network_metadata=self.network_a),
            objects.NUMACell(
                id=2,
                cpuset=set([3, 4]),
                memory=4096,
                cpu_usage=2,
                memory_usage=0,
                pinned_cpus=set(),
                mempages=[],
                siblings=[set([3]), set([4])],
                network_metadata=self.network_b)])

        self.instance = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([1, 2]),
                                     memory=2048)])

    def test_no_required_networks(self):
        """Validate behavior if the user doesn't request networks.

        No networks == no affinity to worry about.
        """
        network_metadata = objects.NetworkMetadata(
            physnets=set(), tunneled=False)
        supports = hw._numa_cells_support_network_metadata(
            self.host, [self.host.cells[0]], network_metadata)
        self.assertTrue(supports)

    def test_missing_networks(self):
        """Validate behavior with a physical network without affinity.

        If we haven't recorded NUMA affinity for a given physical network, we
        clearly shouldn't fail to build.
        """
        network_metadata = objects.NetworkMetadata(
            physnets=set(['baz']), tunneled=False)
        supports = hw._numa_cells_support_network_metadata(
            self.host, [self.host.cells[0]], network_metadata)
        self.assertTrue(supports)

    def test_physnet_networks(self):
        """Validate behavior with a single physical network."""
        network_metadata = objects.NetworkMetadata(
            physnets=set(['foo']), tunneled=False)

        # The required network is affined to host NUMA node 0 so this should
        # pass
        supports = hw._numa_cells_support_network_metadata(
            self.host, [self.host.cells[0]], network_metadata)
        self.assertTrue(supports)

        # ...while it should fail for the other host NUMA node
        supports = hw._numa_cells_support_network_metadata(
            self.host, [self.host.cells[1]], network_metadata)
        self.assertFalse(supports)

        # ...but it will pass if we chose both host NUMA nodes
        supports = hw._numa_cells_support_network_metadata(
            self.host, self.host.cells, network_metadata)
        self.assertTrue(supports)

    def test_tunnel_network(self):
        """Validate behavior with a single tunneled network.

        Neutron currently only allows a single tunnel provider network so this
        is realistic anyway.
        """
        network_metadata = objects.NetworkMetadata(
            physnets=set(), tunneled=True)

        # The required network is affined to host NUMA node 1 so this should
        # fail
        supports = hw._numa_cells_support_network_metadata(
            self.host, [self.host.cells[0]], network_metadata)
        self.assertFalse(supports)

        # ...but it will pass for the other host NUMA node
        supports = hw._numa_cells_support_network_metadata(
            self.host, [self.host.cells[1]], network_metadata)
        self.assertTrue(supports)

    def test_multiple_networks(self):
        """Validate behavior with multiple networks.

        If we request multiple networks that are spread across host NUMA
        nodes, we're going to need to use multiple host instances.
        """
        network_metadata = objects.NetworkMetadata(
            physnets=set(['foo', 'bar']), tunneled=True)

        # Because the requested networks are spread across multiple host nodes,
        # this should fail because no single node can satisfy the request
        supports = hw._numa_cells_support_network_metadata(
            self.host, [self.host.cells[0]], network_metadata)
        self.assertFalse(supports)
        supports = hw._numa_cells_support_network_metadata(
            self.host, [self.host.cells[1]], network_metadata)
        self.assertFalse(supports)

        # ...but it will pass if we provide all necessary nodes
        supports = hw._numa_cells_support_network_metadata(
            self.host, self.host.cells, network_metadata)
        self.assertTrue(supports)


class MemEncryptionNotRequiredTestCase(test.NoDBTestCase):
    def _test_encrypted_memory_support_not_required(self, flavor=None,
                                                    image_meta=None):
        if flavor is None:
            flavor = objects.Flavor(extra_specs={})

        if image_meta is None:
            image_meta = objects.ImageMeta(properties=objects.ImageMetaProps())

        self.assertFalse(hw.get_mem_encryption_constraint(flavor, image_meta))

    def test_requirement_disabled(self):
        self._test_encrypted_memory_support_not_required()

    def test_require_false_extra_spec(self):
        for extra_spec in ('0', 'false', 'False'):
            self._test_encrypted_memory_support_not_required(
                objects.Flavor(extra_specs={'hw:mem_encryption': extra_spec})
            )

    def test_require_false_image_prop(self):
        for image_prop in ('0', 'false', 'False'):
            self._test_encrypted_memory_support_not_required(
                image_meta=objects.ImageMeta(
                    properties=objects.ImageMetaProps(
                        hw_mem_encryption=image_prop))
            )

    def test_require_both_false(self):
        for extra_spec in ('0', 'false', 'False'):
            for image_prop in ('0', 'false', 'False'):
                self._test_encrypted_memory_support_not_required(
                    objects.Flavor(
                        extra_specs={'hw:mem_encryption': extra_spec}),
                    objects.ImageMeta(
                        properties=objects.ImageMetaProps(
                            hw_mem_encryption=image_prop))
                )


class MemEncryptionFlavorImageConflictTestCase(test.NoDBTestCase):
    def _test_encrypted_memory_support_conflict(self, extra_spec,
                                                image_prop_in, image_prop_out):
        # NOTE(aspiers): hw_mem_encryption image property is a
        # FlexibleBooleanField, so the result should always be coerced
        # to a boolean.
        self.assertIsInstance(image_prop_out, bool)

        flavor_name = 'm1.faketiny'
        image_name = 'fakecirros'
        flavor = objects.Flavor(
            name=flavor_name,
            extra_specs={'hw:mem_encryption': extra_spec}
        )
        image_meta = objects.ImageMeta(
            name=image_name,
            properties=objects.ImageMetaProps(
                hw_mem_encryption=image_prop_in)
        )

        error = (
            "Flavor %(flavor_name)s has hw:mem_encryption extra spec "
            "explicitly set to %(flavor_val)s, conflicting with "
            "image %(image_name)s which has hw_mem_encryption property "
            "explicitly set to %(image_val)s"
        )
        exc = self.assertRaises(
            exception.FlavorImageConflict,
            hw.get_mem_encryption_constraint,
            flavor, image_meta
        )
        error_data = {
            'flavor_name': flavor_name,
            'flavor_val': extra_spec,
            'image_name': image_name,
            'image_val': image_prop_out,
        }
        self.assertEqual(error % error_data, str(exc))

    def test_require_encrypted_memory_support_conflict1(self):
        for extra_spec in ('0', 'false', 'False'):
            for image_prop_in in ('1', 'true', 'True'):
                self._test_encrypted_memory_support_conflict(
                    extra_spec, image_prop_in, True
                )

    def test_require_encrypted_memory_support_conflict2(self):
        for extra_spec in ('1', 'true', 'True'):
            for image_prop_in in ('0', 'false', 'False'):
                self._test_encrypted_memory_support_conflict(
                    extra_spec, image_prop_in, False
                )


class MemEncryptionRequestedInvalidImagePropsTestCase(test.NoDBTestCase):
    flavor_name = 'm1.faketiny'
    image_name = 'fakecirros'
    image_id = '7ec4448e-f3fd-44b1-b172-9a7980f0f29f'

    def _test_encrypted_memory_support_raises(self, enc_extra_spec,
                                              enc_image_prop, image_props,
                                              error_data):
        extra_specs = {}
        if enc_extra_spec:
            extra_specs['hw:mem_encryption'] = enc_extra_spec
        flavor = objects.Flavor(name=self.flavor_name, extra_specs=extra_specs)
        if enc_image_prop:
            image_props['hw_mem_encryption'] = enc_image_prop
        image_meta = fake_image_obj(
            {'id': self.image_id, 'name': self.image_name},
            {}, image_props)
        exc = self.assertRaises(self.expected_exception,
                                hw.get_mem_encryption_constraint,
                                flavor, image_meta)
        self.assertEqual(self.expected_error % error_data, str(exc))


class MemEncryptionRequestedWithoutUEFITestCase(
        MemEncryptionRequestedInvalidImagePropsTestCase):
    expected_exception = exception.FlavorImageConflict
    expected_error = (
        "Memory encryption requested by %(requesters)s but image "
        "%(image_name)s doesn't have 'hw_firmware_type' property "
        "set to 'uefi'"
    )

    def _test_encrypted_memory_support_no_uefi(self, enc_extra_spec,
                                               enc_image_prop, requesters):
        error_data = {'requesters': requesters,
                      'image_name': self.image_name}
        for image_props in ({},
                            {'hw_machine_type': 'q35'},
                            {'hw_firmware_type': 'bios'},
                            {'hw_machine_type': 'q35',
                             'hw_firmware_type': 'bios'}):
            self._test_encrypted_memory_support_raises(enc_extra_spec,
                                                       enc_image_prop,
                                                       image_props, error_data)

    def test_flavor_requires_encrypted_memory_support_no_uefi(self):
        for extra_spec in ('1', 'true', 'True'):
            self._test_encrypted_memory_support_no_uefi(
                extra_spec, None,
                "hw:mem_encryption extra spec in %s flavor" % self.flavor_name)

    def test_image_requires_encrypted_memory_support_no_uefi(self):
        for image_prop in ('1', 'true', 'True'):
            self._test_encrypted_memory_support_no_uefi(
                None, image_prop,
                "hw_mem_encryption property of image %s" % self.image_name)

    def test_flavor_image_require_encrypted_memory_support_no_uefi(self):
        for extra_spec in ('1', 'true', 'True'):
            for image_prop in ('1', 'true', 'True'):
                self._test_encrypted_memory_support_no_uefi(
                    extra_spec, image_prop,
                    "hw:mem_encryption extra spec in %s flavor and "
                    "hw_mem_encryption property of image %s"
                    % (self.flavor_name, self.image_name))


class MemEncryptionRequestedWithInvalidMachineTypeTestCase(
       MemEncryptionRequestedInvalidImagePropsTestCase):
    expected_exception = exception.InvalidMachineType
    expected_error = (
        "Machine type '%(mtype)s' is not compatible with image %(image_name)s "
        "(%(image_id)s): q35 type is required for SEV to work")

    def _test_encrypted_memory_support_pc(self, enc_extra_spec,
                                              enc_image_prop):
        error_data = {'image_id': self.image_id,
                      'image_name': self.image_name,
                      'mtype': 'pc'}
        image_props = {'hw_firmware_type': 'uefi',
                       'hw_machine_type': 'pc'}
        self._test_encrypted_memory_support_raises(enc_extra_spec,
                                                   enc_image_prop,
                                                   image_props, error_data)

    def test_flavor_requires_encrypted_memory_support_pc(self):
        for extra_spec in ('1', 'true', 'True'):
            self._test_encrypted_memory_support_pc(extra_spec, None)

    def test_image_requires_encrypted_memory_support_pc(self):
        for image_prop in ('1', 'true', 'True'):
            self._test_encrypted_memory_support_pc(None, image_prop)

    def test_flavor_image_require_encrypted_memory_support_pc(self):
        for extra_spec in ('1', 'true', 'True'):
            for image_prop in ('1', 'true', 'True'):
                self._test_encrypted_memory_support_pc(
                    extra_spec, image_prop)


class MemEncryptionRequiredTestCase(test.NoDBTestCase):
    flavor_name = "m1.faketiny"
    image_name = 'fakecirros'
    image_id = '8a71a380-be23-47eb-9e72-9998586a0268'

    @mock.patch.object(hw, 'LOG')
    def _test_encrypted_memory_support_required(self, extra_specs,
                                                image_props,
                                                requesters, mock_log):
        image_props['hw_firmware_type'] = 'uefi'

        def _test_get_mem_encryption_constraint():
            flavor = objects.Flavor(name=self.flavor_name,
                                    extra_specs=extra_specs)
            image_meta = objects.ImageMeta.from_dict({
                'id': self.image_id,
                'name': self.image_name,
                'properties': image_props})
            self.assertTrue(hw.get_mem_encryption_constraint(flavor,
                                                             image_meta))
            mock_log.debug.assert_has_calls([
                mock.call("Memory encryption requested by %s", requesters)
            ])

        _test_get_mem_encryption_constraint()
        for mtype in ('q35', 'pc-q35-2.1'):
            image_props['hw_machine_type'] = mtype
            _test_get_mem_encryption_constraint()

    def test_require_encrypted_memory_support_extra_spec(self):
        for extra_spec in ('1', 'true', 'True'):
            self._test_encrypted_memory_support_required(
                {'hw:mem_encryption': extra_spec},
                {},
                "hw:mem_encryption extra spec in %s flavor" % self.flavor_name
            )

    def test_require_encrypted_memory_support_image_prop(self):
        for image_prop in ('1', 'true', 'True'):
            self._test_encrypted_memory_support_required(
                {},
                {'hw_mem_encryption': image_prop},
                "hw_mem_encryption property of image %s" % self.image_name
            )

    def test_require_encrypted_memory_support_both_required(self):
        for extra_spec in ('1', 'true', 'True'):
            for image_prop in ('1', 'true', 'True'):
                self._test_encrypted_memory_support_required(
                    {'hw:mem_encryption': extra_spec},
                    {'hw_mem_encryption': image_prop},
                    "hw:mem_encryption extra spec in %s flavor and "
                    "hw_mem_encryption property of image %s" %
                    (self.flavor_name, self.image_name)
                )


class PCINUMAAffinityPolicyTest(test.NoDBTestCase):

    def test_get_pci_numa_policy_flavor(self):

        for policy in fields.PCINUMAAffinityPolicy.ALL:
            extra_specs = {
                "hw:pci_numa_affinity_policy": policy,
            }
            image_meta = objects.ImageMeta.from_dict({"properties": {}})
            flavor = objects.Flavor(
                vcpus=16, memory_mb=2048, extra_specs=extra_specs)
            self.assertEqual(
                policy, hw.get_pci_numa_policy_constraint(flavor, image_meta))

    def test_get_pci_numa_policy_image(self):
        for policy in fields.PCINUMAAffinityPolicy.ALL:
            props = {
                "hw_pci_numa_affinity_policy": policy,
            }
            image_meta = objects.ImageMeta.from_dict({"properties": props})
            flavor = objects.Flavor(
                vcpus=16, memory_mb=2048, extra_specs={})
            self.assertEqual(
                policy, hw.get_pci_numa_policy_constraint(flavor, image_meta))

    def test_get_pci_numa_policy_no_conflict(self):

        for policy in fields.PCINUMAAffinityPolicy.ALL:
            extra_specs = {
                "hw:pci_numa_affinity_policy": policy,
            }
            flavor = objects.Flavor(
                vcpus=16, memory_mb=2048, extra_specs=extra_specs)
            props = {
                "hw_pci_numa_affinity_policy": policy,
            }
            image_meta = objects.ImageMeta.from_dict({"properties": props})
            self.assertEqual(
                policy, hw.get_pci_numa_policy_constraint(flavor, image_meta))

    def test_get_pci_numa_policy_conflict(self):
        extra_specs = {
            "hw:pci_numa_affinity_policy":
                fields.PCINUMAAffinityPolicy.LEGACY,
        }
        flavor = objects.Flavor(
            vcpus=16, memory_mb=2048, extra_specs=extra_specs)
        props = {
            "hw_pci_numa_affinity_policy":
                fields.PCINUMAAffinityPolicy.REQUIRED,
        }
        image_meta = objects.ImageMeta.from_dict({"properties": props})
        self.assertRaises(
            exception.ImagePCINUMAPolicyForbidden,
            hw.get_pci_numa_policy_constraint, flavor, image_meta)

    def test_get_pci_numa_policy_invalid(self):
        extra_specs = {
            "hw:pci_numa_affinity_policy": "fake",
        }
        flavor = objects.Flavor(
            vcpus=16, memory_mb=2048, extra_specs=extra_specs)
        image_meta = objects.ImageMeta.from_dict({"properties": {}})
        self.assertRaises(
            exception.InvalidPCINUMAAffinity,
            hw.get_pci_numa_policy_constraint, flavor, image_meta)
        with testtools.ExpectedException(ValueError):
            image_meta.properties.hw_pci_numa_affinity_policy = "fake"


@ddt.ddt
class RescuePropertyTestCase(test.NoDBTestCase):

    @ddt.unpack
    @ddt.data({'props': {'hw_rescue_device': 'disk',
                         'hw_rescue_bus': 'virtio'}, 'expected': True},
              {'props': {'hw_rescue_device': 'disk'}, 'expected': True},
              {'props': {'hw_rescue_bus': 'virtio'}, 'expected': True},
              {'props': {'hw_disk_bus': 'virtio'}, 'expected': False})
    def test_check_hw_rescue_props(self, props=None, expected=None):
        meta = objects.ImageMeta.from_dict({'disk_format': 'raw'})
        meta.properties = objects.ImageMetaProps.from_dict(props)
        self.assertEqual(expected, hw.check_hw_rescue_props(meta))
