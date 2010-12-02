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
import webob

from nova import db
from nova import flags
import nova.api.openstack
from nova.api.openstack import servers
import nova.db.api
from nova.db.sqlalchemy.models import Instance
import nova.rpc
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS
FLAGS.verbose = True


def return_server(context, id):
    return stub_instance(id)


def return_servers(context, user_id=1):
    return [stub_instance(i, user_id) for i in xrange(5)]


def return_security_group(context, instance_id, security_group_id):
    pass


def stub_instance(id, user_id=1):
    return Instance(id=id, state=0, image_id=10, display_name='server%s' % id,
                    user_id=user_id)


class ServersTest(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fakes.stub_out_image_service(self.stubs)
        self.stubs.Set(nova.db.api, 'instance_get_all', return_servers)
        self.stubs.Set(nova.db.api, 'instance_get_by_internal_id',
                       return_server)
        self.stubs.Set(nova.db.api, 'instance_get_all_by_user',
                       return_servers)
        self.stubs.Set(nova.db.api, 'instance_add_security_group',
                       return_security_group)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get_server_by_id(self):
        req = webob.Request.blank('/v1.0/servers/1')
        res = req.get_response(nova.api.API('os'))
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server1')

    def test_get_server_list(self):
        req = webob.Request.blank('/v1.0/servers')
        res = req.get_response(nova.api.API('os'))
        res_dict = json.loads(res.body)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s['id'], i)
            self.assertEqual(s['name'], 'server%d' % i)
            self.assertEqual(s.get('imageId', None), None)
            i += 1

    def test_create_instance(self):
        def server_update(context, id, params):
            pass

        def instance_create(context, inst):
            return {'id': 1, 'internal_id': 1}

        def fake_method(*args, **kwargs):
            pass

        def project_get_network(context, user_id):
            return dict(id='1', host='localhost')

        def queue_get_for(context, *args):
            return 'network_topic'

        self.stubs.Set(nova.db.api, 'project_get_network', project_get_network)
        self.stubs.Set(nova.db.api, 'instance_create', instance_create)
        self.stubs.Set(nova.rpc, 'cast', fake_method)
        self.stubs.Set(nova.rpc, 'call', fake_method)
        self.stubs.Set(nova.db.api, 'instance_update',
            server_update)
        self.stubs.Set(nova.db.api, 'queue_get_for', queue_get_for)
        self.stubs.Set(nova.network.manager.VlanManager, 'allocate_fixed_ip',
            fake_method)

        body = dict(server=dict(
            name='server_test', imageId=2, flavorId=2, metadata={},
            personality={}))
        req = webob.Request.blank('/v1.0/servers')
        req.method = 'POST'
        req.body = json.dumps(body)

        res = req.get_response(nova.api.API('os'))

        self.assertEqual(res.status_int, 200)

    def test_update_no_body(self):
        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'PUT'
        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status_int, 422)

    def test_update_bad_params(self):
        """ Confirm that update is filtering params """
        inst_dict = dict(cat='leopard', name='server_test', adminPass='bacon')
        self.body = json.dumps(dict(server=inst_dict))

        def server_update(context, id, params):
            self.update_called = True
            filtered_dict = dict(name='server_test', admin_pass='bacon')
            self.assertEqual(params, filtered_dict)

        self.stubs.Set(nova.db.api, 'instance_update',
            server_update)

        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'PUT'
        req.body = self.body
        req.get_response(nova.api.API('os'))

    def test_update_server(self):
        inst_dict = dict(name='server_test', adminPass='bacon')
        self.body = json.dumps(dict(server=inst_dict))

        def server_update(context, id, params):
            filtered_dict = dict(name='server_test', admin_pass='bacon')
            self.assertEqual(params, filtered_dict)

        self.stubs.Set(nova.db.api, 'instance_update',
            server_update)

        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'PUT'
        req.body = self.body
        req.get_response(nova.api.API('os'))

    def test_create_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedules')
        req.method = 'POST'
        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status, '404 Not Found')

    def test_delete_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedules')
        req.method = 'DELETE'
        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status, '404 Not Found')

    def test_get_server_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedules')
        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status, '404 Not Found')

    def test_get_all_server_details(self):
        req = webob.Request.blank('/v1.0/servers/detail')
        res = req.get_response(nova.api.API('os'))
        res_dict = json.loads(res.body)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s['id'], i)
            self.assertEqual(s['name'], 'server%d' % i)
            self.assertEqual(s['imageId'], 10)
            i += 1

    def test_server_reboot(self):
        body = dict(server=dict(
            name='server_test', imageId=2, flavorId=2, metadata={},
            personality={}))
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(nova.api.API('os'))

    def test_server_rebuild(self):
        body = dict(server=dict(
            name='server_test', imageId=2, flavorId=2, metadata={},
            personality={}))
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(nova.api.API('os'))

    def test_server_resize(self):
        body = dict(server=dict(
            name='server_test', imageId=2, flavorId=2, metadata={},
            personality={}))
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(nova.api.API('os'))

    def test_delete_server_instance(self):
        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'DELETE'

        self.server_delete_called = False

        def instance_destroy_mock(context, id):
            self.server_delete_called = True

        self.stubs.Set(nova.db.api, 'instance_destroy',
            instance_destroy_mock)

        res = req.get_response(nova.api.API('os'))
        self.assertEqual(res.status, '202 Accepted')
        self.assertEqual(self.server_delete_called, True)


if __name__ == "__main__":
    unittest.main()
