#   Copyright 2011 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import webob

from nova.api.openstack.compute.plugins.v3 import admin_actions
from nova.compute import vm_states
import nova.context
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


class CommonMixin(object):
    def setUp(self):
        super(CommonMixin, self).setUp()
        self.controller = admin_actions.AdminActionsController()
        self.compute_api = self.controller.compute_api
        self.context = nova.context.RequestContext('fake', 'fake')

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(admin_actions, 'AdminActionsController',
                       _fake_controller)

        self.app = fakes.wsgi_app_v3(init_only=('servers',
                                                'os-admin-actions'),
                                     fake_auth_context=self.context)
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def _make_request(self, url, body):
        req = webob.Request.blank('/v3' + url)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.content_type = 'application/json'
        return req.get_response(self.app)

    def _stub_instance_get(self, uuid=None):
        if uuid is None:
            uuid = uuidutils.generate_uuid()
        instance = fake_instance.fake_db_instance(
                id=1, uuid=uuid, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        instance = instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), instance)
        self.compute_api.get(self.context, uuid, expected_attrs=None,
                             want_objects=True).AndReturn(instance)
        return instance

    def _stub_instance_get_failure(self, exc_info, uuid=None):
        if uuid is None:
            uuid = uuidutils.generate_uuid()
        self.compute_api.get(self.context, uuid, expected_attrs=None,
                             want_objects=True).AndRaise(exc_info)
        return uuid

    def _test_non_existing_instance(self, action, body_map=None):
        uuid = uuidutils.generate_uuid()
        self._stub_instance_get_failure(
                exception.InstanceNotFound(instance_id=uuid), uuid=uuid)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % uuid,
                                 {action: body_map.get(action)})
        self.assertEqual(404, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_action(self, action, body=None, method=None):
        if method is None:
            method = action

        instance = self._stub_instance_get()
        getattr(self.compute_api, method)(self.context, instance)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {action: None})
        self.assertEqual(202, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_invalid_state(self, action, method=None, body_map=None,
                            compute_api_args_map=None):
        if method is None:
            method = action
        if body_map is None:
            body_map = {}
        if compute_api_args_map is None:
            compute_api_args_map = {}

        instance = self._stub_instance_get()

        args, kwargs = compute_api_args_map.get(action, ((), {}))

        getattr(self.compute_api, method)(self.context, instance,
                                          *args, **kwargs).AndRaise(
                exception.InstanceInvalidState(
                    attr='vm_state', instance_uuid=instance['uuid'],
                    state='foo', method=method))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {action: body_map.get(action)})
        self.assertEqual(409, res.status_int)
        self.assertIn("Cannot \'%s\' while instance" % action, res.body)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_locked_instance(self, action, method=None):
        if method is None:
            method = action

        instance = self._stub_instance_get()
        getattr(self.compute_api, method)(self.context, instance).AndRaise(
                exception.InstanceIsLocked(instance_uuid=instance['uuid']))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {action: None})
        self.assertEqual(409, res.status_int)
        self.assertIn('Instance %s is locked' % instance['uuid'], res.body)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()


class AdminActionsTest(CommonMixin, test.NoDBTestCase):
    def test_actions(self):
        actions = ['reset_network', 'inject_network_info']

        for action in actions:
            self.mox.StubOutWithMock(self.compute_api, action)
            self._test_action(action)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_actions_with_non_existed_instance(self):
        actions = ['reset_network', 'inject_network_info', 'reset_state']
        body_map = {'reset_state': {'state': 'active'}}
        for action in actions:
            self._test_non_existing_instance(action,
                                             body_map=body_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_actions_with_locked_instance(self):
        actions = ['reset_network', 'inject_network_info']

        for action in actions:
            self.mox.StubOutWithMock(self.compute_api, action)
            self._test_locked_instance(action)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')


class ResetStateTests(test.NoDBTestCase):
    def setUp(self):
        super(ResetStateTests, self).setUp()

        self.uuid = uuidutils.generate_uuid()

        self.admin_api = admin_actions.AdminActionsController()
        self.compute_api = self.admin_api.compute_api

        url = '/servers/%s/action' % self.uuid
        self.request = fakes.HTTPRequestV3.blank(url)
        self.context = self.request.environ['nova.context']

    def test_no_state(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"reset_state": None})

    def test_bad_state(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"reset_state": {"state": "spam"}})

    def test_no_instance(self):
        self.mox.StubOutWithMock(self.compute_api, 'get')
        exc = exception.InstanceNotFound(instance_id='inst_ud')
        self.compute_api.get(self.context, self.uuid, expected_attrs=None,
                             want_objects=True).AndRaise(exc)

        self.mox.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"reset_state": {"state": "active"}})

    def _setup_mock(self, expected):
        instance = instance_obj.Instance()
        instance.uuid = self.uuid
        instance.vm_state = 'fake'
        instance.task_state = 'fake'
        instance.obj_reset_changes()

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api, 'get')

        def check_state(admin_state_reset=True):
            self.assertEqual(set(expected.keys()),
                             instance.obj_what_changed())
            for k, v in expected.items():
                self.assertEqual(v, getattr(instance, k),
                                 "Instance.%s doesn't match" % k)
            instance.obj_reset_changes()

        self.compute_api.get(self.context, instance.uuid, expected_attrs=None,
                             want_objects=True).AndReturn(instance)
        instance.save(admin_state_reset=True).WithSideEffects(check_state)

    def test_reset_active(self):
        self._setup_mock(dict(vm_state=vm_states.ACTIVE,
                              task_state=None))
        self.mox.ReplayAll()

        body = {"reset_state": {"state": "active"}}
        result = self.admin_api._reset_state(self.request, self.uuid, body)

        self.assertEqual(202, result.status_int)

    def test_reset_error(self):
        self._setup_mock(dict(vm_state=vm_states.ERROR,
                              task_state=None))
        self.mox.ReplayAll()
        body = {"reset_state": {"state": "error"}}
        result = self.admin_api._reset_state(self.request, self.uuid, body)

        self.assertEqual(202, result.status_int)
