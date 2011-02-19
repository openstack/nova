# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
"""
Tests For Nova-Manage
"""

import time
import os
import subprocess

from nova import test
from nova.db.sqlalchemy.session import get_session
from nova.db.sqlalchemy import models


class NovaManageTestCase(test.TestCase):
    """Test case for nova-manage"""
    def setUp(self):
        super(NovaManageTestCase, self).setUp()
        session = get_session()
        max_flavorid = session.query(models.InstanceTypes).\
                                     order_by("flavorid desc").first()
        self.flavorid = str(max_flavorid["flavorid"] + 1)
        self.name = str(int(time.time()))
        self.fnull = open(os.devnull, 'w')

    def teardown(self):
        self.fnull.close()

    def test_create_and_delete_instance_types(self):
        myname = self.name + "create_and_delete"
        retcode = subprocess.call([
            "bin/nova-manage",
            "instance_type",
            "create",
            self.name,
            "256",
            "1",
            "120",
            self.flavorid,
            "2",
            "10",
            "10"],
            stdout=self.fnull)
        self.assertEqual(0, retcode)
        retcode = subprocess.call(["bin/nova-manage", "instance_type",
                                    "delete", self.name], stdout=self.fnull)
        self.assertEqual(0, retcode)
        retcode = subprocess.call(["bin/nova-manage", "instance_type",
                                    "delete", self.name, "--purge"],
                                    stdout=self.fnull)
        self.assertEqual(0, retcode)

    def test_list_instance_types_or_flavors(self):
        for c in ["instance_type", "flavor"]:
            retcode = subprocess.call(["bin/nova-manage", c, \
                                        "list"], stdout=self.fnull)
            self.assertEqual(0, retcode)

    def test_list_specific_instance_type(self):
        retcode = subprocess.call(["bin/nova-manage", "instance_type", "list",
                                    "m1.medium"], stdout=self.fnull)
        self.assertEqual(0, retcode)

    def test_should_error_on_bad_create_args(self):
        # shouldn't be able to create instance type with 0 vcpus
        retcode = subprocess.call(["bin/nova-manage", "instance_type",
                                    "create", self.name + "bad_args",
                                    "256", "0", "120", self.flavorid],
                                    stdout=self.fnull)
        self.assertEqual(1, retcode)

    def test_should_fail_on_duplicate_flavorid(self):
        # flavorid 1 is set in migration seed data
        retcode = subprocess.call(["bin/nova-manage", "instance_type",\
                                    "create", self.name + "dupflavor", "256",
                                    "1", "120", "1"], stdout=self.fnull)
        self.assertEqual(3, retcode)

    def test_should_fail_on_duplicate_name(self):
        duplicate_name = self.name + "dup_name"
        retcode = subprocess.call([
            "bin/nova-manage",
            "instance_type",
            "create",
            duplicate_name,
            "256",
            "1",
            "120",
            self.flavorid,
            "2",
            "10",
            "10"],
            stdout=self.fnull)
        self.assertEqual(0, retcode)
        duplicate_retcode = subprocess.call([
            "bin/nova-manage",
            "instance_type",
            "create",
            duplicate_name,
            "512",
            "1",
            "240",
            str(int(self.flavorid) + 1),
            "2",
            "10",
            "10"],
            stdout=self.fnull)
        self.assertEqual(3, duplicate_retcode)
        delete_retcode = subprocess.call(["bin/nova-manage", "instance_type",
                                    "delete", duplicate_name, "--purge"],
                                    stdout=self.fnull)
        self.assertEqual(0, delete_retcode)

    def test_instance_type_delete_should_fail_without_valid_name(self):
        retcode = subprocess.call(["bin/nova-manage", "instance_type",
                                    "delete", "doesntexist"],
                                    stdout=self.fnull)
        self.assertEqual(1, retcode)
