# Copyright 2011 OpenStack LLC.
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

import json

import webob

from nova import compute
from nova import exception
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS
FLAGS.verbose = True


def fake_compute_get(*args, **kwargs):
    return fakes.stub_instance(1, task_state="kayaking",
                               vm_state="slightly crunchy",
                               power_state="empowered")


class ExtendedStatusTest(test.TestCase):

    def setUp(self):
        super(ExtendedStatusTest, self).setUp()
        self.uuid = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
        self.url = '/v2/fake/servers/%s' % self.uuid
        fakes.stub_out_nw_api(self.stubs)
        self.flags(allow_admin_api=True)
        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)

    def _make_request(self):
        req = webob.Request.blank(self.url)
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        return res

    def assertServerStates(self, server, vm_state, power_state, task_state):
        self.assertEqual(server.get('OS-EXT-STS:vm_state'), vm_state)
        self.assertEqual(server.get('OS-EXT-STS:power_state'), power_state)
        self.assertEqual(server.get('OS-EXT-STS:task_state'), task_state)

    def test_extended_status(self):
        res = self._make_request()
        body = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertServerStates(body['server'],
                                vm_state='slightly crunchy',
                                power_state='empowered',
                                task_state='kayaking')

    def test_extended_status_no_instance_fails(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound()

        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)
        res = self._make_request()

        self.assertEqual(res.status_int, 404)
