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

import webob

from nova import compute
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes


UUID = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
last_add_fixed_ip = (None, None)
last_remove_fixed_ip = (None, None)


def compute_api_add_fixed_ip(self, context, instance, network_id):
    global last_add_fixed_ip

    last_add_fixed_ip = (instance['uuid'], network_id)


def compute_api_remove_fixed_ip(self, context, instance, address):
    global last_remove_fixed_ip

    last_remove_fixed_ip = (instance['uuid'], address)


def compute_api_get(self, context, instance_id, want_objects=False):
    instance = instance_obj.Instance()
    instance.uuid = instance_id
    instance.id = 1
    instance.vm_state = 'fake'
    instance.task_state = 'fake'
    instance.obj_reset_changes()
    return instance


class FixedIpTest(test.NoDBTestCase):
    def setUp(self):
        super(FixedIpTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(compute.api.API, "add_fixed_ip",
                       compute_api_add_fixed_ip)
        self.stubs.Set(compute.api.API, "remove_fixed_ip",
                       compute_api_remove_fixed_ip)
        self.stubs.Set(compute.api.API, 'get', compute_api_get)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Multinic'])
        self.app = fakes.wsgi_app(init_only=('servers',))

    def test_add_fixed_ip(self):
        global last_add_fixed_ip
        last_add_fixed_ip = (None, None)

        body = dict(addFixedIp=dict(networkId='test_net'))
        req = webob.Request.blank('/v2/fake/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 202)
        self.assertEqual(last_add_fixed_ip, (UUID, 'test_net'))

    def test_add_fixed_ip_no_network(self):
        global last_add_fixed_ip
        last_add_fixed_ip = (None, None)

        body = dict(addFixedIp=dict())
        req = webob.Request.blank('/v2/fake/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 422)
        self.assertEqual(last_add_fixed_ip, (None, None))

    def test_remove_fixed_ip(self):
        global last_remove_fixed_ip
        last_remove_fixed_ip = (None, None)

        body = dict(removeFixedIp=dict(address='10.10.10.1'))
        req = webob.Request.blank('/v2/fake/servers/%s/action' % UUID)
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
        req = webob.Request.blank('/v2/fake/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 422)
        self.assertEqual(last_remove_fixed_ip, (None, None))
