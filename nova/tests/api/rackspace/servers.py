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

def return_servers(context):
    return [stub_instance(i) for i in xrange(5)]

def stub_instance(id):
    return Instance(id=id, state=0, )

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

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get_server_by_id(self):
        req = webob.Request.blank('/v1.0/servers/1')
        req.headers['content-type'] = 'application/json'
        res = req.get_response(nova.api.API())
        print res

    def test_get_backup_schedule(self):
        pass

    def test_get_server_list(self):
        req = webob.Request.blank('/v1.0/servers')
        res = req.get_response(nova.api.API())
        print res

    def test_create_instance(self):
        pass

    def test_get_server_details(self):
        req = webob.Request.blank('/v1.0/servers/detail')
        res = req.get_response(nova.api.API())
        print res

    def test_get_server_ips(self):
        pass

    def test_server_reboot(self):
        pass

    def test_server_rebuild(self):
        pass

    def test_server_resize(self):
        pass

    def test_delete_server_instance(self):
        pass

if __name__ == "__main__":
    unittest.main()
