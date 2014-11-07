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
from oslo.config import cfg
from oslo.serialization import jsonutils
import webob

from nova import compute
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')


def rescue(self, context, instance, rescue_password=None,
           rescue_image_ref=None):
    pass


def unrescue(self, context, instance):
    pass


def fake_compute_get(*args, **kwargs):
    uuid = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
    return {'id': 1, 'uuid': uuid}


class RescueTestV21(test.NoDBTestCase):
    _prefix = '/v2/fake'

    def setUp(self):
        super(RescueTestV21, self).setUp()

        self.stubs.Set(compute.api.API, "get", fake_compute_get)
        self.stubs.Set(compute.api.API, "rescue", rescue)
        self.stubs.Set(compute.api.API, "unrescue", unrescue)
        self.app = self._get_app()

    def _get_app(self):
        return fakes.wsgi_app_v21(init_only=('servers', 'os-rescue'))

    def test_rescue_from_locked_server(self):
        def fake_rescue_from_locked_server(self, context,
            instance, rescue_password=None, rescue_image_ref=None):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.stubs.Set(compute.api.API,
                       'rescue',
                       fake_rescue_from_locked_server)
        body = {"rescue": {"adminPass": "AABBCC112233"}}
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 409)

    def test_rescue_with_preset_password(self):
        body = {"rescue": {"adminPass": "AABBCC112233"}}
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)
        resp_json = jsonutils.loads(resp.body)
        self.assertEqual("AABBCC112233", resp_json['adminPass'])

    def test_rescue_generates_password(self):
        body = dict(rescue=None)
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)
        resp_json = jsonutils.loads(resp.body)
        self.assertEqual(CONF.password_length, len(resp_json['adminPass']))

    def test_rescue_of_rescued_instance(self):
        body = dict(rescue=None)

        def fake_rescue(*args, **kwargs):
            raise exception.InstanceInvalidState('fake message')

        self.stubs.Set(compute.api.API, "rescue", fake_rescue)
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 409)

    def test_unrescue(self):
        body = dict(unrescue=None)
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 202)

    def test_unrescue_from_locked_server(self):
        def fake_unrescue_from_locked_server(self, context,
            instance):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])

        self.stubs.Set(compute.api.API,
                       'unrescue',
                       fake_unrescue_from_locked_server)

        body = dict(unrescue=None)
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 409)

    def test_unrescue_of_active_instance(self):
        body = dict(unrescue=None)

        def fake_unrescue(*args, **kwargs):
            raise exception.InstanceInvalidState('fake message')

        self.stubs.Set(compute.api.API, "unrescue", fake_unrescue)
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 409)

    def test_rescue_raises_unrescuable(self):
        body = dict(rescue=None)

        def fake_rescue(*args, **kwargs):
            raise exception.InstanceNotRescuable('fake message')

        self.stubs.Set(compute.api.API, "rescue", fake_rescue)
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 400)

    @mock.patch('nova.compute.api.API.rescue')
    def test_rescue_with_image_specified(self, mock_compute_api_rescue):
        instance = fake_compute_get()
        body = {"rescue": {"adminPass": "ABC123",
                           "rescue_image_ref": "img-id"}}
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)
        resp_json = jsonutils.loads(resp.body)
        self.assertEqual("ABC123", resp_json['adminPass'])

        mock_compute_api_rescue.assert_called_with(mock.ANY, instance,
                                                   rescue_password=u'ABC123',
                                                   rescue_image_ref=u'img-id')

    @mock.patch('nova.compute.api.API.rescue')
    def test_rescue_without_image_specified(self, mock_compute_api_rescue):
        instance = fake_compute_get()
        body = {"rescue": {"adminPass": "ABC123"}}

        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 200)
        resp_json = jsonutils.loads(resp.body)
        self.assertEqual("ABC123", resp_json['adminPass'])

        mock_compute_api_rescue.assert_called_with(mock.ANY, instance,
                                                   rescue_password=u'ABC123',
                                                   rescue_image_ref=None)

    def test_rescue_with_none(self):
        body = dict(rescue=None)
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    def test_rescue_with_empty_dict(self):
        body = dict(rescue=dict())
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    def test_rescue_disable_password(self):
        self.flags(enable_instance_password=False)
        body = dict(rescue=None)
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)
        resp_json = jsonutils.loads(resp.body)
        self.assertNotIn('adminPass', resp_json)

    def test_rescue_with_invalid_property(self):
        body = {"rescue": {"test": "test"}}
        req = webob.Request.blank(self._prefix + '/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(400, resp.status_int)


class RescueTestV20(RescueTestV21):

    def _get_app(self):
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=None)
        return fakes.wsgi_app(init_only=('servers',))

    def test_rescue_with_invalid_property(self):
        # NOTE(cyeoh): input validation in original v2 code does not
        # check for invalid properties.
        pass

    def test_rescue_disable_password(self):
        # NOTE(cyeoh): Original v2.0 code does not support disabling
        # the admin password being returned through a conf setting
        pass
