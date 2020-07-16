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

import mock

import ddt
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
import six
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import shelve as shelve_v21
from nova.compute import task_states
from nova.compute import vm_states
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


@ddt.ddt
class ShelveControllerTest(test.NoDBTestCase):
    plugin = shelve_v21

    def setUp(self):
        super().setUp()
        self.controller = self.plugin.ShelveController()
        self.req = fakes.HTTPRequest.blank('')

    @ddt.data(
        exception.InstanceIsLocked(instance_uuid=uuids.instance),
        exception.OperationNotSupportedForVTPM(
            instance_uuid=uuids.instance, operation='foo'),
        exception.UnexpectedTaskStateError(
            instance_uuid=uuids.instance, expected=None,
            actual=task_states.SHELVING),
    )
    @mock.patch('nova.compute.api.API.shelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve__http_conflict_error(
        self, exc, mock_get_instance, mock_shelve,
    ):
        mock_get_instance.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        mock_shelve.side_effect = exc

        self.assertRaises(
            webob.exc.HTTPConflict, self.controller._shelve,
            self.req, uuids.fake, {})

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_locked_server(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        self.stub_out('nova.compute.api.API.unshelve',
                      fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self.controller._unshelve,
                          self.req, uuids.fake, body={'unshelve': {}})

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_offload_locked_server(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        self.stub_out('nova.compute.api.API.shelve_offload',
                      fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._shelve_offload,
                          self.req, uuids.fake, {})


class UnshelveServerControllerTestV277(test.NoDBTestCase):
    """Server controller test for microversion 2.77

    Add availability_zone parameter to unshelve a shelved-offloaded server of
    2.77 microversion.
    """
    wsgi_api_version = '2.77'

    def setUp(self):
        super(UnshelveServerControllerTestV277, self).setUp()
        self.controller = shelve_v21.ShelveController()
        self.req = fakes.HTTPRequest.blank(
                '/%s/servers/a/action' % fakes.FAKE_PROJECT_ID,
                use_admin_context=True, version=self.wsgi_api_version)
        # These tests don't care about ports with QoS bandwidth resources.
        self.stub_out('nova.api.openstack.common.'
                      'instance_has_port_with_resource_request',
                      lambda *a, **kw: False)

    def fake_get_instance(self):
        ctxt = self.req.environ['nova.context']
        return fake_instance.fake_instance_obj(
            ctxt, uuid=fakes.FAKE_UUID, vm_state=vm_states.SHELVED_OFFLOADED)

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_az_pre_2_77_failed(self, mock_get_instance):
        """Make sure specifying an AZ before microversion 2.77 is ignored."""
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {
            'unshelve': {
                'availability_zone': 'us-east'
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (api_version_request.
                APIVersionRequest('2.76'))
        with mock.patch.object(self.controller.compute_api,
                               'unshelve') as mock_unshelve:
            self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'], instance, new_az=None)

    @mock.patch('nova.compute.api.API.unshelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_none_pre_2_77_success(
            self, mock_get_instance, mock_unshelve):
        """Make sure we can unshelve server with None
        before microversion 2.77.
        """
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {'unshelve': None}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (api_version_request.
                APIVersionRequest('2.76'))
        self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'], instance, new_az=None)

    @mock.patch('nova.compute.api.API.unshelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_empty_dict_with_v2_77_failed(
            self, mock_get_instance, mock_unshelve):
        """Make sure we cannot unshelve server with empty dict."""
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {'unshelve': {}}
        self.req.body = jsonutils.dump_as_bytes(body)
        exc = self.assertRaises(exception.ValidationError,
                                self.controller._unshelve,
                                self.req, fakes.FAKE_UUID,
                                body=body)
        self.assertIn("\'availability_zone\' is a required property",
                      six.text_type(exc))

    def test_invalid_az_name_with_int(self):
        body = {
            'unshelve': {
                'availability_zone': 1234
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError,
                          self.controller._unshelve,
                          self.req, fakes.FAKE_UUID,
                          body=body)

    def test_no_az_value(self):
        body = {
            'unshelve': {
                'availability_zone': None
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError,
                          self.controller._unshelve,
                          self.req, fakes.FAKE_UUID,
                          body=body)

    def test_unshelve_with_additional_param(self):
        body = {
            'unshelve': {
                'availability_zone': 'us-east',
                'additional_param': 1
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        exc = self.assertRaises(
            exception.ValidationError,
            self.controller._unshelve, self.req,
            fakes.FAKE_UUID, body=body)
        self.assertIn("Additional properties are not allowed",
                      six.text_type(exc))
