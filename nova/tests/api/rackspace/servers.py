# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import json
import unittest
import stubout
import nova.api.rackspace
import nova.db.api
from nova import flags
from nova.api.rackspace import servers
from nova.db.sqlalchemy.models import Instance
from nova.tests.api.test_helper import *
from nova.tests.api.rackspace import test_helper
from nova import db

FLAGS = flags.FLAGS

def return_server(context, id):
    return stub_instance(id)

def return_servers(context, user_id=1):
    return [stub_instance(i, user_id) for i in xrange(5)]


def stub_instance(id, user_id=1):
    return Instance(
        id=id, state=0, image_id=10, server_name='server%s'%id,
        user_id=user_id
    )

class ServersTest(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        test_helper.FakeAuthManager.auth_data = {}
        test_helper.FakeAuthDatabase.data = {}
        test_helper.stub_for_testing(self.stubs)
        test_helper.stub_out_rate_limiting(self.stubs)
        test_helper.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db.api, 'instance_get_all', return_servers)
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        self.stubs.Set(nova.db.api, 'instance_get_all_by_user', 
            return_servers)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get_server_by_id(self):
        req = webob.Request.blank('/v1.0/servers/1')
        res = req.get_response(nova.api.API())
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], '1')
        self.assertEqual(res_dict['server']['name'], 'server1')

    def test_get_backup_schedule(self):
        pass

    def test_get_server_list(self):
        req = webob.Request.blank('/v1.0/servers')
        res = req.get_response(nova.api.API())
        res_dict = json.loads(res.body)
        
        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s['id'], i)
            self.assertEqual(s['name'], 'server%d'%i)
            self.assertEqual(s.get('imageId', None), None)
            i += 1

    def test_create_instance(self):
        pass

    def test_update_server_password(self):
        pass

    def test_update_server_name(self):
        pass

    def test_create_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedules')
        req.method = 'POST'
        res = req.get_response(nova.api.API())
        self.assertEqual(res.status, '404 Not Found')

    def test_delete_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedules')
        req.method = 'DELETE'
        res = req.get_response(nova.api.API())
        self.assertEqual(res.status, '404 Not Found')

    def test_get_server_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedules')
        res = req.get_response(nova.api.API())
        self.assertEqual(res.status, '404 Not Found')

    def test_get_all_server_details(self):
        req = webob.Request.blank('/v1.0/servers/detail')
        res = req.get_response(nova.api.API())
        res_dict = json.loads(res.body)
        
        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s['id'], i)
            self.assertEqual(s['name'], 'server%d'%i)
            self.assertEqual(s['imageId'], 10)
            i += 1

    def test_server_reboot(self):
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        res = req.get_response(nova.api.API())
        res_dict = json.loads(res.body)

    def test_server_rebuild(self):
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        res = req.get_response(nova.api.API())
        res_dict = json.loads(res.body)

    def test_server_resize(self):
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        res = req.get_response(nova.api.API())
        res_dict = json.loads(res.body)

    def test_delete_server_instance(self):
        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'DELETE'

        self.server_delete_called = False
        def instance_destroy_mock(context, id):
            self.server_delete_called = True 

        self.stubs.Set(nova.db.api, 'instance_destroy',
            instance_destroy_mock)

        res = req.get_response(nova.api.API())
        self.assertEqual(res.status, '202 Accepted')
        self.assertEqual(self.server_delete_called, True)

if __name__ == "__main__":
    unittest.main()
