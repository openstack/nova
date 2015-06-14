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

from oslo_utils import timeutils
from oslo_utils import uuidutils
import webob

from nova.compute import vm_states
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


class CommonMixin(object):
    def setUp(self):
        super(CommonMixin, self).setUp()
        self.compute_api = None
        self.req = fakes.HTTPRequest.blank('')
        self.context = self.req.environ['nova.context']

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
        controller_function = getattr(self.controller, action)
        self.assertRaises(webob.exc.HTTPNotFound,
                          controller_function,
                          self.req, uuid, body=body_map)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_action(self, action, body=None, method=None,
                     compute_api_args_map=None):
        if method is None:
            method = action.replace('_', '')
        compute_api_args_map = compute_api_args_map or {}

        instance = self._stub_instance_get()
        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance, *args,
                                          **kwargs)

        self.mox.ReplayAll()
        controller_function = getattr(self.controller, action)
        res = controller_function(self.req, instance.uuid, body=body)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if self._api_version == '2.1':
            status_int = controller_function.wsgi_code
        else:
            status_int = res.status_int
        self.assertEqual(202, status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_not_implemented_state(self, action, method=None):
        if method is None:
            method = action.replace('_', '')

        instance = self._stub_instance_get()
        body = {}
        compute_api_args_map = {}
        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance,
                                          *args, **kwargs).AndRaise(
                NotImplementedError())

        self.mox.ReplayAll()
        controller_function = getattr(self.controller, action)
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          controller_function,
                          self.req, instance.uuid, body=body)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_invalid_state(self, action, method=None, body_map=None,
                            compute_api_args_map=None,
                            exception_arg=None):
        if method is None:
            method = action.replace('_', '')
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
        controller_function = getattr(self.controller, action)
        ex = self.assertRaises(webob.exc.HTTPConflict,
                               controller_function,
                               self.req, instance.uuid,
                               body=body_map)
        self.assertIn("Cannot \'%(action)s\' instance %(id)s"
                      % {'action': exception_arg or method,
                         'id': instance.uuid}, ex.explanation)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_locked_instance(self, action, method=None, body=None,
                              compute_api_args_map=None):
        if method is None:
            method = action.replace('_', '')

        compute_api_args_map = compute_api_args_map or {}
        instance = self._stub_instance_get()

        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance, *args,
                                          **kwargs).AndRaise(
                exception.InstanceIsLocked(instance_uuid=instance.uuid))

        self.mox.ReplayAll()

        controller_function = getattr(self.controller, action)
        self.assertRaises(webob.exc.HTTPConflict,
                          controller_function,
                          self.req, instance.uuid, body=body)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_instance_not_found_in_compute_api(self, action,
                         method=None, body=None, compute_api_args_map=None):
        if method is None:
            method = action.replace('_', '')
        compute_api_args_map = compute_api_args_map or {}

        instance = self._stub_instance_get()

        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance, *args,
                                          **kwargs).AndRaise(
                exception.InstanceNotFound(instance_id=instance.uuid))

        self.mox.ReplayAll()

        controller_function = getattr(self.controller, action)
        self.assertRaises(webob.exc.HTTPNotFound,
                          controller_function,
                          self.req, instance.uuid, body=body)
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
            self.mox.StubOutWithMock(self.compute_api,
                                     method or action.replace('_', ''))
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
            self.mox.StubOutWithMock(self.compute_api,
                                     method or action.replace('_', ''))
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
            args_map=None, exception_args=None):
        method_translations = method_translations or {}
        body_map = body_map or {}
        args_map = args_map or {}
        exception_args = exception_args or {}
        for action in actions:
            method = method_translations.get(action)
            exception_arg = exception_args.get(action)
            self.mox.StubOutWithMock(self.compute_api,
                                     method or action.replace('_', ''))
            self._test_invalid_state(action, method=method,
                                     body_map=body_map,
                                     compute_api_args_map=args_map,
                                     exception_arg=exception_arg)
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
            self.mox.StubOutWithMock(self.compute_api,
                                     method or action.replace('_', ''))
            self._test_locked_instance(action, method=method, body=body,
                                       compute_api_args_map=args_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')
