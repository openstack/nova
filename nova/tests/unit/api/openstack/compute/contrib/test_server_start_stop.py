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

from mox3 import mox
import webob

from nova.api.openstack.compute.contrib import server_start_stop \
    as server_v2
from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import servers \
    as server_v21
from nova.compute import api as compute_api
from nova import db
from nova import exception
from nova.openstack.common import policy as common_policy
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes


def fake_instance_get(context, instance_id,
                      columns_to_join=None, use_slave=False):
    result = fakes.stub_instance(id=1, uuid=instance_id)
    result['created_at'] = None
    result['deleted_at'] = None
    result['updated_at'] = None
    result['deleted'] = 0
    result['info_cache'] = {'network_info': '[]',
                            'instance_uuid': result['uuid']}
    return result


def fake_start_stop_not_ready(self, context, instance):
    raise exception.InstanceNotReady(instance_id=instance["uuid"])


def fake_start_stop_locked_server(self, context, instance):
    raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])


def fake_start_stop_invalid_state(self, context, instance):
    raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])


class ServerStartStopTestV21(test.TestCase):
    start_policy = "compute:v3:servers:start"
    stop_policy = "compute:v3:servers:stop"

    def setUp(self):
        super(ServerStartStopTestV21, self).setUp()
        self._setup_controller()

    def _setup_controller(self):
        ext_info = plugins.LoadedExtensionInfo()
        self.controller = server_v21.ServersController(
                              extension_info=ext_info)

    def test_start(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        self.mox.StubOutWithMock(compute_api.API, 'start')
        compute_api.API.start(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.controller._start_server(req, 'test_inst', body)

    def test_start_policy_failed(self):
        rules = {
            self.start_policy:
                common_policy.parse_rule("project_id:non_fake")
        }
        policy.set_rules(rules)
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._start_server,
                                req, 'test_inst', body)
        self.assertIn(self.start_policy, exc.format_message())

    def test_start_not_ready(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'start', fake_start_stop_not_ready)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, 'test_inst', body)

    def test_start_locked_server(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'start', fake_start_stop_locked_server)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, 'test_inst', body)

    def test_start_invalid_state(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'start', fake_start_stop_invalid_state)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, 'test_inst', body)

    def test_stop(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        self.mox.StubOutWithMock(compute_api.API, 'stop')
        compute_api.API.stop(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(stop="")
        self.controller._stop_server(req, 'test_inst', body)

    def test_stop_policy_failed(self):
        rules = {
            self.stop_policy:
                common_policy.parse_rule("project_id:non_fake")
        }
        policy.set_rules(rules)
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(stop="")
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._stop_server,
                                req, 'test_inst', body)
        self.assertIn(self.stop_policy, exc.format_message())

    def test_stop_not_ready(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'stop', fake_start_stop_not_ready)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, 'test_inst', body)

    def test_stop_locked_server(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'stop', fake_start_stop_locked_server)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, 'test_inst', body)

    def test_stop_invalid_state(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'stop', fake_start_stop_invalid_state)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, 'test_inst', body)

    def test_start_with_bogus_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._start_server, req, 'test_inst', body)

    def test_stop_with_bogus_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._stop_server, req, 'test_inst', body)


class ServerStartStopTestV2(ServerStartStopTestV21):
    start_policy = "compute:start"
    stop_policy = "compute:stop"

    def _setup_controller(self):
        self.controller = server_v2.ServerStartStopActionController()
