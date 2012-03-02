# Copyright (c) 2012 Midokura Japan K.K.
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

import unittest

import mox
import webob

from nova.api.openstack.compute.contrib import server_start_stop
from nova import compute
from nova import test
from nova.tests.api.openstack import fakes


def fake_compute_api_get(self, context, instance_id):
    return {'id': 1, 'uuid': instance_id}


class ServerStartStopTest(test.TestCase):

    def setUp(self):
        super(ServerStartStopTest, self).setUp()
        self.controller = server_start_stop.ServerStartStopActionController()

    def test_start(self):
        self.stubs.Set(compute.API, 'get', fake_compute_api_get)
        self.mox.StubOutWithMock(compute.API, 'start')
        compute.API.start(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.controller._start_server(req, 'test_inst', body)

    def test_stop(self):
        self.stubs.Set(compute.API, 'get', fake_compute_api_get)
        self.mox.StubOutWithMock(compute.API, 'stop')
        compute.API.stop(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(stop="")
        self.controller._stop_server(req, 'test_inst', body)

    def test_start_with_bogus_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._start_server, req, 'test_inst', body)

    def test_stop_with_bogus_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._stop_server, req, 'test_inst', body)


if __name__ == '__main__':
    unittest.main()
