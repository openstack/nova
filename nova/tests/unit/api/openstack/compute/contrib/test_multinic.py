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

import mock
from oslo.serialization import jsonutils
import webob

from nova import compute
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes


UUID = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
last_add_fixed_ip = (None, None)
last_remove_fixed_ip = (None, None)


def compute_api_add_fixed_ip(self, context, instance, network_id):
    global last_add_fixed_ip

    last_add_fixed_ip = (instance['uuid'], network_id)


def compute_api_remove_fixed_ip(self, context, instance, address):
    global last_remove_fixed_ip

    last_remove_fixed_ip = (instance['uuid'], address)


def compute_api_get(self, context, instance_id, want_objects=False,
                    expected_attrs=None):
    instance = objects.Instance()
    instance.uuid = instance_id
    instance.id = 1
    instance.vm_state = 'fake'
    instance.task_state = 'fake'
    instance.obj_reset_changes()
    return instance


class FixedIpTestV21(test.NoDBTestCase):
    def setUp(self):
        super(FixedIpTestV21, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(compute.api.API, "add_fixed_ip",
                       compute_api_add_fixed_ip)
        self.stubs.Set(compute.api.API, "remove_fixed_ip",
                       compute_api_remove_fixed_ip)
        self.stubs.Set(compute.api.API, 'get', compute_api_get)
        self.app = self._get_app()

    def _get_app(self):
        return fakes.wsgi_app_v21(init_only=('servers', 'os-multinic'))

    def _get_url(self):
        return '/v2/fake'

    def test_add_fixed_ip(self):
        global last_add_fixed_ip
        last_add_fixed_ip = (None, None)

        body = dict(addFixedIp=dict(networkId='test_net'))
        req = webob.Request.blank(
            self._get_url() + '/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 202)
        self.assertEqual(last_add_fixed_ip, (UUID, 'test_net'))

    def _test_add_fixed_ip_bad_request(self, body):
        req = webob.Request.blank(
            self._get_url() + '/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'
        resp = req.get_response(self.app)
        self.assertEqual(400, resp.status_int)

    def test_add_fixed_ip_empty_network_id(self):
        body = {'addFixedIp': {'network_id': ''}}
        self._test_add_fixed_ip_bad_request(body)

    def test_add_fixed_ip_network_id_bigger_than_36(self):
        body = {'addFixedIp': {'network_id': 'a' * 37}}
        self._test_add_fixed_ip_bad_request(body)

    def test_add_fixed_ip_no_network(self):
        global last_add_fixed_ip
        last_add_fixed_ip = (None, None)

        body = dict(addFixedIp=dict())
        req = webob.Request.blank(
            self._get_url() + '/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 400)
        self.assertEqual(last_add_fixed_ip, (None, None))

    @mock.patch.object(compute.api.API, 'add_fixed_ip')
    def test_add_fixed_ip_no_more_ips_available(self, mock_add_fixed_ip):
        mock_add_fixed_ip.side_effect = exception.NoMoreFixedIps(net='netid')

        body = dict(addFixedIp=dict(networkId='test_net'))
        req = webob.Request.blank(
            self._get_url() + '/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 400)

    def test_remove_fixed_ip(self):
        global last_remove_fixed_ip
        last_remove_fixed_ip = (None, None)

        body = dict(removeFixedIp=dict(address='10.10.10.1'))
        req = webob.Request.blank(
            self._get_url() + '/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 202)
        self.assertEqual(last_remove_fixed_ip, (UUID, '10.10.10.1'))

    def test_remove_fixed_ip_no_address(self):
        global last_remove_fixed_ip
        last_remove_fixed_ip = (None, None)

        body = dict(removeFixedIp=dict())
        req = webob.Request.blank(
            self._get_url() + '/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 400)
        self.assertEqual(last_remove_fixed_ip, (None, None))

    def test_remove_fixed_ip_invalid_address(self):
        body = {'remove_fixed_ip': {'address': ''}}
        req = webob.Request.blank(
            self._get_url() + '/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'
        resp = req.get_response(self.app)
        self.assertEqual(400, resp.status_int)

    @mock.patch.object(compute.api.API, 'remove_fixed_ip',
        side_effect=exception.FixedIpNotFoundForSpecificInstance(
            instance_uuid=UUID, ip='10.10.10.1'))
    def test_remove_fixed_ip_not_found(self, _remove_fixed_ip):

        body = {'remove_fixed_ip': {'address': '10.10.10.1'}}
        req = webob.Request.blank(
            self._get_url() + '/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(400, resp.status_int)


class FixedIpTestV2(FixedIpTestV21):
    def setUp(self):
        super(FixedIpTestV2, self).setUp()
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Multinic'])

    def _get_app(self):
        return fakes.wsgi_app(init_only=('servers',))

    def test_remove_fixed_ip_invalid_address(self):
        # NOTE(cyeoh): This test is disabled for the V2 API because it is
        # has poorer input validation.
        pass
