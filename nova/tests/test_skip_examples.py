# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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


class ExampleSkipTestCase(test.TestCase):
    test_counter = 0

    @test.skip_test("Example usage of @test.skip_test()")
    def test_skip_test_example(self):
        self.fail("skip_test failed to work properly.")

    @test.skip_if(True, "Example usage of @test.skip_if()")
    def test_skip_if_example(self):
        self.fail("skip_if failed to work properly.")

    @test.skip_unless(False, "Example usage of @test.skip_unless()")
    def test_skip_unless_example(self):
        self.fail("skip_unless failed to work properly.")

    @test.skip_if(False, "This test case should never be skipped.")
    def test_001_increase_test_counter(self):
        ExampleSkipTestCase.test_counter += 1

    @test.skip_unless(True, "This test case should never be skipped.")
    def test_002_increase_test_counter(self):
        ExampleSkipTestCase.test_counter += 1

    def test_003_verify_test_counter(self):
        self.assertEquals(ExampleSkipTestCase.test_counter, 2,
                          "Tests were not skipped appropriately")
