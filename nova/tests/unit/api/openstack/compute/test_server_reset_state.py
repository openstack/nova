#   Copyright 2015 NEC Corporation. All rights reserved.
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

import mock
from oslo_utils import uuidutils
import webob

from nova.api.openstack.compute import admin_actions \
        as admin_actions_v21
from nova.compute import vm_states
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes


class ResetStateTestsV21(test.NoDBTestCase):
    admin_act = admin_actions_v21
    bad_request = exception.ValidationError

    def setUp(self):
        super(ResetStateTestsV21, self).setUp()
        self.uuid = uuidutils.generate_uuid()
        self.admin_api = self.admin_act.AdminActionsController()
        self.compute_api = self.admin_api.compute_api

        self.request = self._get_request()
        self.context = self.request.environ['nova.context']
        self.instance = self._create_instance()

    def _create_instance(self):
        instance = objects.Instance()
        instance.uuid = self.uuid
        instance.vm_state = 'fake'
        instance.task_state = 'fake'
        instance.obj_reset_changes()
        return instance

    def _check_instance_state(self, expected):
        self.assertEqual(set(expected.keys()),
                         self.instance.obj_what_changed())
        for k, v in expected.items():
            self.assertEqual(v, getattr(self.instance, k),
                             "Instance.%s doesn't match" % k)
        self.instance.obj_reset_changes()

    def _get_request(self):
        return fakes.HTTPRequest.blank('')

    def test_no_state(self):
        self.assertRaises(self.bad_request,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          body={"os-resetState": None})

    def test_bad_state(self):
        self.assertRaises(self.bad_request,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          body={"os-resetState": {"state": "spam"}})

    def test_no_instance(self):
        self.compute_api.get = mock.MagicMock(
            side_effect=exception.InstanceNotFound(instance_id='inst_ud'))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          body={"os-resetState": {"state": "active"}})

        self.compute_api.get.assert_called_once_with(
            self.context, self.uuid, expected_attrs=None)

    def test_reset_active(self):
        expected = dict(vm_state=vm_states.ACTIVE, task_state=None)
        self.instance.save = mock.MagicMock(
            side_effect=lambda **kw: self._check_instance_state(expected))
        self.compute_api.get = mock.MagicMock(return_value=self.instance)

        body = {"os-resetState": {"state": "active"}}
        result = self.admin_api._reset_state(self.request, self.uuid,
                                             body=body)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.admin_api,
                      admin_actions_v21.AdminActionsController):
            status_int = self.admin_api._reset_state.wsgi_code
        else:
            status_int = result.status_int
        self.assertEqual(202, status_int)

        self.compute_api.get.assert_called_once_with(
            self.context, self.instance.uuid, expected_attrs=None)
        self.instance.save.assert_called_once_with(admin_state_reset=True)

    def test_reset_error(self):
        expected = dict(vm_state=vm_states.ERROR, task_state=None)
        self.instance.save = mock.MagicMock(
            side_effect=lambda **kw: self._check_instance_state(expected))
        self.compute_api.get = mock.MagicMock(return_value=self.instance)

        body = {"os-resetState": {"state": "error"}}
        result = self.admin_api._reset_state(self.request, self.uuid,
                                             body=body)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.admin_api,
                      admin_actions_v21.AdminActionsController):
            status_int = self.admin_api._reset_state.wsgi_code
        else:
            status_int = result.status_int
        self.assertEqual(202, status_int)

        self.compute_api.get.assert_called_once_with(
            self.context, self.instance.uuid, expected_attrs=None)
        self.instance.save.assert_called_once_with(admin_state_reset=True)
