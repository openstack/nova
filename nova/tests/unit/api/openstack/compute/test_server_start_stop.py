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

import mock
from oslo_policy import policy as oslo_policy
import six
import webob

from nova.api.openstack.compute import servers \
        as server_v21
from nova.compute import api as compute_api
from nova import db
from nova import exception
from nova import policy
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit.api.openstack import fakes
from nova.tests import uuidsentinel as uuids


class ServerStartStopTestV21(test.TestCase):

    def setUp(self):
        super(ServerStartStopTestV21, self).setUp()
        self._setup_controller()
        self.req = fakes.HTTPRequest.blank('')
        self.useFixture(nova_fixtures.SingleCellSimple())
        self.stub_out('nova.db.instance_get_by_uuid',
                      fakes.fake_instance_get())

    def _setup_controller(self):
        self.controller = server_v21.ServersController()

    @mock.patch.object(compute_api.API, 'start')
    def test_start(self, start_mock):
        body = dict(start="")
        self.controller._start_server(self.req, uuids.instance, body)
        start_mock.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(compute_api.API, 'start',
                       side_effect=exception.InstanceNotReady(
                           instance_id=uuids.instance))
    def test_start_not_ready(self, start_mock):
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, self.req, uuids.instance, body)

    @mock.patch.object(compute_api.API, 'start',
                       side_effect=exception.InstanceIsLocked(
                           instance_uuid=uuids.instance))
    def test_start_locked_server(self, start_mock):
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, self.req, uuids.instance, body)

    @mock.patch.object(compute_api.API, 'start',
                       side_effect=exception.InstanceIsLocked(
                           instance_uuid=uuids.instance))
    def test_start_invalid_state(self, start_mock):
        body = dict(start="")
        ex = self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, self.req, uuids.instance, body)
        self.assertIn('is locked', six.text_type(ex))

    @mock.patch.object(compute_api.API, 'stop')
    def test_stop(self, stop_mock):
        body = dict(stop="")
        self.controller._stop_server(self.req, uuids.instance, body)
        stop_mock.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(compute_api.API, 'stop',
                       side_effect=exception.InstanceNotReady(
                           instance_id=uuids.instance))
    def test_stop_not_ready(self, stop_mock):
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, self.req, uuids.instance, body)

    @mock.patch.object(compute_api.API, 'stop',
                       side_effect=exception.InstanceIsLocked(
                           instance_uuid=uuids.instance))
    def test_stop_locked_server(self, stop_mock):
        body = dict(stop="")
        ex = self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, self.req, uuids.instance, body)
        self.assertIn('is locked', six.text_type(ex))

    @mock.patch.object(compute_api.API, 'stop',
                       side_effect=exception.InstanceIsLocked(
                           instance_uuid=uuids.instance))
    def test_stop_invalid_state(self, stop_mock):
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, self.req, uuids.instance, body)

    @mock.patch.object(db, 'instance_get_by_uuid',
                       side_effect=exception.InstanceNotFound(
                           instance_id=uuids.instance))
    def test_start_with_bogus_id(self, get_mock):
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._start_server, self.req, uuids.instance, body)

    @mock.patch.object(db, 'instance_get_by_uuid',
                       side_effect=exception.InstanceNotFound(
                           instance_id=uuids.instance))
    def test_stop_with_bogus_id(self, get_mock):
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._stop_server, self.req, uuids.instance, body)


class ServerStartStopPolicyEnforcementV21(test.TestCase):
    start_policy = "os_compute_api:servers:start"
    stop_policy = "os_compute_api:servers:stop"

    def setUp(self):
        super(ServerStartStopPolicyEnforcementV21, self).setUp()
        self.controller = server_v21.ServersController()
        self.req = fakes.HTTPRequest.blank('')
        self.useFixture(nova_fixtures.SingleCellSimple())
        self.stub_out(
            'nova.db.instance_get_by_uuid',
            fakes.fake_instance_get(
                project_id=self.req.environ['nova.context'].project_id))

    def test_start_policy_failed(self):
        rules = {
            self.start_policy: "project_id:non_fake"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        body = dict(start="")
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._start_server,
                                self.req, uuids.instance, body)
        self.assertIn(self.start_policy, exc.format_message())

    def test_start_overridden_policy_failed_with_other_user_in_same_project(
        self):
        rules = {
            self.start_policy: "user_id:%(user_id)s"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        # Change the user_id in request context.
        self.req.environ['nova.context'].user_id = 'other-user'
        body = dict(start="")
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._start_server,
                                self.req, uuids.instance, body)
        self.assertIn(self.start_policy, exc.format_message())

    @mock.patch('nova.compute.api.API.start')
    def test_start_overridden_policy_pass_with_same_user(self, start_mock):
        rules = {
            self.start_policy: "user_id:%(user_id)s"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        body = dict(start="")
        self.controller._start_server(self.req, uuids.instance, body)
        start_mock.assert_called_once_with(mock.ANY, mock.ANY)

    def test_stop_policy_failed_with_other_project(self):
        rules = {
            self.stop_policy: "project_id:%(project_id)s"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        body = dict(stop="")
        # Change the project_id in request context.
        self.req.environ['nova.context'].project_id = 'other-project'
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._stop_server,
                                self.req, uuids.instance, body)
        self.assertIn(self.stop_policy, exc.format_message())

    @mock.patch('nova.compute.api.API.stop')
    def test_stop_overridden_policy_pass_with_same_project(self, stop_mock):
        rules = {
            self.stop_policy: "project_id:%(project_id)s"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        body = dict(stop="")
        self.controller._stop_server(self.req, uuids.instance, body)
        stop_mock.assert_called_once_with(mock.ANY, mock.ANY)

    def test_stop_overridden_policy_failed_with_other_user_in_same_project(
        self):
        rules = {
            self.stop_policy: "user_id:%(user_id)s"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        # Change the user_id in request context.
        self.req.environ['nova.context'].user_id = 'other-user'
        body = dict(stop="")
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._stop_server,
                                self.req, uuids.instance, body)
        self.assertIn(self.stop_policy, exc.format_message())

    @mock.patch('nova.compute.api.API.stop')
    def test_stop_overridden_policy_pass_with_same_user(self, stop_mock):
        rules = {
            self.stop_policy: "user_id:%(user_id)s"
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        body = dict(stop="")
        self.controller._stop_server(self.req, uuids.instance, body)
        stop_mock.assert_called_once_with(mock.ANY, mock.ANY)
