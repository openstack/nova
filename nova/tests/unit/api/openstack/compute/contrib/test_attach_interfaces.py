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
from oslo_config import cfg

from nova.api.openstack.compute.contrib import attach_interfaces \
    as attach_interfaces_v2
from nova.api.openstack.compute.plugins.v3 import attach_interfaces \
    as attach_interfaces_v3
from nova.compute import api as compute_api
from nova import exception
from nova.network import api as network_api
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_network_cache_model

from webob import exc


CONF = cfg.CONF

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


def fake_list_ports(self, *args, **kwargs):
    result = []
    for port in ports:
        if port['device_id'] == kwargs['device_id']:
            result.append(port)
    return {'ports': result}


def fake_show_port(self, context, port_id, **kwargs):
    for port in ports:
        if port['id'] == port_id:
            return {'port': port}
    else:
        raise exception.PortNotFound(port_id=port_id)


def fake_attach_interface(self, context, instance, network_id, port_id,
                          requested_ip='192.168.1.3'):
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


def fake_get_instance(self, *args, **kwargs):
    return objects.Instance(uuid=FAKE_UUID1)


class InterfaceAttachTestsV21(test.NoDBTestCase):
    controller_cls = attach_interfaces_v3.InterfaceAttachmentController
    validate_exc = exception.ValidationError
    in_use_exc = exc.HTTPConflict
    not_found_exc = exc.HTTPNotFound

    def setUp(self):
        super(InterfaceAttachTestsV21, self).setUp()
        self.flags(auth_strategy=None, group='neutron')
        self.flags(url='http://anyhost/', group='neutron')
        self.flags(url_timeout=30, group='neutron')
        self.stubs.Set(network_api.API, 'show_port', fake_show_port)
        self.stubs.Set(network_api.API, 'list_ports', fake_list_ports)
        self.stubs.Set(compute_api.API, 'get', fake_get_instance)
        self.expected_show = {'interfaceAttachment':
            {'net_id': FAKE_NET_ID1,
             'port_id': FAKE_PORT_ID1,
             'mac_addr': port_data1['mac_address'],
             'port_state': port_data1['status'],
             'fixed_ips': port_data1['fixed_ips'],
            }}
        self.attachments = self.controller_cls()
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

    def test_show_invalid(self):
        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.show, self.req, FAKE_UUID2,
                          FAKE_PORT_ID1)

    @mock.patch.object(network_api.API, 'show_port',
                       side_effect=exception.Forbidden)
    def test_show_forbidden(self, show_port_mock):
        self.assertRaises(exc.HTTPForbidden,
                          self.attachments.show, self.req, FAKE_UUID1,
                          FAKE_PORT_ID1)

    def test_delete(self):
        self.stubs.Set(compute_api.API, 'detach_interface',
                       fake_detach_interface)

        result = self.attachments.delete(self.req, FAKE_UUID1, FAKE_PORT_ID1)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.attachments,
                      attach_interfaces_v3.InterfaceAttachmentController):
            status_int = self.attachments.delete.wsgi_code
        else:
            status_int = result.status_int
        self.assertEqual(202, status_int)

    def test_detach_interface_instance_locked(self):
        def fake_detach_interface_from_locked_server(self, context,
            instance, port_id):
            raise exception.InstanceIsLocked(instance_uuid=FAKE_UUID1)

        self.stubs.Set(compute_api.API,
                       'detach_interface',
                       fake_detach_interface_from_locked_server)

        self.assertRaises(exc.HTTPConflict,
                          self.attachments.delete,
                          self.req,
                          FAKE_UUID1,
                          FAKE_PORT_ID1)

    def test_delete_interface_not_found(self):
        self.stubs.Set(compute_api.API, 'detach_interface',
                       fake_detach_interface)

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.delete,
                          self.req,
                          FAKE_UUID1,
                          'invaid-port-id')

    def test_attach_interface_instance_locked(self):
        def fake_attach_interface_to_locked_server(self, context,
            instance, network_id, port_id, requested_ip):
            raise exception.InstanceIsLocked(instance_uuid=FAKE_UUID1)

        self.stubs.Set(compute_api.API,
                       'attach_interface',
                       fake_attach_interface_to_locked_server)
        body = {}
        self.assertRaises(exc.HTTPConflict,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    def test_attach_interface_without_network_id(self):
        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface)
        body = {}
        result = self.attachments.create(self.req, FAKE_UUID1, body=body)
        self.assertEqual(result['interfaceAttachment']['net_id'],
            FAKE_NET_ID1)

    def test_attach_interface_with_network_id(self):
        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface)
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID2}}
        result = self.attachments.create(self.req, FAKE_UUID1, body=body)
        self.assertEqual(result['interfaceAttachment']['net_id'],
            FAKE_NET_ID2)

    def _attach_interface_bad_request_case(self, body):
        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface)
        self.assertRaises(exc.HTTPBadRequest,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    def _attach_interface_not_found_case(self, body):
        self.stubs.Set(compute_api.API, 'attach_interface',
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

        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface_invalid_state)
        body = {'interfaceAttachment': {'net_id': FAKE_NET_ID1}}
        self.assertRaises(exc.HTTPConflict,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)

    def test_detach_interface_with_invalid_state(self):
        def fake_detach_interface_invalid_state(*args, **kwargs):
            raise exception.InstanceInvalidState(
                instance_uuid='', attr='', state='',
                method='detach_interface')

        self.stubs.Set(compute_api.API, 'detach_interface',
                       fake_detach_interface_invalid_state)
        self.assertRaises(exc.HTTPConflict,
                          self.attachments.delete,
                          self.req,
                          FAKE_UUID1,
                          FAKE_NET_ID1)

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
        fake_instance = objects.Instance(uuid=FAKE_UUID1)
        get_mock.return_value = fake_instance
        attach_mock.side_effect = exception.FixedIpAlreadyInUse(
            address='10.0.2.2', instance_uuid=FAKE_UUID1)
        body = {}
        self.assertRaises(self.in_use_exc,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)
        ctxt = self.req.environ['nova.context']
        attach_mock.assert_called_once_with(ctxt, fake_instance, None,
                                            None, None)
        get_mock.assert_called_once_with(ctxt, FAKE_UUID1,
                                         want_objects=True,
                                         expected_attrs=None)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'attach_interface')
    def test_attach_interface_port_in_use(self,
                                          attach_mock,
                                          get_mock):
        fake_instance = objects.Instance(uuid=FAKE_UUID1)
        get_mock.return_value = fake_instance
        attach_mock.side_effect = exception.PortInUse(
            port_id=FAKE_PORT_ID1)
        body = {}
        self.assertRaises(self.in_use_exc,
                          self.attachments.create, self.req, FAKE_UUID1,
                          body=body)
        ctxt = self.req.environ['nova.context']
        attach_mock.assert_called_once_with(ctxt, fake_instance, None,
                                            None, None)
        get_mock.assert_called_once_with(ctxt, FAKE_UUID1,
                                         want_objects=True,
                                         expected_attrs=None)

    def _test_attach_interface_with_invalid_parameter(self, param):
        self.stubs.Set(compute_api.API, 'attach_interface',
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


class InterfaceAttachTestsV2(InterfaceAttachTestsV21):
    controller_cls = attach_interfaces_v2.InterfaceAttachmentController
    validate_exc = exc.HTTPBadRequest
    in_use_exc = exc.HTTPBadRequest
    not_found_exc = exc.HTTPBadRequest

    def test_attach_interface_instance_with_non_uuid_net_id(self):
        pass

    def test_attach_interface_instance_with_non_uuid_port_id(self):
        pass

    def test_attach_interface_instance_with_non_array_fixed_ips(self):
        pass
