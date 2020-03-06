# Copyright 2012 SINA Inc.
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
import six
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute import attach_interfaces \
        as attach_interfaces_v21
from nova.compute import api as compute_api
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network_cache_model


FAKE_UUID1 = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FAKE_UUID2 = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'

FAKE_PORT_ID1 = '11111111-1111-1111-1111-111111111111'
FAKE_PORT_ID2 = '22222222-2222-2222-2222-222222222222'
FAKE_PORT_ID3 = '33333333-3333-3333-3333-333333333333'
FAKE_NOT_FOUND_PORT_ID = '00000000-0000-0000-0000-000000000000'

FAKE_NET_ID1 = '44444444-4444-4444-4444-444444444444'
FAKE_NET_ID2 = '55555555-5555-5555-5555-555555555555'
FAKE_NET_ID3 = '66666666-6666-6666-6666-666666666666'
FAKE_BAD_NET_ID = '00000000-0000-0000-0000-000000000000'

port_data1 = {
    "id": FAKE_PORT_ID1,
    "network_id": FAKE_NET_ID1,
    "admin_state_up": True,
    "status": "ACTIVE",
    "mac_address": "aa:aa:aa:aa:aa:aa",
    "fixed_ips": ["10.0.1.2"],
    "device_id": FAKE_UUID1,
}

port_data2 = {
    "id": FAKE_PORT_ID2,
    "network_id": FAKE_NET_ID2,
    "admin_state_up": True,
    "status": "ACTIVE",
    "mac_address": "bb:bb:bb:bb:bb:bb",
    "fixed_ips": ["10.0.2.2"],
    "device_id": FAKE_UUID1,
}

port_data3 = {
    "id": FAKE_PORT_ID3,
    "network_id": FAKE_NET_ID3,
    "admin_state_up": True,
    "status": "ACTIVE",
    "mac_address": "bb:bb:bb:bb:bb:bb",
    "fixed_ips": ["10.0.2.2"],
    "device_id": '',
}

fake_networks = [FAKE_NET_ID1, FAKE_NET_ID2]
ports = [port_data1, port_data2, port_data3]


def fake_show_port(context, port_id, **kwargs):
    for port in ports:
        if port['id'] == port_id:
            return {'port': port}
    else:
        raise exception.PortNotFound(port_id=port_id)


def fake_attach_interface(self, context, instance, network_id, port_id,
                          requested_ip='192.168.1.3', tag=None):
    if not network_id:
        # if no network_id is given when add a port to an instance, use the
        # first default network.
        network_id = fake_networks[0]
    if network_id == FAKE_BAD_NET_ID:
        raise exception.NetworkNotFound(network_id=network_id)
    if not port_id:
        port_id = ports[fake_networks.index(network_id)]['id']
    if port_id == FAKE_NOT_FOUND_PORT_ID:
        raise exception.PortNotFound(port_id=port_id)
    vif = fake_network_cache_model.new_vif()
    vif['id'] = port_id
    vif['network']['id'] = network_id
    vif['network']['subnets'][0]['ips'][0]['address'] = requested_ip
    return vif


def fake_detach_interface(self, context, instance, port_id):
    for port in ports:
        if port['id'] == port_id:
            return
    raise exception.PortNotFound(port_id=port_id)


def fake_get_instance(self, context, instance_id, expected_attrs=None,
                      cell_down_support=False):
    return fake_instance.fake_instance_obj(
            context, id=1, uuid=instance_id, project_id=context.project_id)


