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

import unittest
import logging

from nova.auth.users import UserManager
from nova.auth import rbac
from nova import exception
from nova import flags
from nova import test

FLAGS = flags.FLAGS
class Context(object):
    pass

class AccessTestCase(test.BaseTestCase):
    def setUp(self):
        super(AccessTestCase, self).setUp()
        FLAGS.fake_libvirt = True
        FLAGS.fake_storage = True
        um = UserManager.instance()
        # Make test users
        try:
            self.testadmin = um.create_user('testadmin')
        except Exception, err:
            logging.error(str(err))
        try:
            self.testpmsys = um.create_user('testpmsys')
        except: pass
        try:
            self.testnet = um.create_user('testnet')
        except: pass
        try:
            self.testsys = um.create_user('testsys')
        except: pass
        # Assign some rules
        try:
            um.add_role('testadmin', 'cloudadmin')
        except: pass
        try:
            um.add_role('testpmsys', 'sysadmin')
        except: pass
        try:
            um.add_role('testnet', 'netadmin')
        except: pass
        try:
            um.add_role('testsys', 'sysadmin')
        except: pass

        # Make a test project
        try:
            self.project = um.create_project('testproj', 'testpmsys', 'a test project', ['testpmsys', 'testnet', 'testsys'])
        except: pass
        try:
            self.project.add_role(self.testnet, 'netadmin')
        except: pass
        try:
            self.project.add_role(self.testsys, 'sysadmin')
        except: pass
        self.context = Context()
        self.context.project = self.project
        #user is set in each test

    def tearDown(self):
        um = UserManager.instance()
        # Delete the test project
        um.delete_project('testproj')
        # Delete the test user
        um.delete_user('testadmin')
        um.delete_user('testpmsys')
        um.delete_user('testnet')
        um.delete_user('testsys')
        super(AccessTestCase, self).tearDown()

    def test_001_allow_all(self):
        self.context.user = self.testadmin
        self.assertTrue(self._allow_all(self.context))
        self.context.user = self.testpmsys
        self.assertTrue(self._allow_all(self.context))
        self.context.user = self.testnet
        self.assertTrue(self._allow_all(self.context))
        self.context.user = self.testsys
        self.assertTrue(self._allow_all(self.context))

    def test_002_allow_none(self):
        self.context.user = self.testadmin
        self.assertTrue(self._allow_none(self.context))
        self.context.user = self.testpmsys
        self.assertRaises(exception.NotAuthorized, self._allow_none, self.context)
        self.context.user = self.testnet
        self.assertRaises(exception.NotAuthorized, self._allow_none, self.context)
        self.context.user = self.testsys
        self.assertRaises(exception.NotAuthorized, self._allow_none, self.context)

    def test_003_allow_project_manager(self):
        self.context.user = self.testadmin
        self.assertTrue(self._allow_project_manager(self.context))
        self.context.user = self.testpmsys
        self.assertTrue(self._allow_project_manager(self.context))
        self.context.user = self.testnet
        self.assertRaises(exception.NotAuthorized, self._allow_project_manager, self.context)
        self.context.user = self.testsys
        self.assertRaises(exception.NotAuthorized, self._allow_project_manager, self.context)

    def test_004_allow_sys_and_net(self):
        self.context.user = self.testadmin
        self.assertTrue(self._allow_sys_and_net(self.context))
        self.context.user = self.testpmsys # doesn't have the per project sysadmin
        self.assertRaises(exception.NotAuthorized, self._allow_sys_and_net, self.context)
        self.context.user = self.testnet
        self.assertTrue(self._allow_sys_and_net(self.context))
        self.context.user = self.testsys
        self.assertTrue(self._allow_sys_and_net(self.context))

    def test_005_allow_sys_no_pm(self):
        self.context.user = self.testadmin
        self.assertTrue(self._allow_sys_no_pm(self.context))
        self.context.user = self.testpmsys
        self.assertRaises(exception.NotAuthorized, self._allow_sys_no_pm, self.context)
        self.context.user = self.testnet
        self.assertRaises(exception.NotAuthorized, self._allow_sys_no_pm, self.context)
        self.context.user = self.testsys
        self.assertTrue(self._allow_sys_no_pm(self.context))

    @rbac.allow('all')
    def _allow_all(self, context):
        return True

    @rbac.allow('none')
    def _allow_none(self, context):
        return True

    @rbac.allow('projectmanager')
    def _allow_project_manager(self, context):
        return True

    @rbac.allow('sysadmin', 'netadmin')
    def _allow_sys_and_net(self, context):
        return True

    @rbac.allow('sysadmin')
    @rbac.deny('projectmanager')
    def _allow_sys_no_pm(self, context):
        return True

if __name__ == "__main__":
    # TODO: Implement use_fake as an option
    unittest.main()
