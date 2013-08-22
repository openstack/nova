# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2011 OpenStack Foundation
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
from oslo.config import cfg

from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import servers
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import db
from nova.openstack.common import jsonutils
import nova.openstack.common.rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
import nova.tests.image.fake

CONF = cfg.CONF
MANUAL_INSTANCE_UUID = fakes.FAKE_UUID
AUTO_INSTANCE_UUID = fakes.FAKE_UUID.replace('a', 'b')

stub_instance = fakes.stub_instance

API_DISK_CONFIG = 'os-disk-config:disk_config'


def instance_addresses(context, instance_id):
    return None


class DiskConfigTestCase(test.TestCase):

    def setUp(self):
        super(DiskConfigTestCase, self).setUp()
        nova.tests.image.fake.stub_out_image_service(self.stubs)

        fakes.stub_out_nw_api(self.stubs)

        FAKE_INSTANCES = [
            fakes.stub_instance(1,
                                uuid=MANUAL_INSTANCE_UUID,
                                auto_disk_config=False),
            fakes.stub_instance(2,
                                uuid=AUTO_INSTANCE_UUID,
                                auto_disk_config=True)
        ]

        def fake_instance_get(context, id_):
            for instance in FAKE_INSTANCES:
                if id_ == instance['id']:
                    return instance

        self.stubs.Set(db, 'instance_get', fake_instance_get)

        def fake_instance_get_by_uuid(context, uuid, columns_to_join=None):
            for instance in FAKE_INSTANCES:
                if uuid == instance['uuid']:
                    return instance

        self.stubs.Set(db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid)

        def fake_instance_get_all(context, *args, **kwargs):
            return FAKE_INSTANCES

        self.stubs.Set(db, 'instance_get_all', fake_instance_get_all)
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_instance_get_all)

        def fake_instance_create(context, inst_, session=None):
            inst = fake_instance.fake_db_instance(**{
                    'id': 1,
                    'uuid': AUTO_INSTANCE_UUID,
                    'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
                    'updated_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
                    'progress': 0,
                    'name': 'instance-1',  # this is a property
                    'task_state': '',
                    'vm_state': '',
                    'auto_disk_config': inst_['auto_disk_config'],
                    'security_groups': inst_['security_groups'],
                    })

            def fake_instance_get_for_create(context, id_, *args, **kwargs):
                return (inst, inst)

            self.stubs.Set(db, 'instance_update_and_get_original',
                           fake_instance_get_for_create)

            def fake_instance_get_all_for_create(context, *args, **kwargs):
                return [inst]
            self.stubs.Set(db, 'instance_get_all',
                           fake_instance_get_all_for_create)
            self.stubs.Set(db, 'instance_get_all_by_filters',
                           fake_instance_get_all_for_create)

            def fake_instance_add_security_group(context, instance_id,
                                                 security_group_id):
                pass

            self.stubs.Set(db,
                           'instance_add_security_group',
                           fake_instance_add_security_group)

            return inst

        self.stubs.Set(db, 'instance_create', fake_instance_create)

        self.app = fakes.wsgi_app_v3(init_only=('servers',
                                                'os-disk-config'))
        CONF.set_override('extensions_blacklist', 'os-disk-config',
                          'osapi_v3')
        self.no_disk_config_app = fakes.wsgi_app_v3(init_only=('servers'))

    def tearDown(self):
        super(DiskConfigTestCase, self).tearDown()
        nova.tests.image.fake.FakeImageService_reset()

    def assertDiskConfig(self, dict_, value):
        self.assert_(API_DISK_CONFIG in dict_)
        self.assertEqual(dict_[API_DISK_CONFIG], value)

    def test_show_server(self):
        req = fakes.HTTPRequestV3.blank(
            '/v3/servers/%s' % MANUAL_INSTANCE_UUID)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

        req = fakes.HTTPRequestV3.blank(
            '/v3/servers/%s' % AUTO_INSTANCE_UUID)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_detail_servers(self):
        req = fakes.HTTPRequestV3.blank('/v3/servers/detail')
        res = req.get_response(self.app)
        server_dicts = jsonutils.loads(res.body)['servers']

        expectations = ['MANUAL', 'AUTO']
        for server_dict, expected in zip(server_dicts, expectations):
            self.assertDiskConfig(server_dict, expected)

    def test_create_server_override_auto_with_disk_config_enabled(self):
        req = fakes.HTTPRequestV3.blank('/v3/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                'name': 'server_test',
                'image_ref': 'cedef40a-ed67-4d10-800e-17455edce175',
                'flavor_ref': '1',
                API_DISK_CONFIG: 'AUTO'
            },
        }

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIn('auto_disk_config', kwargs)
            self.assertTrue(kwargs['auto_disk_config'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_create_server_override_manual(self):
        req = fakes.HTTPRequestV3.blank('/v3/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                    'name': 'server_test',
                    'image_ref': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'flavor_ref': '1',
                    API_DISK_CONFIG: 'MANUAL'
                    },
               }

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

    def test_create_server_detect_from_image(self):
        """If user doesn't pass in diskConfig for server, use image metadata
        to specify AUTO or MANUAL.
        """
        req = fakes.HTTPRequestV3.blank('/v3/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                    'name': 'server_test',
                    'image_ref': 'a440c04b-79fa-479c-bed1-0b816eaec379',
                    'flavor_ref': '1',
                    },
               }

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

        req = fakes.HTTPRequestV3.blank('/v3/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                    'name': 'server_test',
                    'image_ref': '70a599e0-31e7-49b7-b260-868f441e862b',
                    'flavor_ref': '1',
                    },
               }

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_update_server_invalid_disk_config(self):
        # Return BadRequest if user passes an invalid diskConfig value.
        req = fakes.HTTPRequestV3.blank(
            '/v3/servers/%s' % MANUAL_INSTANCE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {API_DISK_CONFIG: 'server_test'}}
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 400)
        expected_msg = ('{"badRequest": {"message": "%s must be either'
                        ' \'MANUAL\' or \'AUTO\'.", "code": 400}}' %
                        API_DISK_CONFIG)
        self.assertEqual(res.body, expected_msg)

    def test_rebuild_instance_with_disk_config(self):
        info = dict(image_href_in_call=None)

        def rebuild(self2, context, instance, image_href, *args, **kwargs):
            self.assertIn('auto_disk_config', kwargs)
            self.assertFalse(kwargs['auto_disk_config'])
            info['image_href_in_call'] = image_href

        self.stubs.Set(compute_api.API, 'rebuild', rebuild)

        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/os-images/%s' % image_uuid
        body = {
            'rebuild': {
                'image_ref': image_uuid,
                'os-disk-config:disk_config': 'MANUAL',
            },
        }

        req = fakes.HTTPRequestV3.blank(
            '/v3/servers/%s/action' % AUTO_INSTANCE_UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(info['image_href_in_call'], image_uuid)

    def test_resize_instance_with_disk_config(self):
        self.resize_called = False

        def resize_mock(*args, **kwargs):
            self.assertIn('auto_disk_config', kwargs)
            self.assertFalse(kwargs['auto_disk_config'])
            self.resize_called = True

        self.stubs.Set(compute_api.API, 'resize', resize_mock)

        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/os-images/%s' % image_uuid
        body = {
            'resize': {
                "flavor_ref": "2",
                'os-disk-config:disk_config': 'MANUAL',
            },
        }

        req = fakes.HTTPRequestV3.blank(
            '/v3/servers/%s/action' % AUTO_INSTANCE_UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)

    def test_update_instance_with_disk_config_disabled(self):
        self.update_called = False

        def update(self2, update_dict):
            self.assertNotIn('auto_disk_config', update_dict)
            self.update_called = True

        def cache_db_instance(*arg, **kwargs):
            pass

        def save(self2, context, expected_task_state=None):
            pass

        self.stubs.Set(nova.objects.instance.Instance, 'save',
                       save)
        self.stubs.Set(nova.api.openstack.wsgi.Request,
                       "cache_db_instance", cache_db_instance)
        self.stubs.Set(nova.objects.instance.Instance, 'update',
                       update)

        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/os-images/%s' % image_uuid
        body = {
            'server': {
                "name": "update_test",
                'os-disk-config:disk_config': 'MANUAL',
            },
        }

        req = fakes.HTTPRequestV3.blank(
            '/v3/servers/%s' % AUTO_INSTANCE_UUID)
        req.method = 'PUT'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.no_disk_config_app)
        self.assertTrue(self.update_called)

    def test_update_instance_with_disk_config(self):
        self.update_called = False

        def update(self2, update_dict):
            self.assertIn('auto_disk_config', update_dict)
            self.assertFalse(update_dict['auto_disk_config'])
            self.update_called = True

        def cache_db_instance(*arg, **kwargs):
            pass

        def save(self2, context, expected_task_state=None):
            pass

        self.stubs.Set(nova.objects.instance.Instance, 'save',
                       save)
        self.stubs.Set(nova.api.openstack.wsgi.Request,
                       "cache_db_instance", cache_db_instance)
        self.stubs.Set(nova.objects.instance.Instance, 'update',
                       update)

        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/os-images/%s' % image_uuid
        body = {
            'server': {
                "name": "update_test",
                'os-disk-config:disk_config': 'MANUAL',
            },
        }

        req = fakes.HTTPRequestV3.blank('/v3/servers/%s' % AUTO_INSTANCE_UUID)
        req.method = 'PUT'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertTrue(self.update_called)


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
        CONF.set_override('extensions_blacklist', 'os-disk-config',
                          'osapi_v3')
        self.no_disk_config_controller = servers.ServersController(
            extension_info=ext_info)

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/v3/os-images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = {
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': MANUAL_INSTANCE_UUID,
                'instance_type': dict(inst_type),
                'access_ip_v4': '1.2.3.4',
                'access_ip_v6': 'fead::1234',
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "user_data": None,
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
            }

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

        def fake_method(*args, **kwargs):
            pass

        def queue_get_for(context, *args):
            return 'network_topic'

        def return_security_group(context, instance_id, security_group_id):
            pass

        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        nova.tests.image.fake.stub_out_image_service(self.stubs)
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(db, 'instance_system_metadata_update',
                       fake_method)
        self.stubs.Set(db, 'instance_get', instance_get)
        self.stubs.Set(db, 'instance_update', instance_update)
        self.stubs.Set(nova.openstack.common.rpc, 'cast', fake_method)

        return_server = fakes.fake_instance_get()
        return_servers = fakes.fake_instance_get_all_by_filters()
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       return_server)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)

    def test_create_server_override_auto_with_disk_config_disabled(self):
        req = fakes.HTTPRequestV3.blank('/v3/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                'name': 'server_test',
                'image_ref': 'cedef40a-ed67-4d10-800e-17455edce175',
                'flavor_ref': '1',
                'os-disk-config:disk_config': 'AUTO'
            },
        }
        self.create_called = False
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('os-disk-config:disk_config', kwargs)
            self.assertNotIn('auto_disk_config', kwargs)
            self.create_called = True
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        req.body = jsonutils.dumps(body)
        res = self.no_disk_config_controller.create(
            req,
            body).obj['server']
        self.assertTrue(self.create_called)

    def test_rebuild_instance_with_disk_config_disabled(self):
        info = dict(image_href_in_call=None)

        def rebuild(self2, context, instance, image_href, *args, **kwargs):
            self.assertNotIn('os-disk-config:disk_config', kwargs)
            self.assertNotIn('auto_disk_config', kwargs)
            info['image_href_in_call'] = image_href

        self.stubs.Set(compute_api.API, 'rebuild', rebuild)
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        body = {
            'rebuild': {
                'image_ref': image_uuid,
                'os-disk-config:disk_config': 'MANUAL',
            },
        }

        req = fakes.HTTPRequestV3.blank(
            '/v3/servers/%s/action' % AUTO_INSTANCE_UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = self.no_disk_config_controller._action_rebuild(
            req,
            AUTO_INSTANCE_UUID,
            body).obj
        self.assertEqual(info['image_href_in_call'], image_uuid)

    def test_resize_instance_with_disk_config_disabled(self):
        self.resize_called = False

        def resize_mock(*args, **kwargs):
            self.assertNotIn('os-disk-config:disk_config', kwargs)
            self.assertNotIn('auto_disk_config', kwargs)
            self.resize_called = True

        self.stubs.Set(compute_api.API, 'resize', resize_mock)

        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/os-images/%s' % image_uuid
        body = {
            'resize': {
                "flavor_ref": "2",
                'os-disk-config:disk_config': 'MANUAL',
            },
        }

        req = fakes.HTTPRequestV3.blank(
            '/v3/servers/%s/action' % AUTO_INSTANCE_UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        self.no_disk_config_controller._action_resize(
            req,
            AUTO_INSTANCE_UUID,
            body)
        self.assertTrue(self.resize_called)


class TestServerCreateRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestServerCreateRequestXMLDeserializer, self).setUp()
        ext_info = plugins.LoadedExtensionInfo()
        controller = servers.ServersController(extension_info=ext_info)
        self.create_deserializer = servers.CreateDeserializer(controller)
        self.deserializer = servers.ActionDeserializer(controller)
        CONF.set_override('extensions_blacklist', 'os-disk-config',
                          'osapi_v3')
        no_disk_config_controller = servers.ServersController(
            extension_info=ext_info)
        self.create_no_disk_config_deserializer =\
            servers.CreateDeserializer(no_disk_config_controller)
        self.no_disk_config_deserializer =\
            servers.ActionDeserializer(no_disk_config_controller)

    def test_create_request_with_disk_config(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v3"
        xmlns:os-disk-config=
        "http://docs.openstack.org/compute/ext/disk_config/api/v3"
        name="disk_config_test"
        image_ref="1"
        flavor_ref="1"
        os-disk-config:disk_config="AUTO"/>"""
        request = self.create_deserializer.deserialize(serial_request)
        expected = {
            "server": {
            "name": "disk_config_test",
            "image_ref": "1",
            "flavor_ref": "1",
            "os-disk-config:disk_config": "AUTO",
            },
        }

        self.assertEquals(request['body'], expected)

    def test_create_request_with_disk_config_disabled(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v3"
        xmlns:os-disk-config=
        "http://docs.openstack.org/compute/ext/disk_config/api/v3"
        name="disk_config_test"
        image_ref="1"
        flavor_ref="1"
        os-disk-config:disk_config="AUTO"/>"""
        request = self.create_no_disk_config_deserializer.\
            deserialize(serial_request)
        expected = {
            "server": {
            "name": "disk_config_test",
            "image_ref": "1",
            "flavor_ref": "1",
            },
        }

        self.assertEquals(request['body'], expected)

    def test_rebuild_request(self):
        serial_request = """
     <rebuild xmlns="http://docs.openstack.org/compute/api/v3"
        xmlns:os-disk-config=
        "http://docs.openstack.org/compute/ext/disk_config/api/v3"
        os-disk-config:disk_config="MANUAL" image_ref="1"/>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "rebuild": {
                "image_ref": "1",
                "os-disk-config:disk_config": "MANUAL",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_rebuild_request_with_disk_config_disabled(self):
        serial_request = """
     <rebuild xmlns="http://docs.openstack.org/compute/api/v3"
        xmlns:os-disk-config=
        "http://docs.openstack.org/compute/ext/disk_config/api/v3"
        os-disk-config:disk_config="MANUAL" image_ref="1"/>"""
        request = self.no_disk_config_deserializer.deserialize(serial_request)
        expected = {
            "rebuild": {
                "image_ref": "1",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_resize_request(self):
        serial_request = """
        <resize xmlns="http://docs.openstack.org/compute/api/v3"
        xmlns:os-disk-config=
        "http://docs.openstack.org/compute/ext/disk_config/api/v3"
        os-disk-config:disk_config="MANUAL" flavor_ref="1"/>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "resize": {
                "flavor_ref": "1",
                "os-disk-config:disk_config": "MANUAL",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_resize_request_with_disk_config_disabled(self):
        serial_request = """
        <resize xmlns="http://docs.openstack.org/compute/api/v3"
        xmlns:os-disk-config=
        "http://docs.openstack.org/compute/ext/disk_config/api/v3"
        os-disk-config:disk_config="MANUAL" flavor_ref="1"/>"""
        request = self.no_disk_config_deserializer.deserialize(serial_request)
        expected = {
            "resize": {
                "flavor_ref": "1",
            },
        }
        self.assertEquals(request['body'], expected)
