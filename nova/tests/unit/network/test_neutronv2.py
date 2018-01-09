# Copyright 2012 OpenStack Foundation
# All Rights Reserved
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
#

import collections
import copy

from keystoneauth1.fixture import V2Token
from keystoneauth1 import loading as ks_loading
from keystoneauth1 import service_token
import mock
from mox3 import mox
import netaddr
from neutronclient.common import exceptions
from neutronclient.v2_0 import client
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_policy import policy as oslo_policy
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import requests_mock
import six
from six.moves import range

from nova.compute import flavors
from nova import context
from nova import exception
from nova.network import model
from nova.network.neutronv2 import api as neutronapi
from nova.network.neutronv2 import constants
from nova import objects
from nova.objects import network_request as net_req_obj
from nova.pci import manager as pci_manager
from nova.pci import utils as pci_utils
from nova.pci import whitelist as pci_whitelist
from nova import policy
from nova import service_auth
from nova import test
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids

CONF = cfg.CONF

# NOTE: Neutron client raises Exception which is discouraged by HACKING.
#       We set this variable here and use it for assertions below to avoid
#       the hacking checks until we can make neutron client throw a custom
#       exception class instead.
NEUTRON_CLIENT_EXCEPTION = Exception

fake_info_cache = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'instance_uuid': uuids.instance,
    'network_info': '[]',
    }


class MyComparator(mox.Comparator):
    def __init__(self, lhs):
        self.lhs = lhs

    def _com_dict(self, lhs, rhs):
        if len(lhs) != len(rhs):
            return False
        for key, value in lhs.items():
            if key not in rhs:
                return False
            rhs_value = rhs[key]
            if not self._com(value, rhs_value):
                return False
        return True

    def _com_list(self, lhs, rhs):
        if len(lhs) != len(rhs):
            return False
        for lhs_value in lhs:
            if lhs_value not in rhs:
                return False
        return True

    def _com(self, lhs, rhs):
        if lhs is None:
            return rhs is None
        if isinstance(lhs, dict):
            if not isinstance(rhs, dict):
                return False
            return self._com_dict(lhs, rhs)
        if isinstance(lhs, list):
            if not isinstance(rhs, list):
                return False
            return self._com_list(lhs, rhs)
        if isinstance(lhs, tuple):
            if not isinstance(rhs, tuple):
                return False
            return self._com_list(lhs, rhs)
        return lhs == rhs

    def equals(self, rhs):
        return self._com(self.lhs, rhs)

    def __repr__(self):
        return str(self.lhs)


class TestNeutronClient(test.NoDBTestCase):

    def setUp(self):
        super(TestNeutronClient, self).setUp()
        neutronapi.reset_state()
        self.addCleanup(service_auth.reset_globals)

    def test_ksa_adapter_loading_defaults(self):
        """No 'url' triggers ksa loading path with defaults."""
        my_context = context.RequestContext('userid',
                                            uuids.my_tenant,
                                            auth_token='token')
        cl = neutronapi.get_client(my_context)
        self.assertEqual('network', cl.httpclient.service_type)
        self.assertIsNone(cl.httpclient.service_name)
        self.assertEqual(['internal', 'public'], cl.httpclient.interface)
        self.assertIsNone(cl.httpclient.region_name)
        self.assertIsNone(cl.httpclient.endpoint_override)

    def test_ksa_adapter_loading(self):
        """Test ksa loading path with specified values."""
        self.flags(group='neutron',
                   service_type='st',
                   service_name='sn',
                   valid_interfaces='admin',
                   region_name='RegionTwo',
                   endpoint_override='eo')
        my_context = context.RequestContext('userid',
                                            uuids.my_tenant,
                                            auth_token='token')
        cl = neutronapi.get_client(my_context)
        self.assertEqual('st', cl.httpclient.service_type)
        self.assertEqual('sn', cl.httpclient.service_name)
        self.assertEqual(['admin'], cl.httpclient.interface)
        self.assertEqual('RegionTwo', cl.httpclient.region_name)
        self.assertEqual('eo', cl.httpclient.endpoint_override)

    def test_withtoken(self):
        self.flags(url='http://anyhost/', group='neutron')
        self.flags(timeout=30, group='neutron')
        my_context = context.RequestContext('userid',
                                            uuids.my_tenant,
                                            auth_token='token')
        cl = neutronapi.get_client(my_context)

        self.assertEqual(CONF.neutron.url, cl.httpclient.endpoint_override)
        # Specifying 'url' defaults 'region_name'
        self.assertEqual('RegionOne', cl.httpclient.region_name)
        self.assertEqual(my_context.auth_token, cl.httpclient.auth.auth_token)
        self.assertEqual(CONF.neutron.timeout, cl.httpclient.session.timeout)

    def test_withouttoken(self):
        my_context = context.RequestContext('userid', uuids.my_tenant)
        self.assertRaises(exception.Unauthorized,
                          neutronapi.get_client,
                          my_context)

    @mock.patch.object(ks_loading, 'load_auth_from_conf_options')
    def test_non_admin_with_service_token(self, mock_load):
        self.flags(send_service_user_token=True, group='service_user')

        my_context = context.RequestContext('userid',
                                            uuids.my_tenant,
                                            auth_token='token')

        cl = neutronapi.get_client(my_context)
        self.assertIsInstance(cl.httpclient.auth,
                              service_token.ServiceTokenAuthWrapper)

    @mock.patch.object(client.Client, "list_networks",
                       side_effect=exceptions.Unauthorized())
    def test_Unauthorized_user(self, mock_list_networks):
        my_context = context.RequestContext('userid', uuids.my_tenant,
                                            auth_token='token',
                                            is_admin=False)
        client = neutronapi.get_client(my_context)
        self.assertRaises(
            exception.Unauthorized,
            client.list_networks)

    @mock.patch.object(client.Client, "list_networks",
                       side_effect=exceptions.Unauthorized())
    def test_Unauthorized_admin(self, mock_list_networks):
        my_context = context.RequestContext('userid', uuids.my_tenant,
                                            auth_token='token',
                                            is_admin=True)
        client = neutronapi.get_client(my_context)
        self.assertRaises(
            exception.NeutronAdminCredentialConfigurationInvalid,
            client.list_networks)

    @mock.patch.object(client.Client, "create_port",
                       side_effect=exceptions.Forbidden())
    def test_Forbidden(self, mock_create_port):
        my_context = context.RequestContext('userid', uuids.my_tenant,
                                            auth_token='token',
                                            is_admin=False)
        client = neutronapi.get_client(my_context)
        exc = self.assertRaises(
            exception.Forbidden,
            client.create_port)
        self.assertIsInstance(exc.format_message(), six.text_type)

    def test_withtoken_context_is_admin(self):
        self.flags(url='http://anyhost/', group='neutron')
        self.flags(timeout=30, group='neutron')
        my_context = context.RequestContext('userid',
                                            uuids.my_tenant,
                                            auth_token='token',
                                            is_admin=True)
        cl = neutronapi.get_client(my_context)

        self.assertEqual(CONF.neutron.url, cl.httpclient.endpoint_override)
        self.assertEqual(my_context.auth_token,
                         cl.httpclient.auth.auth_token)
        self.assertEqual(CONF.neutron.timeout, cl.httpclient.session.timeout)

    def test_withouttoken_keystone_connection_error(self):
        self.flags(url='http://anyhost/', group='neutron')
        my_context = context.RequestContext('userid', uuids.my_tenant)
        self.assertRaises(NEUTRON_CLIENT_EXCEPTION,
                          neutronapi.get_client,
                          my_context)

    @mock.patch('nova.network.neutronv2.api._ADMIN_AUTH')
    @mock.patch.object(client.Client, "list_networks", new=mock.Mock())
    def test_reuse_admin_token(self, m):
        self.flags(url='http://anyhost/', group='neutron')
        my_context = context.RequestContext('userid', uuids.my_tenant,
                                            auth_token='token')

        tokens = ['new_token2', 'new_token1']

        def token_vals(*args, **kwargs):
            return tokens.pop()

        m.get_token.side_effect = token_vals

        client1 = neutronapi.get_client(my_context, True)
        client1.list_networks(retrieve_all=False)
        self.assertEqual('new_token1', client1.httpclient.auth.get_token(None))

        client1 = neutronapi.get_client(my_context, True)
        client1.list_networks(retrieve_all=False)
        self.assertEqual('new_token2', client1.httpclient.auth.get_token(None))

    @mock.patch.object(ks_loading, 'load_auth_from_conf_options')
    def test_load_auth_plugin_failed(self, mock_load_from_conf):
        mock_load_from_conf.return_value = None
        from neutronclient.common import exceptions as neutron_client_exc
        self.assertRaises(neutron_client_exc.Unauthorized,
                          neutronapi._load_auth_plugin, CONF)

    @mock.patch.object(client.Client, "list_networks",
                       side_effect=exceptions.Unauthorized())
    def test_wrapper_exception_translation(self, m):
        my_context = context.RequestContext('userid', 'my_tenantid',
                                            auth_token='token')
        client = neutronapi.get_client(my_context)
        self.assertRaises(
            exception.Unauthorized,
            client.list_networks)


class TestNeutronv2Base(test.TestCase):

    def setUp(self):
        super(TestNeutronv2Base, self).setUp()
        self.context = context.RequestContext('userid', uuids.my_tenant)
        setattr(self.context,
                'auth_token',
                'bff4a5a6b9eb4ea2a6efec6eefb77936')
        self.tenant_id = '9d049e4b60b64716978ab415e6fbd5c0'
        self.instance = {'project_id': self.tenant_id,
                         'uuid': uuids.fake,
                         'display_name': 'test_instance',
                         'hostname': 'test-instance',
                         'availability_zone': 'nova',
                         'host': 'some_host',
                         'info_cache': {'network_info': []},
                         'security_groups': []}
        self.instance2 = {'project_id': self.tenant_id,
                         'uuid': uuids.fake,
                         'display_name': 'test_instance2',
                         'availability_zone': 'nova',
                         'info_cache': {'network_info': []},
                         'security_groups': []}
        self.nets1 = [{'id': uuids.my_netid1,
                      'name': 'my_netname1',
                      'subnets': ['mysubnid1'],
                      'tenant_id': uuids.my_tenant}]
        self.nets2 = []
        self.nets2.append(self.nets1[0])
        self.nets2.append({'id': uuids.my_netid2,
                           'name': 'my_netname2',
                           'subnets': ['mysubnid2'],
                           'tenant_id': uuids.my_tenant})
        self.nets3 = self.nets2 + [{'id': uuids.my_netid3,
                                    'name': 'my_netname3',
                                    'subnets': ['mysubnid3'],
                                    'tenant_id': uuids.my_tenant}]
        self.nets4 = [{'id': 'his_netid4',
                      'name': 'his_netname4',
                      'tenant_id': 'his_tenantid'}]
        # A network request with external networks
        self.nets5 = self.nets1 + [{'id': 'the-external-one',
                                    'name': 'out-of-this-world',
                                    'subnets': ['mysubnid5'],
                                    'router:external': True,
                                    'tenant_id': 'should-be-an-admin'}]
        # A network request with a duplicate
        self.nets6 = []
        self.nets6.append(self.nets1[0])
        self.nets6.append(self.nets1[0])
        # A network request with a combo
        self.nets7 = []
        self.nets7.append(self.nets2[1])
        self.nets7.append(self.nets1[0])
        self.nets7.append(self.nets2[1])
        self.nets7.append(self.nets1[0])
        # A network request with only external network
        self.nets8 = [self.nets5[1]]
        # An empty network
        self.nets9 = []
        # A network that is both shared and external
        self.nets10 = [{'id': 'net_id', 'name': 'net_name',
                        'router:external': True, 'shared': True,
                        'subnets': ['mysubnid10']}]
        # A network with non-blank dns_domain to test _update_port_dns_name
        self.nets11 = [{'id': uuids.my_netid1,
                      'name': 'my_netname1',
                      'subnets': ['mysubnid1'],
                      'tenant_id': uuids.my_tenant,
                      'dns_domain': 'my-domain.org.'}]

        self.nets = [self.nets1, self.nets2, self.nets3, self.nets4,
                     self.nets5, self.nets6, self.nets7, self.nets8,
                     self.nets9, self.nets10, self.nets11]

        self.port_address = '10.0.1.2'
        self.port_data1 = [{'network_id': uuids.my_netid1,
                           'device_id': self.instance2['uuid'],
                           'tenant_id': self.tenant_id,
                           'device_owner': 'compute:nova',
                           'id': uuids.portid_1,
                           'binding:vnic_type': model.VNIC_TYPE_NORMAL,
                           'status': 'DOWN',
                           'admin_state_up': True,
                           'fixed_ips': [{'ip_address': self.port_address,
                                          'subnet_id': 'my_subid1'}],
                           'mac_address': 'my_mac1', }]
        self.float_data1 = [{'port_id': uuids.portid_1,
                             'fixed_ip_address': self.port_address,
                             'floating_ip_address': '172.0.1.2'}]
        self.dhcp_port_data1 = [{'fixed_ips': [{'ip_address': '10.0.1.9',
                                               'subnet_id': 'my_subid1'}],
                                 'status': 'ACTIVE',
                                 'admin_state_up': True}]
        self.port_address2 = '10.0.2.2'
        self.port_data2 = []
        self.port_data2.append(self.port_data1[0])
        self.port_data2.append({'network_id': uuids.my_netid2,
                                'device_id': self.instance['uuid'],
                                'tenant_id': self.tenant_id,
                                'admin_state_up': True,
                                'status': 'ACTIVE',
                                'device_owner': 'compute:nova',
                                'id': uuids.portid_2,
                                'binding:vnic_type': model.VNIC_TYPE_NORMAL,
                                'fixed_ips':
                                        [{'ip_address': self.port_address2,
                                          'subnet_id': 'my_subid2'}],
                                'mac_address': 'my_mac2', })
        self.float_data2 = []
        self.float_data2.append(self.float_data1[0])
        self.float_data2.append({'port_id': uuids.portid_2,
                                 'fixed_ip_address': '10.0.2.2',
                                 'floating_ip_address': '172.0.2.2'})
        self.port_data3 = [{'network_id': uuids.my_netid1,
                           'device_id': 'device_id3',
                           'tenant_id': self.tenant_id,
                           'status': 'DOWN',
                           'admin_state_up': True,
                           'device_owner': 'compute:nova',
                           'id': uuids.portid_3,
                           'binding:vnic_type': model.VNIC_TYPE_NORMAL,
                           'fixed_ips': [],  # no fixed ip
                           'mac_address': 'my_mac3', }]
        self.subnet_data1 = [{'id': 'my_subid1',
                             'cidr': '10.0.1.0/24',
                             'network_id': uuids.my_netid1,
                             'gateway_ip': '10.0.1.1',
                             'dns_nameservers': ['8.8.1.1', '8.8.1.2']}]
        self.subnet_data2 = []
        self.subnet_data_n = [{'id': 'my_subid1',
                               'cidr': '10.0.1.0/24',
                               'network_id': uuids.my_netid1,
                               'gateway_ip': '10.0.1.1',
                               'dns_nameservers': ['8.8.1.1', '8.8.1.2']},
                              {'id': 'my_subid2',
                               'cidr': '20.0.1.0/24',
                              'network_id': uuids.my_netid2,
                              'gateway_ip': '20.0.1.1',
                              'dns_nameservers': ['8.8.1.1', '8.8.1.2']}]
        self.subnet_data2.append({'id': 'my_subid2',
                                  'cidr': '10.0.2.0/24',
                                  'network_id': uuids.my_netid2,
                                  'gateway_ip': '10.0.2.1',
                                  'dns_nameservers': ['8.8.2.1', '8.8.2.2']})

        self.fip_pool = {'id': '4fdbfd74-eaf8-4884-90d9-00bd6f10c2d3',
                         'name': 'ext_net',
                         'router:external': True,
                         'tenant_id': 'admin_tenantid'}
        self.fip_pool_nova = {'id': '435e20c3-d9f1-4f1b-bee5-4611a1dd07db',
                              'name': 'nova',
                              'router:external': True,
                              'tenant_id': 'admin_tenantid'}
        self.fip_unassociated = {'tenant_id': uuids.my_tenant,
                                 'id': uuids.fip_id1,
                                 'floating_ip_address': '172.24.4.227',
                                 'floating_network_id': self.fip_pool['id'],
                                 'port_id': None,
                                 'fixed_ip_address': None,
                                 'router_id': None}
        fixed_ip_address = self.port_data2[1]['fixed_ips'][0]['ip_address']
        self.fip_associated = {'tenant_id': uuids.my_tenant,
                               'id': uuids.fip_id2,
                               'floating_ip_address': '172.24.4.228',
                               'floating_network_id': self.fip_pool['id'],
                               'port_id': self.port_data2[1]['id'],
                               'fixed_ip_address': fixed_ip_address,
                               'router_id': 'router_id1'}
        self._returned_nw_info = []
        self.mox.StubOutWithMock(neutronapi, 'get_client')
        self.moxed_client = self.mox.CreateMock(client.Client)
        self.addCleanup(CONF.reset)
        self.addCleanup(self.mox.VerifyAll)
        self.addCleanup(self.mox.UnsetStubs)
        self.addCleanup(self.stubs.UnsetAll)

    def _fake_instance_object(self, instance):
        return fake_instance.fake_instance_obj(self.context, **instance)

    def _fake_instance_info_cache(self, nw_info, instance_uuid=None):
        info_cache = {}
        if instance_uuid is None:
            info_cache['instance_uuid'] = uuids.fake
        else:
            info_cache['instance_uuid'] = instance_uuid
        info_cache['deleted'] = False
        info_cache['created_at'] = timeutils.utcnow()
        info_cache['deleted_at'] = timeutils.utcnow()
        info_cache['updated_at'] = timeutils.utcnow()
        info_cache['network_info'] = model.NetworkInfo.hydrate(six.text_type(
                                    jsonutils.dumps(nw_info)))
        return info_cache

    def _fake_instance_object_with_info_cache(self, instance):
        expected_attrs = ['info_cache']
        instance = objects.Instance._from_db_object(self.context,
               objects.Instance(), fake_instance.fake_db_instance(**instance),
               expected_attrs=expected_attrs)
        return instance

    def _stub_allocate_for_instance(self, net_idx=1, **kwargs):
        self.instance = self._fake_instance_object(self.instance)
        self.instance2 = self._fake_instance_object(self.instance2)

        api = neutronapi.API()
        self.mox.StubOutWithMock(api, 'get_instance_nw_info')
        self.mox.StubOutWithMock(api, '_refresh_neutron_extensions_cache')
        self.mox.StubOutWithMock(api, '_populate_neutron_extension_values')

        bind_host_id = kwargs.get('bind_host_id') or None

        has_dns_extension = False
        if kwargs.get('dns_extension'):
            has_dns_extension = True
            api.extensions[constants.DNS_INTEGRATION] = 1

        # Net idx is 1-based for compatibility with existing unit tests
        nets = self.nets[net_idx - 1]
        ports = {}
        fixed_ips = {}

        macs = kwargs.pop('macs', None)
        if macs:
            macs = set(macs)

        req_net_ids = []
        ordered_networks = []
        self._stub_allocate_for_instance_show_port(nets, ports, fixed_ips,
            macs, req_net_ids, ordered_networks, **kwargs)

        if kwargs.get('_break') == 'pre_list_networks':
            self.mox.ReplayAll()
            return api

        self._stub_allocate_for_instance_list_networks(req_net_ids, nets)

        if kwargs.get('_break') == 'post_list_networks':
            self.mox.ReplayAll()
            return api

        if (('requested_networks' not in kwargs or
             kwargs['requested_networks'].as_tuples() == [(None, None, None)])
            and len(nets) > 1):
                self.mox.ReplayAll()
                return api

        if kwargs.get('_break') == 'post_list_extensions':
            self.mox.ReplayAll()
            return api

        self._stub_allocate_for_instance_create_port(
            ordered_networks, fixed_ips, nets)

        neutronapi.get_client(
            mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)

        preexisting_port_ids = []
        ports_in_requested_net_order = []
        nets_in_requested_net_order = []
        index = 0
        for request in ordered_networks:
            index += 1
            port_req_body = {
                'port': {
                    'device_id': self.instance.uuid,
                    'device_owner': 'compute:nova',
                },
            }
            # Network lookup for available network_id
            network = None
            for net in nets:
                if net['id'] == request.network_id:
                    network = net
                    break
            # if net_id did not pass validate_networks() and not available
            # here then skip it safely not continuing with a None Network
            else:
                continue

            api._populate_neutron_extension_values(mox.IgnoreArg(),
                                                   self.instance,
                                                   mox.IgnoreArg(),
                                                   mox.IgnoreArg(),
                                                   network=network,
                                                   neutron=self.moxed_client,
                                                   bind_host_id=bind_host_id).\
                                                   AndReturn(None)

            if macs:
                port_req_body['port']['mac_address'] = macs.pop()

            if not request.port_id:
                port_id = uuids.fake
                update_port_res = {'port': {
                    'id': port_id,
                    'mac_address': 'fakemac%i' % index}}
                ports_in_requested_net_order.append(port_id)
                if kwargs.get('_break') == 'mac' + request.network_id:
                    self.mox.ReplayAll()
                    return api
            else:
                ports_in_requested_net_order.append(request.port_id)
                preexisting_port_ids.append(request.port_id)
                port_id = request.port_id
                update_port_res = {'port': ports[port_id]}

            new_mac = port_req_body['port'].get('mac_address')
            if new_mac:
                update_port_res['port']['mac_address'] = new_mac

            self.moxed_client.update_port(port_id,
                                          MyComparator(port_req_body)
                                          ).AndReturn(update_port_res)

            if has_dns_extension:
                if net_idx == 11:
                    port_req_body_dns = {
                        'port': {
                            'dns_name': self.instance.hostname
                        }
                    }
                    res_port_dns = {
                        'port': {
                            'id': ports_in_requested_net_order[-1]
                        }
                    }
                    self.moxed_client.update_port(
                        ports_in_requested_net_order[-1],
                        MyComparator(port_req_body_dns)
                        ).AndReturn(res_port_dns)
            nets_in_requested_net_order.append(network)

        api.get_instance_nw_info(mox.IgnoreArg(),
                                 self.instance,
                                 networks=nets_in_requested_net_order,
                                 port_ids=ports_in_requested_net_order,
                                 admin_client=self.moxed_client,
                                 preexisting_port_ids=preexisting_port_ids,
                                 update_cells=True
                                ).AndReturn(self._returned_nw_info)
        self.mox.ReplayAll()
        return api

    def _stub_allocate_for_instance_show_port(self, nets, ports, fixed_ips,
            macs, req_net_ids, ordered_networks, **kwargs):
        if 'requested_networks' in kwargs:
            for request in kwargs['requested_networks']:
                if request.port_id:
                    if request.port_id == uuids.portid_3:
                        self.moxed_client.show_port(request.port_id
                        ).AndReturn(
                            {'port': {'id': uuids.portid_3,
                                      'network_id': uuids.my_netid1,
                                      'tenant_id': self.tenant_id,
                                      'mac_address': 'my_mac1',
                                      'device_id': kwargs.get('_device') and
                                                   self.instance2.uuid or
                                                   ''}})
                        ports[uuids.my_netid1] = [self.port_data1[0],
                                            self.port_data3[0]]
                        ports[request.port_id] = self.port_data3[0]
                        request.network_id = uuids.my_netid1
                        if macs is not None:
                            macs.discard('my_mac1')
                    elif request.port_id == uuids.non_existent_uuid:
                        PortNotFound = exceptions.PortNotFoundClient(
                            status_code=404)
                        self.moxed_client.show_port(request.port_id
                        ).AndRaise(PortNotFound)
                    else:
                        self.moxed_client.show_port(request.port_id).AndReturn(
                            {'port': {'id': uuids.portid_1,
                                      'network_id': uuids.my_netid1,
                                      'tenant_id': self.tenant_id,
                                      'mac_address': 'my_mac1',
                                      'device_id': kwargs.get('_device') and
                                                   self.instance2.uuid or
                                                   '',
                                      'dns_name': kwargs.get('_dns_name') or
                                                  ''}})
                        ports[request.port_id] = self.port_data1[0]
                        request.network_id = uuids.my_netid1
                        if macs is not None:
                            macs.discard('my_mac1')
                else:
                    fixed_ips[request.network_id] = request.address
                req_net_ids.append(request.network_id)
                ordered_networks.append(request)
        else:
            for n in nets:
                ordered_networks.append(
                    objects.NetworkRequest(network_id=n['id']))

    def _stub_allocate_for_instance_list_networks(self, req_net_ids, nets):
        # search all req_net_ids as in api.py
        search_ids = req_net_ids
        if search_ids:
            mox_list_params = {'id': mox.SameElementsAs(search_ids)}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': nets})
        else:
            mox_list_params = {'tenant_id': self.instance.project_id,
                               'shared': False}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': nets})
            mox_list_params = {'shared': True}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': []})

    def _stub_allocate_for_instance_create_port(self, ordered_networks,
            fixed_ips, nets):
        for request in ordered_networks:
            if not request.port_id:
                # Check network is available, skip if not
                network = None
                for net in nets:
                    if net['id'] == request.network_id:
                        network = net
                        break
                if network is None:
                    continue

                port_req_body_create = {'port': {'device_id':
                                                 self.instance.uuid}}
                request.address = fixed_ips.get(request.network_id)
                if request.address:
                    port_req_body_create['port']['fixed_ips'] = [
                        {'ip_address': str(request.address)}]
                port_req_body_create['port']['network_id'] = \
                    request.network_id
                port_req_body_create['port']['admin_state_up'] = True
                port_req_body_create['port']['tenant_id'] = \
                    self.instance.project_id
                res_port = {'port': {'id': uuids.fake}}
                self.moxed_client.create_port(
                    MyComparator(port_req_body_create)).AndReturn(res_port)

    def _verify_nw_info(self, nw_inf, index=0):
        id_suffix = index + 1
        self.assertEqual('10.0.%s.2' % id_suffix,
                         nw_inf.fixed_ips()[index]['address'])
        self.assertEqual('172.0.%s.2' % id_suffix,
            nw_inf.fixed_ips()[index].floating_ip_addresses()[0])
        self.assertEqual('my_netname%s' % id_suffix,
                         nw_inf[index]['network']['label'])
        self.assertEqual(getattr(uuids, 'portid_%s' % id_suffix),
                         nw_inf[index]['id'])
        self.assertEqual('my_mac%s' % id_suffix, nw_inf[index]['address'])
        self.assertEqual('10.0.%s.0/24' % id_suffix,
            nw_inf[index]['network']['subnets'][0]['cidr'])

        ip_addr = model.IP(address='8.8.%s.1' % id_suffix,
                           version=4, type='dns')
        self.assertIn(ip_addr, nw_inf[index]['network']['subnets'][0]['dns'])

    def _get_instance_nw_info(self, number):
        api = neutronapi.API()
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(mox.IgnoreArg(),
                                          self.instance['uuid'],
                                          mox.IgnoreArg()).AndReturn(
                                              fake_info_cache)
        port_data = number == 1 and self.port_data1 or self.port_data2
        net_info_cache = []
        for port in port_data:
            net_info_cache.append({"network": {"id": port['network_id']},
                                   "id": port['id']})

        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': port_data})
        net_ids = [port['network_id'] for port in port_data]
        nets = number == 1 and self.nets1 or self.nets2
        self.moxed_client.list_networks(
            id=net_ids).AndReturn({'networks': nets})
        for i in range(1, number + 1):
            float_data = number == 1 and self.float_data1 or self.float_data2
            for ip in port_data[i - 1]['fixed_ips']:
                float_data = [x for x in float_data
                              if x['fixed_ip_address'] == ip['ip_address']]
                self.moxed_client.list_floatingips(
                    fixed_ip_address=ip['ip_address'],
                    port_id=port_data[i - 1]['id']).AndReturn(
                        {'floatingips': float_data})
            subnet_data = i == 1 and self.subnet_data1 or self.subnet_data2
            self.moxed_client.list_subnets(
                id=mox.SameElementsAs(['my_subid%s' % i])).AndReturn(
                    {'subnets': subnet_data})
            self.moxed_client.list_ports(
                network_id=subnet_data[0]['network_id'],
                device_owner='network:dhcp').AndReturn(
                    {'ports': []})
        self.instance['info_cache'] = self._fake_instance_info_cache(
            net_info_cache, self.instance['uuid'])
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_get')
        api.db.instance_info_cache_get(mox.IgnoreArg(),
                                       self.instance['uuid']).AndReturn(
                                           self.instance['info_cache'])

        self.mox.ReplayAll()

        instance = self._fake_instance_object_with_info_cache(self.instance)
        nw_inf = api.get_instance_nw_info(self.context, instance)
        for i in range(0, number):
            self._verify_nw_info(nw_inf, i)

    def _allocate_for_instance(self, net_idx=1, **kwargs):
        api = self._stub_allocate_for_instance(net_idx, **kwargs)
        self._vifs_created = []

        def _new_vif(*args):
            m = mock.MagicMock()
            self._vifs_created.append(m)
            return m

        with mock.patch('nova.objects.VirtualInterface') as mock_vif:
            mock_vif.side_effect = _new_vif

            requested_networks = kwargs.get("requested_networks", None)
            allowed_keys = ["macs", "security_groups", "bind_host_id"]
            afi_kwargs = {}
            for key in kwargs.keys():
                if key in allowed_keys:
                    afi_kwargs[key] = kwargs[key]

            return api.allocate_for_instance(self.context, self.instance,
                    False, requested_networks, **afi_kwargs)


