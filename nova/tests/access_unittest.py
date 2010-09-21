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
import webob

from nova import exception
from nova import flags
from nova import test
from nova.api import ec2
from nova.auth import manager


FLAGS = flags.FLAGS
class Context(object):
    pass

class AccessTestCase(test.BaseTestCase):
    def setUp(self):
        super(AccessTestCase, self).setUp()
        um = manager.AuthManager()
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
        #user is set in each test
        self.mw = ec2.Authorizer(lambda x,y: y('200 OK', []) and '')
        self.mw.action_roles = {'str': {
                '_allow_all': ['all'],
                '_allow_none': [],
                '_allow_project_manager': ['projectmanager'],
                '_allow_sys_and_net': ['sysadmin', 'netadmin'],
                '_allow_sysadmin': ['sysadmin']}}

    def tearDown(self):
        um = manager.AuthManager()
        # Delete the test project
        um.delete_project('testproj')
        # Delete the test user
        um.delete_user('testadmin')
        um.delete_user('testpmsys')
        um.delete_user('testnet')
        um.delete_user('testsys')
        super(AccessTestCase, self).tearDown()

    def response_status(self, user, methodName):
        context = Context()
        context.project = self.project
        context.user = user
        environ = {'ec2.context' : context,
                   'ec2.controller': 'some string',
                   'ec2.action': methodName}
        req = webob.Request.blank('/', environ)
        resp = req.get_response(self.mw)
        return resp.status_int

    def shouldAllow(self, user, methodName):
        self.assertEqual(200, self.response_status(user, methodName))

    def shouldDeny(self, user, methodName):
        self.assertEqual(401, self.response_status(user, methodName))

    def test_001_allow_all(self):
        users = [self.testadmin, self.testpmsys, self.testnet, self.testsys]
        for user in users:
            self.shouldAllow(user, '_allow_all')

    def test_002_allow_none(self):
        self.shouldAllow(self.testadmin, '_allow_none')
        users = [self.testpmsys, self.testnet, self.testsys]
        for user in users:
            self.shouldDeny(user, '_allow_none')

    def test_003_allow_project_manager(self):
        for user in [self.testadmin, self.testpmsys]:
            self.shouldAllow(user, '_allow_project_manager')
        for user in [self.testnet, self.testsys]:
            self.shouldDeny(user, '_allow_project_manager')

    def test_004_allow_sys_and_net(self):
        for user in [self.testadmin, self.testnet, self.testsys]:
            self.shouldAllow(user, '_allow_sys_and_net')
        # denied because it doesn't have the per project sysadmin
        for user in [self.testpmsys]:
            self.shouldDeny(user, '_allow_sys_and_net')

if __name__ == "__main__":
    # TODO: Implement use_fake as an option
    unittest.main()
