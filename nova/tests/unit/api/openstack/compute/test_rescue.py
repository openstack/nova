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
import webob

from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import rescue as rescue_v21
from nova import compute
import nova.conf
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance

CONF = nova.conf.CONF
UUID = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'


def rescue(self, context, instance, rescue_password=None,
           rescue_image_ref=None, allow_bfv_rescue=False):
    pass


def unrescue(self, context, instance):
    pass


def fake_compute_get(*args, **kwargs):
    return fake_instance.fake_instance_obj(args[1], id=1,
                                           uuid=UUID, **kwargs)


class RescueTestV21(test.NoDBTestCase):

    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'

    def setUp(self):
        super(RescueTestV21, self).setUp()

        self.stub_out("nova.compute.api.API.get", fake_compute_get)
        self.stub_out("nova.compute.api.API.rescue", rescue)
        self.stub_out("nova.compute.api.API.unrescue", unrescue)
        self.controller = self._set_up_controller()
        self.fake_req = fakes.HTTPRequest.blank('')

    def _set_up_controller(self):
        return rescue_v21.RescueController()

    def _allow_bfv_rescue(self):
        return api_version_request.is_supported(self.fake_req, '2.87')

    @mock.patch.object(compute.api.API, "rescue")
    def test_rescue_from_locked_server(self, mock_rescue):
        mock_rescue.side_effect = exception.InstanceIsLocked(
            instance_uuid=UUID)

        body = {"rescue": {"adminPass": "AABBCC112233"}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)
        self.assertTrue(mock_rescue.called)

    def test_rescue_with_preset_password(self):
        body = {"rescue": {"adminPass": "AABBCC112233"}}
        resp = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual("AABBCC112233", resp['adminPass'])

    def test_rescue_generates_password(self):
        body = dict(rescue=None)
        resp = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual(CONF.password_length, len(resp['adminPass']))

    @mock.patch.object(compute.api.API, "rescue")
    def test_rescue_of_rescued_instance(self, mock_rescue):
        mock_rescue.side_effect = exception.InstanceInvalidState(
            'fake message')
        body = dict(rescue=None)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)
        self.assertTrue(mock_rescue.called)

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

    @mock.patch.object(compute.api.API, "unrescue")
    def test_unrescue_from_locked_server(self, mock_unrescue):
        mock_unrescue.side_effect = exception.InstanceIsLocked(
            instance_uuid=UUID)

        body = dict(unrescue=None)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._unrescue,
                          self.fake_req, UUID, body=body)
        self.assertTrue(mock_unrescue.called)

    @mock.patch.object(compute.api.API, "unrescue")
    def test_unrescue_of_active_instance(self, mock_unrescue):
        mock_unrescue.side_effect = exception.InstanceInvalidState(
            'fake message')
        body = dict(unrescue=None)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._unrescue,
                          self.fake_req, UUID, body=body)
        self.assertTrue(mock_unrescue.called)

    @mock.patch.object(compute.api.API, "rescue")
    def test_rescue_raises_unrescuable(self, mock_rescue):
        mock_rescue.side_effect = exception.InstanceNotRescuable(
            'fake message')
        body = dict(rescue=None)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)
        self.assertTrue(mock_rescue.called)

    @mock.patch.object(compute.api.API, "rescue",
        side_effect=exception.UnsupportedRescueImage(image='fake'))
    def test_rescue_raises_unsupported_image(self, mock_rescue):
        body = dict(rescue=None)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)
        self.assertTrue(mock_rescue.called)

    def test_rescue_with_bad_image_specified(self):
        body = {"rescue": {"adminPass": "ABC123",
                           "rescue_image_ref": "img-id"}}
        self.assertRaises(exception.ValidationError,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)

    def test_rescue_with_imageRef_as_full_url(self):
        image_href = ('http://localhost/v2/fake/images/'
                      '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6')
        body = {"rescue": {"adminPass": "ABC123",
                           "rescue_image_ref": image_href}}
        self.assertRaises(exception.ValidationError,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)

    def test_rescue_with_imageRef_as_empty_string(self):
        body = {"rescue": {"adminPass": "ABC123",
                           "rescue_image_ref": ''}}
        self.assertRaises(exception.ValidationError,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)

    @mock.patch('nova.compute.api.API.rescue')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_rescue_with_image_specified(
        self, get_instance_mock, mock_compute_api_rescue):
        instance = fake_instance.fake_instance_obj(
            self.fake_req.environ['nova.context'])
        get_instance_mock.return_value = instance
        body = {"rescue": {"adminPass": "ABC123",
            "rescue_image_ref": self.image_uuid}}
        resp_json = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual("ABC123", resp_json['adminPass'])

        mock_compute_api_rescue.assert_called_with(
            mock.ANY,
            instance,
            rescue_password=u'ABC123',
            rescue_image_ref=self.image_uuid,
            allow_bfv_rescue=self._allow_bfv_rescue())

    @mock.patch('nova.compute.api.API.rescue')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_rescue_without_image_specified(
        self, get_instance_mock, mock_compute_api_rescue):
        instance = fake_instance.fake_instance_obj(
            self.fake_req.environ['nova.context'])
        get_instance_mock.return_value = instance
        body = {"rescue": {"adminPass": "ABC123"}}

        resp_json = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual("ABC123", resp_json['adminPass'])

        mock_compute_api_rescue.assert_called_with(
            mock.ANY, instance, rescue_password=u'ABC123',
            rescue_image_ref=None, allow_bfv_rescue=self._allow_bfv_rescue())

    def test_rescue_with_none(self):
        body = dict(rescue=None)
        resp = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual(CONF.password_length, len(resp['adminPass']))

    def test_rescue_with_empty_dict(self):
        body = dict(rescue=dict())
        resp = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertEqual(CONF.password_length, len(resp['adminPass']))

    def test_rescue_disable_password(self):
        self.flags(enable_instance_password=False, group='api')
        body = dict(rescue=None)
        resp_json = self.controller._rescue(self.fake_req, UUID, body=body)
        self.assertNotIn('adminPass', resp_json)

    def test_rescue_with_invalid_property(self):
        body = {"rescue": {"test": "test"}}
        self.assertRaises(exception.ValidationError,
                          self.controller._rescue,
                          self.fake_req, UUID, body=body)


class RescueTestV287(RescueTestV21):

    def setUp(self):
        super(RescueTestV287, self).setUp()
        v287_req = api_version_request.APIVersionRequest('2.87')
        self.fake_req.api_version_request = v287_req

    @mock.patch('nova.compute.api.API.rescue')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_allow_bfv_rescue(self, mock_get_instance, mock_compute_rescue):
        instance = fake_instance.fake_instance_obj(
            self.fake_req.environ['nova.context'])
        mock_get_instance.return_value = instance

        body = {"rescue": {"adminPass": "ABC123"}}
        self.controller._rescue(self.fake_req, uuids.instance, body=body)

        # Assert that allow_bfv_rescue is True for this 2.87 request
        mock_get_instance.assert_called_once_with(
            mock.ANY, mock.ANY, uuids.instance)
        mock_compute_rescue.assert_called_with(
            mock.ANY, instance, rescue_image_ref=None,
            rescue_password=u'ABC123', allow_bfv_rescue=True)