class TestNeutronv2(TestNeutronv2Base):

    def test_get_instance_nw_info_1(self):
        # Test to get one port in one network and subnet.
        neutronapi.get_client(mox.IgnoreArg(),
                             admin=True).MultipleTimes().AndReturn(
            self.moxed_client)
        self._get_instance_nw_info(1)

    def test_get_instance_nw_info_2(self):
        # Test to get one port in each of two networks and subnets.
        neutronapi.get_client(mox.IgnoreArg(),
                             admin=True).MultipleTimes().AndReturn(
            self.moxed_client)
        self._get_instance_nw_info(2)

    def test_get_instance_nw_info_with_nets_add_interface(self):
        # This tests that adding an interface to an instance does not
        # remove the first instance from the instance.
        network_model = model.Network(id='network_id',
                                      bridge='br-int',
                                      injected='injected',
                                      label='fake_network',
                                      tenant_id='fake_tenant')
        network_cache = {'info_cache': {
            'network_info': [{'id': self.port_data2[0]['id'],
                              'address': 'mac_address',
                              'network': network_model,
                              'type': 'ovs',
                              'ovs_interfaceid': 'ovs_interfaceid',
                              'devname': 'devname'}]}}

        self._fake_get_instance_nw_info_helper(network_cache,
                                               self.port_data2,
                                               self.nets2,
                                               [self.port_data2[1]['id']])

    def test_get_instance_nw_info_remove_ports_from_neutron(self):
        # This tests that when a port is removed in neutron it
        # is also removed from the nova.
        network_model = model.Network(id=self.port_data2[0]['network_id'],
                                      bridge='br-int',
                                      injected='injected',
                                      label='fake_network',
                                      tenant_id='fake_tenant')
        network_cache = {'info_cache': {
            'network_info': [{'id': 'network_id',
                              'address': 'mac_address',
                              'network': network_model,
                              'type': 'ovs',
                              'ovs_interfaceid': 'ovs_interfaceid',
                              'devname': 'devname'}]}}

        self._fake_get_instance_nw_info_helper(network_cache,
                                               self.port_data2,
                                               None,
                                               None)

    def test_get_instance_nw_info_ignores_neutron_ports(self):
        # Tests that only ports in the network_cache are updated
        # and ports returned from neutron that match the same
        # instance_id/device_id are ignored.
        port_data2 = copy.copy(self.port_data2)

        # set device_id on the ports to be the same.
        port_data2[1]['device_id'] = port_data2[0]['device_id']
        network_model = model.Network(id='network_id',
                                      bridge='br-int',
                                      injected='injected',
                                      label='fake_network',
                                      tenant_id='fake_tenant')
        network_cache = {'info_cache': {
            'network_info': [{'id': 'network_id',
                              'address': 'mac_address',
                              'network': network_model,
                              'type': 'ovs',
                              'ovs_interfaceid': 'ovs_interfaceid',
                              'devname': 'devname'}]}}

        self._fake_get_instance_nw_info_helper(network_cache,
                                               port_data2,
                                               None,
                                               None)

    def test_get_instance_nw_info_ignores_neutron_ports_empty_cache(self):
        # Tests that ports returned from neutron that match the same
        # instance_id/device_id are ignored when the instance info cache is
        # empty.
        port_data2 = copy.copy(self.port_data2)

        # set device_id on the ports to be the same.
        port_data2[1]['device_id'] = port_data2[0]['device_id']
        network_cache = {'info_cache': {'network_info': []}}

        self._fake_get_instance_nw_info_helper(network_cache,
                                               port_data2,
                                               None,
                                               None)

    def _fake_get_instance_nw_info_helper(self, network_cache,
                                          current_neutron_ports,
                                          networks=None, port_ids=None):
        """Helper function to test get_instance_nw_info.

        :param network_cache - data already in the nova network cache.
        :param current_neutron_ports - updated list of ports from neutron.
        :param networks - networks of ports being added to instance.
        :param port_ids - new ports being added to instance.
        """

        # keep a copy of the original ports/networks to pass to
        # get_instance_nw_info() as the code below changes them.
        original_port_ids = copy.copy(port_ids)
        original_networks = copy.copy(networks)

        api = neutronapi.API()
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(
            mox.IgnoreArg(),
            self.instance['uuid'], mox.IgnoreArg()).AndReturn(fake_info_cache)
        neutronapi.get_client(mox.IgnoreArg(),
                             admin=True).MultipleTimes().AndReturn(
            self.moxed_client)
        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': current_neutron_ports})

        ifaces = network_cache['info_cache']['network_info']

        if port_ids is None:
            port_ids = [iface['id'] for iface in ifaces]
            net_ids = [iface['network']['id'] for iface in ifaces]
            nets = [{'id': iface['network']['id'],
                     'name': iface['network']['label'],
                     'tenant_id': iface['network']['meta']['tenant_id']}
                    for iface in ifaces]
        if networks is None:
            if ifaces:
                self.moxed_client.list_networks(
                    id=net_ids).AndReturn({'networks': nets})
            else:
                non_shared_nets = [
                    {'id': iface['network']['id'],
                     'name': iface['network']['label'],
                     'tenant_id': iface['network']['meta']['tenant_id']}
                    for iface in ifaces if not iface['shared']]
                shared_nets = [
                    {'id': iface['network']['id'],
                     'name': iface['network']['label'],
                     'tenant_id': iface['network']['meta']['tenant_id']}
                    for iface in ifaces if iface['shared']]
                self.moxed_client.list_networks(
                    shared=False,
                    tenant_id=self.instance['project_id']
                        ).AndReturn({'networks': non_shared_nets})
                self.moxed_client.list_networks(
                    shared=True).AndReturn({'networks': shared_nets})
        else:
            networks = networks + [
                dict(id=iface['network']['id'],
                     name=iface['network']['label'],
                     tenant_id=iface['network']['meta']['tenant_id'])
                for iface in ifaces]
            port_ids = [iface['id'] for iface in ifaces] + port_ids

        index = 0

        current_neutron_port_map = {}
        for current_neutron_port in current_neutron_ports:
            current_neutron_port_map[current_neutron_port['id']] = (
                current_neutron_port)
        for port_id in port_ids:
            current_neutron_port = current_neutron_port_map.get(port_id)
            if current_neutron_port:
                for ip in current_neutron_port['fixed_ips']:
                    self.moxed_client.list_floatingips(
                        fixed_ip_address=ip['ip_address'],
                        port_id=current_neutron_port['id']).AndReturn(
                            {'floatingips': [self.float_data2[index]]})
                    self.moxed_client.list_subnets(
                        id=mox.SameElementsAs([ip['subnet_id']])
                        ).AndReturn(
                            {'subnets': [self.subnet_data_n[index]]})
                    self.moxed_client.list_ports(
                        network_id=current_neutron_port['network_id'],
                        device_owner='network:dhcp').AndReturn(
                        {'ports': self.dhcp_port_data1})
                    index += 1
        self.instance['info_cache'] = self._fake_instance_info_cache(
            network_cache['info_cache']['network_info'], self.instance['uuid'])

        self.mox.StubOutWithMock(api.db, 'instance_info_cache_get')
        api.db.instance_info_cache_get(
            mox.IgnoreArg(),
            self.instance['uuid']).MultipleTimes().AndReturn(
                self.instance['info_cache'])

        self.mox.ReplayAll()

        instance = self._fake_instance_object_with_info_cache(self.instance)

        nw_infs = api.get_instance_nw_info(self.context,
                                           instance,
                                           networks=original_networks,
                                           port_ids=original_port_ids)

        self.assertEqual(index, len(nw_infs))
        # ensure that nic ordering is preserved
        for iface_index in range(index):
            self.assertEqual(port_ids[iface_index],
                             nw_infs[iface_index]['id'])

    def test_get_instance_nw_info_without_subnet(self):
        # Test get instance_nw_info for a port without subnet.
        api = neutronapi.API()
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(
            mox.IgnoreArg(),
            self.instance['uuid'], mox.IgnoreArg()).AndReturn(fake_info_cache)
        neutronapi.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': self.port_data3})
        self.moxed_client.list_networks(
            id=[self.port_data1[0]['network_id']]).AndReturn(
                {'networks': self.nets1})

        net_info_cache = []
        for port in self.port_data3:
            net_info_cache.append({"network": {"id": port['network_id']},
                                   "id": port['id']})
        self.instance['info_cache'] = self._fake_instance_info_cache(
            net_info_cache, self.instance['uuid'])

        self.mox.StubOutWithMock(api.db, 'instance_info_cache_get')
        api.db.instance_info_cache_get(
            mox.IgnoreArg(),
            self.instance['uuid']).AndReturn(self.instance['info_cache'])

        self.mox.ReplayAll()

        instance = self._fake_instance_object_with_info_cache(self.instance)
        nw_inf = api.get_instance_nw_info(self.context,
                                          instance)

        id_suffix = 3
        self.assertEqual(0, len(nw_inf.fixed_ips()))
        self.assertEqual('my_netname1', nw_inf[0]['network']['label'])
        self.assertEqual(uuids.portid_3, nw_inf[0]['id'])
        self.assertEqual('my_mac%s' % id_suffix, nw_inf[0]['address'])
        self.assertEqual(0, len(nw_inf[0]['network']['subnets']))

    def test_refresh_neutron_extensions_cache(self):
        api = neutronapi.API()

        # Note: Don't want the default get_client from setUp()
        self.mox.ResetAll()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(
            self.moxed_client)
        self.moxed_client.list_extensions().AndReturn(
            {'extensions': [{'name': constants.QOS_QUEUE}]})
        self.mox.ReplayAll()
        api._refresh_neutron_extensions_cache(mox.IgnoreArg())
        self.assertEqual(
            {constants.QOS_QUEUE: {'name': constants.QOS_QUEUE}},
            api.extensions)

    def test_populate_neutron_extension_values_rxtx_factor(self):
        api = neutronapi.API()

        # Note: Don't want the default get_client from setUp()
        self.mox.ResetAll()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(
            self.moxed_client)
        self.moxed_client.list_extensions().AndReturn(
            {'extensions': [{'name': constants.QOS_QUEUE}]})
        self.mox.ReplayAll()
        flavor = flavors.get_default_flavor()
        flavor['rxtx_factor'] = 1
        instance = objects.Instance(system_metadata={})
        instance.flavor = flavor
        port_req_body = {'port': {}}
        api._populate_neutron_extension_values(self.context, instance,
                                               None, port_req_body)
        self.assertEqual(1, port_req_body['port']['rxtx_factor'])

    def test_allocate_for_instance_1(self):
        # Allocate one port in one network env.
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self._allocate_for_instance(1)

    def test_allocate_for_instance_2(self):
        # Allocate one port in two networks env.
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(net_idx=2)
        self.assertRaises(exception.NetworkAmbiguous,
                          api.allocate_for_instance,
                          self.context, self.instance, False, None)

    def test_allocate_for_instance_accepts_macs_kwargs_None(self):
        # The macs kwarg should be accepted as None.
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self._allocate_for_instance(1, macs=None)

    def test_allocate_for_instance_accepts_macs_kwargs_set(self):
        # The macs kwarg should be accepted, as a set, the
        # _allocate_for_instance helper checks that the mac is used to create a
        # port.
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self._allocate_for_instance(1, macs=set(['ab:cd:ef:01:23:45']))

    def test_allocate_for_instance_with_mac_added_to_port(self):
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        # NOTE(johngarbutt) we override the provided mac with a new one
        self._allocate_for_instance(net_idx=1,
                                    requested_networks=requested_networks,
                                    macs=set(['ab:cd:ef:01:23:45']))
        self.assertEqual('ab:cd:ef:01:23:45/%s' % uuids.portid_1,
                         self._vifs_created[0].address)

    def test_allocate_for_instance_accepts_only_portid(self):
        # Make sure allocate_for_instance works when only a portid is provided
        self._returned_nw_info = self.port_data1
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        result = self._allocate_for_instance(
            requested_networks=objects.NetworkRequestList(
                objects=[objects.NetworkRequest(port_id=uuids.portid_1,
                                                tag='test')]))
        self.assertEqual(self.port_data1, result)
        self.assertEqual(1, len(self._vifs_created))
        self.assertEqual('test', self._vifs_created[0].tag)
        self.assertEqual(self.instance.uuid,
                         self._vifs_created[0].instance_uuid)
        self.assertEqual(uuids.portid_1, self._vifs_created[0].uuid)
        self.assertEqual('%s/%s' % (self.port_data1[0]['mac_address'],
                                    self.port_data1[0]['id']),
                         self._vifs_created[0].address)

    @mock.patch('nova.network.neutronv2.api.API._unbind_ports')
    def test_allocate_for_instance_not_enough_macs_via_ports(self,
                                                             mock_unbind):
        # using a hypervisor MAC via a pre-created port will stop it being
        # used to dynamically create a port on a network. We put the network
        # first in requested_networks so that if the code were to not pre-check
        # requested ports, it would incorrectly assign the mac and not fail.
        requested_networks = objects.NetworkRequestList(
            objects = [
                objects.NetworkRequest(network_id=self.nets2[1]['id']),
                objects.NetworkRequest(port_id=uuids.portid_1)])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(
            net_idx=2, requested_networks=requested_networks,
            macs=set(['my_mac1']),
            _break='mac' + self.nets2[1]['id'])
        self.assertRaises(exception.PortNotFree,
                          api.allocate_for_instance, self.context,
                          self.instance, False, requested_networks,
                          macs=set(['my_mac1']))
        mock_unbind.assert_called_once_with(self.context, [],
                                            self.moxed_client, mock.ANY)

    @mock.patch('nova.network.neutronv2.api.API._unbind_ports')
    def test_allocate_for_instance_not_enough_macs(self, mock_unbind):
        # If not enough MAC addresses are available to allocate to networks, an
        # error should be raised.
        # We could pass in macs=set(), but that wouldn't tell us that
        # allocate_for_instance tracks used macs properly, so we pass in one
        # mac, and ask for two networks.
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=self.nets2[1]['id']),
                     objects.NetworkRequest(network_id=self.nets2[0]['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(
            net_idx=2, requested_networks=requested_networks,
            macs=set(['my_mac2']),
            _break='mac' + self.nets2[0]['id'])
        with mock.patch.object(api, '_delete_ports'):
            self.assertRaises(exception.PortNotFree,
                              api.allocate_for_instance, self.context,
                              self.instance, False,
                              requested_networks=requested_networks,
                              macs=set(['my_mac2']))
        mock_unbind.assert_called_once_with(self.context, [],
                                            self.moxed_client, mock.ANY)

    def test_allocate_for_instance_two_macs_two_networks(self):
        # If two MACs are available and two networks requested, two new ports
        # get made and no exceptions raised.
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=self.nets2[1]['id']),
                     objects.NetworkRequest(network_id=self.nets2[0]['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self._allocate_for_instance(
            net_idx=2, requested_networks=requested_networks,
            macs=set(['my_mac2', 'my_mac1']))

    def test_allocate_for_instance_without_requested_networks(self):
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(net_idx=3)
        self.assertRaises(exception.NetworkAmbiguous,
                          api.allocate_for_instance,
                          self.context, self.instance, False, None)

    def test_allocate_for_instance_with_requested_non_available_network(self):
        """verify that a non available network is ignored.
        self.nets2 (net_idx=2) is composed of self.nets3[0] and self.nets3[1]
        Do not create a port on a non available network self.nets3[2].
       """
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets3[0], self.nets3[2], self.nets3[1])])
        requested_networks[0].tag = 'foo'
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self._allocate_for_instance(net_idx=2,
                                    requested_networks=requested_networks)
        self.assertEqual(2, len(self._vifs_created))
        # NOTE(danms) nets3[2] is chosen above as one that won't validate,
        # so we never actually run create() on the VIF.
        vifs_really_created = [vif for vif in self._vifs_created
                               if vif.create.called]
        self.assertEqual(2, len(vifs_really_created))
        self.assertEqual([('foo', 'fakemac1/%s' % uuids.fake),
                          (None, 'fakemac3/%s' % uuids.fake)],
                         [(vif.tag, vif.address)
                          for vif in vifs_really_created])

    def test_allocate_for_instance_with_requested_networks(self):
        # specify only first and last network
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets3[1], self.nets3[0], self.nets3[2])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self._allocate_for_instance(net_idx=3,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_with_no_subnet_defined(self):
        # net_id=4 does not specify subnet and does not set the option
        # port_security_disabled to True, so Neutron will not been
        # able to associate the default security group to the port
        # requested to be created. We expect an exception to be
        # raised.
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.assertRaises(exception.SecurityGroupCannotBeApplied,
                          self._allocate_for_instance, net_idx=4,
                          _break='post_list_extensions')

    def test_allocate_for_instance_with_invalid_network_id(self):
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(
                network_id=uuids.non_existent_uuid)])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(net_idx=9,
            requested_networks=requested_networks,
            _break='post_list_networks')
        self.assertRaises(exception.NetworkNotFound,
                          api.allocate_for_instance,
                          self.context, self.instance, False,
                          requested_networks=requested_networks)

    def test_allocate_for_instance_with_requested_networks_with_fixedip(self):
        # specify only first and last network
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=self.nets1[0]['id'],
                                            address='10.0.1.0')])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self._allocate_for_instance(net_idx=1,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_with_requested_networks_with_port(self):
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self._allocate_for_instance(net_idx=1,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_no_networks(self):
        """verify the exception thrown when there are no networks defined."""
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        api = neutronapi.API()
        self.moxed_client.list_networks(
            tenant_id=self.instance.project_id,
            shared=False).AndReturn(
                {'networks': model.NetworkInfo([])})
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(shared=True).AndReturn(
            {'networks': model.NetworkInfo([])})
        self.mox.ReplayAll()
        nwinfo = api.allocate_for_instance(self.context, self.instance,
                                           False, None)
        self.assertEqual(0, len(nwinfo))

    @mock.patch(
        'nova.network.neutronv2.api.API._populate_neutron_extension_values')
    @mock.patch('nova.network.neutronv2.api.API._create_ports_for_instance')
    @mock.patch('nova.network.neutronv2.api.API._unbind_ports')
    def test_allocate_for_instance_ex1(self, mock_unbind, mock_create_ports,
            mock_populate):
        """verify we will delete created ports
        if we fail to allocate all net resources.

        Mox to raise exception when creating a second port.
        In this case, the code should delete the first created port.
        """
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        api = neutronapi.API()
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets2[0], self.nets2[1])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=[uuids.my_netid1, uuids.my_netid2]).AndReturn(
            {'networks': self.nets2})
        mock_create_ports.return_value = [
            (request, (getattr(uuids, 'portid_%s' % request.network_id)))
            for request in requested_networks
        ]
        neutronapi.get_client(
            mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        index = 0
        for network in self.nets2:
            binding_port_req_body = {
                'port': {
                    'device_id': self.instance.uuid,
                    'device_owner': 'compute:nova',
                },
            }
            port_req_body = {
                'port': {
                    'network_id': network['id'],
                    'admin_state_up': True,
                    'tenant_id': self.instance.project_id,
                },
            }
            port_req_body['port'].update(binding_port_req_body['port'])
            port_id = getattr(uuids, 'portid_%s' % network['id'])
            port = {'id': port_id, 'mac_address': 'foo'}

            if index == 0:
                self.moxed_client.update_port(port_id,
                    MyComparator(binding_port_req_body)).AndReturn(
                        {'port': port})
            else:
                NeutronOverQuota = exceptions.MacAddressInUseClient()
                self.moxed_client.update_port(port_id,
                    MyComparator(binding_port_req_body)).AndRaise(
                        NeutronOverQuota)
            index += 1
        self.moxed_client.delete_port(
            getattr(uuids, 'portid_%s' % self.nets2[0]['id']))
        self.moxed_client.delete_port(
            getattr(uuids, 'portid_%s' % self.nets2[1]['id']))
        self.mox.ReplayAll()
        self.assertRaises(exception.PortInUse,
                          api.allocate_for_instance,
                          self.context, self.instance, False,
                          requested_networks=requested_networks)
        mock_unbind.assert_called_once_with(self.context, [],
                                            self.moxed_client, mock.ANY)

    def test_allocate_for_instance_ex2(self):
        """verify we have no port to delete
        if we fail to allocate the first net resource.

        Mox to raise exception when creating the first port.
        In this case, the code should not delete any ports.
        """
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        api = neutronapi.API()
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets2[0], self.nets2[1])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=[uuids.my_netid1, uuids.my_netid2]).AndReturn(
            {'networks': self.nets2})
        port_req_body = {
            'port': {
                'network_id': self.nets2[0]['id'],
                'admin_state_up': True,
                'device_id': self.instance.uuid,
                'tenant_id': self.instance.project_id,
            },
        }
        self.moxed_client.create_port(
            MyComparator(port_req_body)).AndRaise(
                Exception("fail to create port"))
        self.mox.ReplayAll()
        self.assertRaises(NEUTRON_CLIENT_EXCEPTION, api.allocate_for_instance,
                          self.context, self.instance, False,
                          requested_networks=requested_networks)

    def test_allocate_for_instance_no_port_or_network(self):
        class BailOutEarly(Exception):
            pass
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.mox.StubOutWithMock(api, '_get_available_networks')
        # Make sure we get an empty list and then bail out of the rest
        # of the function
        api._get_available_networks(self.context, self.instance.project_id,
                                    [],
                                    neutron=self.moxed_client,
                                    auto_allocate=False).\
                                    AndRaise(BailOutEarly)
        self.mox.ReplayAll()
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest()])
        self.assertRaises(BailOutEarly,
                          api.allocate_for_instance, self.context,
                          self.instance, False, requested_networks)

    def test_allocate_for_instance_second_time(self):
        # Make sure that allocate_for_instance only returns ports that it
        # allocated during _that_ run.
        new_port = {'id': uuids.fake}
        self._returned_nw_info = self.port_data1 + [new_port]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        nw_info = self._allocate_for_instance()
        self.assertEqual([new_port], nw_info)

    def test_allocate_for_instance_port_in_use(self):
        # If a port is already in use, an exception should be raised.
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(
            requested_networks=requested_networks,
            _break='pre_list_networks',
            _device=True)
        self.assertRaises(exception.PortInUse,
                          api.allocate_for_instance, self.context,
                          self.instance, False, requested_networks)

    def test_allocate_for_instance_port_not_found(self):
        # If a port is not found, an exception should be raised.
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.non_existent_uuid)])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(
            requested_networks=requested_networks,
            _break='pre_list_networks')
        self.assertRaises(exception.PortNotFound,
                          api.allocate_for_instance, self.context,
                          self.instance, False, requested_networks)

    def test_allocate_for_instance_port_invalid_tenantid(self):
        self.tenant_id = 'invalid_id'
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(
            requested_networks=requested_networks,
            _break='pre_list_networks')
        self.assertRaises(exception.PortNotUsable,
                          api.allocate_for_instance, self.context,
                          self.instance, False, requested_networks)

    def test_allocate_for_instance_with_externalnet_forbidden(self):
        """Only one network is available, it's external, and the client
           is unauthorized to use it.
        """
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        # no networks in the tenant
        self.moxed_client.list_networks(
            tenant_id=self.instance.project_id,
            shared=False).AndReturn(
                {'networks': model.NetworkInfo([])})
        # external network is shared
        self.moxed_client.list_networks(shared=True).AndReturn(
            {'networks': self.nets8})
        self.mox.ReplayAll()
        api = neutronapi.API()
        self.assertRaises(exception.ExternalNetworkAttachForbidden,
                          api.allocate_for_instance, self.context,
                          self.instance, False, None)

    def test_allocate_for_instance_with_externalnet_multiple(self):
        """Multiple networks are available, one the client is authorized
           to use, and an external one the client is unauthorized to use.
        """
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        # network found in the tenant
        self.moxed_client.list_networks(
            tenant_id=self.instance.project_id,
            shared=False).AndReturn(
                {'networks': self.nets1})
        # external network is shared
        self.moxed_client.list_networks(shared=True).AndReturn(
            {'networks': self.nets8})
        self.mox.ReplayAll()
        api = neutronapi.API()
        self.assertRaises(
            exception.NetworkAmbiguous,
            api.allocate_for_instance,
            self.context, self.instance, False, None)

    def test_allocate_for_instance_with_externalnet_admin_ctx(self):
        """Only one network is available, it's external, and the client
           is authorized.
        """
        admin_ctx = context.RequestContext('userid', uuids.my_tenant,
                                           is_admin=True)
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(net_idx=8)
        api.allocate_for_instance(admin_ctx, self.instance, False, None)

    def test_allocate_for_instance_with_external_shared_net(self):
        """Only one network is available, it's external and shared."""
        ctx = context.RequestContext('userid', uuids.my_tenant)
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        api = self._stub_allocate_for_instance(net_idx=10)
        api.allocate_for_instance(ctx, self.instance, False, None)

    def _deallocate_for_instance(self, number, requested_networks=None):
        # TODO(mriedem): Remove this conversion when all neutronv2 APIs are
        # converted to handling instance objects.
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        api = neutronapi.API()
        port_data = number == 1 and self.port_data1 or self.port_data2
        ports = {port['id'] for port in port_data}
        ret_data = copy.deepcopy(port_data)
        if requested_networks:
            if isinstance(requested_networks, objects.NetworkRequestList):
                # NOTE(danms): Temporary and transitional
                with mock.patch('nova.utils.is_neutron', return_value=True):
                    requested_networks = requested_networks.as_tuples()
            for net, fip, port, request_id in requested_networks:
                ret_data.append({'network_id': net,
                                 'device_id': self.instance.uuid,
                                 'device_owner': 'compute:nova',
                                 'id': port,
                                 'status': 'DOWN',
                                 'admin_state_up': True,
                                 'fixed_ips': [],
                                 'mac_address': 'fake_mac', })
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_ports(
            device_id=self.instance.uuid).AndReturn(
                {'ports': ret_data})

        neutronapi.get_client(
            mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        if requested_networks:
            for net, fip, port, request_id in requested_networks:
                self.moxed_client.show_port(port, fields='binding:profile'
                        ).AndReturn({'port': ret_data[0]})
                self.moxed_client.update_port(port)
        for port in ports:
            self.moxed_client.delete_port(port).InAnyOrder("delete_port_group")

        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(self.context,
                                          self.instance.uuid,
                                          {'network_info': '[]'}).AndReturn(
                                              fake_info_cache)
        self.mox.ReplayAll()

        api = neutronapi.API()
        api.deallocate_for_instance(self.context, self.instance,
                                    requested_networks=requested_networks)

    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_1_with_requested(self, mock_preexisting):
        mock_preexisting.return_value = []
        requested = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='fake-net',
                                            address='1.2.3.4',
                                            port_id=uuids.portid_5)])
        # Test to deallocate in one port env.
        self._deallocate_for_instance(1, requested_networks=requested)

    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_2_with_requested(self, mock_preexisting):
        mock_preexisting.return_value = []
        requested = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='fake-net',
                                            address='1.2.3.4',
                                            port_id=uuids.portid_6)])
        # Test to deallocate in one port env.
        self._deallocate_for_instance(2, requested_networks=requested)

    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_1(self, mock_preexisting):
        mock_preexisting.return_value = []
        # Test to deallocate in one port env.
        self._deallocate_for_instance(1)

    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_2(self, mock_preexisting):
        mock_preexisting.return_value = []
        # Test to deallocate in two ports env.
        self._deallocate_for_instance(2)

    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_port_not_found(self,
                                                    mock_preexisting):
        # TODO(mriedem): Remove this conversion when all neutronv2 APIs are
        # converted to handling instance objects.
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        mock_preexisting.return_value = []
        port_data = self.port_data1
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        neutronapi.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        self.moxed_client.list_ports(
            device_id=self.instance.uuid).AndReturn(
                {'ports': port_data})

        NeutronNotFound = exceptions.NeutronClientException(status_code=404)
        for port in reversed(port_data):
            self.moxed_client.delete_port(port['id']).AndRaise(
                                                        NeutronNotFound)
        self.mox.ReplayAll()

        api = neutronapi.API()
        api.deallocate_for_instance(self.context, self.instance)

    def _test_deallocate_port_for_instance(self, number):
        port_data = number == 1 and self.port_data1 or self.port_data2
        nets = number == 1 and self.nets1 or self.nets2
        self.moxed_client.delete_port(port_data[0]['id'])

        net_info_cache = []
        for port in port_data:
            net_info_cache.append({"network": {"id": port['network_id']},
                                   "id": port['id']})
        self.instance['info_cache'] = self._fake_instance_info_cache(
            net_info_cache, self.instance['uuid'])
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(
            self.moxed_client)
        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': port_data[1:]})
        net_ids = [port['network_id'] for port in port_data]
        neutronapi.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        self.moxed_client.list_networks(id=net_ids).AndReturn(
            {'networks': nets})
        float_data = number == 1 and self.float_data1 or self.float_data2
        for data in port_data[1:]:
            for ip in data['fixed_ips']:
                self.moxed_client.list_floatingips(
                    fixed_ip_address=ip['ip_address'],
                    port_id=data['id']).AndReturn(
                        {'floatingips': float_data[1:]})
        for port in port_data[1:]:
            self.moxed_client.list_subnets(id=['my_subid2']).AndReturn({})

        self.mox.StubOutWithMock(api.db, 'instance_info_cache_get')
        api.db.instance_info_cache_get(mox.IgnoreArg(),
                                       self.instance['uuid']).AndReturn(
                                           self.instance['info_cache'])

        self.mox.ReplayAll()

        instance = self._fake_instance_object_with_info_cache(self.instance)
        nwinfo = api.deallocate_port_for_instance(self.context, instance,
                                                  port_data[0]['id'])
        self.assertEqual(len(port_data[1:]), len(nwinfo))
        if len(port_data) > 1:
            self.assertEqual(uuids.my_netid2, nwinfo[0]['network']['id'])

    def test_deallocate_port_for_instance_1(self):
        # Test to deallocate the first and only port
        self._test_deallocate_port_for_instance(1)

    def test_deallocate_port_for_instance_2(self):
        # Test to deallocate the first port of two
        self._test_deallocate_port_for_instance(2)

    def test_list_ports(self):
        search_opts = {'parm': 'value'}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_ports(**search_opts)
        self.mox.ReplayAll()
        neutronapi.API().list_ports(self.context, **search_opts)

    def test_show_port(self):
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port('foo').AndReturn(
                {'port': self.port_data1[0]})
        self.mox.ReplayAll()
        neutronapi.API().show_port(self.context, 'foo')

    def test_validate_networks(self):
        requested_networks = [(uuids.my_netid1, None, None, None),
                              (uuids.my_netid2, None, None, None)]
        ids = [uuids.my_netid1, uuids.my_netid2]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.show_quota(
            uuids.my_tenant).AndReturn(
                    {'quota': {'port': 50}})
        self.moxed_client.list_ports(
            tenant_id=uuids.my_tenant, fields=['id']).AndReturn(
                    {'ports': []})
        self.mox.ReplayAll()
        api = neutronapi.API()
        api.validate_networks(self.context, requested_networks, 1)

    def test_validate_networks_without_port_quota_on_network_side(self):
        requested_networks = [(uuids.my_netid1, None, None, None),
                              (uuids.my_netid2, None, None, None)]
        ids = [uuids.my_netid1, uuids.my_netid2]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.show_quota(
            uuids.my_tenant).AndReturn(
                    {'quota': {}})
        self.mox.ReplayAll()
        api = neutronapi.API()
        api.validate_networks(self.context, requested_networks, 1)

    def test_validate_networks_ex_1(self):
        requested_networks = [(uuids.my_netid1, None, None, None)]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs([uuids.my_netid1])).AndReturn(
                {'networks': self.nets1})
        self.moxed_client.show_quota(
            uuids.my_tenant).AndReturn(
                    {'quota': {'port': 50}})
        self.moxed_client.list_ports(
            tenant_id=uuids.my_tenant, fields=['id']).AndReturn(
                    {'ports': []})
        self.mox.ReplayAll()
        api = neutronapi.API()
        try:
            api.validate_networks(self.context, requested_networks, 1)
        except exception.NetworkNotFound as ex:
            self.assertIn("my_netid2", six.text_type(ex))

    def test_validate_networks_ex_2(self):
        requested_networks = [(uuids.my_netid1, None, None, None),
                              (uuids.my_netid2, None, None, None),
                              (uuids.my_netid3, None, None, None)]
        ids = [uuids.my_netid1, uuids.my_netid2, uuids.my_netid3]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets1})
        self.mox.ReplayAll()
        api = neutronapi.API()
        try:
            api.validate_networks(self.context, requested_networks, 1)
        except exception.NetworkNotFound as ex:
            self.assertIn(uuids.my_netid2, six.text_type(ex))
            self.assertIn(uuids.my_netid3, six.text_type(ex))

    def test_validate_networks_duplicate_enable(self):
        # Verify that no duplicateNetworks exception is thrown when duplicate
        # network ids are passed to validate_networks.
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(network_id=uuids.my_netid1)])
        ids = [uuids.my_netid1, uuids.my_netid1]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                 {'networks': self.nets1})
        self.moxed_client.show_quota(
            uuids.my_tenant).AndReturn(
                {'quota': {'port': 50}})
        self.moxed_client.list_ports(
            tenant_id=uuids.my_tenant, fields=['id']).AndReturn(
                 {'ports': []})
        self.mox.ReplayAll()
        api = neutronapi.API()
        api.validate_networks(self.context, requested_networks, 1)

    def test_allocate_for_instance_with_requested_networks_duplicates(self):
        # specify a duplicate network to allocate to instance
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets6[0], self.nets6[1])])
        neutronapi.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)
        self._allocate_for_instance(net_idx=6,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_requested_networks_duplicates_port(self):
        # specify first port and last port that are in same network
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port['id'])
                     for port in (self.port_data1[0], self.port_data3[0])])
        neutronapi.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)
        self._allocate_for_instance(net_idx=6,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_requested_networks_duplicates_combo(self):
        # specify a combo net_idx=7 : net2, port in net1, net2, port in net1
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid2),
                     objects.NetworkRequest(port_id=self.port_data1[0]['id']),
                     objects.NetworkRequest(network_id=uuids.my_netid2),
                     objects.NetworkRequest(port_id=self.port_data3[0]['id'])])
        neutronapi.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)
        self._allocate_for_instance(net_idx=7,
                                    requested_networks=requested_networks)

    def test_validate_networks_not_specified(self):
        requested_networks = objects.NetworkRequestList(objects=[])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            tenant_id=self.context.project_id,
            shared=False).AndReturn(
                {'networks': self.nets1})
        self.moxed_client.list_networks(
            shared=True).AndReturn(
                {'networks': self.nets2})
        self.mox.ReplayAll()
        api = neutronapi.API()
        self.assertRaises(exception.NetworkAmbiguous,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_port_not_found(self):
        # Verify that the correct exception is thrown when a non existent
        # port is passed to validate_networks.

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(
                network_id=uuids.my_netid1,
                port_id=uuids.portid_1)])

        PortNotFound = exceptions.PortNotFoundClient()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(requested_networks[0].port_id).AndRaise(
            PortNotFound)
        self.mox.ReplayAll()
        api = neutronapi.API()
        self.assertRaises(exception.PortNotFound,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_port_show_raises_non404(self):
        # Verify that the correct exception is thrown when a non existent
        # port is passed to validate_networks.
        fake_port_id = uuids.portid_1

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(
                network_id=uuids.my_netid1,
                port_id=fake_port_id)])

        NeutronNotFound = exceptions.NeutronClientException(status_code=0)
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(requested_networks[0].port_id).AndRaise(
                                                        NeutronNotFound)
        self.mox.ReplayAll()
        api = neutronapi.API()
        exc = self.assertRaises(exception.NovaException,
                                api.validate_networks,
                                self.context, requested_networks, 1)
        expected_exception_message = ('Failed to access port %(port_id)s: '
                                      'An unknown exception occurred.' %
                                      {'port_id': fake_port_id})
        self.assertEqual(expected_exception_message, str(exc))

    def test_validate_networks_port_in_use(self):
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=self.port_data3[0]['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(self.port_data3[0]['id']).\
            AndReturn({'port': self.port_data3[0]})

        self.mox.ReplayAll()

        api = neutronapi.API()
        self.assertRaises(exception.PortInUse,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_port_no_subnet_id(self):
        port_a = self.port_data3[0]
        port_a['device_id'] = None
        port_a['device_owner'] = None

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port_a['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(port_a['id']).AndReturn({'port': port_a})

        self.mox.ReplayAll()

        api = neutronapi.API()
        self.assertRaises(exception.PortRequiresFixedIP,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_no_subnet_id(self):
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='his_netid4')])
        ids = ['his_netid4']
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets4})
        self.mox.ReplayAll()
        api = neutronapi.API()
        self.assertRaises(exception.NetworkRequiresSubnet,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_ports_in_same_network_enable(self):
        # Verify that duplicateNetworks exception is not thrown when ports
        # on same duplicate network are passed to validate_networks.
        port_a = self.port_data3[0]
        port_a['fixed_ips'] = {'ip_address': '10.0.0.2',
                               'subnet_id': 'subnet_id'}
        port_b = self.port_data1[0]
        self.assertEqual(port_a['network_id'], port_b['network_id'])
        for port in [port_a, port_b]:
            port['device_id'] = None
            port['device_owner'] = None

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port_a['id']),
                     objects.NetworkRequest(port_id=port_b['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(port_a['id']).AndReturn(
                                                 {'port': port_a})
        self.moxed_client.show_port(port_b['id']).AndReturn(
                                                 {'port': port_b})

        self.mox.ReplayAll()

        api = neutronapi.API()
        api.validate_networks(self.context, requested_networks, 1)

    def test_validate_networks_ports_not_in_same_network(self):
        port_a = self.port_data3[0]
        port_a['fixed_ips'] = {'ip_address': '10.0.0.2',
                               'subnet_id': 'subnet_id'}
        port_b = self.port_data2[1]
        self.assertNotEqual(port_a['network_id'], port_b['network_id'])
        for port in [port_a, port_b]:
            port['device_id'] = None
            port['device_owner'] = None

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port_a['id']),
                     objects.NetworkRequest(port_id=port_b['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(port_a['id']).AndReturn({'port': port_a})
        self.moxed_client.show_port(port_b['id']).AndReturn({'port': port_b})
        self.mox.ReplayAll()

        api = neutronapi.API()
        api.validate_networks(self.context, requested_networks, 1)

    def test_validate_networks_no_quota(self):
        # Test validation for a request for one instance needing
        # two ports, where the quota is 2 and 2 ports are in use
        #  => instances which can be created = 0
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(network_id=uuids.my_netid2)])
        ids = [uuids.my_netid1, uuids.my_netid2]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.show_quota(
            uuids.my_tenant).AndReturn(
                    {'quota': {'port': 2}})
        self.moxed_client.list_ports(
            tenant_id=uuids.my_tenant, fields=['id']).AndReturn(
                    {'ports': self.port_data2})
        self.mox.ReplayAll()
        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 1)
        self.assertEqual(0, max_count)

    def test_validate_networks_with_ports_and_networks(self):
        # Test validation for a request for one instance needing
        # one port allocated via nova with another port being passed in.
        port_b = self.port_data2[1]
        port_b['device_id'] = None
        port_b['device_owner'] = None
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(port_id=port_b['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(port_b['id']).AndReturn({'port': port_b})
        ids = [uuids.my_netid1]
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets1})
        self.moxed_client.show_quota(
            uuids.my_tenant).AndReturn(
                    {'quota': {'port': 5}})
        self.moxed_client.list_ports(
            tenant_id=uuids.my_tenant, fields=['id']).AndReturn(
                    {'ports': self.port_data2})
        self.mox.ReplayAll()
        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 1)
        self.assertEqual(1, max_count)

    def test_validate_networks_one_port_and_no_networks(self):
        # Test that show quota is not called if no networks are
        # passed in and only ports.
        port_b = self.port_data2[1]
        port_b['device_id'] = None
        port_b['device_owner'] = None
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port_b['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(port_b['id']).AndReturn({'port': port_b})
        self.mox.ReplayAll()
        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 1)
        self.assertEqual(1, max_count)

    def test_validate_networks_some_quota(self):
        # Test validation for a request for two instance needing
        # two ports each, where the quota is 5 and 2 ports are in use
        #  => instances which can be created = 1
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(network_id=uuids.my_netid2)])
        ids = [uuids.my_netid1, uuids.my_netid2]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.show_quota(
            uuids.my_tenant).AndReturn(
                    {'quota': {'port': 5}})
        self.moxed_client.list_ports(
            tenant_id=uuids.my_tenant, fields=['id']).AndReturn(
                    {'ports': self.port_data2})
        self.mox.ReplayAll()
        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 2)
        self.assertEqual(1, max_count)

    def test_validate_networks_unlimited_quota(self):
        # Test validation for a request for two instance needing
        # two ports each, where the quota is -1 (unlimited)
        #  => instances which can be created = 1
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(network_id=uuids.my_netid2)])
        ids = [uuids.my_netid1, uuids.my_netid2]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.show_quota(
            uuids.my_tenant).AndReturn(
                    {'quota': {'port': -1}})
        self.mox.ReplayAll()
        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 2)
        self.assertEqual(2, max_count)

    def test_validate_networks_no_quota_but_ports_supplied(self):
        port_a = self.port_data3[0]
        port_a['fixed_ips'] = {'ip_address': '10.0.0.2',
                               'subnet_id': 'subnet_id'}
        port_b = self.port_data2[1]
        self.assertNotEqual(port_a['network_id'], port_b['network_id'])
        for port in [port_a, port_b]:
            port['device_id'] = None
            port['device_owner'] = None

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port_a['id']),
                     objects.NetworkRequest(port_id=port_b['id'])])
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_port(port_a['id']).AndReturn({'port': port_a})
        self.moxed_client.show_port(port_b['id']).AndReturn({'port': port_b})

        self.mox.ReplayAll()

        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 1)
        self.assertEqual(1, max_count)

    def _mock_list_ports(self, port_data=None):
        if port_data is None:
            port_data = self.port_data2
        address = self.port_address
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_ports(
            fixed_ips=MyComparator('ip_address=%s' % address)).AndReturn(
                {'ports': port_data})
        self.mox.ReplayAll()
        return address

    def test_get_fixed_ip_by_address_fails_for_no_ports(self):
        address = self._mock_list_ports(port_data=[])
        api = neutronapi.API()
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          api.get_fixed_ip_by_address,
                          self.context, address)

    def test_get_fixed_ip_by_address_succeeds_for_1_port(self):
        address = self._mock_list_ports(port_data=self.port_data1)
        api = neutronapi.API()
        result = api.get_fixed_ip_by_address(self.context, address)
        self.assertEqual(self.instance2['uuid'], result['instance_uuid'])

    def test_get_fixed_ip_by_address_fails_for_more_than_1_port(self):
        address = self._mock_list_ports()
        api = neutronapi.API()
        self.assertRaises(exception.FixedIpAssociatedWithMultipleInstances,
                          api.get_fixed_ip_by_address,
                          self.context, address)

    def _get_available_networks(self, prv_nets, pub_nets,
                                req_ids=None, context=None):
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        nets = prv_nets + pub_nets
        if req_ids:
            mox_list_params = {'id': req_ids}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': nets})
        else:
            mox_list_params = {'tenant_id': self.instance['project_id'],
                               'shared': False}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': prv_nets})
            mox_list_params = {'shared': True}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': pub_nets})

        self.mox.ReplayAll()
        rets = api._get_available_networks(
            context if context else self.context,
            self.instance['project_id'],
            req_ids)
        self.assertEqual(nets, rets)

    def test_get_available_networks_all_private(self):
        self._get_available_networks(prv_nets=self.nets2, pub_nets=[])

    def test_get_available_networks_all_public(self):
        self._get_available_networks(prv_nets=[], pub_nets=self.nets2)

    def test_get_available_networks_private_and_public(self):
        self._get_available_networks(prv_nets=self.nets1, pub_nets=self.nets4)

    def test_get_available_networks_with_network_ids(self):
        prv_nets = [self.nets3[0]]
        pub_nets = [self.nets3[-1]]
        # specify only first and last network
        req_ids = [net['id'] for net in (self.nets3[0], self.nets3[-1])]
        self._get_available_networks(prv_nets, pub_nets, req_ids)

    def test_get_available_networks_with_custom_policy(self):
        rules = {'network:attach_external_network': ''}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        req_ids = [net['id'] for net in self.nets5]
        self._get_available_networks(self.nets5, pub_nets=[], req_ids=req_ids)

    def test_get_floating_ip_pools(self):
        api = neutronapi.API()
        search_opts = {'router:external': True}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool, self.fip_pool_nova]})
        self.mox.ReplayAll()
        pools = api.get_floating_ip_pools(self.context)
        expected = [self.fip_pool['name'], self.fip_pool_nova['name']]
        self.assertEqual(expected, pools)

    def _get_expected_fip_model(self, fip_data, idx=0):
        expected = {'id': fip_data['id'],
                    'address': fip_data['floating_ip_address'],
                    'pool': self.fip_pool['name'],
                    'project_id': fip_data['tenant_id'],
                    'fixed_ip': None,
                    'instance': ({'uuid': self.port_data2[idx]['device_id']}
                                 if fip_data['port_id']
                                 else None)}
        if fip_data['fixed_ip_address']:
            expected['fixed_ip'] = {'address': fip_data['fixed_ip_address']}
        return expected

    def _compare(self, obj, dic):
        for key, value in dic.items():
            objvalue = obj[key]
            if isinstance(value, dict):
                self._compare(objvalue, value)
            elif isinstance(objvalue, netaddr.IPAddress):
                self.assertEqual(value, str(objvalue))
            else:
                self.assertEqual(value, objvalue)

    def _test_get_floating_ip(self, fip_data, idx=0, by_address=False):
        api = neutronapi.API()
        fip_id = fip_data['id']
        net_id = fip_data['floating_network_id']
        address = fip_data['floating_ip_address']
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        if by_address:
            self.moxed_client.list_floatingips(floating_ip_address=address).\
                AndReturn({'floatingips': [fip_data]})
        else:
            self.moxed_client.show_floatingip(fip_id).\
                AndReturn({'floatingip': fip_data})
        self.moxed_client.show_network(net_id).\
            AndReturn({'network': self.fip_pool})
        if fip_data['port_id']:
            self.moxed_client.show_port(fip_data['port_id']).\
                AndReturn({'port': self.port_data2[idx]})
        self.mox.ReplayAll()

        expected = self._get_expected_fip_model(fip_data, idx)

        if by_address:
            fip = api.get_floating_ip_by_address(self.context, address)
        else:
            fip = api.get_floating_ip(self.context, fip_id)
        self._compare(fip, expected)

    def test_get_floating_ip_unassociated(self):
        self._test_get_floating_ip(self.fip_unassociated, idx=0)

    def test_get_floating_ip_associated(self):
        self._test_get_floating_ip(self.fip_associated, idx=1)

    def test_get_floating_ip_by_address(self):
        self._test_get_floating_ip(self.fip_unassociated, idx=0,
                                   by_address=True)

    def test_get_floating_ip_by_address_associated(self):
        self._test_get_floating_ip(self.fip_associated, idx=1,
                                   by_address=True)

    def test_get_floating_ip_by_address_not_found(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': []})
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          api.get_floating_ip_by_address,
                          self.context, address)

    def test_get_floating_ip_by_id_not_found(self):
        api = neutronapi.API()
        NeutronNotFound = exceptions.NeutronClientException(status_code=404)
        floating_ip_id = self.fip_unassociated['id']
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_floatingip(floating_ip_id).\
            AndRaise(NeutronNotFound)
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpNotFound,
                          api.get_floating_ip,
                          self.context, floating_ip_id)

    def test_get_floating_ip_raises_non404(self):
        api = neutronapi.API()
        NeutronNotFound = exceptions.NeutronClientException(status_code=0)
        floating_ip_id = self.fip_unassociated['id']
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.show_floatingip(floating_ip_id).\
            AndRaise(NeutronNotFound)
        self.mox.ReplayAll()
        self.assertRaises(exceptions.NeutronClientException,
                          api.get_floating_ip,
                          self.context, floating_ip_id)

    def test_get_floating_ip_by_address_multiple_found(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated] * 2})
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpMultipleFoundForAddress,
                          api.get_floating_ip_by_address,
                          self.context, address)

    def test_get_floating_ips_by_project(self):
        api = neutronapi.API()
        project_id = self.context.project_id
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_floatingips(tenant_id=project_id).\
            AndReturn({'floatingips': [self.fip_unassociated,
                                       self.fip_associated]})
        search_opts = {'router:external': True}
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool, self.fip_pool_nova]})
        self.moxed_client.list_ports(tenant_id=project_id).\
                AndReturn({'ports': self.port_data2})
        self.mox.ReplayAll()

        expected = [self._get_expected_fip_model(self.fip_unassociated),
                    self._get_expected_fip_model(self.fip_associated, idx=1)]
        fips = api.get_floating_ips_by_project(self.context)
        self.assertEqual(len(expected), len(fips))
        for i, expected_value in enumerate(expected):
            self._compare(fips[i], expected_value)

    def _test_get_instance_id_by_floating_address(self, fip_data,
                                                  associated=False):
        api = neutronapi.API()
        address = fip_data['floating_ip_address']
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_floatingips(floating_ip_address=address).\
                AndReturn({'floatingips': [fip_data]})
        if associated:
            self.moxed_client.show_port(fip_data['port_id']).\
                AndReturn({'port': self.port_data2[1]})
        self.mox.ReplayAll()

        if associated:
            expected = self.port_data2[1]['device_id']
        else:
            expected = None
        fip = api.get_instance_id_by_floating_address(self.context, address)
        self.assertEqual(expected, fip)

    def test_get_instance_id_by_floating_address(self):
        self._test_get_instance_id_by_floating_address(self.fip_unassociated)

    def test_get_instance_id_by_floating_address_associated(self):
        self._test_get_instance_id_by_floating_address(self.fip_associated,
                                                       associated=True)

    def test_allocate_floating_ip(self):
        api = neutronapi.API()
        pool_name = self.fip_pool['name']
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool]})
        self.moxed_client.create_floatingip(
            {'floatingip': {'floating_network_id': pool_id}}).\
            AndReturn({'floatingip': self.fip_unassociated})
        self.mox.ReplayAll()
        fip = api.allocate_floating_ip(self.context, 'ext_net')
        self.assertEqual(self.fip_unassociated['floating_ip_address'], fip)

    def test_allocate_floating_ip_addr_gen_fail(self):
        api = neutronapi.API()
        pool_name = self.fip_pool['name']
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool]})
        self.moxed_client.create_floatingip(
            {'floatingip': {'floating_network_id': pool_id}}).\
            AndRaise(exceptions.IpAddressGenerationFailureClient)
        self.mox.ReplayAll()
        self.assertRaises(exception.NoMoreFloatingIps,
                          api.allocate_floating_ip, self.context, 'ext_net')

    def test_allocate_floating_ip_exhausted_fail(self):
        api = neutronapi.API()
        pool_name = self.fip_pool['name']
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool]})
        self.moxed_client.create_floatingip(
            {'floatingip': {'floating_network_id': pool_id}}).\
            AndRaise(exceptions.ExternalIpAddressExhaustedClient)
        self.mox.ReplayAll()
        self.assertRaises(exception.NoMoreFloatingIps,
                          api.allocate_floating_ip, self.context, 'ext_net')

    def test_allocate_floating_ip_with_pool_id(self):
        api = neutronapi.API()
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'id': pool_id}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool]})
        self.moxed_client.create_floatingip(
            {'floatingip': {'floating_network_id': pool_id}}).\
            AndReturn({'floatingip': self.fip_unassociated})
        self.mox.ReplayAll()
        fip = api.allocate_floating_ip(self.context, pool_id)
        self.assertEqual(self.fip_unassociated['floating_ip_address'], fip)

    def test_allocate_floating_ip_with_default_pool(self):
        api = neutronapi.API()
        pool_name = self.fip_pool_nova['name']
        pool_id = self.fip_pool_nova['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool_nova]})
        self.moxed_client.create_floatingip(
            {'floatingip': {'floating_network_id': pool_id}}).\
            AndReturn({'floatingip': self.fip_unassociated})
        self.mox.ReplayAll()
        fip = api.allocate_floating_ip(self.context)
        self.assertEqual(self.fip_unassociated['floating_ip_address'], fip)

    def test_disassociate_and_release_floating_ip(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        fip_id = self.fip_unassociated['id']
        floating_ip = {'address': address}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated]})
        self.moxed_client.delete_floatingip(fip_id)
        self.mox.ReplayAll()
        api.disassociate_and_release_floating_ip(self.context, None,
                                               floating_ip)

    def test_disassociate_and_release_floating_ip_with_instance(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        fip_id = self.fip_unassociated['id']
        floating_ip = {'address': address}
        instance = self._fake_instance_object(self.instance)
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated]})
        self.moxed_client.delete_floatingip(fip_id)
        self._setup_mock_for_refresh_cache(api, [instance])
        self.mox.ReplayAll()
        api.disassociate_and_release_floating_ip(self.context, instance,
                                                 floating_ip)

    def _setup_mock_for_refresh_cache(self, api, instances):
        nw_info = model.NetworkInfo()
        self.mox.StubOutWithMock(api, '_get_instance_nw_info')
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        for instance in instances:
            api._get_instance_nw_info(mox.IgnoreArg(), instance).\
                AndReturn(nw_info)
            api.db.instance_info_cache_update(mox.IgnoreArg(),
                                              instance['uuid'],
                                              mox.IgnoreArg()).AndReturn(
                                                  fake_info_cache)

    def test_associate_floating_ip(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        fixed_address = self.port_address2
        fip_id = self.fip_unassociated['id']
        instance = self._fake_instance_object(self.instance)

        search_opts = {'device_owner': 'compute:nova',
                       'device_id': instance.uuid}

        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_ports(**search_opts).\
            AndReturn({'ports': [self.port_data2[1]]})
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated]})
        self.moxed_client.update_floatingip(
            fip_id, {'floatingip': {'port_id': self.fip_associated['port_id'],
                                    'fixed_ip_address': fixed_address}})
        self._setup_mock_for_refresh_cache(api, [instance])

        self.mox.ReplayAll()
        api.associate_floating_ip(self.context, instance,
                                  address, fixed_address)

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_reassociate_floating_ip(self, mock_get):
        api = neutronapi.API()
        address = self.fip_associated['floating_ip_address']
        new_fixed_address = self.port_address
        fip_id = self.fip_associated['id']

        search_opts = {'device_owner': 'compute:nova',
                       'device_id': self.instance2['uuid']}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_ports(**search_opts).\
            AndReturn({'ports': [self.port_data2[0]]})
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_associated]})
        self.moxed_client.update_floatingip(
            fip_id, {'floatingip': {'port_id': uuids.portid_1,
                                    'fixed_ip_address': new_fixed_address}})
        self.moxed_client.show_port(self.fip_associated['port_id']).\
                AndReturn({'port': self.port_data2[1]})

        mock_get.return_value = fake_instance.fake_instance_obj(
            self.context, **self.instance)
        instance2 = self._fake_instance_object(self.instance2)
        self._setup_mock_for_refresh_cache(api, [mock_get.return_value,
                                                 instance2])

        self.mox.ReplayAll()
        api.associate_floating_ip(self.context, instance2,
                                  address, new_fixed_address)

    def test_associate_floating_ip_not_found_fixed_ip(self):
        instance = self._fake_instance_object(self.instance)
        api = neutronapi.API()
        address = self.fip_associated['floating_ip_address']
        fixed_address = self.fip_associated['fixed_ip_address']

        search_opts = {'device_owner': 'compute:nova',
                       'device_id': self.instance['uuid']}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_ports(**search_opts).\
            AndReturn({'ports': [self.port_data2[0]]})

        self.mox.ReplayAll()
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          api.associate_floating_ip, self.context,
                          instance, address, fixed_address)

    def test_disassociate_floating_ip(self):
        instance = self._fake_instance_object(self.instance)
        api = neutronapi.API()
        address = self.fip_associated['floating_ip_address']
        fip_id = self.fip_associated['id']
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_associated]})
        self.moxed_client.update_floatingip(
            fip_id, {'floatingip': {'port_id': None}})
        self._setup_mock_for_refresh_cache(api, [instance])

        self.mox.ReplayAll()
        api.disassociate_floating_ip(self.context, instance, address)

    def test_add_fixed_ip_to_instance(self):
        instance = self._fake_instance_object(self.instance)
        api = neutronapi.API()
        self._setup_mock_for_refresh_cache(api, [instance])
        network_id = uuids.my_netid1
        search_opts = {'network_id': network_id}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_subnets(
            **search_opts).AndReturn({'subnets': self.subnet_data_n})

        search_opts = {'device_id': instance.uuid,
                       'device_owner': 'compute:nova',
                       'network_id': network_id}
        self.moxed_client.list_ports(
            **search_opts).AndReturn({'ports': self.port_data1})
        port_req_body = {
            'port': {
                'fixed_ips': [{'subnet_id': 'my_subid1'},
                              {'subnet_id': 'my_subid1'}],
            },
        }
        port = self.port_data1[0]
        port['fixed_ips'] = [{'subnet_id': 'my_subid1'}]
        self.moxed_client.update_port(uuids.portid_1,
            MyComparator(port_req_body)).AndReturn({'port': port})

        self.mox.ReplayAll()
        api.add_fixed_ip_to_instance(self.context,
                                     instance,
                                     network_id)

    def test_remove_fixed_ip_from_instance(self):
        instance = self._fake_instance_object(self.instance)
        api = neutronapi.API()
        self._setup_mock_for_refresh_cache(api, [instance])
        address = '10.0.0.3'
        zone = 'compute:%s' % self.instance['availability_zone']
        search_opts = {'device_id': self.instance['uuid'],
                       'device_owner': zone,
                       'fixed_ips': 'ip_address=%s' % address}
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_ports(
            **search_opts).AndReturn({'ports': self.port_data1})
        port_req_body = {
            'port': {
                'fixed_ips': [],
            },
        }
        port = self.port_data1[0]
        port['fixed_ips'] = []
        self.moxed_client.update_port(uuids.portid_1,
            MyComparator(port_req_body)).AndReturn({'port': port})

        self.mox.ReplayAll()
        api.remove_fixed_ip_from_instance(self.context, instance,
                                          address)

    def test_list_floating_ips_without_l3_support(self):
        api = neutronapi.API()
        NeutronNotFound = exceptions.NotFound()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_floatingips(
            fixed_ip_address='1.1.1.1', port_id=1).AndRaise(NeutronNotFound)
        self.mox.ReplayAll()
        neutronapi.get_client(uuids.fake)
        floatingips = api._get_floating_ips_by_fixed_and_port(
            self.moxed_client, '1.1.1.1', 1)
        self.assertEqual([], floatingips)

    def test_nw_info_get_ips(self):
        fake_port = {
            'fixed_ips': [
                {'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            }
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.mox.StubOutWithMock(api, '_get_floating_ips_by_fixed_and_port')
        api._get_floating_ips_by_fixed_and_port(
            self.moxed_client, '1.1.1.1', 'port-id').AndReturn(
                [{'floating_ip_address': '10.0.0.1'}])
        self.mox.ReplayAll()
        neutronapi.get_client(uuids.fake)
        result = api._nw_info_get_ips(self.moxed_client, fake_port)
        self.assertEqual(1, len(result))
        self.assertEqual('1.1.1.1', result[0]['address'])
        self.assertEqual('10.0.0.1', result[0]['floating_ips'][0]['address'])

    def test_nw_info_get_subnets(self):
        fake_port = {
            'fixed_ips': [
                {'ip_address': '1.1.1.1'},
                {'ip_address': '2.2.2.2'}],
            'id': 'port-id',
            }
        fake_subnet = model.Subnet(cidr='1.0.0.0/8')
        fake_ips = [model.IP(x['ip_address']) for x in fake_port['fixed_ips']]
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, '_get_subnets_from_port')
        api._get_subnets_from_port(
            self.context, fake_port, None).AndReturn(
            [fake_subnet])
        self.mox.ReplayAll()
        subnets = api._nw_info_get_subnets(self.context, fake_port, fake_ips)
        self.assertEqual(1, len(subnets))
        self.assertEqual(1, len(subnets[0]['ips']))
        self.assertEqual('1.1.1.1', subnets[0]['ips'][0]['address'])

    def _test_nw_info_build_network(self, vif_type):
        fake_port = {
            'fixed_ips': [{'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            'network_id': 'net-id',
            'binding:vif_type': vif_type,
            }
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [{'id': 'net-id', 'name': 'foo', 'tenant_id': 'tenant',
                      'mtu': 9000}]
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.mox.ReplayAll()
        neutronapi.get_client(uuids.fake)
        net, iid = api._nw_info_build_network(fake_port, fake_nets,
                                              fake_subnets)
        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id', net['id'])
        self.assertEqual('foo', net['label'])
        self.assertEqual('tenant', net.get_meta('tenant_id'))
        self.assertEqual(9000, net.get_meta('mtu'))
        self.assertEqual(CONF.flat_injected, net.get_meta('injected'))
        return net, iid

    def test_nw_info_build_network_ovs(self):
        net, iid = self._test_nw_info_build_network(model.VIF_TYPE_OVS)
        self.assertEqual(CONF.neutron.ovs_bridge, net['bridge'])
        self.assertNotIn('should_create_bridge', net)
        self.assertEqual('port-id', iid)

    def test_nw_info_build_network_dvs(self):
        net, iid = self._test_nw_info_build_network(model.VIF_TYPE_DVS)
        self.assertEqual('net-id', net['bridge'])
        self.assertNotIn('should_create_bridge', net)
        self.assertNotIn('ovs_interfaceid', net)
        self.assertIsNone(iid)

    def test_nw_info_build_network_bridge(self):
        net, iid = self._test_nw_info_build_network(model.VIF_TYPE_BRIDGE)
        self.assertEqual('brqnet-id', net['bridge'])
        self.assertTrue(net['should_create_bridge'])
        self.assertIsNone(iid)

    def test_nw_info_build_network_tap(self):
        net, iid = self._test_nw_info_build_network(model.VIF_TYPE_TAP)
        self.assertIsNone(net['bridge'])
        self.assertNotIn('should_create_bridge', net)
        self.assertIsNone(iid)

    def test_nw_info_build_network_other(self):
        net, iid = self._test_nw_info_build_network(None)
        self.assertIsNone(net['bridge'])
        self.assertNotIn('should_create_bridge', net)
        self.assertIsNone(iid)

    def test_nw_info_build_no_match(self):
        fake_port = {
            'fixed_ips': [{'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            'network_id': 'net-id1',
            'tenant_id': 'tenant',
            'binding:vif_type': model.VIF_TYPE_OVS,
            }
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [{'id': 'net-id2', 'name': 'foo', 'tenant_id': 'tenant'}]
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.mox.ReplayAll()
        neutronapi.get_client(uuids.fake)
        net, iid = api._nw_info_build_network(fake_port, fake_nets,
                                              fake_subnets)
        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id1', net['id'])
        self.assertEqual('tenant', net['meta']['tenant_id'])

    def test_nw_info_build_network_vhostuser(self):
        fake_port = {
            'fixed_ips': [{'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            'network_id': 'net-id',
            'binding:vif_type': model.VIF_TYPE_VHOSTUSER,
            'binding:vif_details': {
                    model.VIF_DETAILS_VHOSTUSER_OVS_PLUG: True
                                    }
            }
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [{'id': 'net-id', 'name': 'foo', 'tenant_id': 'tenant'}]
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.mox.ReplayAll()
        neutronapi.get_client(uuids.fake)
        net, iid = api._nw_info_build_network(fake_port, fake_nets,
                                              fake_subnets)
        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id', net['id'])
        self.assertEqual('foo', net['label'])
        self.assertEqual('tenant', net.get_meta('tenant_id'))
        self.assertEqual(CONF.flat_injected, net.get_meta('injected'))
        self.assertEqual(CONF.neutron.ovs_bridge, net['bridge'])
        self.assertNotIn('should_create_bridge', net)
        self.assertEqual('port-id', iid)

    def test_nw_info_build_network_vhostuser_fp(self):
        fake_port = {
            'fixed_ips': [{'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            'network_id': 'net-id',
            'binding:vif_type': model.VIF_TYPE_VHOSTUSER,
            'binding:vif_details': {
                    model.VIF_DETAILS_VHOSTUSER_FP_PLUG: True,
                    model.VIF_DETAILS_VHOSTUSER_OVS_PLUG: False,
                                    }
            }
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [{'id': 'net-id', 'name': 'foo', 'tenant_id': 'tenant'}]
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.mox.ReplayAll()
        neutronapi.get_client(uuids.fake)
        net, ovs_interfaceid = api._nw_info_build_network(
            fake_port, fake_nets, fake_subnets)
        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id', net['id'])
        self.assertEqual('foo', net['label'])
        self.assertEqual('tenant', net.get_meta('tenant_id'))
        self.assertEqual('brqnet-id', net['bridge'])
        self.assertIsNone(ovs_interfaceid)

    def _test_nw_info_build_custom_bridge(self, vif_type, extra_details=None):
        fake_port = {
            'fixed_ips': [{'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            'network_id': 'net-id',
            'binding:vif_type': vif_type,
            'binding:vif_details': {
                model.VIF_DETAILS_BRIDGE_NAME: 'custom-bridge',
            }
        }
        if extra_details:
            fake_port['binding:vif_details'].update(extra_details)
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [{'id': 'net-id', 'name': 'foo', 'tenant_id': 'tenant'}]
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.mox.ReplayAll()
        neutronapi.get_client(uuids.fake)
        net, iid = api._nw_info_build_network(fake_port, fake_nets,
                                              fake_subnets)
        self.assertNotEqual(CONF.neutron.ovs_bridge, net['bridge'])
        self.assertEqual('custom-bridge', net['bridge'])

    def test_nw_info_build_custom_ovs_bridge(self):
        self._test_nw_info_build_custom_bridge(model.VIF_TYPE_OVS)

    def test_nw_info_build_custom_ovs_bridge_vhostuser(self):
        self._test_nw_info_build_custom_bridge(model.VIF_TYPE_VHOSTUSER,
                {model.VIF_DETAILS_VHOSTUSER_OVS_PLUG: True})

    def test_nw_info_build_custom_lb_bridge(self):
        self._test_nw_info_build_custom_bridge(model.VIF_TYPE_BRIDGE)

    def test_build_network_info_model(self):
        api = neutronapi.API()

        fake_inst = objects.Instance()
        fake_inst.project_id = uuids.fake
        fake_inst.uuid = uuids.instance
        fake_inst.info_cache = objects.InstanceInfoCache()
        fake_inst.info_cache.network_info = model.NetworkInfo()
        fake_ports = [
            # admin_state_up=True and status='ACTIVE' thus vif.active=True
            {'id': 'port1',
             'network_id': 'net-id',
             'admin_state_up': True,
             'status': 'ACTIVE',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:01',
             'binding:vif_type': model.VIF_TYPE_BRIDGE,
             'binding:vnic_type': model.VNIC_TYPE_NORMAL,
             'binding:vif_details': {},
             },
            # admin_state_up=False and status='DOWN' thus vif.active=True
            {'id': 'port2',
             'network_id': 'net-id',
             'admin_state_up': False,
             'status': 'DOWN',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:02',
             'binding:vif_type': model.VIF_TYPE_BRIDGE,
             'binding:vnic_type': model.VNIC_TYPE_NORMAL,
             'binding:vif_details': {},
             },
            # admin_state_up=True and status='DOWN' thus vif.active=False
             {'id': 'port0',
             'network_id': 'net-id',
             'admin_state_up': True,
             'status': 'DOWN',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:03',
             'binding:vif_type': model.VIF_TYPE_BRIDGE,
             'binding:vnic_type': model.VNIC_TYPE_NORMAL,
             'binding:vif_details': {},
             },
            # admin_state_up=True and status='ACTIVE' thus vif.active=True
            {'id': 'port3',
             'network_id': 'net-id',
             'admin_state_up': True,
             'status': 'ACTIVE',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:04',
             'binding:vif_type': model.VIF_TYPE_HW_VEB,
             'binding:vnic_type': model.VNIC_TYPE_DIRECT,
             neutronapi.BINDING_PROFILE: {'pci_vendor_info': '1137:0047',
                                          'pci_slot': '0000:0a:00.1',
                                          'physical_network': 'phynet1'},
             'binding:vif_details': {model.VIF_DETAILS_PROFILEID: 'pfid'},
             },
            # admin_state_up=True and status='ACTIVE' thus vif.active=True
            {'id': 'port4',
             'network_id': 'net-id',
             'admin_state_up': True,
             'status': 'ACTIVE',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:05',
             'binding:vif_type': model.VIF_TYPE_802_QBH,
             'binding:vnic_type': model.VNIC_TYPE_MACVTAP,
             neutronapi.BINDING_PROFILE: {'pci_vendor_info': '1137:0047',
                                          'pci_slot': '0000:0a:00.2',
                                          'physical_network': 'phynet1'},
             'binding:vif_details': {model.VIF_DETAILS_PROFILEID: 'pfid'},
             },
            # admin_state_up=True and status='ACTIVE' thus vif.active=True
            # This port has no binding:vnic_type to verify default is assumed
            {'id': 'port5',
             'network_id': 'net-id',
             'admin_state_up': True,
             'status': 'ACTIVE',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:06',
             'binding:vif_type': model.VIF_TYPE_BRIDGE,
             # No binding:vnic_type
             'binding:vif_details': {},
             },
            # This does not match the networks we provide below,
            # so it should be ignored (and is here to verify that)
            {'id': 'port6',
             'network_id': 'other-net-id',
             'admin_state_up': True,
             'status': 'DOWN',
             'binding:vnic_type': model.VNIC_TYPE_NORMAL,
             },
            ]
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [
            {'id': 'net-id',
             'name': 'foo',
             'tenant_id': uuids.fake,
             }
            ]
        neutronapi.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        self.moxed_client.list_ports(
            tenant_id=uuids.fake, device_id=uuids.instance).AndReturn(
                {'ports': fake_ports})

        self.mox.StubOutWithMock(api, '_get_floating_ips_by_fixed_and_port')
        self.mox.StubOutWithMock(api, '_get_subnets_from_port')
        requested_ports = [fake_ports[2], fake_ports[0], fake_ports[1],
                           fake_ports[3], fake_ports[4], fake_ports[5]]
        for requested_port in requested_ports:
            api._get_floating_ips_by_fixed_and_port(
                self.moxed_client, '1.1.1.1', requested_port['id']).AndReturn(
                    [{'floating_ip_address': '10.0.0.1'}])
        for requested_port in requested_ports:
            api._get_subnets_from_port(self.context, requested_port,
                                       self.moxed_client).AndReturn(
                fake_subnets)

        self.mox.StubOutWithMock(api, '_get_preexisting_port_ids')
        api._get_preexisting_port_ids(fake_inst).AndReturn(['port5'])
        self.mox.ReplayAll()
        fake_inst.info_cache = objects.InstanceInfoCache.new(
            self.context, uuids.instance)
        fake_inst.info_cache.network_info = model.NetworkInfo.hydrate([])
        nw_infos = api._build_network_info_model(
            self.context, fake_inst,
            fake_nets,
            [fake_ports[2]['id'],
             fake_ports[0]['id'],
             fake_ports[1]['id'],
             fake_ports[3]['id'],
             fake_ports[4]['id'],
             fake_ports[5]['id']],
            preexisting_port_ids=['port3'])

        self.assertEqual(6, len(nw_infos))
        index = 0
        for nw_info in nw_infos:
            self.assertEqual(requested_ports[index]['mac_address'],
                             nw_info['address'])
            self.assertEqual('tapport' + str(index), nw_info['devname'])
            self.assertIsNone(nw_info['ovs_interfaceid'])
            self.assertEqual(requested_ports[index]['binding:vif_type'],
                             nw_info['type'])
            if nw_info['type'] == model.VIF_TYPE_BRIDGE:
                self.assertEqual('brqnet-id', nw_info['network']['bridge'])
            self.assertEqual(requested_ports[index].get('binding:vnic_type',
                                model.VNIC_TYPE_NORMAL), nw_info['vnic_type'])
            self.assertEqual(requested_ports[index].get('binding:vif_details'),
                             nw_info.get('details'))
            self.assertEqual(
                # If the requested port does not define a binding:profile, or
                # has it set to None, we default to an empty dict to avoid
                # NoneType errors.
                requested_ports[index].get(neutronapi.BINDING_PROFILE) or {},
                nw_info.get('profile'))
            index += 1

        self.assertFalse(nw_infos[0]['active'])
        self.assertTrue(nw_infos[1]['active'])
        self.assertTrue(nw_infos[2]['active'])
        self.assertTrue(nw_infos[3]['active'])
        self.assertTrue(nw_infos[4]['active'])
        self.assertTrue(nw_infos[5]['active'])

        self.assertEqual('port0', nw_infos[0]['id'])
        self.assertEqual('port1', nw_infos[1]['id'])
        self.assertEqual('port2', nw_infos[2]['id'])
        self.assertEqual('port3', nw_infos[3]['id'])
        self.assertEqual('port4', nw_infos[4]['id'])
        self.assertEqual('port5', nw_infos[5]['id'])

        self.assertFalse(nw_infos[0]['preserve_on_delete'])
        self.assertFalse(nw_infos[1]['preserve_on_delete'])
        self.assertFalse(nw_infos[2]['preserve_on_delete'])
        self.assertTrue(nw_infos[3]['preserve_on_delete'])
        self.assertFalse(nw_infos[4]['preserve_on_delete'])
        self.assertTrue(nw_infos[5]['preserve_on_delete'])

    @mock.patch('nova.network.neutronv2.api.API._nw_info_get_subnets')
    @mock.patch('nova.network.neutronv2.api.API._nw_info_get_ips')
    @mock.patch('nova.network.neutronv2.api.API._nw_info_build_network')
    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    @mock.patch('nova.network.neutronv2.api.API._gather_port_ids_and_networks')
    def test_build_network_info_model_empty(
            self, mock_gather_port_ids_and_networks,
            mock_get_preexisting_port_ids,
            mock_nw_info_build_network,
            mock_nw_info_get_ips,
            mock_nw_info_get_subnets):
        # An empty instance info network cache should not be populated from
        # ports found in Neutron.
        api = neutronapi.API()

        fake_inst = objects.Instance()
        fake_inst.project_id = uuids.fake
        fake_inst.uuid = uuids.instance
        fake_inst.info_cache = objects.InstanceInfoCache()
        fake_inst.info_cache.network_info = model.NetworkInfo()
        fake_ports = [
            # admin_state_up=True and status='ACTIVE' thus vif.active=True
            {'id': 'port1',
             'network_id': 'net-id',
             'admin_state_up': True,
             'status': 'ACTIVE',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:01',
             'binding:vif_type': model.VIF_TYPE_BRIDGE,
             'binding:vnic_type': model.VNIC_TYPE_NORMAL,
             'binding:vif_details': {},
             },
            ]
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]

        neutronapi.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        self.moxed_client.list_ports(
            tenant_id=uuids.fake, device_id=uuids.instance).AndReturn(
                {'ports': fake_ports})

        mock_gather_port_ids_and_networks.return_value = ([], [])
        mock_get_preexisting_port_ids.return_value = []
        mock_nw_info_build_network.return_value = (None, None)
        mock_nw_info_get_ips.return_value = []
        mock_nw_info_get_subnets.return_value = fake_subnets

        self.mox.ReplayAll()

        nw_infos = api._build_network_info_model(
            self.context, fake_inst)
        self.assertEqual(0, len(nw_infos))

    def test_get_subnets_from_port(self):
        api = neutronapi.API()

        port_data = copy.copy(self.port_data1[0])
        subnet_data1 = copy.copy(self.subnet_data1)
        subnet_data1[0]['host_routes'] = [
            {'destination': '192.168.0.0/24', 'nexthop': '1.0.0.10'}
        ]
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_subnets(
            id=[port_data['fixed_ips'][0]['subnet_id']]
        ).AndReturn({'subnets': subnet_data1})
        self.moxed_client.list_ports(
            network_id=subnet_data1[0]['network_id'],
            device_owner='network:dhcp').AndReturn({'ports': []})
        self.mox.ReplayAll()

        subnets = api._get_subnets_from_port(self.context, port_data)

        self.assertEqual(1, len(subnets))
        self.assertEqual(1, len(subnets[0]['routes']))
        self.assertEqual(subnet_data1[0]['host_routes'][0]['destination'],
                         subnets[0]['routes'][0]['cidr'])
        self.assertEqual(subnet_data1[0]['host_routes'][0]['nexthop'],
                         subnets[0]['routes'][0]['gateway']['address'])

    def test_get_all_empty_list_networks(self):
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(self.moxed_client)
        self.moxed_client.list_networks().AndReturn({'networks': []})
        self.mox.ReplayAll()
        networks = api.get_all(self.context)
        self.assertIsInstance(networks, objects.NetworkList)
        self.assertEqual(0, len(networks))

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_port_vnic_info_multi_segment(self, mock_get_client):
        api = neutronapi.API()
        self.mox.ResetAll()
        test_port = {
            'port': {'id': 'my_port_id1',
                      'network_id': 'net-id',
                      'binding:vnic_type': model.VNIC_TYPE_DIRECT,
                     },
            }
        test_net = {'network': {'segments':
                                    [{'provider:physical_network': 'phynet10',
                                      'provider:segmentation_id': 1000,
                                      'provider:network_type': 'vlan'},
                                     {'provider:physical_network': None,
                                      'provider:segmentation_id': 153,
                                      'provider:network_type': 'vxlan'}]}}
        test_ext_list = {'extensions':
                            [{'name': 'Multi Provider Network',
                             'alias': 'multi-segments'}]}

        mock_client = mock_get_client()
        mock_client.show_port.return_value = test_port
        mock_client.list_extensions.return_value = test_ext_list
        mock_client.show_network.return_value = test_net
        vnic_type, phynet_name = api._get_port_vnic_info(
            self.context, mock_client, test_port['port']['id'])

        mock_client.show_network.assert_called_once_with(
            test_port['port']['network_id'],
            fields='segments')
        self.assertEqual('phynet10', phynet_name)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_port_vnic_info_vlan_with_multi_segment_ext(self,
                                                            mock_get_client):
        api = neutronapi.API()
        self.mox.ResetAll()
        test_port = {
            'port': {'id': 'my_port_id1',
                      'network_id': 'net-id',
                      'binding:vnic_type': model.VNIC_TYPE_DIRECT,
                     },
            }
        test_net = {'network': {'provider:physical_network': 'phynet10',
                                'provider:segmentation_id': 1000,
                                'provider:network_type': 'vlan'}}
        test_ext_list = {'extensions':
                            [{'name': 'Multi Provider Network',
                             'alias': 'multi-segments'}]}

        mock_client = mock_get_client()
        mock_client.show_port.return_value = test_port
        mock_client.list_extensions.return_value = test_ext_list
        mock_client.show_network.return_value = test_net
        vnic_type, phynet_name = api._get_port_vnic_info(
            self.context, mock_client, test_port['port']['id'])

        mock_client.show_network.assert_called_with(
            test_port['port']['network_id'],
            fields='provider:physical_network')
        self.assertEqual('phynet10', phynet_name)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_port_vnic_info_multi_segment_no_phynet(self, mock_get_client):
        api = neutronapi.API()
        self.mox.ResetAll()
        test_port = {
            'port': {'id': 'my_port_id1',
                      'network_id': 'net-id',
                      'binding:vnic_type': model.VNIC_TYPE_DIRECT,
                     },
            }
        test_net = {'network': {'segments':
                                    [{'provider:physical_network': None,
                                      'provider:segmentation_id': 1000,
                                      'provider:network_type': 'vlan'},
                                     {'provider:physical_network': None,
                                      'provider:segmentation_id': 153,
                                      'provider:network_type': 'vlan'}]}}
        test_ext_list = {'extensions':
                            [{'name': 'Multi Provider Network',
                             'alias': 'multi-segments'}]}

        mock_client = mock_get_client()
        mock_client.show_port.return_value = test_port
        mock_client.list_extensions.return_value = test_ext_list
        mock_client.show_network.return_value = test_net
        self.assertRaises(exception.NovaException,
                          api._get_port_vnic_info,
                          self.context, mock_client, test_port['port']['id'])

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.MagicMock())
    def test_get_port_vnic_info_1(self, mock_get_client):
        api = neutronapi.API()
        self.mox.ResetAll()
        test_port = {
            'port': {'id': 'my_port_id1',
                      'network_id': 'net-id',
                      'binding:vnic_type': model.VNIC_TYPE_DIRECT,
                     },
            }
        test_net = {'network': {'provider:physical_network': 'phynet1'}}

        mock_client = mock_get_client()
        mock_client.show_port.return_value = test_port
        mock_client.show_network.return_value = test_net
        vnic_type, phynet_name = api._get_port_vnic_info(
            self.context, mock_client, test_port['port']['id'])

        mock_client.show_port.assert_called_once_with(test_port['port']['id'],
            fields=['binding:vnic_type', 'network_id'])
        mock_client.show_network.assert_called_once_with(
            test_port['port']['network_id'],
            fields='provider:physical_network')
        self.assertEqual(model.VNIC_TYPE_DIRECT, vnic_type)
        self.assertEqual('phynet1', phynet_name)

    def _test_get_port_vnic_info(self, mock_get_client,
                                 binding_vnic_type=None):
        api = neutronapi.API()
        self.mox.ResetAll()
        test_port = {
            'port': {'id': 'my_port_id2',
                      'network_id': 'net-id',
                      },
            }

        if binding_vnic_type:
            test_port['port']['binding:vnic_type'] = binding_vnic_type

        mock_get_client.reset_mock()
        mock_client = mock_get_client()
        mock_client.show_port.return_value = test_port
        vnic_type, phynet_name = api._get_port_vnic_info(
            self.context, mock_client, test_port['port']['id'])

        mock_client.show_port.assert_called_once_with(test_port['port']['id'],
            fields=['binding:vnic_type', 'network_id'])
        self.assertEqual(model.VNIC_TYPE_NORMAL, vnic_type)
        self.assertFalse(phynet_name)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_port_vnic_info_2(self, mock_get_client):
        self._test_get_port_vnic_info(mock_get_client,
                                      binding_vnic_type=model.VNIC_TYPE_NORMAL)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_port_vnic_info_3(self, mock_get_client):
        self._test_get_port_vnic_info(mock_get_client)

    @mock.patch.object(neutronapi.API, "_get_port_vnic_info")
    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_create_pci_requests_for_sriov_ports(self, mock_get_client,
                                                 mock_get_port_vnic_info):
        api = neutronapi.API()
        self.mox.ResetAll()
        requested_networks = objects.NetworkRequestList(
            objects = [
                objects.NetworkRequest(port_id=uuids.portid_1),
                objects.NetworkRequest(network_id='net1'),
                objects.NetworkRequest(port_id=uuids.portid_2),
                objects.NetworkRequest(port_id=uuids.portid_3),
                objects.NetworkRequest(port_id=uuids.portid_4),
                objects.NetworkRequest(port_id=uuids.portid_5)])
        pci_requests = objects.InstancePCIRequests(requests=[])
        mock_get_port_vnic_info.side_effect = [
                (model.VNIC_TYPE_DIRECT, 'phynet1'),
                (model.VNIC_TYPE_NORMAL, ''),
                (model.VNIC_TYPE_MACVTAP, 'phynet1'),
                (model.VNIC_TYPE_MACVTAP, 'phynet2'),
                (model.VNIC_TYPE_DIRECT_PHYSICAL, 'phynet3')
            ]
        api.create_pci_requests_for_sriov_ports(
            None, pci_requests, requested_networks)
        self.assertEqual(4, len(pci_requests.requests))
        has_pci_request_id = [net.pci_request_id is not None for net in
                              requested_networks.objects]
        self.assertEqual(pci_requests.requests[3].spec[0]["dev_type"],
                         "type-PF")
        expected_results = [True, False, False, True, True, True]
        self.assertEqual(expected_results, has_pci_request_id)


class TestNeutronv2WithMock(test.TestCase):
    """Used to test Neutron V2 API with mock."""

    def setUp(self):
        super(TestNeutronv2WithMock, self).setUp()
        self.api = neutronapi.API()
        self.context = context.RequestContext(
            'fake-user', 'fake-project',
            auth_token='bff4a5a6b9eb4ea2a6efec6eefb77936')

    @mock.patch('nova.network.neutronv2.api.API._show_port')
    def test_deferred_ip_port_immediate_allocation(self, mock_show):
        port = {'network_id': 'my_netid1',
                'device_id': None,
                'id': uuids.port,
                'fixed_ips': [],  # no fixed ip
                'ip_allocation': 'immediate', }

        mock_show.return_value = port

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port['id'])])
        self.assertRaises(exception.PortRequiresFixedIP,
                          self.api.validate_networks,
                          self.context, requested_networks, 1)

    @mock.patch('nova.network.neutronv2.api.API._show_port')
    def test_deferred_ip_port_deferred_allocation(self, mock_show):
        port = {'network_id': 'my_netid1',
                'device_id': None,
                'id': uuids.port,
                'fixed_ips': [],  # no fixed ip
                'ip_allocation': 'deferred', }

        mock_show.return_value = port

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port['id'])])
        count = self.api.validate_networks(self.context, requested_networks, 1)
        self.assertEqual(1, count)

    @mock.patch('oslo_concurrency.lockutils.lock')
    def test_get_instance_nw_info_locks_per_instance(self, mock_lock):
        instance = objects.Instance(uuid=uuids.fake)
        api = neutronapi.API()
        mock_lock.side_effect = test.TestingException
        self.assertRaises(test.TestingException,
                          api.get_instance_nw_info, 'context', instance)
        mock_lock.assert_called_once_with('refresh_cache-%s' % instance.uuid)

    @mock.patch('nova.network.neutronv2.api.LOG')
    def test_get_instance_nw_info_verify_duplicates_ignored(self, mock_log):
        """test that the returned networks & port_ids from
        _gather_port_ids_and_networks doesn't contain any duplicates

        The test fakes an instance with two ports connected to two networks.
        The _gather_port_ids_and_networks method will be called with the
        instance and a list of port ids of which one port id is configured
        already to the instance (== duplicate #1) and a list of
        networks that already contains a network to which an instance port
        is connected (== duplicate #2).

        All-in-all, we expect the resulting port ids list to contain 3 items
        (["instance_port_1", "port_1", "port_2"]) and the resulting networks
        list to contain 3 items (["net_1", "net_2", "instance_network_1"])
        while the warning message for duplicate items was executed twice
        (due to "duplicate #1" & "duplicate #2")
        """

        networks = [model.Network(id="net_1"),
                    model.Network(id="net_2")]
        port_ids = ["port_1", "port_2"]

        instance_networks = [{"id": "instance_network_1",
                              "name": "fake_network",
                              "tenant_id": "fake_tenant_id"}]
        instance_port_ids = ["instance_port_1"]

        network_info = model.NetworkInfo(
            [{'id': port_ids[0],
              'network': networks[0]},
             {'id': instance_port_ids[0],
              'network': model.Network(
                  id=instance_networks[0]["id"],
                  label=instance_networks[0]["name"],
                  meta={"tenant_id": instance_networks[0]["tenant_id"]})}]
        )

        instance_uuid = uuids.fake
        instance = objects.Instance(uuid=instance_uuid,
                                    info_cache=objects.InstanceInfoCache(
                                        context=self.context,
                                        instance_uuid=instance_uuid,
                                        network_info=network_info))

        new_networks, new_port_ids = self.api._gather_port_ids_and_networks(
            self.context, instance, networks, port_ids)

        self.assertEqual(new_networks, networks + instance_networks)
        self.assertEqual(new_port_ids, instance_port_ids + port_ids)
        self.assertEqual(2, mock_log.warning.call_count)

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch.object(neutronapi.API, '_get_instance_nw_info')
    @mock.patch('nova.network.base_api.update_instance_cache_with_nw_info')
    def test_get_instance_nw_info(self, mock_update, mock_get, mock_lock):
        fake_result = mock.sentinel.get_nw_info_result
        mock_get.return_value = fake_result
        instance = fake_instance.fake_instance_obj(self.context)
        result = self.api.get_instance_nw_info(self.context, instance)
        mock_get.assert_called_once_with(self.context, instance)
        mock_update.assert_called_once_with(self.api, self.context, instance,
                                            nw_info=fake_result,
                                            update_cells=False)
        self.assertEqual(fake_result, result)

    def _test_validate_networks_fixed_ip_no_dup(self, nets, requested_networks,
                                                ids, list_port_values):

        def _fake_list_ports(**search_opts):
            for args, return_value in list_port_values:
                if args == search_opts:
                    return return_value
            self.fail('Unexpected call to list_ports %s' % search_opts)

        with test.nested(
            mock.patch.object(client.Client, 'list_ports',
                              side_effect=_fake_list_ports),
            mock.patch.object(client.Client, 'list_networks',
                              return_value={'networks': nets}),
            mock.patch.object(client.Client, 'show_quota',
                              return_value={'quota': {'port': 50}})) as (
                list_ports_mock, list_networks_mock, show_quota_mock):

            self.api.validate_networks(self.context, requested_networks, 1)

            self.assertEqual(len(list_port_values),
                             len(list_ports_mock.call_args_list))
            list_networks_mock.assert_called_once_with(id=ids)
            show_quota_mock.assert_called_once_with('fake-project')

    def test_validate_networks_over_limit_quota(self):
        """Test validates that a relevant exception is being raised when
           there are more ports defined, than there is a quota for it.
        """
        requested_networks = [(uuids.my_netid1, '10.0.1.2', None, None),
                              (uuids.my_netid2, '10.0.1.3', None, None)]

        list_port_values = [({'network_id': uuids.my_netid1,
                              'fixed_ips': 'ip_address=10.0.1.2',
                              'fields': 'device_id'},
                             {'ports': []}),
                            ({'network_id': uuids.my_netid2,
                              'fixed_ips': 'ip_address=10.0.1.3',
                              'fields': 'device_id'},
                             {'ports': []}),

                            ({'tenant_id': 'fake-project', 'fields': ['id']},
                             {'ports': [1, 2, 3, 4, 5]})]

        nets = [{'subnets': '1'}, {'subnets': '2'}]

        def _fake_list_ports(**search_opts):
            for args, return_value in list_port_values:
                if args == search_opts:
                    return return_value

        with test.nested(
            mock.patch.object(self.api, '_get_available_networks',
                              return_value=nets),
            mock.patch.object(client.Client, 'list_ports',
                              side_effect=_fake_list_ports),
            mock.patch.object(client.Client, 'show_quota',
                              return_value={'quota': {'port': 1}})):

                exc = self.assertRaises(exception.PortLimitExceeded,
                                        self.api.validate_networks,
                                        self.context, requested_networks, 1)
                expected_exception_msg = ('The number of defined ports: '
                                          '%(ports)d is over the limit: '
                                          '%(quota)d' %
                                          {'ports': 5,
                                           'quota': 1})
                self.assertEqual(expected_exception_msg, str(exc))

    def test_validate_networks_fixed_ip_no_dup1(self):
        # Test validation for a request for a network with a
        # fixed ip that is not already in use because no fixed ips in use

        nets1 = [{'id': uuids.my_netid1,
                  'name': 'my_netname1',
                  'subnets': ['mysubnid1'],
                  'tenant_id': 'fake-project'}]

        requested_networks = [(uuids.my_netid1, '10.0.1.2', None, None)]
        ids = [uuids.my_netid1]
        list_port_values = [({'network_id': uuids.my_netid1,
                              'fixed_ips': 'ip_address=10.0.1.2',
                              'fields': 'device_id'},
                             {'ports': []}),
                            ({'tenant_id': 'fake-project', 'fields': ['id']},
                             {'ports': []})]
        self._test_validate_networks_fixed_ip_no_dup(nets1, requested_networks,
                                                     ids, list_port_values)

    def test_validate_networks_fixed_ip_no_dup2(self):
        # Test validation for a request for a network with a
        # fixed ip that is not already in use because not used on this net id

        nets2 = [{'id': uuids.my_netid1,
                  'name': 'my_netname1',
                  'subnets': ['mysubnid1'],
                  'tenant_id': 'fake-project'},
                 {'id': uuids.my_netid2,
                  'name': 'my_netname2',
                  'subnets': ['mysubnid2'],
                  'tenant_id': 'fake-project'}]

        requested_networks = [(uuids.my_netid1, '10.0.1.2', None, None),
                              (uuids.my_netid2, '10.0.1.3', None, None)]
        ids = [uuids.my_netid1, uuids.my_netid2]
        list_port_values = [({'network_id': uuids.my_netid1,
                              'fixed_ips': 'ip_address=10.0.1.2',
                              'fields': 'device_id'},
                             {'ports': []}),
                            ({'network_id': uuids.my_netid2,
                              'fixed_ips': 'ip_address=10.0.1.3',
                              'fields': 'device_id'},
                             {'ports': []}),

                            ({'tenant_id': 'fake-project', 'fields': ['id']},
                             {'ports': []})]

        self._test_validate_networks_fixed_ip_no_dup(nets2, requested_networks,
                                                     ids, list_port_values)

    def test_validate_networks_fixed_ip_dup(self):
        # Test validation for a request for a network with a
        # fixed ip that is already in use

        requested_networks = [(uuids.my_netid1, '10.0.1.2', None, None)]
        list_port_mock_params = {'network_id': uuids.my_netid1,
                                 'fixed_ips': 'ip_address=10.0.1.2',
                                 'fields': 'device_id'}
        list_port_mock_return = {'ports': [({'device_id': 'my_deviceid'})]}

        with mock.patch.object(client.Client, 'list_ports',
                               return_value=list_port_mock_return) as (
            list_ports_mock):

            self.assertRaises(exception.FixedIpAlreadyInUse,
                              self.api.validate_networks,
                              self.context, requested_networks, 1)

            list_ports_mock.assert_called_once_with(**list_port_mock_params)

    def test_allocate_floating_ip_exceed_limit(self):
        # Verify that the correct exception is thrown when quota exceed
        pool_name = 'dummy'
        api = neutronapi.API()
        with test.nested(
            mock.patch.object(client.Client, 'create_floatingip'),
            mock.patch.object(api,
                '_get_floating_ip_pool_id_by_name_or_id')) as (
            create_mock, get_mock):
            create_mock.side_effect = exceptions.OverQuotaClient()

            self.assertRaises(exception.FloatingIpLimitExceeded,
                          api.allocate_floating_ip,
                          self.context, pool_name)

    def test_allocate_floating_ip_no_ipv4_subnet(self):
        api = neutronapi.API()
        net_id = uuids.fake
        error_msg = ('Bad floatingip request: Network %s does not contain '
                     'any IPv4 subnet' % net_id)
        with test.nested(
            mock.patch.object(client.Client, 'create_floatingip'),
            mock.patch.object(api,
                '_get_floating_ip_pool_id_by_name_or_id')) as (
            create_mock, get_mock):
            create_mock.side_effect = exceptions.BadRequest(error_msg)

            self.assertRaises(exception.FloatingIpBadRequest,
                              api.allocate_floating_ip, self.context,
                              'ext_net')

    @mock.patch('nova.network.neutronv2.api.get_client')
    @mock.patch('nova.network.neutronv2.api.API._get_floating_ip_by_address',
                return_value={'port_id': None, 'id': 'abc'})
    def test_release_floating_ip(self, mock_get_ip, mock_ntrn):
        """Validate default behavior."""
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        address = '172.24.4.227'

        self.api.release_floating_ip(self.context, address)

        mock_ntrn.assert_called_once_with(self.context)
        mock_get_ip.assert_called_once_with(mock_nc, address)
        mock_nc.delete_floatingip.assert_called_once_with('abc')

    @mock.patch('nova.network.neutronv2.api.get_client')
    @mock.patch('nova.network.neutronv2.api.API._get_floating_ip_by_address',
                return_value={'port_id': 'abc', 'id': 'abc'})
    def test_release_floating_ip_associated(self, mock_get_ip, mock_ntrn):
        """Ensure release fails if a port is still associated with it.

        If the floating IP has a port associated with it, as indicated by a
        configured port_id, then any attempt to release should fail.
        """
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        address = '172.24.4.227'

        self.assertRaises(exception.FloatingIpAssociated,
                          self.api.release_floating_ip,
                          self.context, address)

    @mock.patch('nova.network.neutronv2.api.get_client')
    @mock.patch('nova.network.neutronv2.api.API._get_floating_ip_by_address',
                return_value={'port_id': None, 'id': 'abc'})
    def test_release_floating_ip_not_found(self, mock_get_ip, mock_ntrn):
        """Ensure neutron's NotFound exception is correctly handled.

        Sometimes, trying to delete a floating IP multiple times in a short
        delay can trigger an exception because the operation is not atomic. If
        neutronclient's call to delete fails with a NotFound error, then we
        should correctly handle this.
        """
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.delete_floatingip.side_effect = exceptions.NotFound()
        address = '172.24.4.227'

        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          self.api.release_floating_ip,
                          self.context, address)

    @mock.patch.object(client.Client, 'create_port')
    def test_create_port_minimal_raise_no_more_ip(self, create_port_mock):
        instance = fake_instance.fake_instance_obj(self.context)
        create_port_mock.side_effect = \
            exceptions.IpAddressGenerationFailureClient()
        self.assertRaises(exception.NoMoreFixedIps,
                          self.api._create_port_minimal,
                          neutronapi.get_client(self.context),
                          instance, uuids.my_netid1)
        self.assertTrue(create_port_mock.called)

    @mock.patch.object(client.Client, 'update_port',
                       side_effect=exceptions.MacAddressInUseClient())
    def test_update_port_for_instance_mac_address_in_use(self,
                                                         update_port_mock):
        port_uuid = uuids.port
        instance = objects.Instance(uuid=uuids.instance)
        port_req_body = {'port': {
                            'id': port_uuid,
                            'mac_address': 'XX:XX:XX:XX:XX:XX',
                            'network_id': uuids.network_id}}

        self.assertRaises(exception.PortInUse,
                          self.api._update_port,
                          neutronapi.get_client(self.context),
                          instance, port_uuid, port_req_body)
        update_port_mock.assert_called_once_with(port_uuid, port_req_body)

    @mock.patch.object(client.Client, 'update_port',
        side_effect=exceptions.HostNotCompatibleWithFixedIpsClient())
    def test_update_port_for_instance_fixed_ips_invalid(self,
                                                        update_port_mock):
        port_uuid = uuids.port
        instance = objects.Instance(uuid=uuids.instance)
        port_req_body = {'port': {
                            'id': port_uuid,
                            'mac_address': 'XX:XX:XX:XX:XX:XX',
                            'network_id': uuids.network_id}}

        self.assertRaises(exception.FixedIpInvalidOnHost,
                          self.api._update_port,
                          neutronapi.get_client(self.context),
                          instance, port_uuid, port_req_body)
        update_port_mock.assert_called_once_with(port_uuid, port_req_body)

    @mock.patch.object(client.Client, 'update_port')
    def test_update_port_for_instance_binding_failure(self,
            update_port_mock):
        port_uuid = uuids.port
        instance = objects.Instance(uuid=uuids.instance)
        port_req_body = {'port': {
                            'id': port_uuid,
                            'mac_address': 'XX:XX:XX:XX:XX:XX',
                            'network_id': uuids.network_id}}
        update_port_mock.return_value = {'port': {
            'id': port_uuid,
            'binding:vif_type': model.VIF_TYPE_BINDING_FAILED
        }}

        self.assertRaises(exception.PortBindingFailed,
                          self.api._update_port,
                          neutronapi.get_client(self.context),
                          instance, port_uuid, port_req_body)

    @mock.patch.object(client.Client, 'create_port',
                       side_effect=exceptions.IpAddressInUseClient())
    def test_create_port_minimal_raise_ip_in_use(self, create_port_mock):
        instance = fake_instance.fake_instance_obj(self.context)
        fake_ip = '1.1.1.1'

        self.assertRaises(exception.FixedIpAlreadyInUse,
                          self.api._create_port_minimal,
                          neutronapi.get_client(self.context),
                          instance, uuids.my_netid1, fixed_ip=fake_ip)
        self.assertTrue(create_port_mock.called)

    @mock.patch.object(client.Client, 'create_port',
                       side_effect=exceptions.InvalidIpForNetworkClient())
    def test_create_port_minimal_raise_invalid_ip(self, create_port_mock):
        instance = fake_instance.fake_instance_obj(self.context)
        fake_ip = '1.1.1.1'

        exc = self.assertRaises(exception.InvalidInput,
                                self.api._create_port_minimal,
                                neutronapi.get_client(self.context),
                                instance, uuids.my_netid1, fixed_ip=fake_ip)

        expected_exception_msg = ('Invalid input received: Fixed IP %(ip)s is '
                                  'not a valid ip address for network '
                                  '%(net_id)s.' %
                                  {'ip': fake_ip, 'net_id': uuids.my_netid1})
        self.assertEqual(expected_exception_msg, str(exc))
        self.assertTrue(create_port_mock.called)

    def test_get_network_detail_not_found(self):
        api = neutronapi.API()
        expected_exc = exceptions.NetworkNotFoundClient()
        network_uuid = '02cacbca-7d48-4a2c-8011-43eecf8a9786'
        with mock.patch.object(client.Client, 'show_network',
                               side_effect=expected_exc) as (
            fake_show_network):
            self.assertRaises(exception.NetworkNotFound,
                              api.get,
                              self.context,
                              network_uuid)
            fake_show_network.assert_called_once_with(network_uuid)

    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    @mock.patch('nova.network.neutronv2.api.API.'
                '_refresh_neutron_extensions_cache')
    def test_deallocate_for_instance_uses_delete_helper(self,
                                                        mock_refresh,
                                                        mock_preexisting):
        # setup fake data
        instance = fake_instance.fake_instance_obj(self.context)
        mock_preexisting.return_value = []
        port_data = {'ports': [{'id': uuids.fake}]}
        ports = set([port['id'] for port in port_data.get('ports')])
        api = neutronapi.API()
        # setup mocks
        mock_client = mock.Mock()
        mock_client.list_ports.return_value = port_data
        with test.nested(
            mock.patch.object(neutronapi, 'get_client',
                              return_value=mock_client),
            mock.patch.object(api, '_delete_ports')
        ) as (
            mock_get_client, mock_delete
        ):
            # run the code
            api.deallocate_for_instance(self.context, instance)
            # assert the calls
            mock_client.list_ports.assert_called_once_with(
                device_id=instance.uuid)
            mock_delete.assert_called_once_with(
                mock_client, instance, ports, raise_if_fail=True)

    def _test_delete_ports(self, expect_raise):
        results = [exceptions.NeutronClientException, None]
        mock_client = mock.Mock()
        with mock.patch.object(mock_client, 'delete_port',
                               side_effect=results):
            api = neutronapi.API()
            api._delete_ports(mock_client, {'uuid': 'foo'}, ['port1', 'port2'],
                              raise_if_fail=expect_raise)

    def test_delete_ports_raise(self):
        self.assertRaises(exceptions.NeutronClientException,
                          self._test_delete_ports, True)

    def test_delete_ports_no_raise(self):
        self._test_delete_ports(False)

    def test_delete_ports_never_raise_404(self):
        mock_client = mock.Mock()
        mock_client.delete_port.side_effect = exceptions.PortNotFoundClient
        api = neutronapi.API()
        api._delete_ports(mock_client, {'uuid': 'foo'}, ['port1'],
                          raise_if_fail=True)
        mock_client.delete_port.assert_called_once_with('port1')

    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    def test_deallocate_port_for_instance_fails(self, mock_preexisting):
        mock_preexisting.return_value = []
        mock_client = mock.Mock()
        api = neutronapi.API()
        with test.nested(
            mock.patch.object(neutronapi, 'get_client',
                              return_value=mock_client),
            mock.patch.object(api, '_delete_ports',
                              side_effect=exceptions.Unauthorized),
            mock.patch.object(api, 'get_instance_nw_info')
        ) as (
            get_client, delete_ports, get_nw_info
        ):
            self.assertRaises(exceptions.Unauthorized,
                              api.deallocate_port_for_instance,
                              self.context, instance={'uuid': uuids.fake},
                              port_id=uuids.fake)
        # make sure that we didn't try to reload nw info
        self.assertFalse(get_nw_info.called)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def _test_show_port_exceptions(self, client_exc, expected_nova_exc,
                                   get_client_mock):
        show_port_mock = mock.Mock(side_effect=client_exc)
        get_client_mock.return_value.show_port = show_port_mock
        self.assertRaises(expected_nova_exc, self.api.show_port,
                          self.context, 'fake_port_id')

    def test_show_port_not_found(self):
        self._test_show_port_exceptions(exceptions.PortNotFoundClient,
                                        exception.PortNotFound)

    def test_show_port_forbidden(self):
        self._test_show_port_exceptions(exceptions.Unauthorized,
                                        exception.Forbidden)

    def test_show_port_unknown_exception(self):
        self._test_show_port_exceptions(exceptions.NeutronClientException,
                                        exception.NovaException)

    def test_get_network(self):
        api = neutronapi.API()
        with mock.patch.object(client.Client, 'show_network') as mock_show:
            mock_show.return_value = {
                'network': {'id': uuids.instance, 'name': 'fake-network'}
            }
            net_obj = api.get(self.context, uuids.instance)
            self.assertEqual('fake-network', net_obj.label)
            self.assertEqual('fake-network', net_obj.name)
            self.assertEqual(uuids.instance, net_obj.uuid)

    def test_get_all_networks(self):
        api = neutronapi.API()
        with mock.patch.object(client.Client, 'list_networks') as mock_list:
            mock_list.return_value = {
                'networks': [
                    {'id': uuids.network_1, 'name': 'fake-network1'},
                    {'id': uuids.network_2, 'name': 'fake-network2'},
                    ]}
            net_objs = api.get_all(self.context)
            self.assertIsInstance(net_objs, objects.NetworkList)
            self.assertEqual(2, len(net_objs))
            self.assertEqual((uuids.network_1, 'fake-network1'),
                             (net_objs[0].uuid, net_objs[0].name))
            self.assertEqual((uuids.network_2, 'fake-network2'),
                             (net_objs[1].uuid, net_objs[1].name))

    @mock.patch.object(neutronapi.API, "_refresh_neutron_extensions_cache")
    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_instance_vnic_index(self, mock_get_client,
                                        mock_refresh_extensions):
        api = neutronapi.API()
        api.extensions = set([constants.VNIC_INDEX_EXT])
        mock_client = mock_get_client()
        mock_client.update_port.return_value = 'port'

        instance = {'project_id': '9d049e4b60b64716978ab415e6fbd5c0',
                    'uuid': uuids.fake,
                    'display_name': 'test_instance',
                    'availability_zone': 'nova',
                    'host': 'some_host'}
        instance = objects.Instance(**instance)
        vif = {'id': 'fake-port-id'}
        api.update_instance_vnic_index(self.context, instance, vif, 7)
        port_req_body = {'port': {'vnic_index': 7}}
        mock_client.update_port.assert_called_once_with('fake-port-id',
                                                        port_req_body)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_migration_profile(
        self, get_client_mock):
        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)

        # We pass in a port profile which has a migration attribute and also
        # a second port profile attribute 'fake_profile' this can be
        # an sriov port profile attribute or a pci_slot attribute, but for
        # now we are just using a fake one to show that the code does not
        # remove the portbinding_profile it there is one.
        binding_profile = {'fake_profile': 'fake_data',
                           neutronapi.MIGRATING_ATTR: 'my-dest-host'}
        fake_ports = {'ports': [
                        {'id': 'fake-port-1',
                          neutronapi.BINDING_PROFILE: binding_profile,
                         neutronapi.BINDING_HOST_ID: instance.host}]}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock

        self.api._update_port_binding_for_instance(self.context, instance,
                                                   'my-host')
        # Assert that update_port was called on the port with a
        # different host and also the migration profile from the port is
        # removed since it does not match with the current host.
        update_port_mock.assert_called_once_with(
            'fake-port-1', {'port': {neutronapi.BINDING_HOST_ID: 'my-host',
                                     neutronapi.BINDING_PROFILE: {
                                         'fake_profile': 'fake_data'}}})

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_binding_profile_none(
        self, get_client_mock):
        """Tests _update_port_binding_for_instance when the binding:profile
        value is None.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)

        fake_ports = {'ports': [
                        {'id': uuids.portid,
                         neutronapi.BINDING_PROFILE: None,
                         neutronapi.BINDING_HOST_ID: instance.host}]}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock

        self.api._update_port_binding_for_instance(self.context, instance,
                                                   'my-host')
        # Assert that update_port was called on the port with a
        # different host but with no binding profile.
        update_port_mock.assert_called_once_with(
            uuids.portid, {'port': {neutronapi.BINDING_HOST_ID: 'my-host'}})

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_same_host(self,
                                                         get_client_mock):
        instance = fake_instance.fake_instance_obj(self.context)

        # We test two ports, one with the same host as the host passed in and
        # one where binding:host_id isn't set, so we update that port.
        fake_ports = {'ports': [
                        {'id': 'fake-port-1',
                         neutronapi.BINDING_HOST_ID: instance.host},
                        {'id': 'fake-port-2'}]}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock

        self.api._update_port_binding_for_instance(self.context, instance,
                                                   instance.host)
        # Assert that update_port was only called on the port without a host.
        update_port_mock.assert_called_once_with(
            'fake-port-2',
            {'port': {neutronapi.BINDING_HOST_ID: instance.host}})

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_pci(self,
                                            get_client_mock,
                                            get_pci_device_devspec_mock):

        devspec = mock.Mock()
        devspec.get_tags.return_value = {'physical_network': 'physnet1'}
        get_pci_device_devspec_mock.return_value = devspec

        instance = fake_instance.fake_instance_obj(self.context)
        instance.migration_context = objects.MigrationContext()
        instance.migration_context.old_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0a:00.1',
                                       compute_node_id=1,
                                       request_id='1234567890')])
        instance.migration_context.new_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0b:00.1',
                                       compute_node_id=2,
                                       request_id='1234567890')])
        instance.pci_devices = instance.migration_context.old_pci_devices

        # Validate that non-direct port aren't updated (fake-port-2).
        fake_ports = {'ports': [
                        {'id': 'fake-port-1',
                         'binding:vnic_type': 'direct',
                         neutronapi.BINDING_HOST_ID: 'fake-host-old',
                         neutronapi.BINDING_PROFILE:
                            {'pci_slot': '0000:0a:00.1',
                             'physical_network': 'old_phys_net',
                             'pci_vendor_info': 'old_pci_vendor_info'}},
                        {'id': 'fake-port-2',
                         neutronapi.BINDING_HOST_ID: instance.host}]}
        migration = {'status': 'confirmed'}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock

        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock

        self.api._update_port_binding_for_instance(self.context, instance,
                                                   instance.host, migration)
        # Assert that update_port is called with the binding:profile
        # corresponding to the PCI device specified.
        update_port_mock.assert_called_once_with(
            'fake-port-1',
                {'port':
                    {neutronapi.BINDING_HOST_ID: 'fake-host',
                     neutronapi.BINDING_PROFILE:
                        {'pci_slot': '0000:0b:00.1',
                         'physical_network': 'physnet1',
                         'pci_vendor_info': '1377:0047'}}})

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_pci_fail(self,
                                            get_client_mock,
                                            get_pci_device_devspec_mock):

        devspec = mock.Mock()
        devspec.get_tags.return_value = {'physical_network': 'physnet1'}
        get_pci_device_devspec_mock.return_value = devspec

        instance = fake_instance.fake_instance_obj(self.context)
        instance.migration_context = objects.MigrationContext()
        instance.migration_context.old_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0c:00.1',
                                       compute_node_id=1,
                                       request_id='1234567890')])
        instance.migration_context.new_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0d:00.1',
                                       compute_node_id=2,
                                       request_id='1234567890')])
        instance.pci_devices = instance.migration_context.old_pci_devices

        fake_ports = {'ports': [
                        {'id': 'fake-port-1',
                         'binding:vnic_type': 'direct',
                         neutronapi.BINDING_HOST_ID: 'fake-host-old',
                         neutronapi.BINDING_PROFILE:
                            {'pci_slot': '0000:0a:00.1',
                             'physical_network': 'old_phys_net',
                             'pci_vendor_info': 'old_pci_vendor_info'}}]}
        migration = {'status': 'confirmed'}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock

        # Assert exception is raised if the mapping is wrong.
        self.assertRaises(exception.PortUpdateFailed,
                          self.api._update_port_binding_for_instance,
                          self.context,
                          instance,
                          instance.host,
                          migration)

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_pci_no_migration(self,
                                            get_client_mock,
                                            get_pci_device_devspec_mock):
        self.api._has_port_binding_extension = mock.Mock(return_value=True)

        devspec = mock.Mock()
        devspec.get_tags.return_value = {'physical_network': 'physnet1'}
        get_pci_device_devspec_mock.return_value = devspec

        instance = fake_instance.fake_instance_obj(self.context)
        instance.migration_context = objects.MigrationContext()
        instance.migration_context.old_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0a:00.1',
                                       compute_node_id=1,
                                       request_id='1234567890')])
        instance.migration_context.new_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0b:00.1',
                                       compute_node_id=2,
                                       request_id='1234567890')])
        instance.pci_devices = instance.migration_context.old_pci_devices

        fake_ports = {'ports': [
                        {'id': 'fake-port-1',
                         'binding:vnic_type': 'direct',
                         neutronapi.BINDING_HOST_ID: instance.host,
                         neutronapi.BINDING_PROFILE:
                            {'pci_slot': '0000:0a:00.1',
                             'physical_network': 'phys_net',
                             'pci_vendor_info': 'pci_vendor_info'}}]}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock

        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock

        # Try to update the port binding with no migration object.
        self.api._update_port_binding_for_instance(self.context, instance,
                                                   instance.host)
        # No ports should be updated if the port's pci binding did not change.
        update_port_mock.assert_not_called()

    def test_get_pci_mapping_for_migration(self):
        instance = fake_instance.fake_instance_obj(self.context)
        instance.migration_context = objects.MigrationContext()
        old_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0a:00.1',
                                       compute_node_id=1,
                                       request_id='1234567890')])

        new_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0b:00.1',
                                       compute_node_id=2,
                                       request_id='1234567890')])

        instance.migration_context.old_pci_devices = old_pci_devices
        instance.migration_context.new_pci_devices = new_pci_devices
        instance.pci_devices = instance.migration_context.old_pci_devices
        migration = {'status': 'confirmed'}

        pci_mapping = self.api._get_pci_mapping_for_migration(
            self.context, instance, migration)
        self.assertEqual(
            {old_pci_devices[0].address: new_pci_devices[0]}, pci_mapping)

    def test_get_pci_mapping_for_migration_reverted(self):
        instance = fake_instance.fake_instance_obj(self.context)
        instance.migration_context = objects.MigrationContext()
        old_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0a:00.1',
                                       compute_node_id=1,
                                       request_id='1234567890')])

        new_pci_devices = objects.PciDeviceList(
            objects=[objects.PciDevice(vendor_id='1377',
                                       product_id='0047',
                                       address='0000:0b:00.1',
                                       compute_node_id=2,
                                       request_id='1234567890')])

        instance.migration_context.old_pci_devices = old_pci_devices
        instance.migration_context.new_pci_devices = new_pci_devices
        instance.pci_devices = instance.migration_context.old_pci_devices
        migration = {'status': 'reverted'}

        pci_mapping = self.api._get_pci_mapping_for_migration(
            self.context, instance, migration)
        self.assertEqual(
            {new_pci_devices[0].address: old_pci_devices[0]}, pci_mapping)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_profile_for_migration_teardown_false(
        self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        # We test with an instance host and destination_host where the
        # port will be moving.
        get_ports = {'ports': [
                        {'id': uuids.port_id,
                         neutronapi.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock
        migrate_profile = {neutronapi.MIGRATING_ATTR: 'my-new-host'}
        port_data = {'port':
                        {neutronapi.BINDING_PROFILE: migrate_profile}}

        self.api.setup_networks_on_host(self.context,
                                        instance,
                                        host='my-new-host',
                                        teardown=False)
        update_port_mock.assert_called_once_with(
            uuids.port_id,
            port_data)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_profile_for_migration_teardown_false_none_profile(
        self, get_client_mock):
        """Tests setup_networks_on_host when migrating the port to the
        destination host and the binding:profile is None in the port.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        # We test with an instance host and destination_host where the
        # port will be moving but with binding:profile set to None.
        get_ports = {
            'ports': [
                {'id': uuids.port_id,
                 neutronapi.BINDING_HOST_ID: instance.host,
                 neutronapi.BINDING_PROFILE: None}
            ]
        }
        self.api.list_ports = mock.Mock(return_value=get_ports)
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock
        migrate_profile = {neutronapi.MIGRATING_ATTR: 'my-new-host'}
        port_data = {
            'port': {
                neutronapi.BINDING_PROFILE: migrate_profile
            }
        }
        self.api.setup_networks_on_host(
            self.context, instance, host='my-new-host', teardown=False)
        update_port_mock.assert_called_once_with(
            uuids.port_id,
            port_data)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test__setup_migration_port_profile_called_on_teardown_false(
        self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        port_id = uuids.port_id
        get_ports = {'ports': [
                        {'id': port_id,
                         neutronapi.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        self.api._setup_migration_port_profile = mock.Mock()
        self.api.setup_networks_on_host(self.context,
                                        instance,
                                        host='my-new-host',
                                        teardown=False)
        self.api._setup_migration_port_profile.assert_called_once_with(
            self.context, instance, 'my-new-host',
            mock.ANY, get_ports['ports'])

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test__setup_migration_port_profile_not_called_with_host_match(
        self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        get_ports = {'ports': [
                        {'id': uuids.port_id,
                         neutronapi.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        self.api._setup_migration_port_profile = mock.Mock()
        self.api._clear_migration_port_profile = mock.Mock()
        self.api.setup_networks_on_host(self.context,
                                        instance,
                                        host=instance.host,
                                        teardown=False)
        self.api._setup_migration_port_profile.assert_not_called()
        self.api._clear_migration_port_profile.assert_not_called()

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_profile_for_migration_teardown_true_with_profile(
        self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        migrate_profile = {neutronapi.MIGRATING_ATTR: instance.host}
        # Pass a port with an migration porfile attribute.
        port_id = uuids.port_id
        get_ports = {'ports': [
                        {'id': port_id,
                         neutronapi.BINDING_PROFILE: migrate_profile,
                         neutronapi.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock
        self.api.setup_networks_on_host(self.context,
                                        instance,
                                        host=instance.host,
                                        teardown=True)
        update_port_mock.assert_called_once_with(
            port_id, {'port': {neutronapi.BINDING_PROFILE: migrate_profile}})

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_profile_for_migration_teardown_true_no_profile(
        self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        # Pass a port without any migration porfile attribute.
        get_ports = {'ports': [
                        {'id': uuids.port_id,
                         neutronapi.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock
        self.api.setup_networks_on_host(self.context,
                                        instance,
                                        host=instance.host,
                                        teardown=True)
        update_port_mock.assert_not_called()

    def test__update_port_with_migration_profile_raise_exception(self):

        instance = fake_instance.fake_instance_obj(self.context)
        port_id = uuids.port_id
        migrate_profile = {'fake-attribute': 'my-new-host'}
        port_profile = {'port': {neutronapi.BINDING_PROFILE: migrate_profile}}
        update_port_mock = mock.Mock(side_effect=test.TestingException())
        admin_client = mock.Mock(update_port=update_port_mock)
        self.assertRaises(test.TestingException,
                          self.api._update_port_with_migration_profile,
                          instance, port_id, migrate_profile, admin_client)
        update_port_mock.assert_called_once_with(port_id, port_profile)

    @mock.patch('nova.objects.Instance.get_network_info')
    def test_get_preexisting_port_ids(self, mock_get_nw_info):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_get_nw_info.return_value = [model.VIF(
            id='1', preserve_on_delete=False), model.VIF(
            id='2', preserve_on_delete=True), model.VIF(
            id='3', preserve_on_delete=True)]
        result = self.api._get_preexisting_port_ids(instance)
        self.assertEqual(['2', '3'], result, "Invalid preexisting ports")

    def _test_unbind_ports_get_client(self, mock_neutron):
        mock_ctx = mock.Mock(is_admin=False)
        ports = ["1", "2", "3"]

        self.api._unbind_ports(mock_ctx, ports, mock_neutron)

        get_client_calls = []
        get_client_calls.append(mock.call(mock_ctx, admin=True))

        self.assertEqual(1, mock_neutron.call_count)
        mock_neutron.assert_has_calls(get_client_calls, True)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_unbind_ports_get_client_binding_extension(self,
                                                       mock_neutron):
        self._test_unbind_ports_get_client(mock_neutron)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_unbind_ports_get_client(self, mock_neutron):
        self._test_unbind_ports_get_client(mock_neutron)

    @mock.patch('nova.network.neutronv2.api.API._show_port')
    def _test_unbind_ports(self, mock_neutron, mock_show):
        mock_client = mock.Mock()
        mock_update_port = mock.Mock()
        mock_client.update_port = mock_update_port
        mock_ctx = mock.Mock(is_admin=False)
        ports = ["1", "2", "3"]
        mock_show.side_effect = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        api = neutronapi.API()
        api._unbind_ports(mock_ctx, ports, mock_neutron, mock_client)

        body = {'port': {'device_id': '', 'device_owner': ''}}
        body['port'][neutronapi.BINDING_HOST_ID] = None
        body['port'][neutronapi.BINDING_PROFILE] = {}
        update_port_calls = []
        for p in ports:
            update_port_calls.append(mock.call(p, body))

        self.assertEqual(3, mock_update_port.call_count)
        mock_update_port.assert_has_calls(update_port_calls)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_unbind_ports_binding_ext(self, mock_neutron):
        self._test_unbind_ports(mock_neutron)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_unbind_ports(self, mock_neutron):
        self._test_unbind_ports(mock_neutron)

    def test_unbind_ports_no_port_ids(self):
        # Tests that None entries in the ports list are filtered out.
        mock_client = mock.Mock()
        mock_update_port = mock.Mock()
        mock_client.update_port = mock_update_port
        mock_ctx = mock.Mock(is_admin=False)

        api = neutronapi.API()
        api._unbind_ports(mock_ctx, [None], mock_client, mock_client)
        self.assertFalse(mock_update_port.called)

    @mock.patch('nova.network.neutronv2.api.API.get_instance_nw_info')
    @mock.patch('nova.network.neutronv2.api.excutils')
    @mock.patch('nova.network.neutronv2.api.API._delete_ports')
    @mock.patch('nova.network.neutronv2.api.API.'
                '_check_external_network_attach')
    @mock.patch('nova.network.neutronv2.api.LOG')
    @mock.patch('nova.network.neutronv2.api.API._unbind_ports')
    @mock.patch('nova.network.neutronv2.api.API.'
                '_populate_neutron_extension_values')
    @mock.patch('nova.network.neutronv2.api.API._get_available_networks')
    @mock.patch('nova.network.neutronv2.api.get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_allocate_for_instance_unbind(self, mock_vif,
                                          mock_ntrn,
                                          mock_avail_nets,
                                          mock_ext_vals,
                                          mock_unbind,
                                          mock_log,
                                          mock_cena,
                                          mock_del_ports,
                                          mock_exeu,
                                          mock_giwn):
        mock_nc = mock.Mock()

        def show_port(port_id):
            return {'port': {'network_id': 'net-1', 'id': port_id,
                             'mac_address': 'fakemac',
                             'tenant_id': 'proj-1'}}
        mock_nc.show_port = show_port

        mock_ntrn.return_value = mock_nc

        def update_port(port_id, body):
            if port_id == uuids.fail_port_id:
                raise Exception
            return {"port": {'mac_address': 'fakemac',
                             'id': port_id}}
        mock_nc.update_port.side_effect = update_port
        mock_inst = mock.Mock(project_id="proj-1",
                              availability_zone='zone-1',
                              uuid='inst-1')

        nw_req = objects.NetworkRequestList(
            objects = [objects.NetworkRequest(port_id=uuids.portid_1),
                       objects.NetworkRequest(port_id=uuids.portid_2),
                       objects.NetworkRequest(port_id=uuids.fail_port_id)])
        mock_avail_nets.return_value = [{'id': 'net-1',
                                         'subnets': ['subnet1']}]

        self.api.allocate_for_instance(mock.sentinel.ctx, mock_inst, False,
                                       requested_networks=nw_req)

        mock_unbind.assert_called_once_with(mock.sentinel.ctx,
                                            [uuids.portid_1, uuids.portid_2],
                                            mock.ANY,
                                            mock.ANY)

    @mock.patch('nova.network.neutronv2.api._filter_hypervisor_macs')
    @mock.patch('nova.network.neutronv2.api.API._validate_requested_port_ids')
    @mock.patch('nova.network.neutronv2.api.API._get_available_networks')
    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_allocate_port_for_instance_no_networks(self,
                                                    mock_getclient,
                                                    mock_avail_nets,
                                                    mock_validate_port_ids,
                                                    mock_filter_macs):
        """Tests that if no networks are requested and no networks are
        available, we fail with InterfaceAttachFailedNoNetwork.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        mock_validate_port_ids.return_value = ({}, [])
        mock_filter_macs.return_value = None
        mock_avail_nets.return_value = []
        api = neutronapi.API()
        ex = self.assertRaises(exception.InterfaceAttachFailedNoNetwork,
                               api.allocate_port_for_instance,
                               self.context, instance, port_id=None)
        self.assertEqual(
            "No specific network was requested and none are available for "
            "project 'fake-project'.", six.text_type(ex))

    @mock.patch.object(neutronapi.API, 'allocate_for_instance')
    def test_allocate_port_for_instance_with_tag(self, mock_allocate):
        instance = fake_instance.fake_instance_obj(self.context)
        api = neutronapi.API()
        api.allocate_port_for_instance(self.context, instance, None,
                                       network_id=None, requested_ip=None,
                                       bind_host_id=None, tag='foo')
        req_nets_in_call = mock_allocate.call_args[1]['requested_networks']
        self.assertEqual('foo', req_nets_in_call.objects[0].tag)

    @mock.patch('nova.objects.network_request.utils')
    @mock.patch('nova.network.neutronv2.api.LOG')
    @mock.patch('nova.network.neutronv2.api.base_api')
    @mock.patch('nova.network.neutronv2.api.API._delete_ports')
    @mock.patch('nova.network.neutronv2.api.API._unbind_ports')
    @mock.patch('nova.network.neutronv2.api.API._get_preexisting_port_ids')
    @mock.patch('nova.network.neutronv2.api.get_client')
    @mock.patch.object(objects.VirtualInterface, 'delete_by_instance_uuid')
    def test_preexisting_deallocate_for_instance(self, mock_delete_vifs,
                                                 mock_ntrn,
                                                 mock_gppids,
                                                 mock_unbind,
                                                 mock_deletep,
                                                 mock_baseapi,
                                                 mock_log,
                                                 req_utils):
        req_utils.is_neutron.return_value = True
        mock_inst = mock.Mock(project_id="proj-1",
                              availability_zone='zone-1',
                              uuid='inst-1')
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_ports.return_value = {'ports': [
            {'id': uuids.portid_1}, {'id': uuids.portid_2},
            {'id': uuids.portid_3}
        ]}
        nw_req = objects.NetworkRequestList(
            objects = [objects.NetworkRequest(network_id='net-1',
                                              address='192.168.0.3',
                                              port_id=uuids.portid_1,
                                              pci_request_id=uuids.pci_1)])
        mock_gppids.return_value = [uuids.portid_3]

        self.api.deallocate_for_instance(mock.sentinel.ctx, mock_inst,
                                    requested_networks=nw_req)

        mock_unbind.assert_called_once_with(mock.sentinel.ctx,
                                            set([uuids.portid_1,
                                                 uuids.portid_3]),
                                            mock.ANY)
        mock_deletep.assert_called_once_with(mock_nc,
                                             mock_inst,
                                             set([uuids.portid_2]),
                                             raise_if_fail=True)
        mock_delete_vifs.assert_called_once_with(mock.sentinel.ctx, 'inst-1')

    @mock.patch('nova.network.neutronv2.api.API._delete_nic_metadata')
    @mock.patch('nova.network.neutronv2.api.API.get_instance_nw_info')
    @mock.patch('nova.network.neutronv2.api.API._unbind_ports')
    @mock.patch('nova.objects.Instance.get_network_info')
    @mock.patch('nova.network.neutronv2.api.get_client')
    @mock.patch.object(objects.VirtualInterface, 'get_by_uuid')
    def test_preexisting_deallocate_port_for_instance(self,
                                                      mock_get_vif_by_uuid,
                                                      mock_ntrn,
                                                      mock_inst_get_nwinfo,
                                                      mock_unbind,
                                                      mock_netinfo,
                                                      mock_del_nic_meta):
        mock_inst = mock.Mock(project_id="proj-1",
                              availability_zone='zone-1',
                              uuid='inst-1')
        mock_inst.get_network_info.return_value = [model.VIF(
            id='1', preserve_on_delete=False), model.VIF(
            id='2', preserve_on_delete=True), model.VIF(
            id='3', preserve_on_delete=True)]
        mock_client = mock.Mock()
        mock_ntrn.return_value = mock_client
        vif = objects.VirtualInterface()
        vif.tag = 'foo'
        vif.destroy = mock.MagicMock()
        mock_get_vif_by_uuid.return_value = vif
        self.api.deallocate_port_for_instance(mock.sentinel.ctx,
                                              mock_inst, '2')
        mock_unbind.assert_called_once_with(mock.sentinel.ctx, ['2'],
                                            mock_client)
        mock_get_vif_by_uuid.assert_called_once_with(mock.sentinel.ctx, '2')
        mock_del_nic_meta.assert_called_once_with(mock_inst, vif)
        vif.destroy.assert_called_once_with()

    def test_delete_nic_metadata(self):
        vif = objects.VirtualInterface(address='aa:bb:cc:dd:ee:ff', tag='foo')
        instance = fake_instance.fake_instance_obj(self.context)
        instance.device_metadata = objects.InstanceDeviceMetadata(
            devices=[objects.NetworkInterfaceMetadata(
                mac='aa:bb:cc:dd:ee:ff', tag='foo')])
        instance.save = mock.Mock()
        self.api._delete_nic_metadata(instance, vif)
        self.assertEqual(0, len(instance.device_metadata.devices))
        instance.save.assert_called_once_with()

    @mock.patch('nova.network.neutronv2.api.API.'
                '_check_external_network_attach')
    @mock.patch('nova.network.neutronv2.api.API.'
                '_populate_neutron_extension_values')
    @mock.patch('nova.network.neutronv2.api.API._get_available_networks')
    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_port_binding_failed_created_port(self, mock_ntrn,
                                          mock_avail_nets,
                                          mock_ext_vals,
                                          mock_cena):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_inst = mock.Mock(project_id="proj-1",
                              availability_zone='zone-1',
                              uuid=uuids.inst_1)
        mock_avail_nets.return_value = [{'id': 'net-1',
                                         'subnets': ['subnet1']}]
        mock_nc.create_port.return_value = {'port': {'id': uuids.portid_1}}
        port_response = {'port': {'id': uuids.portid_1,
                            'tenant_id': mock_inst.project_id,
                            'binding:vif_type': 'binding_failed'}}
        mock_nc.update_port.return_value = port_response

        self.assertRaises(exception.PortBindingFailed,
                          self.api.allocate_for_instance,
                          mock.sentinel.ctx,
                          mock_inst, False, None)
        mock_nc.delete_port.assert_called_once_with(uuids.portid_1)

    @mock.patch('nova.network.neutronv2.api.API._show_port')
    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_port_binding_failed_with_request(self, mock_ntrn,
                                          mock_show_port):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_inst = mock.Mock(project_id="proj-1",
                              availability_zone='zone-1',
                              uuid='inst-1')
        mock_show_port.return_value = {
                            'id': uuids.portid_1,
                            'tenant_id': mock_inst.project_id,
                            'binding:vif_type': 'binding_failed'}
        nw_req = objects.NetworkRequestList(
            objects = [objects.NetworkRequest(port_id=uuids.portid_1)])

        self.assertRaises(exception.PortBindingFailed,
                          self.api.allocate_for_instance,
                          mock.sentinel.ctx, mock_inst, False,
                          requested_networks=nw_req)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_get_floating_ip_by_address_not_found_neutron_not_found(self,
                                                                mock_ntrn):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_floatingips.side_effect = exceptions.NotFound()
        address = '172.24.4.227'
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          self.api.get_floating_ip_by_address,
                          self.context, address)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_get_floating_ip_by_address_not_found_neutron_raises_non404(self,
                                                                mock_ntrn):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_floatingips.side_effect = exceptions.InternalServerError()
        address = '172.24.4.227'
        self.assertRaises(exceptions.InternalServerError,
                          self.api.get_floating_ip_by_address,
                          self.context, address)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_get_floating_ips_by_project_not_found(self, mock_ntrn):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_floatingips.side_effect = exceptions.NotFound()
        fips = self.api.get_floating_ips_by_project(self.context)
        self.assertEqual([], fips)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_get_floating_ips_by_project_not_found_legacy(self, mock_ntrn):
        # FIXME(danms): Remove this test along with the code path it tests
        # when bug 1513879 is fixed.
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        # neutronclient doesn't raise NotFound in this scenario, it raises a
        # NeutronClientException with status_code=404
        notfound = exceptions.NeutronClientException(status_code=404)
        mock_nc.list_floatingips.side_effect = notfound
        fips = self.api.get_floating_ips_by_project(self.context)
        self.assertEqual([], fips)

    @mock.patch('nova.network.neutronv2.api.get_client')
    def test_get_floating_ips_by_project_raises_non404(self, mock_ntrn):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_floatingips.side_effect = exceptions.InternalServerError()
        self.assertRaises(exceptions.InternalServerError,
                          self.api.get_floating_ips_by_project,
                          self.context)

    @mock.patch('nova.network.neutronv2.api.API._show_port')
    def test_unbind_ports_reset_dns_name(self, mock_show):
        neutron = mock.Mock()
        port_client = mock.Mock()
        self.api.extensions = [constants.DNS_INTEGRATION]
        ports = [uuids.port_id]
        mock_show.return_value = {'id': uuids.port}
        self.api._unbind_ports(self.context, ports, neutron, port_client)
        port_req_body = {'port': {'binding:host_id': None,
                                  'binding:profile': {},
                                  'device_id': '',
                                  'device_owner': '',
                                  'dns_name': ''}}
        port_client.update_port.assert_called_once_with(
            uuids.port_id, port_req_body)

    @mock.patch('nova.network.neutronv2.api.API._show_port')
    def test_unbind_ports_reset_binding_profile(self, mock_show):
        neutron = mock.Mock()
        port_client = mock.Mock()
        ports = [uuids.port_id]
        mock_show.return_value = {
            'id': uuids.port,
            'binding:profile': {'pci_vendor_info': '1377:0047',
                                'pci_slot': '0000:0a:00.1',
                                'physical_network': 'phynet1',
                                'capabilities': ['switchdev']}
            }
        self.api._unbind_ports(self.context, ports, neutron, port_client)
        port_req_body = {'port': {'binding:host_id': None,
                                  'binding:profile':
                                    {'physical_network': 'phynet1',
                                     'capabilities': ['switchdev']},
                                  'device_id': '',
                                  'device_owner': ''}
                        }
        port_client.update_port.assert_called_once_with(
            uuids.port_id, port_req_body)

    def test_make_floating_ip_obj(self):
        self._test_make_floating_ip_obj()

    def test_make_floating_ip_obj_pool_id(self):
        self._test_make_floating_ip_obj(set_pool_name=False)

    def test_make_floating_ip_obj_no_fixed_ip_address(self):
        self._test_make_floating_ip_obj(set_fixed_ip=False)

    def test_make_floating_ip_obj_no_port_id(self):
        self._test_make_floating_ip_obj(set_port=False)

    def _test_make_floating_ip_obj(self, set_port=True, set_fixed_ip=True,
                                   set_pool_name=True):
        net_id = '6cd58996-001a-11e6-86aa-5e5517507c66'
        float_id = 'ea474936-0016-11e6-86aa-5e5517507c66'
        tenant_id = '310b1db6-0017-11e6-86aa-5e5517507c66'
        port_id = '40cfc710-0017-11e6-86aa-5e5517507c66' if set_port else None
        device_id = '6b892334-0017-11e6-86aa-5e5517507c66'
        floating_ip_address = '10.0.0.1'
        fixed_ip_address = '192.168.100.100' if set_fixed_ip else None
        pool_name = 'my_pool' if set_pool_name else None
        pool_id = 'd7f7150e-001b-11e6-86aa-5e5517507c66'

        fip = {'id': float_id,
               'floating_ip_address': floating_ip_address,
               'tenant_id': tenant_id,
               'port_id': port_id,
               'fixed_ip_address': fixed_ip_address,
               'floating_network_id': net_id
              }

        pool_dict = {net_id: {'name': pool_name, 'id': pool_id}}

        port_dict = {port_id: {'device_id': device_id}}

        actual_obj = self.api._make_floating_ip_obj(self.context, fip,
                                                    pool_dict, port_dict)

        expected_pool = pool_name if set_pool_name else pool_id

        if set_fixed_ip:
            if set_port:
                expected_fixed = objects.FixedIP(address=fixed_ip_address,
                                                 instance_uuid=device_id)
            else:
                expected_fixed = objects.FixedIP(address=fixed_ip_address)
        else:
            expected_fixed = None

        if set_port:
            expected_instance = objects.Instance(context=context,
                                                 uuid=device_id)
        else:
            expected_instance = None

        expected_floating = objects.floating_ip.NeutronFloatingIP(
            id=float_id, address=floating_ip_address, pool=expected_pool,
            project_id=tenant_id, fixed_ip_id=port_id,
            fixed_ip=expected_fixed, instance=expected_instance)

        self.assertEqual(expected_floating.obj_to_primitive(),
                         actual_obj.obj_to_primitive())

    @mock.patch('nova.network.neutronv2.api.API.'
                '_populate_neutron_extension_values')
    @mock.patch('nova.network.neutronv2.api.API._update_port',
                # called twice, fails on the 2nd call and triggers the cleanup
                side_effect=(mock.MagicMock(),
                             exception.PortInUse(
                                 port_id=uuids.created_port_id)))
    @mock.patch.object(objects.VirtualInterface, 'create')
    @mock.patch.object(objects.VirtualInterface, 'destroy')
    @mock.patch('nova.network.neutronv2.api.API._unbind_ports')
    @mock.patch('nova.network.neutronv2.api.API._delete_ports')
    def test_update_ports_for_instance_fails_rollback_ports_and_vifs(self,
            mock_delete_ports,
            mock_unbind_ports,
            mock_vif_destroy,
            mock_vif_create,
            mock_update_port,
            mock_populate_ext_values):
        """Makes sure we rollback ports and VIFs if we fail updating ports"""
        instance = fake_instance.fake_instance_obj(self.context)
        ntrn = mock.Mock(spec='neutronclient.v2_0.client.Client')
        # we have two requests, one with a preexisting port and one where nova
        # created the port (on the same network)
        requests_and_created_ports = [
            (objects.NetworkRequest(network_id=uuids.network_id,
                                    port_id=uuids.preexisting_port_id),
             None),  # None means Nova didn't create this port
            (objects.NetworkRequest(network_id=uuids.network_id,
                                    port_id=uuids.created_port_id),
             uuids.created_port_id),
        ]
        network = {'id': uuids.network_id}
        nets = {uuids.network_id: network}
        self.assertRaises(exception.PortInUse,
                          self.api._update_ports_for_instance,
                          self.context, instance, ntrn, ntrn,
                          requests_and_created_ports, nets, bind_host_id=None,
                          available_macs=None, requested_ports_dict=None)
        # assert the calls
        mock_update_port.assert_has_calls([
            mock.call(ntrn, instance, uuids.preexisting_port_id, mock.ANY),
            mock.call(ntrn, instance, uuids.created_port_id, mock.ANY)
        ])
        # we only got to create one vif since the 2nd _update_port call fails
        mock_vif_create.assert_called_once_with()
        # we only destroy one vif since we only created one
        mock_vif_destroy.assert_called_once_with()
        # we unbind the pre-existing port
        mock_unbind_ports.assert_called_once_with(
            self.context, [uuids.preexisting_port_id], ntrn, ntrn)
        # we delete the created port
        mock_delete_ports.assert_called_once_with(
            ntrn, instance, [uuids.created_port_id])

    @mock.patch('nova.network.neutronv2.api.API._get_floating_ip_by_address',
                return_value={"port_id": "1"})
    @mock.patch('nova.network.neutronv2.api.API._show_port',
                side_effect=exception.PortNotFound(port_id='1'))
    def test_get_instance_id_by_floating_address_port_not_found(self,
                                                                mock_show,
                                                                mock_get):
        api = neutronapi.API()
        fip = api.get_instance_id_by_floating_address(self.context,
                                                      '172.24.4.227')
        self.assertIsNone(fip)

    @mock.patch('nova.network.neutronv2.api.API._show_port',
                side_effect=exception.PortNotFound(port_id=uuids.port))
    @mock.patch.object(neutronapi.LOG, 'exception')
    def test_unbind_ports_port_show_portnotfound(self, mock_log, mock_show):
        api = neutronapi.API()
        neutron_client = mock.Mock()
        mock_show.return_value = {'id': uuids.port}
        api._unbind_ports(self.context, [uuids.port_id],
                          neutron_client, neutron_client)
        mock_show.assert_called_once_with(
            mock.ANY, uuids.port_id,
            fields='binding:profile',
            neutron_client=mock.ANY)
        mock_log.assert_not_called()

    @mock.patch('nova.network.neutronv2.api.API._show_port',
                side_effect=Exception)
    @mock.patch.object(neutronapi.LOG, 'exception')
    def test_unbind_ports_port_show_unexpected_error(self,
                                                     mock_log,
                                                     mock_show):
        api = neutronapi.API()
        neutron_client = mock.Mock()
        mock_show.return_value = {'id': uuids.port}
        api._unbind_ports(self.context, [uuids.port_id],
                          neutron_client, neutron_client)
        neutron_client.update_port.assert_called_once_with(
            uuids.port_id, {'port': {
                'device_id': '', 'device_owner': '',
                'binding:profile': {}, 'binding:host_id': None}})
        self.assertTrue(mock_log.called)

    @mock.patch('nova.network.neutronv2.api.API._show_port')
    @mock.patch.object(neutronapi.LOG, 'exception')
    def test_unbind_ports_portnotfound(self, mock_log, mock_show):
        api = neutronapi.API()
        neutron_client = mock.Mock()
        neutron_client.update_port = mock.Mock(
            side_effect=exceptions.PortNotFoundClient)
        mock_show.return_value = {'id': uuids.port}
        api._unbind_ports(self.context, [uuids.port_id],
                          neutron_client, neutron_client)
        neutron_client.update_port.assert_called_once_with(
            uuids.port_id, {'port': {
                'device_id': '', 'device_owner': '',
                'binding:profile': {}, 'binding:host_id': None}})
        mock_log.assert_not_called()

    @mock.patch('nova.network.neutronv2.api.API._show_port')
    @mock.patch.object(neutronapi.LOG, 'exception')
    def test_unbind_ports_unexpected_error(self, mock_log, mock_show):
        api = neutronapi.API()
        neutron_client = mock.Mock()
        neutron_client.update_port = mock.Mock(
            side_effect=test.TestingException)
        mock_show.return_value = {'id': uuids.port}
        api._unbind_ports(self.context, [uuids.port_id],
                          neutron_client, neutron_client)
        neutron_client.update_port.assert_called_once_with(
            uuids.port_id, {'port': {
                'device_id': '', 'device_owner': '',
                'binding:profile': {}, 'binding:host_id': None}})
        self.assertTrue(mock_log.called)

    @mock.patch.object(neutronapi, 'get_client')
    def test_create_pci_requests_for_sriov_ports_no_allocate(self, getclient):
        """Tests that create_pci_requests_for_sriov_ports is a noop if
        networks are specifically requested to not be allocated.
        """
        requested_networks = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id=net_req_obj.NETWORK_ID_NONE)
        ])
        pci_requests = objects.InstancePCIRequests()
        api = neutronapi.API()
        api.create_pci_requests_for_sriov_ports(
            self.context, pci_requests, requested_networks)
        self.assertFalse(getclient.called)

    @mock.patch.object(neutronapi, 'get_client')
    def test_associate_floating_ip_conflict(self, mock_get_client):
        """Tests that if Neutron raises a Conflict we handle it and re-raise
        as a nova-specific exception.
        """
        mock_get_client.return_value.update_floatingip.side_effect = (
            exceptions.Conflict(
                "Cannot associate floating IP 172.24.5.15 "
                "(60a8f00b-4404-4518-ad66-00448a155904) with port "
                "95ee1ffb-6d41-447d-a90e-b6ce5d9c92fa using fixed IP "
                "10.1.0.9, as that fixed IP already has a floating IP on "
                "external network bdcda645-f612-40ab-a956-0d95af42cf7c.")
        )
        with test.nested(
            mock.patch.object(
                self.api, '_get_port_id_by_fixed_address',
                return_value='95ee1ffb-6d41-447d-a90e-b6ce5d9c92fa'),
            mock.patch.object(
                self.api, '_get_floating_ip_by_address',
                return_value={'id': uuids.floating_ip_id})
        ) as (
            _get_floating_ip_by_address, _get_port_id_by_fixed_address
        ):
            instance = fake_instance.fake_instance_obj(
                self.context, uuid='2a2200ec-02fe-484e-885b-9bae7b21ecba')
            self.assertRaises(exception.FloatingIpAssociateFailed,
                              self.api.associate_floating_ip,
                              self.context, instance,
                              '172.24.5.15', '10.1.0.9')


class TestNeutronv2ModuleMethods(test.NoDBTestCase):

    def test_gather_port_ids_and_networks_wrong_params(self):
        api = neutronapi.API()

        # Test with networks not None and port_ids is None
        self.assertRaises(exception.NovaException,
                          api._gather_port_ids_and_networks,
                          'fake_context', 'fake_instance',
                          [{'network': {'name': 'foo'}}], None)

        # Test with networks is None and port_ids not None
        self.assertRaises(exception.NovaException,
                          api._gather_port_ids_and_networks,
                          'fake_context', 'fake_instance',
                          None, ['list', 'of', 'port_ids'])

    def test_ensure_requested_network_ordering_no_preference_ids(self):
        l = [1, 2, 3]

        neutronapi._ensure_requested_network_ordering(
            lambda x: x,
            l,
            None)

    def test_ensure_requested_network_ordering_no_preference_hashes(self):
        l = [{'id': 3}, {'id': 1}, {'id': 2}]

        neutronapi._ensure_requested_network_ordering(
            lambda x: x['id'],
            l,
            None)

        self.assertEqual(l, [{'id': 3}, {'id': 1}, {'id': 2}])

    def test_ensure_requested_network_ordering_with_preference(self):
        l = [{'id': 3}, {'id': 1}, {'id': 2}]

        neutronapi._ensure_requested_network_ordering(
            lambda x: x['id'],
            l,
            [1, 2, 3])

        self.assertEqual(l, [{'id': 1}, {'id': 2}, {'id': 3}])


class TestNeutronv2Portbinding(TestNeutronv2Base):

    def test_allocate_for_instance_portbinding(self):
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(
            self.moxed_client)
        self._allocate_for_instance(1,
                                    bind_host_id=self.instance.get('host'))

    def test_populate_neutron_extension_values_binding(self):
        api = neutronapi.API()
        neutronapi.get_client(mox.IgnoreArg()).AndReturn(
                self.moxed_client)
        self.moxed_client.list_extensions().AndReturn(
            {'extensions': []})
        self.mox.ReplayAll()
        host_id = 'my_host_id'
        instance = {'host': host_id}
        port_req_body = {'port': {}}
        api._populate_neutron_extension_values(self.context, instance,
                                               None, port_req_body,
                                               bind_host_id=host_id)
        self.assertEqual(host_id,
                         port_req_body['port'][neutronapi.BINDING_HOST_ID])
        self.assertFalse(port_req_body['port'].get(neutronapi.BINDING_PROFILE))

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_populate_neutron_extension_values_binding_sriov(self,
                                         mock_get_instance_pci_devs,
                                         mock_get_pci_device_devspec):
        api = neutronapi.API()
        host_id = 'my_host_id'
        instance = {'host': host_id}
        port_req_body = {'port': {}}
        pci_req_id = 'my_req_id'
        pci_dev = {'vendor_id': '1377',
                   'product_id': '0047',
                   'address': '0000:0a:00.1',
                  }
        PciDevice = collections.namedtuple('PciDevice',
                               ['vendor_id', 'product_id', 'address'])
        mydev = PciDevice(**pci_dev)
        profile = {'pci_vendor_info': '1377:0047',
                   'pci_slot': '0000:0a:00.1',
                   'physical_network': 'phynet1',
                  }

        mock_get_instance_pci_devs.return_value = [mydev]
        devspec = mock.Mock()
        devspec.get_tags.return_value = {'physical_network': 'phynet1'}
        mock_get_pci_device_devspec.return_value = devspec
        api._populate_neutron_binding_profile(instance,
                                              pci_req_id, port_req_body)

        self.assertEqual(profile,
                         port_req_body['port'][neutronapi.BINDING_PROFILE])

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_populate_neutron_extension_values_binding_sriov_with_cap(self,
                                         mock_get_instance_pci_devs,
                                         mock_get_pci_device_devspec):
        api = neutronapi.API()
        host_id = 'my_host_id'
        instance = {'host': host_id}
        port_req_body = {'port': {
                             neutronapi.BINDING_PROFILE: {
                                'capabilities': ['switchdev']}}}
        pci_req_id = 'my_req_id'
        pci_dev = {'vendor_id': '1377',
                   'product_id': '0047',
                   'address': '0000:0a:00.1',
                  }
        PciDevice = collections.namedtuple('PciDevice',
                               ['vendor_id', 'product_id', 'address'])
        mydev = PciDevice(**pci_dev)
        profile = {'pci_vendor_info': '1377:0047',
                   'pci_slot': '0000:0a:00.1',
                   'physical_network': 'phynet1',
                   'capabilities': ['switchdev'],
                  }

        mock_get_instance_pci_devs.return_value = [mydev]
        devspec = mock.Mock()
        devspec.get_tags.return_value = {'physical_network': 'phynet1'}
        mock_get_pci_device_devspec.return_value = devspec
        api._populate_neutron_binding_profile(instance,
                                              pci_req_id, port_req_body)

        self.assertEqual(profile,
                         port_req_body['port'][neutronapi.BINDING_PROFILE])

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_populate_neutron_extension_values_binding_sriov_fail(
        self, mock_get_instance_pci_devs, mock_get_pci_device_devspec):
        api = neutronapi.API()
        host_id = 'my_host_id'
        instance = {'host': host_id}
        port_req_body = {'port': {}}
        pci_req_id = 'my_req_id'
        pci_objs = [objects.PciDevice(vendor_id='1377',
                                      product_id='0047',
                                      address='0000:0a:00.1',
                                      compute_node_id=1,
                                      request_id='1234567890')]

        mock_get_instance_pci_devs.return_value = pci_objs
        mock_get_pci_device_devspec.return_value = None

        self.assertRaises(
            exception.PciDeviceNotFound, api._populate_neutron_binding_profile,
            instance, pci_req_id, port_req_body)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_pci_parse_whitelist_called_once(self,
                                             mock_get_instance_pci_devs):
        white_list = [
            '{"address":"0000:0a:00.1","physical_network":"default"}']
        cfg.CONF.set_override('passthrough_whitelist', white_list, 'pci')

        api = neutronapi.API()
        host_id = 'my_host_id'
        instance = {'host': host_id}
        pci_req_id = 'my_req_id'
        port_req_body = {'port': {}}
        pci_dev = {'vendor_id': '1377',
                   'product_id': '0047',
                   'address': '0000:0a:00.1',
                  }

        whitelist = pci_whitelist.Whitelist(CONF.pci.passthrough_whitelist)
        with mock.patch.object(pci_whitelist.Whitelist,
                '_parse_white_list_from_config',
                wraps=whitelist._parse_white_list_from_config
                ) as mock_parse_whitelist:
            for i in range(2):
                mydev = objects.PciDevice.create(None, pci_dev)
                mock_get_instance_pci_devs.return_value = [mydev]
                api._populate_neutron_binding_profile(instance,
                                                  pci_req_id, port_req_body)
                self.assertEqual(0, mock_parse_whitelist.call_count)

    def _populate_pci_mac_address_fakes(self):
        instance = fake_instance.fake_instance_obj(self.context)
        pci_dev = {'vendor_id': '1377',
                   'product_id': '0047',
                   'address': '0000:0a:00.1',
                   'dev_type': 'type-PF'}
        pf = objects.PciDevice()
        vf = objects.PciDevice()
        pf.update_device(pci_dev)

        pci_dev['dev_type'] = 'type-VF'
        vf.update_device(pci_dev)
        return instance, pf, vf

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    @mock.patch.object(pci_utils, 'get_mac_by_pci_address')
    def test_populate_pci_mac_address_pf(self, mock_get_mac_by_pci_address,
                                         mock_get_instance_pci_devs):
        api = neutronapi.API()
        instance, pf, vf = self._populate_pci_mac_address_fakes()

        port_req_body = {'port': {}}
        mock_get_instance_pci_devs.return_value = [pf]
        mock_get_mac_by_pci_address.return_value = 'fake-mac-address'
        expected_port_req_body = {'port': {'mac_address': 'fake-mac-address'}}
        req = port_req_body.copy()
        api._populate_pci_mac_address(instance, 0, req)
        self.assertEqual(expected_port_req_body, req)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    @mock.patch.object(pci_utils, 'get_mac_by_pci_address')
    def test_populate_pci_mac_address_vf(self, mock_get_mac_by_pci_address,
                                         mock_get_instance_pci_devs):
        api = neutronapi.API()
        instance, pf, vf = self._populate_pci_mac_address_fakes()

        port_req_body = {'port': {}}
        mock_get_instance_pci_devs.return_value = [vf]
        req = port_req_body.copy()
        api._populate_pci_mac_address(instance, 42, port_req_body)
        self.assertEqual(port_req_body, req)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    @mock.patch.object(pci_utils, 'get_mac_by_pci_address')
    def test_populate_pci_mac_address_vf_fail(self,
                                              mock_get_mac_by_pci_address,
                                              mock_get_instance_pci_devs):
        api = neutronapi.API()
        instance, pf, vf = self._populate_pci_mac_address_fakes()

        port_req_body = {'port': {}}
        mock_get_instance_pci_devs.return_value = [vf]
        mock_get_mac_by_pci_address.side_effect = (
            exception.PciDeviceNotFoundById)
        req = port_req_body.copy()
        api._populate_pci_mac_address(instance, 42, port_req_body)
        self.assertEqual(port_req_body, req)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_populate_pci_mac_address_no_device(self,
                                                mock_get_instance_pci_devs):
        api = neutronapi.API()
        instance, pf, vf = self._populate_pci_mac_address_fakes()

        port_req_body = {'port': {}}
        mock_get_instance_pci_devs.return_value = []
        req = port_req_body.copy()
        api._populate_pci_mac_address(instance, 42, port_req_body)
        self.assertEqual(port_req_body, req)

    def _test_update_port_binding_true(self, expected_bind_host,
                                       func_name, *args):
        api = neutronapi.API()
        func = getattr(api, func_name)

        neutronapi.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        search_opts = {'device_id': self.instance['uuid'],
                       'tenant_id': self.instance['project_id']}
        ports = {'ports': [{'id': 'test1'}]}
        self.moxed_client.list_ports(**search_opts).AndReturn(ports)
        port_req_body = {'port':
                         {neutronapi.BINDING_HOST_ID: expected_bind_host}}
        self.moxed_client.update_port('test1',
                                      port_req_body).AndReturn(None)
        self.mox.ReplayAll()
        func(*args)

    def _test_update_port_true_exception(self, expected_bind_host,
                                         func_name, *args):
        api = neutronapi.API()
        func = getattr(api, func_name)

        neutronapi.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        search_opts = {'device_id': self.instance['uuid'],
                       'tenant_id': self.instance['project_id']}
        ports = {'ports': [{'id': 'test1'}]}
        self.moxed_client.list_ports(**search_opts).AndReturn(ports)
        port_req_body = {'port':
                         {neutronapi.BINDING_HOST_ID: expected_bind_host}}
        self.moxed_client.update_port('test1',
                                      port_req_body).AndRaise(
            Exception("fail to update port"))
        self.mox.ReplayAll()
        self.assertRaises(NEUTRON_CLIENT_EXCEPTION,
                          func,
                          *args)

    def test_migrate_instance_finish_binding_true(self):
        migration = {'source_compute': self.instance.get('host'),
                     'dest_compute': 'dest_host'}
        instance = self._fake_instance_object(self.instance)
        self._test_update_port_binding_true('dest_host',
                                            'migrate_instance_finish',
                                            self.context,
                                            instance,
                                            migration)

    def test_migrate_instance_finish_binding_true_exception(self):
        migration = {'source_compute': self.instance.get('host'),
                     'dest_compute': 'dest_host'}
        instance = self._fake_instance_object(self.instance)
        self._test_update_port_true_exception('dest_host',
                                              'migrate_instance_finish',
                                              self.context,
                                              instance,
                                              migration)

    def test_setup_instance_network_on_host_true(self):
        instance = self._fake_instance_object(self.instance)
        self._test_update_port_binding_true('fake_host',
                                            'setup_instance_network_on_host',
                                            self.context,
                                            instance,
                                            'fake_host')

    def test_setup_instance_network_on_host_exception(self):
        instance = self._fake_instance_object(self.instance)
        self._test_update_port_true_exception(
            'fake_host', 'setup_instance_network_on_host',
            self.context, instance, 'fake_host')

    def test_associate_not_implemented(self):
        api = neutronapi.API()
        self.assertRaises(NotImplementedError,
                          api.associate,
                          self.context, 'id')


class TestAllocateForInstance(test.NoDBTestCase):
    def setUp(self):
        super(TestAllocateForInstance, self).setUp()
        self.context = context.RequestContext('userid', uuids.my_tenant)
        self.instance = objects.Instance(uuid=uuids.instance,
            project_id=uuids.tenant_id, hostname="host")

    def test_allocate_for_instance_raises_invalid_input(self):
        api = neutronapi.API()
        self.instance.project_id = ""

        self.assertRaises(exception.InvalidInput,
            api.allocate_for_instance, self.context, self.instance,
            False, None)

    @mock.patch.object(neutronapi.API, 'get_instance_nw_info')
    @mock.patch.object(neutronapi.API, '_update_ports_for_instance')
    @mock.patch.object(neutronapi, '_filter_hypervisor_macs')
    @mock.patch.object(neutronapi.API, '_create_ports_for_instance')
    @mock.patch.object(neutronapi.API, '_process_security_groups')
    @mock.patch.object(neutronapi.API, '_clean_security_groups')
    @mock.patch.object(neutronapi.API, '_validate_requested_network_ids')
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_for_instance_minimal_args(self, mock_get_client,
            mock_validate_ports, mock_validate_nets, mock_clean_sg, mock_sg,
            mock_create_ports, mock_filter_macs, mock_update_ports, mock_gni):

        api = neutronapi.API()
        mock_get_client.side_effect = ["user", "admin"]
        mock_validate_ports.return_value = ("ports", "ordered_nets")
        mock_validate_nets.return_value = "nets"
        mock_clean_sg.return_value = "security_groups"
        mock_sg.return_value = "security_group_ids"
        mock_create_ports.return_value = "requests_and_created_ports"
        mock_filter_macs.return_value = "available_macs"
        mock_update_ports.return_value = (
            "nets", "ports", [uuids.preexist], [uuids.created])
        mock_gni.return_value = [
            {"id": uuids.created}, {"id": uuids.preexist}, {"id": "foo"}
        ]

        result = api.allocate_for_instance(self.context, self.instance,
                                           False, None)

        # TODO(johngarbutt) we need to replace the old mox coverage
        # with new tests that can build on this very poor test
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"id": uuids.created})
        self.assertEqual(result[1], {"id": uuids.preexist})

    def test_populate_mac_address_skip_if_none(self):
        api = neutronapi.API()
        port_req_body = {}

        api._populate_mac_address(None, port_req_body, None)

        self.assertEqual({}, port_req_body)

    def test_populate_mac_address_raise_if_empty(self):
        api = neutronapi.API()
        port_req_body = {}
        instance = objects.Instance(uuid=uuids.instance)

        self.assertRaises(exception.PortNotFree,
                          api._populate_mac_address,
                          instance, port_req_body, [])

    def test_populate_mac_address_adds_last(self):
        api = neutronapi.API()
        port_req_body = {'port': {"foo": "bar"}}

        api._populate_mac_address(None, port_req_body, ["a", "b"])

        expected_port = {"foo": "bar", "mac_address": "b"}
        self.assertEqual(expected_port, port_req_body["port"])

    def test_ensure_no_port_binding_failure_raises(self):
        port = {
            'id': uuids.port_id,
            'binding:vif_type': model.VIF_TYPE_BINDING_FAILED
        }

        self.assertRaises(exception.PortBindingFailed,
                          neutronapi._ensure_no_port_binding_failure, port)

    def test_ensure_no_port_binding_failure_passes_if_no_binding(self):
        port = {'id': uuids.port_id}
        neutronapi._ensure_no_port_binding_failure(port)

    def test_filter_hypervisor_macs(self):
        ports = {
            'id1': {'id': 'id1', 'mac_address': 'a'},
            'id2': {'id': 'id2', 'mac_address': 'c'}}
        macs = set(['a', 'b'])
        instance = objects.Instance(uuid=uuids.instance)

        result = neutronapi._filter_hypervisor_macs(instance, ports, macs)

        result = list(result)
        self.assertEqual(['b'], result)

    def test_validate_requested_port_ids_no_ports(self):
        api = neutronapi.API()
        mock_client = mock.Mock()
        network_list = [objects.NetworkRequest(network_id='net-1')]
        requested_networks = objects.NetworkRequestList(objects=network_list)

        ports, ordered_networks = api._validate_requested_port_ids(
            self.context, self.instance, mock_client, requested_networks)

        self.assertEqual({}, ports)
        self.assertEqual(network_list, ordered_networks)

    def test_validate_requested_port_ids_success(self):
        api = neutronapi.API()
        mock_client = mock.Mock()
        requested_networks = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id='net-1'),
            objects.NetworkRequest(port_id=uuids.port_id)])
        port = {
            "id": uuids.port_id,
            "tenant_id": uuids.tenant_id,
            "network_id": 'net-2'
        }
        mock_client.show_port.return_value = {"port": port}

        ports, ordered_networks = api._validate_requested_port_ids(
            self.context, self.instance, mock_client, requested_networks)

        mock_client.show_port.assert_called_once_with(uuids.port_id)
        self.assertEqual({uuids.port_id: port}, ports)
        self.assertEqual(2, len(ordered_networks))
        self.assertEqual(requested_networks[0], ordered_networks[0])
        self.assertEqual('net-2', ordered_networks[1].network_id)

    def _assert_validate_requested_port_ids_raises(self, exception, extras):
        api = neutronapi.API()
        mock_client = mock.Mock()
        requested_networks = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(port_id=uuids.port_id)])
        port = {
            "id": uuids.port_id,
            "tenant_id": uuids.tenant_id,
            "network_id": 'net-2'
        }
        port.update(extras)
        mock_client.show_port.return_value = {"port": port}

        self.assertRaises(exception, api._validate_requested_port_ids,
            self.context, self.instance, mock_client, requested_networks)

    def test_validate_requested_port_ids_raise_not_usable(self):
        self._assert_validate_requested_port_ids_raises(
            exception.PortNotUsable,
            {"tenant_id": "foo"})

    def test_validate_requested_port_ids_raise_in_use(self):
        self._assert_validate_requested_port_ids_raises(
            exception.PortInUse,
            {"device_id": "foo"})

    def test_validate_requested_port_ids_raise_dns(self):
        self._assert_validate_requested_port_ids_raises(
            exception.PortNotUsableDNS,
            {"dns_name": "foo"})

    def test_validate_requested_port_ids_raise_binding(self):
        self._assert_validate_requested_port_ids_raises(
            exception.PortBindingFailed,
            {"binding:vif_type": model.VIF_TYPE_BINDING_FAILED})

    def test_validate_requested_network_ids_success_auto_net(self):
        requested_networks = []
        ordered_networks = []
        api = neutronapi.API()
        mock_client = mock.Mock()
        nets = [{'id': "net1"}]
        mock_client.list_networks.side_effect = [{}, {"networks": nets}]

        result = api._validate_requested_network_ids(self.context,
            self.instance, mock_client, requested_networks, ordered_networks)

        self.assertEqual(nets, list(result.values()))
        expected_call_list = [
            mock.call(shared=False, tenant_id=uuids.tenant_id),
            mock.call(shared=True)
        ]
        self.assertEqual(expected_call_list,
            mock_client.list_networks.call_args_list)

    def test_validate_requested_network_ids_success_found_net(self):
        ordered_networks = [objects.NetworkRequest(network_id="net1")]
        requested_networks = objects.NetworkRequestList(ordered_networks)
        api = neutronapi.API()
        mock_client = mock.Mock()
        nets = [{'id': "net1"}]
        mock_client.list_networks.return_value = {"networks": nets}

        result = api._validate_requested_network_ids(self.context,
            self.instance, mock_client, requested_networks, ordered_networks)

        self.assertEqual(nets, list(result.values()))
        mock_client.list_networks.assert_called_once_with(id=['net1'])

    def test_validate_requested_network_ids_success_no_nets(self):
        requested_networks = []
        ordered_networks = []
        api = neutronapi.API()
        mock_client = mock.Mock()
        mock_client.list_networks.side_effect = [{}, {"networks": []}]

        result = api._validate_requested_network_ids(self.context,
            self.instance, mock_client, requested_networks, ordered_networks)

        self.assertEqual({}, result)
        expected_call_list = [
            mock.call(shared=False, tenant_id=uuids.tenant_id),
            mock.call(shared=True)
        ]
        self.assertEqual(expected_call_list,
            mock_client.list_networks.call_args_list)

    def _assert_validate_requested_network_ids_raises(self, exception, nets,
            requested_networks=None):
        ordered_networks = []
        if requested_networks is None:
            requested_networks = objects.NetworkRequestList()
        api = neutronapi.API()
        mock_client = mock.Mock()
        mock_client.list_networks.side_effect = [{}, {"networks": nets}]

        self.assertRaises(exception, api._validate_requested_network_ids,
            self.context, self.instance, mock_client,
            requested_networks, ordered_networks)

    def test_validate_requested_network_ids_raises_forbidden(self):
        self._assert_validate_requested_network_ids_raises(
            exception.ExternalNetworkAttachForbidden,
            [{'id': "net1", 'router:external': True, 'shared': False}])

    def test_validate_requested_network_ids_raises_net_not_found(self):
        requested_networks = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id="1")])
        self._assert_validate_requested_network_ids_raises(
            exception.NetworkNotFound,
            [], requested_networks=requested_networks)

    def test_validate_requested_network_ids_raises_too_many_nets(self):
        self._assert_validate_requested_network_ids_raises(
            exception.NetworkAmbiguous,
            [{'id': "net1"}, {'id': "net2"}])

    def test_create_ports_for_instance_no_security(self):
        api = neutronapi.API()
        ordered_networks = [objects.NetworkRequest(network_id=uuids.net)]
        nets = {uuids.net: {"id": uuids.net, "port_security_enabled": False}}
        mock_client = mock.Mock()
        mock_client.create_port.return_value = {"port": {"id": uuids.port}}

        result = api._create_ports_for_instance(self.context, self.instance,
            ordered_networks, nets, mock_client, None)

        self.assertEqual([(ordered_networks[0], uuids.port)], result)
        mock_client.create_port.assert_called_once_with(
            {'port': {
                'network_id': uuids.net, 'tenant_id': uuids.tenant_id,
                'admin_state_up': True, 'device_id': self.instance.uuid}})

    def test_create_ports_for_instance_with_security_groups(self):
        api = neutronapi.API()
        ordered_networks = [objects.NetworkRequest(network_id=uuids.net)]
        nets = {uuids.net: {"id": uuids.net, "subnets": [uuids.subnet]}}
        mock_client = mock.Mock()
        mock_client.create_port.return_value = {"port": {"id": uuids.port}}
        security_groups = [uuids.sg]

        result = api._create_ports_for_instance(self.context, self.instance,
            ordered_networks, nets, mock_client, security_groups)

        self.assertEqual([(ordered_networks[0], uuids.port)], result)
        mock_client.create_port.assert_called_once_with(
            {'port': {
                'network_id': uuids.net, 'tenant_id': uuids.tenant_id,
                'admin_state_up': True, 'security_groups': security_groups,
                'device_id': self.instance.uuid}})

    def test_create_ports_for_instance_with_cleanup_after_pc_failure(self):
        api = neutronapi.API()
        ordered_networks = [
            objects.NetworkRequest(network_id=uuids.net1),
            objects.NetworkRequest(network_id=uuids.net2),
            objects.NetworkRequest(network_id=uuids.net3),
            objects.NetworkRequest(network_id=uuids.net4)
        ]
        nets = {
            uuids.net1: {"id": uuids.net1, "port_security_enabled": False},
            uuids.net2: {"id": uuids.net2, "port_security_enabled": False},
            uuids.net3: {"id": uuids.net3, "port_security_enabled": False},
            uuids.net4: {"id": uuids.net4, "port_security_enabled": False}
        }
        error = exception.PortLimitExceeded()
        mock_client = mock.Mock()
        mock_client.create_port.side_effect = [
            {"port": {"id": uuids.port1}},
            {"port": {"id": uuids.port2}},
            error
        ]

        self.assertRaises(exception.PortLimitExceeded,
            api._create_ports_for_instance,
            self.context, self.instance, ordered_networks, nets,
            mock_client, None)

        self.assertEqual([mock.call(uuids.port1), mock.call(uuids.port2)],
            mock_client.delete_port.call_args_list)
        self.assertEqual(3, mock_client.create_port.call_count)

    def test_create_ports_for_instance_with_cleanup_after_sg_failure(self):
        api = neutronapi.API()
        ordered_networks = [
            objects.NetworkRequest(network_id=uuids.net1),
            objects.NetworkRequest(network_id=uuids.net2),
            objects.NetworkRequest(network_id=uuids.net3)
        ]
        nets = {
            uuids.net1: {"id": uuids.net1, "port_security_enabled": False},
            uuids.net2: {"id": uuids.net2, "port_security_enabled": False},
            uuids.net3: {"id": uuids.net3, "port_security_enabled": True}
        }
        mock_client = mock.Mock()
        mock_client.create_port.side_effect = [
            {"port": {"id": uuids.port1}},
            {"port": {"id": uuids.port2}}
        ]

        self.assertRaises(exception.SecurityGroupCannotBeApplied,
            api._create_ports_for_instance,
            self.context, self.instance, ordered_networks, nets,
            mock_client, None)

        self.assertEqual([mock.call(uuids.port1), mock.call(uuids.port2)],
            mock_client.delete_port.call_args_list)
        self.assertEqual(2, mock_client.create_port.call_count)

    def test_create_ports_for_instance_raises_subnets_missing(self):
        api = neutronapi.API()
        ordered_networks = [objects.NetworkRequest(network_id=uuids.net)]
        nets = {uuids.net: {"id": uuids.net, "port_security_enabled": True}}
        mock_client = mock.Mock()

        self.assertRaises(exception.SecurityGroupCannotBeApplied,
            api._create_ports_for_instance,
            self.context, self.instance,
            ordered_networks, nets, mock_client, None)

        self.assertFalse(mock_client.create_port.called)

    def test_create_ports_for_instance_raises_security_off(self):
        api = neutronapi.API()
        ordered_networks = [objects.NetworkRequest(network_id=uuids.net)]
        nets = {uuids.net: {
            "id": uuids.net,
            "port_security_enabled": False}}
        mock_client = mock.Mock()

        self.assertRaises(exception.SecurityGroupCannotBeApplied,
            api._create_ports_for_instance,
            self.context, self.instance,
            ordered_networks, nets, mock_client, [uuids.sg])

        self.assertFalse(mock_client.create_port.called)

    @mock.patch.object(objects.VirtualInterface, "create")
    def test_update_ports_for_instance_with_portbinding(self, mock_create):
        api = neutronapi.API()
        self.instance.availability_zone = "test_az"
        mock_neutron = mock.Mock()
        mock_admin = mock.Mock()
        requests_and_created_ports = [
            (objects.NetworkRequest(
                network_id=uuids.net1), uuids.port1),
            (objects.NetworkRequest(
                network_id=uuids.net2, port_id=uuids.port2), None)]
        net1 = {"id": uuids.net1}
        net2 = {"id": uuids.net2}
        nets = {uuids.net1: net1, uuids.net2: net2}
        bind_host_id = "bind_host_id"
        available_macs = ["mac1", "mac2"]
        requested_ports_dict = {uuids.port1: {}, uuids.port2: {}}

        mock_neutron.list_extensions.return_value = {"extensions": [
            {"name": "asdf"}]}
        port1 = {"port": {"id": uuids.port1, "mac_address": "mac1r"}}
        port2 = {"port": {"id": uuids.port2, "mac_address": "mac2r"}}
        mock_admin.update_port.side_effect = [port1, port2]

        ordered_nets, ordered_ports, preexisting_port_ids, \
            created_port_ids = api._update_ports_for_instance(
                self.context, self.instance,
                mock_neutron, mock_admin, requests_and_created_ports, nets,
                bind_host_id, available_macs, requested_ports_dict)

        # TODO(johngarbutt) need to build on this test so we can replace
        # all the mox based tests
        self.assertEqual([net1, net2], ordered_nets, "ordered_nets")
        self.assertEqual([uuids.port1, uuids.port2], ordered_ports,
            "ordered_ports")
        self.assertEqual([uuids.port2], preexisting_port_ids, "preexisting")
        self.assertEqual([uuids.port1], created_port_ids, "created")
        mock_admin.update_port.assert_called_with(uuids.port2,
            {'port': {
                'device_owner': 'compute:test_az',
                'mac_address': 'mac1',
                neutronapi.BINDING_HOST_ID: bind_host_id,
                'device_id': self.instance.uuid}})


class TestNeutronv2NeutronHostnameDNS(TestNeutronv2Base):
    def setUp(self):
        super(TestNeutronv2NeutronHostnameDNS, self).setUp()
        neutronapi.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)

    def test_allocate_for_instance_create_port(self):
        # The port's dns_name attribute should be set by the port create
        # request in allocate_for_instance
        self._allocate_for_instance(1, dns_extension=True)

    def test_allocate_for_instance_with_requested_port(self):
        # The port's dns_name attribute should be set by the port update
        # request in allocate_for_instance
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._allocate_for_instance(net_idx=1, dns_extension=True,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_port_dns_name_preset_equal_hostname(self):
        # The port's dns_name attribute should be set by the port update
        # request in allocate_for_instance. The port's dns_name was preset by
        # the user with a value equal to the instance's hostname
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._allocate_for_instance(net_idx=1, dns_extension=True,
                                    requested_networks=requested_networks,
                                    _dns_name='test-instance')

    def test_allocate_for_instance_port_dns_name_preset_noteq_hostname(self):
        # If a pre-existing port has dns_name set, an exception should be
        # raised if dns_name is not equal to the instance's hostname
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        api = self._stub_allocate_for_instance(
            requested_networks=requested_networks,
            dns_extension=True,
            _break='pre_list_networks',
            _dns_name='my-instance')
        self.assertRaises(exception.PortNotUsableDNS,
                          api.allocate_for_instance, self.context,
                          self.instance, False, requested_networks)


class TestNeutronv2NeutronHostnameDNSPortbinding(TestNeutronv2Base):
    def setUp(self):
        super(TestNeutronv2NeutronHostnameDNSPortbinding, self).setUp()
        neutronapi.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)

    def test_allocate_for_instance_create_port(self):
        # The port's dns_name attribute should be set by the port create
        # request in allocate_for_instance
        self._allocate_for_instance(1, dns_extension=True,
                                    bind_host_id=self.instance.get('host'))

    def test_allocate_for_instance_with_requested_port(self):
        # The port's dns_name attribute should be set by the port update
        # request in allocate_for_instance
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._allocate_for_instance(net_idx=1, dns_extension=True,
                                    bind_host_id=self.instance.get('host'),
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_create_port_with_dns_domain(self):
        # The port's dns_name attribute should be set by the port update
        # request in _update_port_dns_name. This should happen only when the
        # port binding extension is enabled and the port's network has a
        # non-blank dns_domain attribute
        self._allocate_for_instance(11, dns_extension=True,
                                    bind_host_id=self.instance.get('host'))

    def test_allocate_for_instance_with_requested_port_with_dns_domain(self):
        # The port's dns_name attribute should be set by the port update
        # request in _update_port_dns_name. This should happen only when the
        # port binding extension is enabled and the port's network has a
        # non-blank dns_domain attribute
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._allocate_for_instance(net_idx=11, dns_extension=True,
                                    bind_host_id=self.instance.get('host'),
                                    requested_networks=requested_networks)


class TestNeutronClientForAdminScenarios(test.NoDBTestCase):

    def setUp(self):
        super(TestNeutronClientForAdminScenarios, self).setUp()
        # NOTE(morganfainberg): The real configuration fixture here is used
        # instead o the already existing fixtures to ensure that the new
        # config options are automatically deregistered at the end of the
        # test run. Without the use of this fixture, the config options
        # from the plugin(s) would persist for all subsequent tests from when
        # these are run (due to glonal conf object) and not be fully
        # representative of a "clean" slate at the start of a test.
        self.config_fixture = self.useFixture(config_fixture.Config())
        oslo_opts = ks_loading.get_auth_plugin_conf_options('v2password')
        self.config_fixture.register_opts(oslo_opts, 'neutron')

    @requests_mock.mock()
    def _test_get_client_for_admin(self, req_mock,
                                   use_id=False, admin_context=False):
        token_value = uuidutils.generate_uuid(dashed=False)
        auth_url = 'http://anyhost/auth'
        token_resp = V2Token(token_id=token_value)
        req_mock.post(auth_url + '/tokens', json=token_resp)

        self.flags(url='http://anyhost/', group='neutron')
        self.flags(auth_type='v2password', group='neutron')
        self.flags(auth_url=auth_url, group='neutron')
        self.flags(timeout=30, group='neutron')
        if use_id:
            self.flags(tenant_id='tenant_id', group='neutron')
            self.flags(user_id='user_id', group='neutron')

        if admin_context:
            my_context = context.get_admin_context()
        else:
            my_context = context.RequestContext('userid', uuids.my_tenant,
                                                auth_token='token')

        # clean global
        neutronapi.reset_state()

        if admin_context:
            # Note that the context does not contain a token but is
            # an admin context  which will force an elevation to admin
            # credentials.
            context_client = neutronapi.get_client(my_context)
        else:
            # Note that the context is not elevated, but the True is passed in
            # which will force an elevation to admin credentials even though
            # the context has an auth_token.
            context_client = neutronapi.get_client(my_context, True)

        admin_auth = neutronapi._ADMIN_AUTH

        self.assertEqual(CONF.neutron.auth_url, admin_auth.auth_url)
        self.assertEqual(CONF.neutron.password, admin_auth.password)

        if use_id:
            self.assertEqual(CONF.neutron.tenant_id,
                             admin_auth.tenant_id)
            self.assertEqual(CONF.neutron.user_id, admin_auth.user_id)

            self.assertIsNone(admin_auth.tenant_name)
            self.assertIsNone(admin_auth.username)
        else:
            self.assertEqual(CONF.neutron.username, admin_auth.username)

            self.assertIsNone(admin_auth.tenant_id)
            self.assertIsNone(admin_auth.user_id)

        self.assertEqual(CONF.neutron.timeout,
                         neutronapi._SESSION.timeout)

        self.assertEqual(
            token_value,
            context_client.httpclient.auth.get_token(neutronapi._SESSION))
        self.assertEqual(
            CONF.neutron.url,
            context_client.httpclient.get_endpoint())

    def test_get_client_for_admin(self):
        self._test_get_client_for_admin()

    def test_get_client_for_admin_with_id(self):
        self._test_get_client_for_admin(use_id=True)

    def test_get_client_for_admin_context(self):
        self._test_get_client_for_admin(admin_context=True)

    def test_get_client_for_admin_context_with_id(self):
        self._test_get_client_for_admin(use_id=True, admin_context=True)


class TestNeutronPortSecurity(test.NoDBTestCase):

    @mock.patch.object(neutronapi.API, 'get_instance_nw_info')
    @mock.patch.object(neutronapi.API, '_update_port_dns_name')
    @mock.patch.object(neutronapi.API, '_create_port_minimal')
    @mock.patch.object(neutronapi.API, '_populate_neutron_extension_values')
    @mock.patch.object(neutronapi.API, '_check_external_network_attach')
    @mock.patch.object(neutronapi.API, '_process_security_groups')
    @mock.patch.object(neutronapi.API, '_get_available_networks')
    @mock.patch.object(neutronapi, '_filter_hypervisor_macs')
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_no_security_groups_requested(
            self, mock_vif, mock_get_client,
            mock_validate_requested_port_ids, mock_filter_macs,
            mock_get_available_networks, mock_process_security_groups,
            mock_check_external_network_attach,
            mock_populate_neutron_extension_values, mock_create_port,
            mock_update_port_dns_name, mock_get_instance_nw_info):
        nets = [
            {'id': 'net1',
             'name': 'net_name1',
             'subnets': ['mysubnid1'],
             'port_security_enabled': True},
            {'id': 'net2',
             'name': 'net_name2',
             'subnets': ['mysubnid2'],
             'port_security_enabled': True}]
        onets = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id='net1'),
            objects.NetworkRequest(network_id='net2')])

        instance = objects.Instance(
            project_id=1, availability_zone='nova', uuid=uuids.instance)
        secgroups = ['default']  # Nova API provides the 'default'

        mock_validate_requested_port_ids.return_value = [None, onets]
        mock_filter_macs.return_value = None
        mock_get_available_networks.return_value = nets
        mock_process_security_groups.return_value = []

        api = neutronapi.API()
        mock_create_port.return_value = {'id': 'foo', 'mac_address': 'bar'}
        api.allocate_for_instance(
            'context', instance, False, requested_networks=onets,
            security_groups=secgroups)

        mock_process_security_groups.assert_called_once_with(
            instance, mock.ANY, [])
        mock_create_port.assert_has_calls([
            mock.call(mock.ANY, instance, u'net1', None, []),
            mock.call(mock.ANY, instance, u'net2', None, [])],
            any_order=True)

    @mock.patch.object(neutronapi.API, 'get_instance_nw_info')
    @mock.patch.object(neutronapi.API, '_update_port_dns_name')
    @mock.patch.object(neutronapi.API, '_create_port_minimal')
    @mock.patch.object(neutronapi.API, '_populate_neutron_extension_values')
    @mock.patch.object(neutronapi.API, '_check_external_network_attach')
    @mock.patch.object(neutronapi.API, '_process_security_groups')
    @mock.patch.object(neutronapi.API, '_get_available_networks')
    @mock.patch.object(neutronapi, '_filter_hypervisor_macs')
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_security_groups_requested(
            self, mock_vif, mock_get_client,
            mock_validate_requested_port_ids, mock_filter_macs,
            mock_get_available_networks, mock_process_security_groups,
            mock_check_external_network_attach,
            mock_populate_neutron_extension_values, mock_create_port,
            mock_update_port_dns_name, mock_get_instance_nw_info):
        nets = [
            {'id': 'net1',
             'name': 'net_name1',
             'subnets': ['mysubnid1'],
             'port_security_enabled': True},
            {'id': 'net2',
             'name': 'net_name2',
             'subnets': ['mysubnid2'],
             'port_security_enabled': True}]
        onets = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id='net1'),
            objects.NetworkRequest(network_id='net2')])

        instance = objects.Instance(
            project_id=1, availability_zone='nova', uuid=uuids.instance)
        secgroups = ['default', 'secgrp1', 'secgrp2']

        mock_validate_requested_port_ids.return_value = [None, onets]
        mock_filter_macs.return_value = None
        mock_get_available_networks.return_value = nets
        mock_process_security_groups.return_value = ['default-uuid',
                                                     'secgrp-uuid1',
                                                     'secgrp-uuid2']

        api = neutronapi.API()
        mock_create_port.return_value = {'id': 'foo', 'mac_address': 'bar'}
        api.allocate_for_instance(
            'context', instance, False, requested_networks=onets,
            security_groups=secgroups)

        mock_create_port.assert_has_calls([
            mock.call(mock.ANY, instance, u'net1', None,
                ['default-uuid', 'secgrp-uuid1', 'secgrp-uuid2']),
            mock.call(mock.ANY, instance, u'net2', None,
                ['default-uuid', 'secgrp-uuid1', 'secgrp-uuid2'])],
            any_order=True)

    @mock.patch.object(neutronapi.API, 'get_instance_nw_info')
    @mock.patch.object(neutronapi.API, '_update_port_dns_name')
    @mock.patch.object(neutronapi.API, '_create_port_minimal')
    @mock.patch.object(neutronapi.API, '_populate_neutron_extension_values')
    @mock.patch.object(neutronapi.API, '_check_external_network_attach')
    @mock.patch.object(neutronapi.API, '_process_security_groups')
    @mock.patch.object(neutronapi.API, '_get_available_networks')
    @mock.patch.object(neutronapi, '_filter_hypervisor_macs')
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_port_security_disabled_no_security_groups_requested(
            self, mock_vif, mock_get_client,
            mock_validate_requested_port_ids, mock_filter_macs,
            mock_get_available_networks, mock_process_security_groups,
            mock_check_external_network_attach,
            mock_populate_neutron_extension_values, mock_create_port,
            mock_update_port_dns_name, mock_get_instance_nw_info):
        nets = [
            {'id': 'net1',
             'name': 'net_name1',
             'subnets': ['mysubnid1'],
             'port_security_enabled': False},
            {'id': 'net2',
             'name': 'net_name2',
             'subnets': ['mysubnid2'],
             'port_security_enabled': False}]
        onets = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id='net1'),
            objects.NetworkRequest(network_id='net2')])

        instance = objects.Instance(
            project_id=1, availability_zone='nova', uuid=uuids.instance)
        secgroups = ['default']  # Nova API provides the 'default'

        mock_validate_requested_port_ids.return_value = [None, onets]
        mock_filter_macs.return_value = None
        mock_get_available_networks.return_value = nets
        mock_process_security_groups.return_value = []

        api = neutronapi.API()
        mock_create_port.return_value = {'id': 'foo', 'mac_address': 'bar'}
        api.allocate_for_instance(
            'context', instance, False, requested_networks=onets,
            security_groups=secgroups)

        mock_process_security_groups.assert_called_once_with(
            instance, mock.ANY, [])
        mock_create_port.assert_has_calls([
            mock.call(mock.ANY, instance, u'net1', None, []),
            mock.call(mock.ANY, instance, u'net2', None, [])],
            any_order=True)

    @mock.patch.object(neutronapi.API, 'get_instance_nw_info')
    @mock.patch.object(neutronapi.API, '_update_port_dns_name')
    @mock.patch.object(neutronapi.API, '_create_port_minimal')
    @mock.patch.object(neutronapi.API, '_populate_neutron_extension_values')
    @mock.patch.object(neutronapi.API, '_check_external_network_attach')
    @mock.patch.object(neutronapi.API, '_process_security_groups')
    @mock.patch.object(neutronapi.API, '_get_available_networks')
    @mock.patch.object(neutronapi, '_filter_hypervisor_macs')
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_port_security_disabled_and_security_groups_requested(
            self, mock_vif, mock_get_client,
            mock_validate_requested_port_ids, mock_filter_macs,
            mock_get_available_networks, mock_process_security_groups,
            mock_check_external_network_attach,
            mock_populate_neutron_extension_values, mock_create_port,
            mock_update_port_dns_name, mock_get_instance_nw_info):
        nets = [
            {'id': 'net1',
             'name': 'net_name1',
             'subnets': ['mysubnid1'],
             'port_security_enabled': True},
            {'id': 'net2',
             'name': 'net_name2',
             'subnets': ['mysubnid2'],
             'port_security_enabled': False}]
        onets = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id='net1'),
            objects.NetworkRequest(network_id='net2')])

        instance = objects.Instance(
            project_id=1, availability_zone='nova', uuid=uuids.instance)
        secgroups = ['default', 'secgrp1', 'secgrp2']

        mock_validate_requested_port_ids.return_value = [None, onets]
        mock_filter_macs.return_value = None
        mock_get_available_networks.return_value = nets
        mock_process_security_groups.return_value = ['default-uuid',
                                                     'secgrp-uuid1',
                                                     'secgrp-uuid2']

        api = neutronapi.API()
        self.assertRaises(
            exception.SecurityGroupCannotBeApplied,
            api.allocate_for_instance,
            'context', instance, False, requested_networks=onets,
            security_groups=secgroups)

        mock_process_security_groups.assert_called_once_with(
            instance, mock.ANY, ['default', 'secgrp1', 'secgrp2'])


class TestNeutronv2AutoAllocateNetwork(test.NoDBTestCase):
    """Tests auto-allocation scenarios"""

    def setUp(self):
        super(TestNeutronv2AutoAllocateNetwork, self).setUp()
        self.api = neutronapi.API()
        self.context = context.RequestContext(uuids.user_id, uuids.project_id)

    def test__can_auto_allocate_network_validation_conflict(self):
        # Tests that the dry-run validation with neutron fails (not ready).
        ntrn = mock.Mock()
        ntrn.validate_auto_allocated_topology_requirements.side_effect = \
            exceptions.Conflict
        self.assertFalse(self.api._can_auto_allocate_network(
            self.context, ntrn))
        validate = ntrn.validate_auto_allocated_topology_requirements
        validate.assert_called_once_with(uuids.project_id)

    def test__can_auto_allocate_network(self):
        # Tests the happy path.
        ntrn = mock.Mock()
        self.assertTrue(self.api._can_auto_allocate_network(
            self.context, ntrn))
        validate = ntrn.validate_auto_allocated_topology_requirements
        validate.assert_called_once_with(uuids.project_id)

    def test__ports_needed_per_instance_no_reqs_no_nets(self):
        # Tests no requested_networks and no available networks.
        with mock.patch.object(self.api, '_get_available_networks',
                               return_value=[]):
            self.assertEqual(
                1, self.api._ports_needed_per_instance(self.context,
                                                       mock.sentinel.neutron,
                                                       None))

    def test__ports_needed_per_instance_empty_reqs_no_nets(self):
        # Tests empty requested_networks and no available networks.
        requested_networks = objects.NetworkRequestList()
        with mock.patch.object(self.api, '_get_available_networks',
                               return_value=[]):
            self.assertEqual(
                1, self.api._ports_needed_per_instance(self.context,
                                                       mock.sentinel.neutron,
                                                       requested_networks))

    def test__ports_needed_per_instance_auto_reqs_no_nets_not_ready(self):
        # Test for when there are no available networks and we're requested
        # to auto-allocate the network but auto-allocation is not available.
        net_req = objects.NetworkRequest(
            network_id=net_req_obj.NETWORK_ID_AUTO)
        requested_networks = objects.NetworkRequestList(objects=[net_req])
        with mock.patch.object(self.api, '_get_available_networks',
                               return_value=[]):
            with mock.patch.object(self.api, '_can_auto_allocate_network',
                                   spec=True, return_value=False) as can_alloc:
                self.assertRaises(
                    exception.UnableToAutoAllocateNetwork,
                    self.api._ports_needed_per_instance,
                    self.context, mock.sentinel.neutron, requested_networks)
            can_alloc.assert_called_once_with(
                self.context, mock.sentinel.neutron)

    def test__ports_needed_per_instance_auto_reqs_no_nets_ok(self):
        # Test for when there are no available networks and we're requested
        # to auto-allocate the network and auto-allocation is available.
        net_req = objects.NetworkRequest(
            network_id=net_req_obj.NETWORK_ID_AUTO)
        requested_networks = objects.NetworkRequestList(objects=[net_req])
        with mock.patch.object(self.api, '_get_available_networks',
                               return_value=[]):
            with mock.patch.object(self.api, '_can_auto_allocate_network',
                                   spec=True, return_value=True) as can_alloc:
                self.assertEqual(
                    1, self.api._ports_needed_per_instance(
                        self.context,
                        mock.sentinel.neutron,
                        requested_networks))
            can_alloc.assert_called_once_with(
                self.context, mock.sentinel.neutron)

    def test__validate_requested_port_ids_auto_allocate(self):
        # Tests that _validate_requested_port_ids doesn't really do anything
        # if there is an auto-allocate network request.
        net_req = objects.NetworkRequest(
            network_id=net_req_obj.NETWORK_ID_AUTO)
        requested_networks = objects.NetworkRequestList(objects=[net_req])
        self.assertEqual(({}, []),
                         self.api._validate_requested_port_ids(
                             self.context, mock.sentinel.instance,
                             mock.sentinel.neutron_client, requested_networks))

    def test__auto_allocate_network_conflict(self):
        # Tests that we handle a 409 from Neutron when auto-allocating topology
        instance = mock.Mock(project_id=self.context.project_id)
        ntrn = mock.Mock()
        ntrn.get_auto_allocated_topology = mock.Mock(
            side_effect=exceptions.Conflict)
        self.assertRaises(exception.UnableToAutoAllocateNetwork,
                          self.api._auto_allocate_network, instance, ntrn)
        ntrn.get_auto_allocated_topology.assert_called_once_with(
            instance.project_id)

    def test__auto_allocate_network_network_not_found(self):
        # Tests that we handle a 404 from Neutron when auto-allocating topology
        instance = mock.Mock(project_id=self.context.project_id)
        ntrn = mock.Mock()
        ntrn.get_auto_allocated_topology.return_value = {
            'auto_allocated_topology': {
                'id': uuids.network_id
            }
        }
        ntrn.show_network = mock.Mock(
            side_effect=exceptions.NetworkNotFoundClient)
        self.assertRaises(exception.UnableToAutoAllocateNetwork,
                          self.api._auto_allocate_network, instance, ntrn)
        ntrn.show_network.assert_called_once_with(uuids.network_id)

    def test__auto_allocate_network(self):
        # Tests the happy path.
        instance = mock.Mock(project_id=self.context.project_id)
        ntrn = mock.Mock()
        ntrn.get_auto_allocated_topology.return_value = {
            'auto_allocated_topology': {
                'id': uuids.network_id
            }
        }
        ntrn.show_network.return_value = {'network': mock.sentinel.network}
        self.assertEqual(mock.sentinel.network,
                         self.api._auto_allocate_network(instance, ntrn))

    def test_allocate_for_instance_auto_allocate(self):
        # Tests the happy path.
        ntrn = mock.Mock()
        # mock neutron.list_networks which is called from
        # _get_available_networks when net_ids is empty, which it will be
        # because _validate_requested_port_ids will return an empty list since
        # we requested 'auto' allocation.
        ntrn.list_networks.return_value = {}

        fake_network = {
            'id': uuids.network_id,
            'subnets': [
                uuids.subnet_id,
            ]
        }

        def fake_get_instance_nw_info(context, instance, **kwargs):
            # assert the network and port are what was used in the test
            self.assertIn('networks', kwargs)
            self.assertEqual(1, len(kwargs['networks']))
            self.assertEqual(uuids.network_id,
                             kwargs['networks'][0]['id'])
            self.assertIn('port_ids', kwargs)
            self.assertEqual(1, len(kwargs['port_ids']))
            self.assertEqual(uuids.port_id, kwargs['port_ids'][0])
            # return a fake vif
            return [model.VIF(id=uuids.port_id)]

        @mock.patch('nova.network.neutronv2.api.get_client', return_value=ntrn)
        @mock.patch.object(self.api, '_auto_allocate_network',
                           return_value=fake_network)
        @mock.patch.object(self.api, '_check_external_network_attach')
        @mock.patch.object(self.api, '_populate_neutron_extension_values')
        @mock.patch.object(self.api, '_populate_mac_address')
        @mock.patch.object(self.api, '_create_port_minimal', spec=True,
                           return_value={'id': uuids.port_id,
                                         'mac_address': 'foo'})
        @mock.patch.object(self.api, '_update_port')
        @mock.patch.object(self.api, '_update_port_dns_name')
        @mock.patch.object(self.api, 'get_instance_nw_info',
                           fake_get_instance_nw_info)
        @mock.patch('nova.objects.VirtualInterface')
        def do_test(self,
                    mock_vif,
                    update_port_dsn_name_mock,
                    update_port_mock,
                    create_port_mock,
                    populate_mac_addr_mock,
                    populate_ext_values_mock,
                    check_external_net_attach_mock,
                    auto_allocate_mock,
                    get_client_mock):
            instance = fake_instance.fake_instance_obj(self.context)
            net_req = objects.NetworkRequest(
                network_id=net_req_obj.NETWORK_ID_AUTO)
            requested_networks = objects.NetworkRequestList(objects=[net_req])

            nw_info = self.api.allocate_for_instance(
                self.context, instance, False, requested_networks)
            self.assertEqual(1, len(nw_info))
            self.assertEqual(uuids.port_id, nw_info[0]['id'])
            # assert that we filtered available networks on admin_state_up=True
            ntrn.list_networks.assert_has_calls([
                mock.call(tenant_id=instance.project_id, shared=False,
                          admin_state_up=True),
                mock.call(shared=True)])

            # assert the calls to create the port are using the network that
            # was auto-allocated
            port_req_body = mock.ANY
            create_port_mock.assert_called_once_with(
                ntrn, instance, uuids.network_id,
                None,   # request.address (fixed IP)
                [],     # security_group_ids - we didn't request any
            )
            update_port_mock.assert_called_once_with(
                ntrn, instance, uuids.port_id, port_req_body)

        do_test(self)
