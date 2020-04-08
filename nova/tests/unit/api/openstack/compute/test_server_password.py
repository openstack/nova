# Copyright 2012 Nebula, Inc.
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

from nova.api.openstack.compute import server_password \
    as server_password_v21
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


class ServerPasswordTestV21(test.NoDBTestCase):
    content_type = 'application/json'
    server_password = server_password_v21
    delete_call = 'self.controller.clear'

    def setUp(self):
        super(ServerPasswordTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        self.stub_out('nova.compute.api.API.get',
                      lambda self, ctxt, *a, **kw:
                          fake_instance.fake_instance_obj(
                          ctxt,
                          system_metadata={},
                          expected_attrs=['system_metadata']))
        self.password = 'fakepass'
        self.controller = self.server_password.ServerPasswordController()
        self.fake_req = fakes.HTTPRequest.blank('')

        def fake_convert_password(context, password):
            self.password = password
            return {}

        self.stub_out('nova.api.metadata.password.extract_password',
                      lambda i: self.password)
        self.stub_out('nova.api.metadata.password.convert_password',
                      fake_convert_password)

    def test_get_password(self):
        res = self.controller.index(self.fake_req, 'fake')
        self.assertEqual(res['password'], 'fakepass')

    def test_reset_password(self):
        with mock.patch('nova.objects.Instance._save_flavor'):
            eval(self.delete_call)(self.fake_req, 'fake')
        self.assertEqual(eval(self.delete_call).wsgi_code, 204)

        res = self.controller.index(self.fake_req, 'fake')
        self.assertEqual(res['password'], '')
