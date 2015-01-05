# Copyright 2013 IBM Corp.
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

from oslo.serialization import jsonutils
from oslo.utils import timeutils
import webob

from nova.compute import vm_states
import nova.context
from nova import exception
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.unit import fake_instance


class CommonMixin(object):
    def setUp(self):
        super(CommonMixin, self).setUp()
        self.compute_api = None
        self.context = nova.context.RequestContext('fake', 'fake')

    def _make_request(self, url, body):
        req = webob.Request.blank('/v2/fake' + url)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.content_type = 'application/json'
        return req.get_response(self.app)

    def _stub_instance_get(self, uuid=None):
        if uuid is None:
            uuid = uuidutils.generate_uuid()
        instance = fake_instance.fake_instance_obj(self.context,
                id=1, uuid=uuid, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
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

    def _test_action(self, action, body=None, method=None,
                     compute_api_args_map=None):
        if method is None:
            method = action

        compute_api_args_map = compute_api_args_map or {}

        instance = self._stub_instance_get()

        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance, *args,
                                          **kwargs)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {action: body})
        self.assertEqual(202, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_not_implemented_state(self, action, method=None):
        if method is None:
            method = action

        instance = self._stub_instance_get()
        body = {}
        compute_api_args_map = {}
        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance,
                                          *args, **kwargs).AndRaise(
                NotImplementedError())

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {action: body})
        self.assertEqual(501, res.status_int)
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
                    attr='vm_state', instance_uuid=instance.uuid,
                    state='foo', method=method))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {action: body_map.get(action)})
        self.assertEqual(409, res.status_int)
        self.assertIn("Cannot \'%(action)s\' instance %(id)s"
                      % {'action': action, 'id': instance.uuid}, res.body)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_locked_instance(self, action, method=None, body=None,
                              compute_api_args_map=None):
        if method is None:
            method = action

        compute_api_args_map = compute_api_args_map or {}
        instance = self._stub_instance_get()

        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance, *args,
                                          **kwargs).AndRaise(
                exception.InstanceIsLocked(instance_uuid=instance.uuid))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {action: body})
        self.assertEqual(409, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_instance_not_found_in_compute_api(self, action,
                         method=None, body=None, compute_api_args_map=None):
        if method is None:
            method = action

        compute_api_args_map = compute_api_args_map or {}

        instance = self._stub_instance_get()

        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance, *args,
                                          **kwargs).AndRaise(
                exception.InstanceNotFound(instance_id=instance.uuid))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {action: body})
        self.assertEqual(404, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()


class CommonTests(CommonMixin, test.NoDBTestCase):
    def _test_actions(self, actions, method_translations=None, body_map=None,
                      args_map=None):
        method_translations = method_translations or {}
        body_map = body_map or {}
        args_map = args_map or {}
        for action in actions:
            method = method_translations.get(action)
            body = body_map.get(action)
            self.mox.StubOutWithMock(self.compute_api, method or action)
            self._test_action(action, method=method, body=body,
                              compute_api_args_map=args_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def _test_actions_instance_not_found_in_compute_api(self,
                  actions, method_translations=None, body_map=None,
                  args_map=None):
        method_translations = method_translations or {}
        body_map = body_map or {}
        args_map = args_map or {}
        for action in actions:
            method = method_translations.get(action)
            body = body_map.get(action)
            self.mox.StubOutWithMock(self.compute_api, method or action)
            self._test_instance_not_found_in_compute_api(
                action, method=method, body=body,
                compute_api_args_map=args_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def _test_actions_with_non_existed_instance(self, actions, body_map=None):
        body_map = body_map or {}
        for action in actions:
            self._test_non_existing_instance(action,
                                             body_map=body_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def _test_actions_raise_conflict_on_invalid_state(
            self, actions, method_translations=None, body_map=None,
            args_map=None):
        method_translations = method_translations or {}
        body_map = body_map or {}
        args_map = args_map or {}
        for action in actions:
            method = method_translations.get(action)
            self.mox.StubOutWithMock(self.compute_api, method or action)
            self._test_invalid_state(action, method=method,
                                     body_map=body_map,
                                     compute_api_args_map=args_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def _test_actions_with_locked_instance(self, actions,
                                           method_translations=None,
                                           body_map=None, args_map=None):
        method_translations = method_translations or {}
        body_map = body_map or {}
        args_map = args_map or {}
        for action in actions:
            method = method_translations.get(action)
            body = body_map.get(action)
            self.mox.StubOutWithMock(self.compute_api, method or action)
            self._test_locked_instance(action, method=method, body=body,
                                       compute_api_args_map=args_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')