class InterfaceAttachTestsV21(test.NoDBTestCase):
    controller_cls = attach_interfaces_v21.InterfaceAttachmentController
    validate_exc = exception.ValidationError
    in_use_exc = exc.HTTPConflict
    not_found_exc = exc.HTTPNotFound
    not_usable_exc = exc.HTTPBadRequest

    def setUp(self):
        super(InterfaceAttachTestsV21, self).setUp()
        self.flags(timeout=30, group='neutron')
        self.stub_out('nova.compute.api.API.get', fake_get_instance)
        self.expected_show = {'interfaceAttachment':
            {'net_id': FAKE_NET_ID1,
             'port_id': FAKE_PORT_ID1,
             'mac_addr': port_data1['mac_address'],
             'port_state': port_data1['status'],
             'fixed_ips': port_data1['fixed_ips'],
            }}
        self.attachments = self.controller_cls()
        show_port_patch = mock.patch.object(self.attachments.network_api,
                                            'show_port', fake_show_port)
        show_port_patch.start()
        self.addCleanup(show_port_patch.stop)
        self.req = fakes.HTTPRequest.blank('')

    @mock.patch.object(compute_api.API, 'get',
                       side_effect=exception.InstanceNotFound(instance_id=''))
    def _test_instance_not_found(self, func, args, mock_get, kwargs=None):
        if not kwargs:
            kwargs = {}
        self.assertRaises(exc.HTTPNotFound, func, self.req, *args, **kwargs)

    def test_show_instance_not_found(self):
        self._test_instance_not_found(self.attachments.show, ('fake', 'fake'))

    def test_index_instance_not_found(self):
        self._test_instance_not_found(self.attachments.index, ('fake', ))

    def test_detach_interface_instance_not_found(self):
        self._test_instance_not_found(self.attachments.delete,
                                      ('fake', 'fake'))

    def test_attach_interface_instance_not_found(self):
        self._test_instance_not_found(self.attachments.create, ('fake', ),
            kwargs={'body': {'interfaceAttachment': {}}})

    def test_show(self):
        result = self.attachments.show(self.req, FAKE_UUID1, FAKE_PORT_ID1)
        self.assertEqual(self.expected_show, result)

    def test_show_with_port_not_found(self):
        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.show, self.req, FAKE_UUID2,
                          FAKE_PORT_ID1)

    def test_show_forbidden(self):
        with mock.patch.object(self.attachments.network_api, 'show_port',
                               side_effect=exception.Forbidden):
            self.assertRaises(exc.HTTPForbidden,
                              self.attachments.show, self.req, FAKE_UUID1,
                              FAKE_PORT_ID1)

    def test_delete(self):
        self.stub_out('nova.compute.api.API.detach_interface',
                      fake_detach_interface)
        req_context = self.req.environ['nova.context']
        inst = objects.Instance(uuid=FAKE_UUID1,
                                project_id=req_context.project_id)
        with mock.patch.object(common, 'get_instance',
                               return_value=inst) as mock_get_instance:
            result = self.attachments.delete(self.req, FAKE_UUID1,
                                             FAKE_PORT_ID1)
            # NOTE: on v2.1, http status code is set as wsgi_code of API
            # method instead of status_int in a response object.
            if isinstance(self.attachments,
                          attach_interfaces_v21.InterfaceAttachmentController):
                status_int = self.attachments.delete.wsgi_code
            else:
                status_int = result.status_int
            self.assertEqual(202, status_int)
            ctxt = self.req.environ['nova.context']
            mock_get_instance.assert_called_with(
                self.attachments.compute_api, ctxt, FAKE_UUID1,
                expected_attrs=['device_metadata'])

    def test_detach_interface_instance_locked(self):
        def fake_detach_interface_from_locked_server(self, context,
            instance, port_id):
            raise exception.InstanceIsLocked(instance_uuid=FAKE_UUID1)

        self.stub_out('nova.compute.api.API.detach_interface',
                      fake_detach_interface_from_locked_server)

        self.assertRaises(exc.HTTPConflict,
                          self.attachments.delete,
                          self.req,
                          FAKE_UUID1,
                          FAKE_PORT_ID1)

    def test_delete_interface_not_found(self):
        self.stub_out('nova.compute.api.API.detach_interface',
                      fake_detach_interface)

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.delete,
                          self.req,
                          FAKE_UUID1,
                          'invalid-port-id')

    def test_attach_interface_instance_locked(self):
        def fake_attach_interface_to_locked_server(self, context,
            instance, network_id, port_id, requested_ip, tag=None):
            raise exception.InstanceIsLocked(instance_uuid=FAKE_UUID1)

        self.stub_out('nova.compute.api.API.attach_interface',
                      fake_attach_interface_to_locked_server)
        body = {}
        self.assertRaises(exc.HTTPConflict,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    def test_attach_interface_without_network_id(self):
        self.stub_out('nova.compute.api.API.attach_interface',
                      fake_attach_interface)
        body = {}
        result = self.attachments.create(self.req, FAKE_UUID1, body=body)
        self.assertEqual(result['interfaceAttachment']['net_id'],
            FAKE_NET_ID1)

    @mock.patch.object(
        compute_api.API, 'attach_interface',
        side_effect=exception.NetworkInterfaceTaggedAttachNotSupported())
    def test_interface_tagged_attach_not_supported(self, mock_attach):
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID2}}
        self.assertRaises(exc.HTTPBadRequest, self.attachments.create,
                          self.req, FAKE_UUID1, body=body)

    def test_attach_interface_with_network_id(self):
        self.stub_out('nova.compute.api.API.attach_interface',
                      fake_attach_interface)
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID2}}
        result = self.attachments.create(self.req, FAKE_UUID1, body=body)
        self.assertEqual(result['interfaceAttachment']['net_id'],
            FAKE_NET_ID2)

    def _attach_interface_bad_request_case(self, body):
        self.stub_out('nova.compute.api.API.attach_interface',
                      fake_attach_interface)
        self.assertRaises(exc.HTTPBadRequest,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    def _attach_interface_not_found_case(self, body):
        self.stub_out('nova.compute.api.API.attach_interface',
                      fake_attach_interface)
        self.assertRaises(self.not_found_exc,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    def test_attach_interface_with_port_and_network_id(self):
        body = {
            'interfaceAttachment': {
                'port_id': FAKE_PORT_ID1,
                'net_id': FAKE_NET_ID2
            }
        }
        self._attach_interface_bad_request_case(body)

    def test_attach_interface_with_not_found_network_id(self):
        body = {
            'interfaceAttachment': {
                'net_id': FAKE_BAD_NET_ID
            }
        }
        self._attach_interface_not_found_case(body)

    def test_attach_interface_with_not_found_port_id(self):
        body = {
            'interfaceAttachment': {
                'port_id': FAKE_NOT_FOUND_PORT_ID
            }
        }
        self._attach_interface_not_found_case(body)

    def test_attach_interface_with_invalid_state(self):
        def fake_attach_interface_invalid_state(*args, **kwargs):
            raise exception.InstanceInvalidState(
                instance_uuid='', attr='', state='',
                method='attach_interface')

        self.stub_out('nova.compute.api.API.attach_interface',
                      fake_attach_interface_invalid_state)
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID1}}
        self.assertRaises(exc.HTTPConflict,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    def test_attach_interface_port_limit_exceeded(self):
        """Tests the scenario where nova-compute attempts to create a port to
        attach but the tenant port quota is exceeded and PortLimitExceeded
        is raised from the neutron API code which results in a 403 response.
        """
        with mock.patch.object(self.attachments.compute_api,
                               'attach_interface',
                               side_effect=exception.PortLimitExceeded):
            body = {'interfaceAttachment': {}}
            ex = self.assertRaises(
                exc.HTTPForbidden, self.attachments.create,
                self.req, FAKE_UUID1, body=body)
        self.assertIn('Maximum number of ports exceeded', six.text_type(ex))

    def test_detach_interface_with_invalid_state(self):
        def fake_detach_interface_invalid_state(*args, **kwargs):
            raise exception.InstanceInvalidState(
                instance_uuid='', attr='', state='',
                method='detach_interface')

        self.stub_out('nova.compute.api.API.detach_interface',
                      fake_detach_interface_invalid_state)
        self.assertRaises(exc.HTTPConflict,
                          self.attachments.delete,
                          self.req,
                          FAKE_UUID1,
                          FAKE_NET_ID1)

    @mock.patch.object(compute_api.API, 'detach_interface',
                       side_effect=NotImplementedError())
    def test_detach_interface_with_not_implemented(self, _mock):
        self.assertRaises(exc.HTTPNotImplemented,
                          self.attachments.delete,
                          self.req, FAKE_UUID1, FAKE_NET_ID1)

    def test_attach_interface_invalid_fixed_ip(self):
        body = {
            'interfaceAttachment': {
                'net_id': FAKE_NET_ID1,
                'fixed_ips': [{'ip_address': 'invalid_ip'}]
            }
        }
        self.assertRaises(self.validate_exc,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'attach_interface')
    def test_attach_interface_fixed_ip_already_in_use(self,
                                                      attach_mock,
                                                      get_mock):
        req_context = self.req.environ['nova.context']
        fake_instance = objects.Instance(uuid=FAKE_UUID1,
                                         project_id=req_context.project_id)
        get_mock.return_value = fake_instance
        attach_mock.side_effect = exception.FixedIpAlreadyInUse(
            address='10.0.2.2', instance_uuid=FAKE_UUID1)
        body = {}
        self.assertRaises(self.in_use_exc,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)
        ctxt = self.req.environ['nova.context']
        attach_mock.assert_called_once_with(ctxt, fake_instance, None,
                                            None, None, tag=None)
        get_mock.assert_called_once_with(ctxt, FAKE_UUID1,
                                         expected_attrs=None,
                                         cell_down_support=False)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'attach_interface')
    def test_attach_interface_port_in_use(self,
                                          attach_mock,
                                          get_mock):
        req_context = self.req.environ['nova.context']
        fake_instance = objects.Instance(uuid=FAKE_UUID1,
                                         project_id=req_context.project_id)
        get_mock.return_value = fake_instance
        attach_mock.side_effect = exception.PortInUse(
            port_id=FAKE_PORT_ID1)
        body = {}
        self.assertRaises(self.in_use_exc,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)
        ctxt = self.req.environ['nova.context']
        attach_mock.assert_called_once_with(ctxt, fake_instance, None,
                                            None, None, tag=None)
        get_mock.assert_called_once_with(ctxt, FAKE_UUID1,
                                         expected_attrs=None,
                                         cell_down_support=False)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'attach_interface')
    def test_attach_interface_port_not_usable(self,
                                              attach_mock,
                                              get_mock):
        req_context = self.req.environ['nova.context']
        fake_instance = objects.Instance(uuid=FAKE_UUID1,
                                         project_id=req_context.project_id)
        get_mock.return_value = fake_instance
        attach_mock.side_effect = exception.PortNotUsable(
            port_id=FAKE_PORT_ID1,
            instance=fake_instance.uuid)
        body = {}
        self.assertRaises(self.not_usable_exc,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)
        ctxt = self.req.environ['nova.context']
        attach_mock.assert_called_once_with(ctxt, fake_instance, None,
                                            None, None, tag=None)
        get_mock.assert_called_once_with(ctxt, FAKE_UUID1,
                                         expected_attrs=None,
                                         cell_down_support=False)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'attach_interface')
    def test_attach_interface_failed_no_network(self, attach_mock, get_mock):
        req_context = self.req.environ['nova.context']
        fake_instance = objects.Instance(uuid=FAKE_UUID1,
                                         project_id=req_context.project_id)
        get_mock.return_value = fake_instance
        attach_mock.side_effect = (
            exception.InterfaceAttachFailedNoNetwork(project_id=FAKE_UUID2))
        self.assertRaises(exc.HTTPBadRequest, self.attachments.create,
                          self.req, FAKE_UUID1, body={})
        ctxt = self.req.environ['nova.context']
        attach_mock.assert_called_once_with(ctxt, fake_instance, None,
                                            None, None, tag=None)
        get_mock.assert_called_once_with(ctxt, FAKE_UUID1,
                                         expected_attrs=None,
                                         cell_down_support=False)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'attach_interface')
    def test_attach_interface_no_more_fixed_ips(self,
                                          attach_mock,
                                          get_mock):
        req_context = self.req.environ['nova.context']
        fake_instance = objects.Instance(uuid=FAKE_UUID1,
                                         project_id=req_context.project_id)
        get_mock.return_value = fake_instance
        attach_mock.side_effect = exception.NoMoreFixedIps(
              net=FAKE_NET_ID1)
        body = {}
        self.assertRaises(exc.HTTPBadRequest,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)
        ctxt = self.req.environ['nova.context']
        attach_mock.assert_called_once_with(ctxt, fake_instance, None,
                                            None, None, tag=None)
        get_mock.assert_called_once_with(ctxt, FAKE_UUID1,
                                         expected_attrs=None,
                                         cell_down_support=False)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'attach_interface')
    def test_attach_interface_failed_securitygroup_cannot_be_applied(
        self, attach_mock, get_mock):
        req_context = self.req.environ['nova.context']
        fake_instance = objects.Instance(uuid=FAKE_UUID1,
                                         project_id=req_context.project_id)
        get_mock.return_value = fake_instance
        attach_mock.side_effect = (
            exception.SecurityGroupCannotBeApplied())
        self.assertRaises(exc.HTTPBadRequest, self.attachments.create,
                          self.req, FAKE_UUID1, body={})
        ctxt = self.req.environ['nova.context']
        attach_mock.assert_called_once_with(ctxt, fake_instance, None,
                                            None, None, tag=None)
        get_mock.assert_called_once_with(ctxt, FAKE_UUID1,
                                         expected_attrs=None,
                                         cell_down_support=False)

    def _test_attach_interface_with_invalid_parameter(self, param):
        self.stub_out('nova.compute.api.API.attach_interface',
                      fake_attach_interface)
        body = {'interface_attachment': param}
        self.assertRaises(exception.ValidationError,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    def test_attach_interface_instance_with_non_uuid_net_id(self):
        param = {'net_id': 'non_uuid'}
        self._test_attach_interface_with_invalid_parameter(param)

    def test_attach_interface_instance_with_non_uuid_port_id(self):
        param = {'port_id': 'non_uuid'}
        self._test_attach_interface_with_invalid_parameter(param)

    def test_attach_interface_instance_with_non_array_fixed_ips(self):
        param = {'fixed_ips': 'non_array'}
        self._test_attach_interface_with_invalid_parameter(param)


class InterfaceAttachTestsV249(test.NoDBTestCase):
    controller_cls = attach_interfaces_v21.InterfaceAttachmentController

    def setUp(self):
        super(InterfaceAttachTestsV249, self).setUp()
        self.attachments = self.controller_cls()
        self.req = fakes.HTTPRequest.blank('', version='2.49')

    def test_tagged_interface_attach_invalid_tag_comma(self):
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID2,
                                        'tag': ','}}
        self.assertRaises(exception.ValidationError, self.attachments.create,
                          self.req, FAKE_UUID1, body=body)

    def test_tagged_interface_attach_invalid_tag_slash(self):
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID2,
                                        'tag': '/'}}
        self.assertRaises(exception.ValidationError, self.attachments.create,
                          self.req, FAKE_UUID1, body=body)

    def test_tagged_interface_attach_invalid_tag_too_long(self):
        tag = ''.join(map(str, range(10, 41)))
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID2,
                                        'tag': tag}}
        self.assertRaises(exception.ValidationError, self.attachments.create,
                          self.req, FAKE_UUID1, body=body)

    @mock.patch('nova.compute.api.API.attach_interface')
    @mock.patch('nova.compute.api.API.get', fake_get_instance)
    def test_tagged_interface_attach_valid_tag(self, _):
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID2,
                                        'tag': 'foo'}}
        with mock.patch.object(self.attachments, 'show'):
            self.attachments.create(self.req, FAKE_UUID1, body=body)


