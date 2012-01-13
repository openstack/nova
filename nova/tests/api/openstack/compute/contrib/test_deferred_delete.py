# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import webob

from nova.api.openstack.compute.contrib import deferred_delete
from nova import compute
from nova import exception
from nova import test


class FakeExtensionDescriptor(object):
    def register(*args, **kwargs):
        pass


class FakeRequest(object):
    def __init__(self, context):
        self.environ = {'nova.context': context}


class DeferredDeleteExtensionTest(test.TestCase):
    def setUp(self):
        super(DeferredDeleteExtensionTest, self).setUp()
        self.extension = deferred_delete.Deferred_delete(
                FakeExtensionDescriptor())
        self.fake_input_dict = {}
        self.fake_uuid = 'fake_uuid'
        self.fake_context = 'fake_context'
        self.fake_req = FakeRequest(self.fake_context)

    def test_force_delete(self):
        self.mox.StubOutWithMock(compute.API, 'get')
        self.mox.StubOutWithMock(compute.API, 'force_delete')

        fake_instance = 'fake_instance'

        compute.API.get(self.fake_context, self.fake_uuid).AndReturn(
                fake_instance)
        compute.API.force_delete(self.fake_context, fake_instance)

        self.mox.ReplayAll()
        res = self.extension._force_delete(self.fake_input_dict,
                self.fake_req, self.fake_uuid)
        self.mox.VerifyAll()
        self.assertEqual(res.status_int, 202)

    def test_force_delete_raises_conflict_on_invalid_state(self):
        self.mox.StubOutWithMock(compute.API, 'get')
        self.mox.StubOutWithMock(compute.API, 'force_delete')

        fake_instance = 'fake_instance'

        compute.API.get(self.fake_context, self.fake_uuid).AndReturn(
                fake_instance)
        compute.API.force_delete(self.fake_context, fake_instance).AndRaise(
                exception.InstanceInvalidState)

        self.mox.ReplayAll()
        self.assertRaises(webob.exc.HTTPConflict,
                self.extension._force_delete, self.fake_input_dict,
                self.fake_req, self.fake_uuid)
        self.mox.VerifyAll()

    def test_restore(self):
        self.mox.StubOutWithMock(compute.API, 'get')
        self.mox.StubOutWithMock(compute.API, 'restore')

        fake_instance = 'fake_instance'

        compute.API.get(self.fake_context, self.fake_uuid).AndReturn(
                fake_instance)
        compute.API.restore(self.fake_context, fake_instance)

        self.mox.ReplayAll()
        res = self.extension._restore(self.fake_input_dict,
                self.fake_req, self.fake_uuid)
        self.mox.VerifyAll()
        self.assertEqual(res.status_int, 202)

    def test_restore_raises_conflict_on_invalid_state(self):
        self.mox.StubOutWithMock(compute.API, 'get')
        self.mox.StubOutWithMock(compute.API, 'restore')

        fake_instance = 'fake_instance'

        compute.API.get(self.fake_context, self.fake_uuid).AndReturn(
                fake_instance)
        compute.API.restore(self.fake_context, fake_instance).AndRaise(
                exception.InstanceInvalidState)

        self.mox.ReplayAll()
        self.assertRaises(webob.exc.HTTPConflict, self.extension._restore,
                self.fake_input_dict, self.fake_req, self.fake_uuid)
        self.mox.VerifyAll()

    def test_get_actions(self):
        result = self.extension.get_actions()
        self.assertEqual(len(result), 2)

        action_and_methods = [(x.action_name, x.handler) for x in result]
        self.assertIn(('restore', self.extension._restore),
                action_and_methods)
        self.assertIn(('forceDelete', self.extension._force_delete),
                action_and_methods)
