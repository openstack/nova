# Copyright 2013 IBM Corp.
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

import datetime
import uuid

from oslo.config import cfg
import webob

from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import servers
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import db
from nova.network import manager
from nova.openstack.common import jsonutils
from nova.openstack.common import rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests.image import fake
from nova.tests import matchers


CONF = cfg.CONF
FAKE_UUID = fakes.FAKE_UUID


def fake_gen_uuid():
    return FAKE_UUID


def return_security_group(context, instance_id, security_group_id):
    pass


class ServersControllerCreateTest(test.TestCase):

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTest, self).setUp()

        self.flags(verbose=True,
                   enable_instance_password=True)
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)
        CONF.set_override('extensions_blacklist', 'os-personality',
                          'osapi_v3')
        self.no_personality_controller = servers.ServersController(
            extension_info=ext_info)

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': FAKE_UUID,
                'instance_type': dict(inst_type),
                'access_ip_v4': '1.2.3.4',
                'access_ip_v6': 'fead::1234',
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "config_drive": None,
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
                "security_groups": inst['security_groups'],
            })

            self.instance_cache_by_id[instance['id']] = instance
            self.instance_cache_by_uuid[instance['uuid']] = instance
            return instance

        def instance_get(context, instance_id):
            """Stub for compute/api create() pulling in instance after
            scheduling
            """
            return self.instance_cache_by_id[instance_id]

        def instance_update(context, uuid, values):
            instance = self.instance_cache_by_uuid[uuid]
            instance.update(values)
            return instance

        def server_update(context, instance_uuid, params):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return (inst, inst)

        def fake_method(*args, **kwargs):
            pass

        def project_get_networks(context, user_id):
            return dict(id='1', host='localhost')

        def queue_get_for(context, *args):
            return 'network_topic'

        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fake.stub_out_image_service(self.stubs)
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(uuid, 'uuid4', fake_gen_uuid)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(db, 'project_get_networks',
                       project_get_networks)
        self.stubs.Set(db, 'instance_create', instance_create)
        self.stubs.Set(db, 'instance_system_metadata_update',
                       fake_method)
        self.stubs.Set(db, 'instance_get', instance_get)
        self.stubs.Set(db, 'instance_update', instance_update)
        self.stubs.Set(rpc, 'cast', fake_method)
        self.stubs.Set(db, 'instance_update_and_get_original',
                       server_update)
        self.stubs.Set(rpc, 'queue_get_for', queue_get_for)
        self.stubs.Set(manager.VlanManager, 'allocate_fixed_ip',
                       fake_method)

        return_server = fakes.fake_instance_get()
        return_servers = fakes.fake_instance_get_all_by_filters()
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       return_server)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(db, 'instance_update_and_get_original',
                       instance_update)

    def _test_create_extra(self, params, no_image=False,
                           override_controller=None):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', image_ref=image_uuid, flavor_ref=2)
        if no_image:
            server.pop('image_ref', None)
        server.update(params)
        body = dict(server=server)
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        if override_controller:
            server = override_controller.create(req, body).obj['server']
        else:
            server = self.controller.create(req, body).obj['server']

    def test_create_instance_with_personality_disabled(self):
        params = {
            'personality': [
                {
                    "path": "/etc/banner.txt",
                    "contents": "MQ==",
                }]}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('injected_files', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params,
            override_controller=self.no_personality_controller)

    def test_create_instance_with_personality_enabled(self):
        params = {
            'personality': [
                {
                    "path": "/etc/banner.txt",
                    "contents": "MQ==",
                }]}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIn('injected_files', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_personality(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/flavors/3'
        value = "A random string"
        body = {
            'server': {
                'name': 'user_data_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': [
                    {
                        "path": "/etc/banner.txt",
                        "contents": "MQ==",
                    },
                ],
            },
        }

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIn('injected_files', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_rebuild_instance_with_personality_diabled(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/images/%s' % image_uuid
        access_ipv4 = '0.0.0.0'
        access_ipv6 = 'fead::1234'
        body = {
            'rebuild': {
                'name': 'new_name',
                'image_ref': image_href,
                'access_ip_v4': access_ipv4,
                'access_ip_v6': access_ipv6,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': [
                    {
                        "path": "/etc/banner.txt",
                        "contents": "MQ==",
                    },
                ],
            },
        }
        self.rebuild_called = True

        def rebuild(*args, **kwargs):
            self.assertNotIn('files_to_inject', kwargs)
            self.rebuild_called = True

        self.stubs.Set(compute_api.API, 'rebuild', rebuild)
        req = fakes.HTTPRequestV3.blank(
            '/servers/%s/action' % FAKE_UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.no_personality_controller._action_rebuild(req,
                                                             FAKE_UUID,
                                                             body).obj
        self.assertTrue(self.rebuild_called)

    def test_rebuild_instance_with_personality(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/images/%s' % image_uuid
        access_ipv4 = '0.0.0.0'
        access_ipv6 = 'fead::1234'
        body = {
            'rebuild': {
                'name': 'new_name',
                'image_ref': image_href,
                'access_ip_v4': access_ipv4,
                'access_ip_v6': access_ipv6,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': [
                    {
                        "path": "/etc/banner.txt",
                        "contents": "MQ==",
                    },
                ],
            },
        }
        self.rebuild_called = False

        def rebuild(*args, **kwargs):
            self.assertIn('files_to_inject', kwargs)
            self.assertIn(('/etc/banner.txt', 'MQ=='),
                          kwargs['files_to_inject'])
            self.rebuild_called = True

        self.stubs.Set(compute_api.API, 'rebuild', rebuild)
        req = fakes.HTTPRequestV3.blank(
            '/servers/%s/action' % FAKE_UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller._action_rebuild(req,
                                              FAKE_UUID,
                                              body).obj
        self.assertTrue(self.rebuild_called)

    def test_rebuild_instance_without_personality(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/images/%s' % image_uuid
        access_ipv4 = '0.0.0.0'
        access_ipv6 = 'fead::1234'
        body = {
            'rebuild': {
                'name': 'new_name',
                'image_ref': image_href,
                'access_ip_v4': access_ipv4,
                'access_ip_v6': access_ipv6,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
              },
        }
        self.rebuild_called = False

        def rebuild(*args, **kwargs):
            self.assertNotIn('files_to_inject', kwargs)
            self.rebuild_called = True

        self.stubs.Set(compute_api.API, 'rebuild', rebuild)
        req = fakes.HTTPRequestV3.blank(
            '/servers/%s/action' % FAKE_UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller._action_rebuild(req,
                                              FAKE_UUID,
                                              body).obj
        self.assertTrue(self.rebuild_called)

    def test_create_instance_invalid_personality(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/flavors/3'

        def fake_create(*args, **kwargs):
            codec = 'utf8'
            content = 'b25zLiINCg0KLVJpY2hhcmQgQ$$%QQmFjaA=='
            start_position = 19
            end_position = 20
            msg = 'invalid start byte'
            raise UnicodeDecodeError(codec, content, start_position,
                                     end_position, msg)

        body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'image_ref': image_uuid,
                'flavor_ref': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                    },
                'personality': [
                    {
                        "path": "/etc/banner.txt",
                        "contents": "b25zLiINCg0KLVJpY2hhcmQgQ$$%QQmFjaA==",
                        },
                    ],
                },
            }

        self.stubs.Set(compute_api.API,
                       'create',
                       fake_create)

        req = fakes.HTTPRequestV3.blank(
            '/servers/%s/action' % FAKE_UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)


class TestServerRebuildRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestServerRebuildRequestXMLDeserializer, self).setUp()
        ext_info = plugins.LoadedExtensionInfo()
        controller = servers.ServersController(extension_info=ext_info)
        self.deserializer = servers.ActionDeserializer(controller)
        self.create_deserializer = servers.CreateDeserializer(controller)

    def test_rebuild_request_with_personality(self):
        serial_request = """
    <rebuild
        xmlns="http://docs.openstack.org/compute/api/v3"
        name="foobar"
        image_ref="1">
        <metadata>
            <meta key="My Server Name">Apache1</meta>
        </metadata>
        <personality>
            <file path="/etc/banner.txt">MQ==</file>
        </personality>
    </rebuild>
        """
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "rebuild": {
                "image_ref": "1",
                "name": "foobar",
                "metadata": {
                    "My Server Name": "Apache1"
                    },
                "personality": [{
                    "path": "/etc/banner.txt",
                    "contents": "MQ=="}
                    ]
                }
        }

        self.assertEquals(request['body'], expected)

    def test_create_request_with_personality(self):
        serial_request = """
    <server  xmlns="http://docs.openstack.org/compute/api/v3"
        image_ref="1"
        flavor_ref="2"
        name="new-server-test">
        <metadata>
           <meta key="My Server Name">Apache1</meta>
        </metadata>
        <personality>
           <file path="/etc/banner.txt">MQ==</file>
        </personality>
    </server>
        """
        request = self.create_deserializer.deserialize(serial_request)
        expected = {
            "server": {
                "flavor_ref": "2",
                "image_ref": "1",
                "metadata": {
                    "My Server Name": "Apache1"
                    },
                "name": "new-server-test",
                "personality": [
                    {
                    "contents": "MQ==",
                    "path": "/etc/banner.txt"
                    }]
                }
            }

        self.assertEquals(request['body'], expected)

    def test_empty_metadata_personality(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        image_ref="1"
        flavor_ref="2">
    <metadata/>
    <personality/>
</server>"""
        request = self.create_deserializer.deserialize(serial_request)
        expected = {
            "server": {
                "name": "new-server-test",
                "image_ref": "1",
                "flavor_ref": "2",
                "metadata": {},
                "personality": [],
            },
        }
        self.assertEquals(request['body'], expected)

    def test_multiple_personality_files(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        image_ref="1"
        flavor_ref="2">
    <personality>
        <file path="/etc/banner.txt">MQ==</file>
        <file path="/etc/hosts">Mg==</file>
    </personality>
</server>"""
        request = self.create_deserializer.deserialize(serial_request)
        expected = {
            "server": {
                "name": "new-server-test",
                "image_ref": "1",
                "flavor_ref": "2",
                "personality": [
                    {"path": "/etc/banner.txt", "contents": "MQ=="},
                    {"path": "/etc/hosts", "contents": "Mg=="},
                ],
            },
        }
        self.assertThat(request['body'], matchers.DictMatches(expected))
