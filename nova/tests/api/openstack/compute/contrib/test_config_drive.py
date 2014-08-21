# Copyright 2012 OpenStack Foundation
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

import webob

from nova.api.openstack.compute.contrib import config_drive
from nova.api.openstack.compute import servers
from nova.api.openstack import extensions
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import db
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests.image import fake


class ConfigDriveTest(test.TestCase):

    def setUp(self):
        super(ConfigDriveTest, self).setUp()
        self.Controller = config_drive.Controller()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fake.stub_out_image_service(self.stubs)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Config_drive'])

    def test_show(self):
        self.stubs.Set(db, 'instance_get',
                        fakes.fake_instance_get())
        self.stubs.Set(db, 'instance_get_by_uuid',
                        fakes.fake_instance_get())
        req = webob.Request.blank('/v2/fake/servers/1')
        req.headers['Content-Type'] = 'application/json'
        response = req.get_response(fakes.wsgi_app(init_only=('servers',)))
        self.assertEqual(response.status_int, 200)
        res_dict = jsonutils.loads(response.body)
        self.assertIn('config_drive', res_dict['server'])

    def test_detail_servers(self):
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fakes.fake_instance_get_all_by_filters())
        req = fakes.HTTPRequest.blank('/v2/fake/servers/detail')
        res = req.get_response(fakes.wsgi_app(init_only=('servers,')))
        server_dicts = jsonutils.loads(res.body)['servers']
        self.assertNotEqual(len(server_dicts), 0)
        for server_dict in server_dicts:
            self.assertIn('config_drive', server_dict)


class ServersControllerCreateTest(test.TestCase):

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTest, self).setUp()

        self.instance_cache_num = 0

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = servers.Controller(self.ext_mgr)

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': fakes.FAKE_UUID,
                'instance_type': dict(inst_type),
                'access_ip_v4': '1.2.3.4',
                'access_ip_v6': 'fead::1234',
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
                "root_device_name": inst.get('root_device_name', 'vda'),
            })

            return instance

        fake.stub_out_image_service(self.stubs)
        self.stubs.Set(db, 'instance_create', instance_create)

    def _test_create_extra(self, params):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        server.update(params)
        body = dict(server=server)
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        server = self.controller.create(req, body=body).obj['server']

    def test_create_instance_with_config_drive_disabled(self):
        params = {'config_drive': "False"}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsNone(kwargs['config_drive'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def _create_instance_body_of_config_drive(self, param):
        self.ext_mgr.extensions = {'os-config-drive': 'fake'}

        def create(*args, **kwargs):
            self.assertIn('config_drive', kwargs)
            return old_create(*args, **kwargs)

        old_create = compute_api.API.create
        self.stubs.Set(compute_api.API, 'create', create)
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/v2/fake/flavors/3'
        body = {
            'server': {
                'name': 'config_drive_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'config_drive': param,
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        return req, body

    def test_create_instance_with_config_drive(self):
        param = True
        req, body = self._create_instance_body_of_config_drive(param)
        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(fakes.FAKE_UUID, server['id'])

    def test_create_instance_with_config_drive_as_boolean_string(self):
        param = 'false'
        req, body = self._create_instance_body_of_config_drive(param)
        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(fakes.FAKE_UUID, server['id'])

    def test_create_instance_with_bad_config_drive(self):
        param = 12345
        req, body = self._create_instance_body_of_config_drive(param)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body=body)

    def test_create_instance_without_config_drive(self):
        param = True
        req, body = self._create_instance_body_of_config_drive(param)
        del body['server']['config_drive']
        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(fakes.FAKE_UUID, server['id'])

    def test_create_instance_with_empty_config_drive(self):
        param = ''
        req, body = self._create_instance_body_of_config_drive(param)
        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(fakes.FAKE_UUID, server['id'])
