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

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils

from nova.api.openstack.compute import extension_info
from nova.api.openstack.compute import servers as servers_v21
from nova.compute import api as compute_api
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake
from nova.tests import uuidsentinel as uuids

CONF = cfg.CONF


class ConfigDriveTestV21(test.TestCase):
    base_url = '/v2/fake/servers/'

    def _setup_wsgi(self):
        self.app = fakes.wsgi_app_v21()

    def setUp(self):
        super(ConfigDriveTestV21, self).setUp()
        fakes.stub_out_networking(self)
        fake.stub_out_image_service(self)
        fakes.stub_out_secgroup_api(self)
        self._setup_wsgi()

    def test_show(self):
        self.stub_out('nova.db.instance_get',
                      fakes.fake_instance_get())
        self.stub_out('nova.db.instance_get_by_uuid',
                      fakes.fake_instance_get())
        # NOTE(sdague): because of the way extensions work, we have to
        # also stub out the Request compute cache with a real compute
        # object. Delete this once we remove all the gorp of
        # extensions modifying the server objects.
        self.stub_out('nova.api.openstack.wsgi.Request.get_db_instance',
                      fakes.fake_compute_get())
        req = fakes.HTTPRequest.blank(self.base_url + uuids.sentinel)
        req.headers['Content-Type'] = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(response.status_int, 200)
        res_dict = jsonutils.loads(response.body)
        self.assertIn('config_drive', res_dict['server'])

    @mock.patch('nova.compute.api.API.get_all')
    def test_detail_servers(self, mock_get_all):
        # NOTE(danms): Orphan these fakes (no context) so that we
        # are sure that the API is requesting what it needs without
        # having to lazy-load.
        mock_get_all.return_value = objects.InstanceList(
            objects=[fakes.stub_instance_obj(ctxt=None, id=1),
                     fakes.stub_instance_obj(ctxt=None, id=2)])
        req = fakes.HTTPRequest.blank(self.base_url + 'detail')
        res = req.get_response(self.app)
        server_dicts = jsonutils.loads(res.body)['servers']
        self.assertNotEqual(len(server_dicts), 0)
        for server_dict in server_dicts:
            self.assertIn('config_drive', server_dict)


class ServersControllerCreateTestV21(test.TestCase):
    base_url = '/v2/fake/'
    bad_request = exception.ValidationError

    def _set_up_controller(self):
        ext_info = extension_info.LoadedExtensionInfo()
        self.controller = servers_v21.ServersController(
            extension_info=ext_info)

    def _verify_config_drive(self, **kwargs):
        self.assertNotIn('config_drive', kwargs)

    def _initialize_extension(self):
        pass

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTestV21, self).setUp()

        self.instance_cache_num = 0
        fakes.stub_out_nw_api(self)
        self._set_up_controller()

        fake.stub_out_image_service(self)

        def create_db_entry_for_new_instance(*args, **kwargs):
            instance = args[4]
            instance.uuid = fakes.FAKE_UUID
            return instance

        self.stub_out('nova.compute.api.API.create_db_entry_for_new_instance',
                      create_db_entry_for_new_instance)

    def _test_create_extra(self, params):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        server.update(params)
        body = dict(server=server)
        req = fakes.HTTPRequest.blank(self.base_url + 'servers')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        server = self.controller.create(req, body=body).obj['server']

    def _create_instance_body_of_config_drive(self, param):
        self._initialize_extension()

        def create(*args, **kwargs):
            self.assertIn('config_drive', kwargs)
            return old_create(*args, **kwargs)

        old_create = compute_api.API.create
        self.stub_out('nova.compute.api.API.create', create)
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = ('http://localhost' + self.base_url + 'flavors/3')
        body = {
            'server': {
                'name': 'config_drive_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'config_drive': param,
            },
        }

        req = fakes.HTTPRequest.blank(self.base_url + 'servers')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
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
        self.assertRaises(self.bad_request,
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
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)