class InterfaceAttachTestsV270(test.NoDBTestCase):
    """os-interface API tests for microversion 2.70"""
    def setUp(self):
        super(InterfaceAttachTestsV270, self).setUp()
        self.attachments = (
            attach_interfaces_v21.InterfaceAttachmentController())
        self.req = fakes.HTTPRequest.blank('', version='2.70')
        self.stub_out('nova.compute.api.API.get', fake_get_instance)

    @mock.patch('nova.objects.VirtualInterface.get_by_uuid', return_value=None)
    def test_show_interface_no_vif(self, mock_get_by_uuid):
        """Tests GET /servers/{server_id}/os-interface/{id} where there is no
        corresponding VirtualInterface database record for the attached port.
        """
        with mock.patch.object(self.attachments.network_api, 'show_port',
                               fake_show_port):
            attachment = self.attachments.show(
                self.req, FAKE_UUID1, FAKE_PORT_ID1)['interfaceAttachment']
        self.assertIn('tag', attachment)
        self.assertIsNone(attachment['tag'])
        ctxt = self.req.environ['nova.context']
        mock_get_by_uuid.assert_called_once_with(ctxt, FAKE_PORT_ID1)

    @mock.patch('nova.objects.VirtualInterfaceList.get_by_instance_uuid',
                return_value=objects.VirtualInterfaceList())
    def test_list_interfaces_no_vifs(self, mock_get_by_instance_uuid):
        """Tests GET /servers/{server_id}/os-interface where there is no
        corresponding VirtualInterface database record for the attached ports.
        """
        with mock.patch.object(self.attachments.network_api, 'list_ports',
                               return_value={'ports': ports}) as list_ports:
            attachments = self.attachments.index(
                self.req, FAKE_UUID1)['interfaceAttachments']
        for attachment in attachments:
            self.assertIn('tag', attachment)
            self.assertIsNone(attachment['tag'])
        ctxt = self.req.environ['nova.context']
        list_ports.assert_called_once_with(ctxt, device_id=FAKE_UUID1)
        mock_get_by_instance_uuid.assert_called_once_with(
            self.req.environ['nova.context'], FAKE_UUID1)
