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

import os
import random
import sys
import unittest
import zipfile

# If ../nova/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...
possible_topdir = os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]),
                                   os.pardir,
                                   os.pardir))
if os.path.exists(os.path.join(possible_topdir, 'nova', '__init__.py')):
    sys.path.insert(0, possible_topdir)

from smoketests import flags
from smoketests import base


FLAGS = flags.FLAGS

# TODO(devamcar): Use random tempfile
ZIP_FILENAME = '/tmp/nova-me-x509.zip'

TEST_PREFIX = 'test%s' % int(random.random() * 1000000)
TEST_USERNAME = '%suser' % TEST_PREFIX
TEST_PROJECTNAME = '%sproject' % TEST_PREFIX


class AdminSmokeTestCase(base.SmokeTestCase):
    def setUp(self):
        import nova_adminclient as adminclient
        self.admin = adminclient.NovaAdminClient(
            access_key=os.getenv('EC2_ACCESS_KEY'),
            secret_key=os.getenv('EC2_SECRET_KEY'),
            clc_url=os.getenv('EC2_URL'),
            region=FLAGS.region)


class UserTests(AdminSmokeTestCase):
    """ Test admin credentials and user creation. """

    def test_001_admin_can_connect(self):
        conn = self.admin.connection_for('admin', 'admin')
        self.assert_(conn)

    def test_002_admin_can_create_user(self):
        user = self.admin.create_user(TEST_USERNAME)
        self.assertEqual(user.username, TEST_USERNAME)

    def test_003_admin_can_create_project(self):
        project = self.admin.create_project(TEST_PROJECTNAME,
                                            TEST_USERNAME)
        self.assertEqual(project.projectname, TEST_PROJECTNAME)

    def test_004_user_can_download_credentials(self):
        buf = self.admin.get_zip(TEST_USERNAME, TEST_PROJECTNAME)
        output = open(ZIP_FILENAME, 'w')
        output.write(buf)
        output.close()

        zip = zipfile.ZipFile(ZIP_FILENAME, 'a', zipfile.ZIP_DEFLATED)
        bad = zip.testzip()
        zip.close()

        self.failIf(bad)

    def test_999_tearDown(self):
        self.admin.delete_project(TEST_PROJECTNAME)
        self.admin.delete_user(TEST_USERNAME)
        try:
            os.remove(ZIP_FILENAME)
        except:
            pass
