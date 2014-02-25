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

from oslo.config import cfg

from nova.api.openstack.compute.plugins.v3 import attach_interfaces
from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova.network import api as network_api
from nova.openstack.common import jsonutils
from nova import test
from nova.tests import fake_network_cache_model

import webob
from webob import exc


CONF = cfg.CONF

FAKE_UUID1 = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FAKE_UUID2 = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'

FAKE_PORT_ID1 = '11111111-1111-1111-1111-111111111111'
FAKE_PORT_ID2 = '22222222-2222-2222-2222-222222222222'
FAKE_PORT_ID3 = '33333333-3333-3333-3333-333333333333'

FAKE_NET_ID1 = '44444444-4444-4444-4444-444444444444'
FAKE_NET_ID2 = '55555555-5555-5555-5555-555555555555'
FAKE_NET_ID3 = '66666666-6666-6666-6666-666666666666'

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


def fake_attach_interface(self, context, instance, network_id, port_id,
                          requested_ip='192.168.1.3'):
    if not network_id:
    # if no network_id is given when add a port to an instance, use the
    # first default network.
        network_id = fake_networks[0]
    if network_id == 'bad_id':
        raise exception.NetworkNotFound(network_id=network_id)
    if not port_id:
        port_id = ports[fake_networks.index(network_id)]['id']
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
    return {}


class InterfaceAttachTests(test.NoDBTestCase):
    def setUp(self):
        super(InterfaceAttachTests, self).setUp()
        self.flags(neutron_auth_strategy=None)
        self.flags(neutron_url='http://anyhost/')
        self.flags(neutron_url_timeout=30)
        self.stubs.Set(network_api.API, 'show_port', fake_show_port)
        self.stubs.Set(network_api.API, 'list_ports', fake_list_ports)
        self.stubs.Set(compute_api.API, 'get', fake_get_instance)
        self.context = context.get_admin_context()
        self.expected_show = {'interface_attachment':
            {'net_id': FAKE_NET_ID1,
             'port_id': FAKE_PORT_ID1,
             'mac_addr': port_data1['mac_address'],
             'port_state': port_data1['status'],
             'fixed_ips': port_data1['fixed_ips'],
            }}

    def test_item_instance_not_found(self):
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank('/v3/servers/fake/os-attach-interfaces/')
        req.method = 'GET'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        def fake_get_instance_exception(self, context, instance_uuid,
                                        **kwargs):
            raise exception.InstanceNotFound(instance_id=instance_uuid)

        self.stubs.Set(compute_api.API, 'get', fake_get_instance_exception)
        self.assertRaises(exc.HTTPNotFound, attachments.index,
                          req, 'fake')

    def test_show(self):
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank('/v3/servers/fake/os-attach-interfaces/show')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        result = attachments.show(req, FAKE_UUID1, FAKE_PORT_ID1)
        self.assertEqual(self.expected_show, result)

    def test_show_instance_not_found(self):
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank('/v3/servers/fake/os-attach-interfaces/show')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        def fake_get_instance_exception(self, context, instance_uuid,
                                        **kwargs):
            raise exception.InstanceNotFound(instance_id=instance_uuid)

        self.stubs.Set(compute_api.API, 'get', fake_get_instance_exception)
        self.assertRaises(exc.HTTPNotFound, attachments.show,
                          req, 'fake', FAKE_PORT_ID1)

    def test_show_invalid(self):
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank('/v3/servers/fake/os-attach-interfaces/show')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(exc.HTTPNotFound,
                          attachments.show, req, FAKE_UUID2, FAKE_PORT_ID1)

    def test_delete(self):
        self.stubs.Set(compute_api.API, 'detach_interface',
                       fake_detach_interface)
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank(
            '/v3/servers/fake/os-attach-interfaces/delete')
        req.method = 'DELETE'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        result = attachments.delete(req, FAKE_UUID1, FAKE_PORT_ID1)
        self.assertEqual('202 Accepted', result.status)

    def test_delete_interface_not_found(self):
        self.stubs.Set(compute_api.API, 'detach_interface',
                       fake_detach_interface)
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank(
            '/v3/servers/fake/os-attach-interfaces/delete')
        req.method = 'DELETE'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(exc.HTTPNotFound,
                          attachments.delete,
                          req,
                          FAKE_UUID1,
                          'invaid-port-id')

    def test_delete_instance_not_found(self):
        self.stubs.Set(compute_api.API, 'detach_interface',
                       fake_detach_interface)
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank(
            '/v3/servers/fake/os-attach-interfaces/delete')
        req.method = 'DELETE'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        def fake_get_instance_exception(self, context, instance_uuid,
                                        **kwargs):
            raise exception.InstanceNotFound(instance_id=instance_uuid)

        self.stubs.Set(compute_api.API, 'get', fake_get_instance_exception)
        self.assertRaises(exc.HTTPNotFound,
                          attachments.delete,
                          req,
                          'fake',
                          'invaid-port-id')

    def test_attach_interface_without_network_id(self):
        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface)
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank(
            '/v3/servers/fake/os-attach-interfaces/attach')
        req.method = 'POST'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        result = attachments.create(req, FAKE_UUID1,
                                    jsonutils.loads(req.body))
        self.assertEqual(result['interface_attachment']['net_id'],
                         FAKE_NET_ID1)

    def test_attach_interface_with_network_id(self):
        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface)
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank(
            '/v3/servers/fake/os-attach-interfaces/attach')
        req.method = 'POST'
        req.body = jsonutils.dumps({'interface_attachment':
                                   {'net_id': FAKE_NET_ID2}})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        result = attachments.create(req,
                                    FAKE_UUID1, jsonutils.loads(req.body))
        self.assertEqual(result['interface_attachment']['net_id'],
                         FAKE_NET_ID2)

    def test_attach_interface_with_port_and_network_id(self):
        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface)
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank(
            '/v3/servers/fake/os-attach-interfaces/attach')
        req.method = 'POST'
        req.body = jsonutils.dumps({'interface_attachment':
                                   {'port_id': FAKE_PORT_ID1,
                                    'net_id': FAKE_NET_ID2}})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        self.assertRaises(exc.HTTPBadRequest,
                          attachments.create, req, FAKE_UUID1,
                          jsonutils.loads(req.body))

    def test_attach_interface_instance_not_found(self):
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank(
            '/v3/servers/fake/os-attach-interfaces/attach')
        req.method = 'POST'
        req.body = jsonutils.dumps({'interface_attachment':
                                   {'net_id': FAKE_NET_ID2}})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        def fake_get_instance_exception(self, context, instance_uuid,
                                        **kwargs):
            raise exception.InstanceNotFound(instance_id=instance_uuid)

        self.stubs.Set(compute_api.API, 'get', fake_get_instance_exception)
        self.assertRaises(exc.HTTPNotFound,
                          attachments.create, req, 'fake',
                          jsonutils.loads(req.body))

    def test_attach_interface_with_invalid_data(self):
        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface)
        attachments = attach_interfaces.InterfaceAttachmentController()
        req = webob.Request.blank(
            '/v3/servers/fake/os-attach-interfaces/attach')
        req.method = 'POST'
        req.body = jsonutils.dumps({'interface_attachment':
                                    {'net_id': 'bad_id'}})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        self.assertRaises(exc.HTTPBadRequest,
                          attachments.create, req, FAKE_UUID1,
                          jsonutils.loads(req.body))
