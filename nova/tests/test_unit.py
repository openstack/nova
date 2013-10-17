# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp
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

from nova import test
from nova import unit


class UnitTest(test.NoDBTestCase):
    def test_byte_unit(self):
        self.assertEqual(unit.Ki, 1024)
        self.assertEqual(unit.Mi, 1024 ** 2)
        self.assertEqual(unit.Gi, 1024 ** 3)
        self.assertEqual(unit.Ti, 1024 ** 4)
        self.assertEqual(unit.Pi, 1024 ** 5)
        self.assertEqual(unit.Ei, 1024 ** 6)
        self.assertEqual(unit.Zi, 1024 ** 7)
        self.assertEqual(unit.Yi, 1024 ** 8)
