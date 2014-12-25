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

import mock
from oslo_config import cfg
import webob

from nova.api.openstack.compute.contrib import rescue as rescue_v2
from nova.api.openstack.compute.plugins.v3 import rescue as rescue_v21
from nova.api.openstack import extensions
from nova import compute
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')
UUID = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'


def rescue(self, context, instance, rescue_password=None,
           rescue_image_ref=None):
    pass


def unrescue(self, context, instance):
    pass


def fake_compute_get(*args, **kwargs):

    return {'id': 1, 'uuid': UUID}


class RescueTestV21(test.NoDBTestCase):
    def setUp(self):
        super(RescueTestV21, self).setUp()

        self.stubs.Set(compute.api.API, "get", fake_compute_get)
        self.stubs.Set(compute.api.API, "rescue", rescue)
        self.stubs.Set(compute.api.API, "unrescue", unrescue)
        self.controller = self._set_up_controller()
        self.fake_req = fakes.HTTPRequest.blank('')

    def _set_up_controller(self):
        return rescue_v21.RescueController()

    def test_rescue_from_locked_server(self):
        def fake_rescue_from_locked_server(self, context,
            instance, rescue_password=None, rescue_image_ref=None):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.stubs.Set(compute.api.API,
                       'rescue',
                       fake_rescue_from_locked_server)
        body = {"rescue": {"adminPass": "AABBCC112233"}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)

    def test_rescue_with_preset_password(self):
        body = {"rescue": {"adminPass": "AABBCC112233"}}
        resp = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual("AABBCC112233", resp['adminPass'])

    def test_rescue_generates_password(self):
        body = dict(rescue=None)
        resp = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual(CONF.password_length, len(resp['adminPass']))

    def test_rescue_of_rescued_instance(self):
        body = dict(rescue=None)

        def fake_rescue(*args, **kwargs):
            raise exception.InstanceInvalidState('fake message')

        self.stubs.Set(compute.api.API, "rescue", fake_rescue)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)

    def test_unrescue(self):
        body = dict(unrescue=None)
        resp = self.controller._unrescue(self.fake_req, UUID, body=body)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.controller,
                      rescue_v21.RescueController):
            status_int = self.controller._unrescue.wsgi_code
        else:
            status_int = resp.status_int
        self.assertEqual(202, status_int)

    def test_unrescue_from_locked_server(self):
        def fake_unrescue_from_locked_server(self, context,
            instance):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.stubs.Set(compute.api.API,
                       'unrescue',
                       fake_unrescue_from_locked_server)

        body = dict(unrescue=None)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._unrescue,
                          self.fake_req, UUID, body=body)

    def test_unrescue_of_active_instance(self):
        body = dict(unrescue=None)

        def fake_unrescue(*args, **kwargs):
            raise exception.InstanceInvalidState('fake message')

        self.stubs.Set(compute.api.API, "unrescue", fake_unrescue)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._unrescue,
                          self.fake_req, UUID, body=body)

    def test_rescue_raises_unrescuable(self):
        body = dict(rescue=None)

        def fake_rescue(*args, **kwargs):
            raise exception.InstanceNotRescuable('fake message')

        self.stubs.Set(compute.api.API, "rescue", fake_rescue)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)

    @mock.patch('nova.compute.api.API.rescue')
    def test_rescue_with_image_specified(self, mock_compute_api_rescue):
        instance = fake_compute_get()
        body = {"rescue": {"adminPass": "ABC123",
                           "rescue_image_ref": "img-id"}}
        resp_json = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual("ABC123", resp_json['adminPass'])

        mock_compute_api_rescue.assert_called_with(mock.ANY, instance,
                                                   rescue_password=u'ABC123',
                                                   rescue_image_ref=u'img-id')

    @mock.patch('nova.compute.api.API.rescue')
    def test_rescue_without_image_specified(self, mock_compute_api_rescue):
        instance = fake_compute_get()
        body = {"rescue": {"adminPass": "ABC123"}}

        resp_json = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual("ABC123", resp_json['adminPass'])

        mock_compute_api_rescue.assert_called_with(mock.ANY, instance,
                                                   rescue_password=u'ABC123',
                                                   rescue_image_ref=None)

    def test_rescue_with_none(self):
        body = dict(rescue=None)
        resp = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual(CONF.password_length, len(resp['adminPass']))

    def test_rescue_with_empty_dict(self):
        body = dict(rescue=dict())
        resp = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual(CONF.password_length, len(resp['adminPass']))

    def test_rescue_disable_password(self):
        self.flags(enable_instance_password=False)
        body = dict(rescue=None)
        resp_json = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertNotIn('adminPass', resp_json)

    def test_rescue_with_invalid_property(self):
        body = {"rescue": {"test": "test"}}
        self.assertRaises(exception.ValidationError,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)


class RescueTestV20(RescueTestV21):

    def _set_up_controller(self):
        ext_mgr = extensions.ExtensionManager()
        ext_mgr.extensions = {'os-extended-rescue-with-image': 'fake'}
        return rescue_v2.RescueController(ext_mgr)

    def test_rescue_with_invalid_property(self):
        # NOTE(cyeoh): input validation in original v2 code does not
        # check for invalid properties.
        pass

    def test_rescue_disable_password(self):
        # NOTE(cyeoh): Original v2.0 code does not support disabling
        # the admin password being returned through a conf setting
        pass
