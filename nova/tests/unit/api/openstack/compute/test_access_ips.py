# Copyright 2013 IBM Corp.
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

from nova.api.openstack.compute import servers as servers_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake

v4_key = "accessIPv4"
v6_key = "accessIPv6"


class AccessIPsAPIValidationTestV21(test.TestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        super(AccessIPsAPIValidationTestV21, self).setUp()

        def fake_save(context, **kwargs):
            pass

        def fake_rebuild(*args, **kwargs):
            pass

        fakes.stub_out_nw_api(self)
        self._set_up_controller()
        fake.stub_out_image_service(self)
        self.stub_out('nova.db.api.instance_get_by_uuid',
                      fakes.fake_instance_get())
        self.stub_out('nova.objects.instance.Instance.save', fake_save)
        self.stub_out('nova.compute.api.API.rebuild', fake_rebuild)

        self.req = fakes.HTTPRequest.blank('')

    def _set_up_controller(self):
        self.controller = servers_v21.ServersController()

    def _verify_update_access_ip(self, res_dict, params):
        for key, value in params.items():
            value = value or ''
            self.assertEqual(res_dict['server'][key], value)

    def _test_create(self, params):
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                'flavorRef': 'http://localhost/123/flavors/3',
            },
        }
        body['server'].update(params)
        res_dict = self.controller.create(self.req, body=body).obj
        return res_dict

    def _test_update(self, params):
        body = {
            'server': {
            },
        }
        body['server'].update(params)

        res_dict = self.controller.update(self.req, fakes.FAKE_UUID, body=body)
        self._verify_update_access_ip(res_dict, params)

    def _test_rebuild(self, params):
        body = {
            'rebuild': {
                'imageRef': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
            },
        }
        body['rebuild'].update(params)
        self.controller._action_rebuild(self.req, fakes.FAKE_UUID, body=body)

    def test_create_server_with_access_ipv4(self):
        params = {v4_key: '192.168.0.10'}
        self._test_create(params)

    def test_create_server_with_access_ip_pass_disabled(self):
        # test with admin passwords disabled See lp bug 921814
        self.flags(enable_instance_password=False, group='api')
        params = {v4_key: '192.168.0.10',
                  v6_key: '2001:db8::9abc'}
        res = self._test_create(params)

        server = res['server']
        self.assertNotIn("admin_password", server)

    def test_create_server_with_invalid_access_ipv4(self):
        params = {v4_key: '1.1.1.1.1.1'}
        self.assertRaises(self.validation_error, self._test_create, params)

    def test_create_server_with_access_ipv6(self):
        params = {v6_key: '2001:db8::9abc'}
        self._test_create(params)

    def test_create_server_with_invalid_access_ipv6(self):
        params = {v6_key: 'fe80:::::::'}
        self.assertRaises(self.validation_error, self._test_create, params)

    def test_update_server_with_access_ipv4(self):
        params = {v4_key: '192.168.0.10'}
        self._test_update(params)

    def test_update_server_with_invalid_access_ipv4(self):
        params = {v4_key: '1.1.1.1.1.1'}
        self.assertRaises(self.validation_error, self._test_update, params)

    def test_update_server_with_access_ipv6(self):
        params = {v6_key: '2001:db8::9abc'}
        self._test_update(params)

    def test_update_server_with_invalid_access_ipv6(self):
        params = {v6_key: 'fe80:::::::'}
        self.assertRaises(self.validation_error, self._test_update, params)

    def test_rebuild_server_with_access_ipv4(self):
        params = {v4_key: '192.168.0.10'}
        self._test_rebuild(params)

    def test_rebuild_server_with_invalid_access_ipv4(self):
        params = {v4_key: '1.1.1.1.1.1'}
        self.assertRaises(self.validation_error, self._test_rebuild,
                          params)

    def test_rebuild_server_with_access_ipv6(self):
        params = {v6_key: '2001:db8::9abc'}
        self._test_rebuild(params)

    def test_rebuild_server_with_invalid_access_ipv6(self):
        params = {v6_key: 'fe80:::::::'}
        self.assertRaises(self.validation_error, self._test_rebuild,
                          params)
