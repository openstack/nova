# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

import logging
import unittest

from nova import vendor

from nova import flags
from nova import test
from nova import validate


class ValidationTestCase(test.TrialTestCase):
    def setUp(self):
        super(ValidationTestCase, self).setUp()

    def tearDown(self):
        super(ValidationTestCase, self).tearDown()

    def test_type_validation(self):
        self.assertTrue(type_case("foo", 5, 1))
        self.assertRaises(TypeError, type_case, "bar", "5", 1)
        self.assertRaises(TypeError, type_case, None, 5, 1)
        
@validate.typetest(instanceid=str, size=int, number_of_instances=int)
def type_case(instanceid, size, number_of_instances):
    return True
