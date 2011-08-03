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
    @test.skip_test("Example usage of @test.skip_test()")
    def test_skip_test(self):
        self.fail("skip_test failed to work properly.")

    @test.skip_if(True, "Example usage of @test.skip_if()")
    def test_skip_if_env_user_exists(self):
        self.fail("skip_if failed to work properly.")

    @test.skip_unless(False, "Example usage of @test.skip_unless()")
    def test_skip_unless_env_foo_exists(self):
        self.fail("skip_unless failed to work properly.")
