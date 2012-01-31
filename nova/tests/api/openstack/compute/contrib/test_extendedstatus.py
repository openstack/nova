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


UUID1 = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
UUID2 = '65ba6da7-3b9a-4b71-bc08-f81fbdb72d1a'
UUID3 = 'b55c356f-4c22-47ed-b622-cc6ba0f4b1ab'


def fake_compute_get(*args, **kwargs):
    return fakes.stub_instance(1, uuid=UUID3, task_state="kayaking",
            vm_state="slightly crunchy", power_state="empowered")


def fake_compute_get_all(*args, **kwargs):
    return [
        fakes.stub_instance(1, uuid=UUID1, task_state="task%s" % UUID1,
                vm_state="vm%s" % UUID1, power_state="power%s" % UUID1),
        fakes.stub_instance(2, uuid=UUID2, task_state="task%s" % UUID2,
                vm_state="vm%s" % UUID2, power_state="power%s" % UUID2),
    ]


class ExtendedStatusTest(test.TestCase):

    def setUp(self):
        super(ExtendedStatusTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        return res

    def assertServerStates(self, server, vm_state, power_state, task_state):
        self.assertEqual(server.get('OS-EXT-STS:vm_state'), vm_state)
        self.assertEqual(server.get('OS-EXT-STS:power_state'), power_state)
        self.assertEqual(server.get('OS-EXT-STS:task_state'), task_state)

    def test_show(self):
        url = '/v2/fake/servers/%s' % UUID3
        res = self._make_request(url)
        body = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertServerStates(body['server'],
                                vm_state='slightly crunchy',
                                power_state='empowered',
                                task_state='kayaking')

    def test_detail(self):
        url = '/v2/fake/servers/detail'
        res = self._make_request(url)
        body = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        for server in body['servers']:
            sid = server['id']
            self.assertServerStates(server,
                                    vm_state='vm%s' % sid,
                                    power_state='power%s' % sid,
                                    task_state='task%s' % sid)

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound()

        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)
        url = '/v2/fake/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)
