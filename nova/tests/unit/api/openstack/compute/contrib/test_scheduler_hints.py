# Copyright 2011 OpenStack Foundation
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
from oslo.serialization import jsonutils

from nova.api.openstack import compute
from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import servers as servers_v21
from nova.api.openstack.compute import servers as servers_v2
from nova.api.openstack import extensions
import nova.compute.api
from nova.compute import flavors
from nova import db
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.image import fake


UUID = fakes.FAKE_UUID


CONF = cfg.CONF


class SchedulerHintsTestCaseV21(test.TestCase):

    def setUp(self):
        super(SchedulerHintsTestCaseV21, self).setUp()
        self.fake_instance = fakes.stub_instance(1, uuid=UUID)
        self._set_up_router()

    def _set_up_router(self):
        self.app = compute.APIRouterV3(init_only=('servers',
                                                  'os-scheduler-hints'))

    def _get_request(self):
        return fakes.HTTPRequestV3.blank('/servers')

    def test_create_server_without_hints(self):

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], {})
            return ([self.fake_instance], '')

        self.stubs.Set(nova.compute.api.API, 'create', fake_create)

        req = self._get_request()
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
               }}

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(202, res.status_int)

    def test_create_server_with_hints(self):

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], {'group': 'foo'})
            return ([self.fake_instance], '')

        self.stubs.Set(nova.compute.api.API, 'create', fake_create)

        req = self._get_request()
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
            },
            'os:scheduler_hints': {'group': 'foo'},
        }

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(202, res.status_int)

    def _create_server_with_scheduler_hints_bad_request(self, param):
        req = self._get_request()
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
            },
            'os:scheduler_hints': param,
        }
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(400, res.status_int)

    def test_create_server_bad_hints_non_dict(self):
        self._create_server_with_scheduler_hints_bad_request('non-dict')

    def test_create_server_bad_hints_long_group(self):
        param = {'group': 'a' * 256}
        self._create_server_with_scheduler_hints_bad_request(param)


class SchedulerHintsTestCaseV2(SchedulerHintsTestCaseV21):

    def _set_up_router(self):
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Scheduler_hints'])
        self.app = compute.APIRouter(init_only=('servers',))

    def _get_request(self):
        return fakes.HTTPRequest.blank('/fake/servers')

    def test_create_server_bad_hints_long_group(self):
        # NOTE: v2.0 API cannot handle this bad request case now.
        # We skip this test for v2.0.
        pass


class ServersControllerCreateTestV21(test.TestCase):

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTestV21, self).setUp()

        self.instance_cache_num = 0
        self._set_up_controller()

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': fakes.FAKE_UUID,
                'instance_type': inst_type,
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

    def _set_up_controller(self):
        ext_info = plugins.LoadedExtensionInfo()
        CONF.set_override('extensions_blacklist', 'os-scheduler-hints',
                          'osapi_v3')
        self.no_scheduler_hints_controller = servers_v21.ServersController(
            extension_info=ext_info)

    def _verify_availability_zone(self, **kwargs):
        self.assertNotIn('scheduler_hints', kwargs)

    def _get_request(self):
        return fakes.HTTPRequestV3.blank('/servers')

    def _test_create_extra(self, params):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        body = dict(server=server)
        body.update(params)
        req = self._get_request()
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        server = self.no_scheduler_hints_controller.create(
                     req, body=body).obj['server']

    def test_create_instance_with_scheduler_hints_disabled(self):
        hints = {'same_host': '48e6a9f6-30af-47e0-bc04-acaed113bb4e'}
        params = {'OS-SCH-HNT:scheduler_hints': hints}
        old_create = nova.compute.api.API.create

        def create(*args, **kwargs):
            self._verify_availability_zone(**kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(nova.compute.api.API, 'create', create)
        self._test_create_extra(params)


class ServersControllerCreateTestV2(ServersControllerCreateTestV21):

    def _set_up_controller(self):
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.no_scheduler_hints_controller = servers_v2.Controller(
                                                 self.ext_mgr)

    def _verify_availability_zone(self, **kwargs):
        self.assertEqual(kwargs['scheduler_hints'], {})

    def _get_request(self):
        return fakes.HTTPRequest.blank('/fake/servers')
