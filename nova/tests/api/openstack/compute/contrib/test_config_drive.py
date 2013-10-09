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

import webob

from nova.api.openstack.compute.contrib import config_drive
from nova import db
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
import nova.tests.image.fake


class ConfigDriveTest(test.TestCase):

    def setUp(self):
        super(ConfigDriveTest, self).setUp()
        self.Controller = config_drive.Controller()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        nova.tests.image.fake.stub_out_image_service(self.stubs)
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
