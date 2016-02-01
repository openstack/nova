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
import six
import webob

from oslo_policy import policy as oslo_policy

from nova.api.openstack.compute import extension_info
from nova.api.openstack.compute.legacy_v2.contrib import server_start_stop \
        as server_v2
from nova.api.openstack.compute import servers \
        as server_v21
from nova.compute import api as compute_api
from nova import exception
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
    start_policy = "os_compute_api:servers:start"
    stop_policy = "os_compute_api:servers:stop"

    def setUp(self):
        super(ServerStartStopTestV21, self).setUp()
        self._setup_controller()
        self.req = fakes.HTTPRequest.blank('')

    def _setup_controller(self):
        ext_info = extension_info.LoadedExtensionInfo()
        self.controller = server_v21.ServersController(
                              extension_info=ext_info)

    def test_start(self):
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        self.mox.StubOutWithMock(compute_api.API, 'start')
        compute_api.API.start(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        body = dict(start="")
        self.controller._start_server(self.req, 'test_inst', body)

    def test_start_policy_failed(self):
        rules = {
            self.start_policy: "project_id:non_fake"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        body = dict(start="")
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._start_server,
                                self.req, 'test_inst', body)
        self.assertIn(self.start_policy, exc.format_message())

    def test_start_not_ready(self):
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'start', fake_start_stop_not_ready)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, self.req, 'test_inst', body)

    def test_start_locked_server(self):
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'start', fake_start_stop_locked_server)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, self.req, 'test_inst', body)

    def test_start_invalid_state(self):
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'start', fake_start_stop_invalid_state)
        body = dict(start="")
        ex = self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, self.req, 'test_inst', body)
        self.assertIn('is locked', six.text_type(ex))

    def test_stop(self):
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        self.mox.StubOutWithMock(compute_api.API, 'stop')
        compute_api.API.stop(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        body = dict(stop="")
        self.controller._stop_server(self.req, 'test_inst', body)

    def test_stop_policy_failed(self):
        rules = {
            self.stop_policy: "project_id:non_fake"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        body = dict(stop="")
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._stop_server,
                                self.req, 'test_inst', body)
        self.assertIn(self.stop_policy, exc.format_message())

    def test_stop_not_ready(self):
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'stop', fake_start_stop_not_ready)
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, self.req, 'test_inst', body)

    def test_stop_locked_server(self):
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'stop', fake_start_stop_locked_server)
        body = dict(stop="")
        ex = self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, self.req, 'test_inst', body)
        self.assertIn('is locked', six.text_type(ex))

    def test_stop_invalid_state(self):
        self.stub_out('nova.db.instance_get_by_uuid', fake_instance_get)
        self.stubs.Set(compute_api.API, 'stop', fake_start_stop_invalid_state)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, self.req, 'test_inst', body)

    def test_start_with_bogus_id(self):
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._start_server, self.req, 'test_inst', body)

    def test_stop_with_bogus_id(self):
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._stop_server, self.req, 'test_inst', body)


class ServerStartStopTestV2(ServerStartStopTestV21):
    start_policy = "compute:start"
    stop_policy = "compute:stop"

    def _setup_controller(self):
        self.controller = server_v2.ServerStartStopActionController()
