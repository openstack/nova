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

from unittest import mock

import ddt
import fixtures
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
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
            self.req, uuids.fake, body={'shelve': None})

    @ddt.data(
        exception.ForbiddenWithAccelerators(),
        exception.OperationNotSupportedForVTPM(
            instance_uuid=uuids.instance, operation='foo'),
        exception.OperationNotSupportedForVDPAInterface(
            instance_uuid=uuids.instance, operation='foo'),
    )
    @mock.patch('nova.compute.api.API.shelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_raise_badrequest_for_not_supported_feature(
        self, exc, mock_get_instance, mock_shelve,
    ):
        mock_get_instance.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        mock_shelve.side_effect = exc
        self.assertRaises(
            webob.exc.HTTPBadRequest, self.controller._shelve,
            self.req, uuids.fake, body={'shelve': None})

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_locked_server(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        self.stub_out('nova.compute.api.API.unshelve',
                      fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self.controller._unshelve,
                          self.req, uuids.fake, body={'unshelve': None})

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_offload_locked_server(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        self.stub_out('nova.compute.api.API.shelve_offload',
                      fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._shelve_offload,
                          self.req, uuids.fake, body={'shelveOffload': None})


class UnshelveServerControllerTestV277(test.NoDBTestCase):
    """Server controller test for microversion 2.77

    Add availability_zone parameter to unshelve a shelved-offloaded server of
    2.77 microversion.
    """
    wsgi_api_version = '2.77'

    def setUp(self):
        super(UnshelveServerControllerTestV277, self).setUp()
        self.mock_neutron_extension_list = self.useFixture(
            fixtures.MockPatch(
                'nova.network.neutron.API._refresh_neutron_extensions_cache'
            )
        ).mock
        self.mock_neutron_extension_list.return_value = {'extensions': []}
        self.controller = shelve_v21.ShelveController()
        self.req = fakes.HTTPRequest.blank(
                '/%s/servers/a/action' % fakes.FAKE_PROJECT_ID,
                use_admin_context=True, version=self.wsgi_api_version)

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
        self.req.api_version_request = (
            api_version_request.APIVersionRequest('2.76')
        )
        with mock.patch.object(
            self.controller.compute_api, 'unshelve'
        ) as mock_unshelve:
            self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'],
            instance,
        )

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
            self.req.environ['nova.context'],
            instance,
        )

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
        self.assertIn("\'availability_zone\' is a required property", str(exc))

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
        self.assertRaises(
                exception.ValidationError,
                self.controller._unshelve,
                self.req,
                fakes.FAKE_UUID, body=body)

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
        self.assertIn("Additional properties are not allowed", str(exc))


class UnshelveServerControllerTestV291(test.NoDBTestCase):
    """Server controller test for microversion 2.91

    Add host parameter to unshelve a shelved-offloaded server of
    2.91 microversion.
    """
    wsgi_api_version = '2.91'

    def setUp(self):
        super(UnshelveServerControllerTestV291, self).setUp()
        self.controller = shelve_v21.ShelveController()
        self.req = fakes.HTTPRequest.blank(
                '/%s/servers/a/action' % fakes.FAKE_PROJECT_ID,
                use_admin_context=True, version=self.wsgi_api_version)

    def fake_get_instance(self):
        ctxt = self.req.environ['nova.context']
        return fake_instance.fake_instance_obj(
            ctxt, uuid=fakes.FAKE_UUID, vm_state=vm_states.SHELVED_OFFLOADED)

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_az_pre_2_91(self, mock_get_instance):
        """Make sure specifying an AZ before microversion 2.91
        is still working.
        """
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {
            'unshelve': {
                'availability_zone': 'us-east',
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (
                api_version_request.APIVersionRequest('2.77'))
        with mock.patch.object(
            self.controller.compute_api, 'unshelve'
        ) as mock_unshelve:
            self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'],
            instance,
            new_az='us-east',
        )

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_without_parameters_2_91(self, mock_get_instance):
        """Make sure not specifying parameters with microversion 2.91
        is working.
        """
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {
            'unshelve': None
        }
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (
                api_version_request.APIVersionRequest('2.91'))
        with mock.patch.object(
                self.controller.compute_api, 'unshelve') as mock_unshelve:
            self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'],
            instance,
        )

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_az_2_91(self, mock_get_instance):
        """Make sure specifying an AZ with microversion 2.91
        is working.
        """
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {
            'unshelve': {
                'availability_zone': 'us-east',
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (
                api_version_request.APIVersionRequest('2.91'))
        with mock.patch.object(
                self.controller.compute_api, 'unshelve') as mock_unshelve:
            self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'],
            instance,
            new_az='us-east',
            host=None,
        )

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_az_none_2_91(self, mock_get_instance):
        """Make sure specifying an AZ to none (unpin server)
        is working.
        """
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {
            'unshelve': {
                'availability_zone': None,
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (
                api_version_request.APIVersionRequest('2.91'))
        with mock.patch.object(
                self.controller.compute_api, 'unshelve') as mock_unshelve:
            self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'],
            instance,
            new_az=None,
            host=None,
        )

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_host_2_91(self, mock_get_instance):
        """Make sure specifying a host with microversion 2.91
        is working.
        """
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {
            'unshelve': {
                'host': 'server02',
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (
                api_version_request.APIVersionRequest('2.91'))
        with mock.patch.object(
                self.controller.compute_api, 'unshelve') as mock_unshelve:
            self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'],
            instance,
            host='server02',
        )

    @mock.patch('nova.compute.api.API.unshelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_az_and_host_with_v2_91(
            self, mock_get_instance, mock_unshelve):
        """Make sure specifying a host and an availability_zone with
        microversion 2.91 is working.
        """
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {
            'unshelve': {
                'availability_zone': 'us-east',
                'host': 'server01',
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (
                api_version_request.APIVersionRequest('2.91'))

        self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        self.controller.compute_api.unshelve.assert_called_once_with(
            self.req.environ['nova.context'],
            instance,
            new_az='us-east',
            host='server01',
        )

    def test_invalid_az_name_with_int(self):
        body = {
            'unshelve': {
                'host': 1234
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(
                exception.ValidationError,
                self.controller._unshelve,
                self.req,
                fakes.FAKE_UUID,
                body=body)

    def test_no_az_value(self):
        body = {
            'unshelve': {
                'host': None
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(
                exception.ValidationError,
                self.controller._unshelve,
                self.req,
                fakes.FAKE_UUID, body=body)

    def test_invalid_host_fqdn_with_int(self):
        body = {
            'unshelve': {
                'host': 1234
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(
                exception.ValidationError,
                self.controller._unshelve,
                self.req,
                fakes.FAKE_UUID,
                body=body)

    def test_no_host(self):
        body = {
            'unshelve': {
                'host': None
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError,
                          self.controller._unshelve,
                          self.req, fakes.FAKE_UUID,
                          body=body)

    def test_unshelve_with_additional_param(self):
        body = {
            'unshelve': {
                'host': 'server01',
                'additional_param': 1
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        exc = self.assertRaises(
            exception.ValidationError,
            self.controller._unshelve, self.req,
            fakes.FAKE_UUID, body=body)
        self.assertIn("Invalid input for field/attribute unshelve.", str(exc))
