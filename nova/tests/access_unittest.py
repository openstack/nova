# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import logging
import os
import unittest

from nova import flags
from nova import test
from nova.auth import users
from nova.endpoint import cloud

FLAGS = flags.FLAGS

class AccessTestCase(test.BaseTestCase):
    def setUp(self):
        FLAGS.fake_libvirt = True
        FLAGS.fake_storage = True
        self.users = users.UserManager.instance()
        super(AccessTestCase, self).setUp()
        # Make a test project
        # Make a test user
        self.users.create_user('test1', 'access', 'secret')

        # Make the test user a member of the project

    def tearDown(self):
        # Delete the test user
        # Delete the test project
        self.users.delete_user('test1')
        pass

    def test_001_basic_user_access(self):
        user = self.users.get_user('test1')
        # instance-foo, should be using object and not owner_id
        instance_id = "i-12345678"
        self.assertTrue(user.is_authorized(instance_id, action="describe_instances"))

    def test_002_sysadmin_access(self):
        user = self.users.get_user('test1')
        bucket = "foo/bar/image"
        self.assertFalse(user.is_authorized(bucket, action="register"))
        self.users.add_role(user, "sysadmin")


if __name__ == "__main__":
    # TODO: Implement use_fake as an option
    unittest.main()
