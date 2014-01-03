# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

from nova import exception
from nova import test
from nova.virt import cpu


class CpuSetTestCase(test.NoDBTestCase):
    def test_get_cpuset_ids_none_returns_none(self):
        self.flags(vcpu_pin_set=None)
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual(None, cpuset_ids)

    def test_get_cpuset_ids_valid_syntax_works(self):
        self.flags(vcpu_pin_set="1")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([1], cpuset_ids)

        self.flags(vcpu_pin_set="1,2")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([1, 2], cpuset_ids)

        self.flags(vcpu_pin_set=", ,   1 ,  ,,  2,    ,")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([1, 2], cpuset_ids)

        self.flags(vcpu_pin_set="1-1")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([1], cpuset_ids)

        self.flags(vcpu_pin_set=" 1 - 1, 1 - 2 , 1 -3")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([1, 2, 3], cpuset_ids)

        self.flags(vcpu_pin_set="1,^2")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([1], cpuset_ids)

        self.flags(vcpu_pin_set="1-2, ^1")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([2], cpuset_ids)

        self.flags(vcpu_pin_set="1-3,5,^2")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([1, 3, 5], cpuset_ids)

        self.flags(vcpu_pin_set=" 1 -    3        ,   ^2,        5")
        cpuset_ids = cpu.get_cpuset_ids()
        self.assertEqual([1, 3, 5], cpuset_ids)

    def test_get_cpuset_ids_invalid_syntax_raises(self):
        self.flags(vcpu_pin_set=" -1-3,5,^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="1-3-,5,^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="-3,5,^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="1-,5,^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="1-3,5,^2^")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="1-3,5,^2-")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="--13,^^5,^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="a-3,5,^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="1-a,5,^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="1-3,b,^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="1-3,5,^c")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="3 - 1, 5 , ^ 2 ")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set=" 1,1, ^1")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set=" 1,^1,^1,2, ^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)

        self.flags(vcpu_pin_set="^2")
        self.assertRaises(exception.Invalid, cpu.get_cpuset_ids)
