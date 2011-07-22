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

import webob

from nova import context
from nova import flags
from nova import test
from nova.api import ec2
from nova.auth import manager

FLAGS = flags.FLAGS


class FakeControllerClass(object):
    pass


class FakeApiRequest(object):
    def __init__(self, action):
        self.controller = FakeControllerClass()
        self.action = action


class AccessTestCase(test.TestCase):
    def _env_for(self, ctxt, action):
        env = {}
        env['nova.context'] = ctxt
        env['ec2.request'] = FakeApiRequest(action)
        return env

    def setUp(self):
        super(AccessTestCase, self).setUp()
        um = manager.AuthManager()
        self.context = context.get_admin_context()
        # Make test users
        self.testadmin = um.create_user('testadmin')
        self.testpmsys = um.create_user('testpmsys')
        self.testnet = um.create_user('testnet')
        self.testsys = um.create_user('testsys')
        # Assign some rules
        um.add_role('testadmin', 'cloudadmin')
        um.add_role('testpmsys', 'sysadmin')
        um.add_role('testnet', 'netadmin')
        um.add_role('testsys', 'sysadmin')

        # Make a test project
        self.project = um.create_project('testproj',
                                         'testpmsys',
                                         'a test project',
                                         ['testpmsys', 'testnet', 'testsys'])
        self.project.add_role(self.testnet, 'netadmin')
        self.project.add_role(self.testsys, 'sysadmin')
        #user is set in each test

        def noopWSGIApp(environ, start_response):
            start_response('200 OK', [])
            return ['']

        self.mw = ec2.Authorizer(noopWSGIApp)
        self.mw.action_roles = {'FakeControllerClass': {
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
        roles = manager.AuthManager().get_active_roles(user, self.project)
        ctxt = context.RequestContext(user.id,
                                      self.project.id,
                                      is_admin=user.is_admin(),
                                      roles=roles)
        environ = self._env_for(ctxt, methodName)
        req = webob.Request.blank('/', environ)
        resp = req.get_response(self.mw)
        return resp.status_int

    def shouldAllow(self, user, methodName):
        self.assertEqual(200, self.response_status(user, methodName))

    def shouldDeny(self, user, methodName):
        self.assertEqual(401, self.response_status(user, methodName))

    def test_allow_all(self):
        users = [self.testadmin, self.testpmsys, self.testnet, self.testsys]
        for user in users:
            self.shouldAllow(user, '_allow_all')

    def test_allow_none(self):
        self.shouldAllow(self.testadmin, '_allow_none')
        users = [self.testpmsys, self.testnet, self.testsys]
        for user in users:
            self.shouldDeny(user, '_allow_none')

    def test_allow_project_manager(self):
        for user in [self.testadmin, self.testpmsys]:
            self.shouldAllow(user, '_allow_project_manager')
        for user in [self.testnet, self.testsys]:
            self.shouldDeny(user, '_allow_project_manager')

    def test_allow_sys_and_net(self):
        for user in [self.testadmin, self.testnet, self.testsys]:
            self.shouldAllow(user, '_allow_sys_and_net')
        # denied because it doesn't have the per project sysadmin
        for user in [self.testpmsys]:
            self.shouldDeny(user, '_allow_sys_and_net')
