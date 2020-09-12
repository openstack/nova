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
from neutronclient.common import exceptions
from neutronclient.v2_0 import client
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_policy import policy as oslo_policy
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_utils import uuidutils
import requests_mock
import six
from six.moves import range

from nova import context
from nova.db.sqlalchemy import api as db_api
from nova import exception
from nova.network import constants
from nova.network import model
from nova.network import neutron as neutronapi
from nova import objects
from nova.objects import network_request as net_req_obj
from nova.objects import virtual_interface as obj_vif
from nova.pci import manager as pci_manager
from nova.pci import request as pci_request
from nova.pci import utils as pci_utils
from nova.pci import whitelist as pci_whitelist
from nova import policy
from nova import service_auth
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_requests as fake_req


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
        self.assertIsNotNone(cl.httpclient.global_request_id)
        self.assertEqual(my_context.global_id,
                         cl.httpclient.global_request_id)

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
        self.flags(endpoint_override='http://anyhost/', group='neutron')
        self.flags(timeout=30, group='neutron')
        # Will use the token rather than load auth from config.
        my_context = context.RequestContext('userid',
                                            uuids.my_tenant,
                                            auth_token='token')
        cl = neutronapi.get_client(my_context)

        self.assertEqual(CONF.neutron.endpoint_override,
                         cl.httpclient.endpoint_override)
        self.assertEqual(CONF.neutron.region_name, cl.httpclient.region_name)
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
        self.flags(endpoint_override='http://anyhost/', group='neutron')
        self.flags(timeout=30, group='neutron')
        # No auth_token set but is_admin will load auth from config.
        my_context = context.RequestContext('userid',
                                            uuids.my_tenant,
                                            is_admin=True)
        with mock.patch.object(neutronapi, '_load_auth_plugin') as mock_auth:
            cl = neutronapi.get_client(my_context)

        self.assertEqual(CONF.neutron.endpoint_override,
                         cl.httpclient.endpoint_override)
        self.assertEqual(mock_auth.return_value.auth_token,
                         cl.httpclient.auth.auth_token)
        self.assertEqual(CONF.neutron.timeout, cl.httpclient.session.timeout)

    def test_withouttoken_keystone_connection_error(self):
        self.flags(endpoint_override='http://anyhost/', group='neutron')
        my_context = context.RequestContext('userid', uuids.my_tenant)
        self.assertRaises(NEUTRON_CLIENT_EXCEPTION,
                          neutronapi.get_client,
                          my_context)

    @mock.patch('nova.network.neutron._ADMIN_AUTH')
    @mock.patch.object(client.Client, "list_networks", new=mock.Mock())
    def test_reuse_admin_token(self, m):
        self.flags(endpoint_override='http://anyhost/', group='neutron')
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

    @mock.patch('nova.network.neutron.LOG.error')
    @mock.patch.object(ks_loading, 'load_auth_from_conf_options')
    def test_load_auth_plugin_failed(self, mock_load_from_conf, mock_log_err):
        mock_load_from_conf.return_value = None
        from neutronclient.common import exceptions as neutron_client_exc
        self.assertRaises(neutron_client_exc.Unauthorized,
                          neutronapi._load_auth_plugin, CONF)
        mock_log_err.assert_called()
        self.assertIn('The [neutron] section of your nova configuration file',
                      mock_log_err.call_args[0][0])

    @mock.patch.object(client.Client, "list_networks",
                       side_effect=exceptions.Unauthorized())
    def test_wrapper_exception_translation(self, m):
        my_context = context.RequestContext('userid', 'my_tenantid',
                                            auth_token='token')
        client = neutronapi.get_client(my_context)
        self.assertRaises(
            exception.Unauthorized,
            client.list_networks)

    def test_neutron_http_retries(self):
        retries = 42
        self.flags(http_retries=retries, group='neutron')
        my_context = context.RequestContext('userid',
                                            uuids.my_tenant,
                                            auth_token='token')
        cl = neutronapi.get_client(my_context)
        self.assertEqual(retries, cl.httpclient.connect_retries)


class TestAPIBase(test.TestCase):

    def setUp(self):
        super(TestAPIBase, self).setUp()
        self.api = neutronapi.API()
        self.context = context.RequestContext(
            'userid', uuids.my_tenant,
            auth_token='bff4a5a6b9eb4ea2a6efec6eefb77936')
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

    def _test_allocate_for_instance_with_virtual_interface(
            self, net_idx=1, **kwargs):
        self._vifs_created = []

        def _new_vif(*args):
            m = mock.MagicMock()
            self._vifs_created.append(m)
            return m

        with mock.patch('nova.objects.VirtualInterface') as mock_vif:
            mock_vif.side_effect = _new_vif
            requested_networks = kwargs.pop('requested_networks', None)

            return self._test_allocate_for_instance(
                net_idx=net_idx, requested_networks=requested_networks,
                **kwargs)

    @mock.patch.object(neutronapi.API, '_populate_neutron_extension_values')
    @mock.patch.object(neutronapi.API, '_refresh_neutron_extensions_cache')
    @mock.patch.object(neutronapi.API, 'get_instance_nw_info',
                       return_value=None)
    @mock.patch.object(neutronapi, 'get_client')
    def _test_allocate_for_instance(self, mock_get_client, mock_get_nw,
                                    mock_refresh, mock_populate, net_idx=1,
                                    requested_networks=None,
                                    exception=None,
                                    context=None,
                                    **kwargs):
        ctxt = context or self.context
        self.instance = self._fake_instance_object(self.instance)
        self.instance2 = self._fake_instance_object(self.instance2)

        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client

        bind_host_id = kwargs.get('bind_host_id')

        has_dns_extension = False
        if kwargs.get('dns_extension'):
            has_dns_extension = True
            self.api.extensions[constants.DNS_INTEGRATION] = 1

        # Net idx is 1-based for compatibility with existing unit tests
        nets = self.nets[net_idx - 1]
        ports = {}
        fixed_ips = {}

        req_net_ids = []
        ordered_networks = []

        expected_show_port_calls = self._stub_allocate_for_instance_show_port(
            nets, ports, fixed_ips, req_net_ids, ordered_networks,
            requested_networks, mocked_client, **kwargs)

        populate_values = []
        update_port_values = []
        try:
            if kwargs.get('_break') == 'pre_list_networks':
                raise test.TestingException()

            expected_list_networks_calls = (
                self._stub_allocate_for_instance_list_networks(
                    req_net_ids, nets, mocked_client))

            pre_create_port = (
                kwargs.get('_break') == 'post_list_networks' or
                ((requested_networks is None or
                  requested_networks.as_tuples() == [(None, None, None)]) and
                 len(nets) > 1) or
                kwargs.get('_break') == 'post_list_extensions')

            if pre_create_port:
                raise test.TestingException()

            expected_create_port_calls = (
                self._stub_allocate_for_instance_create_port(
                    ordered_networks, fixed_ips, nets, mocked_client))

            preexisting_port_ids = []
            ports_in_requested_net_order = []
            nets_in_requested_net_order = []
            index = 0
            expected_populate_calls = []
            expected_update_port_calls = []
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

                populate_values.append(None)
                expected_populate_calls.append(
                    mock.call(mock.ANY, self.instance, mock.ANY, mock.ANY,
                              network=network, neutron=mocked_client,
                              bind_host_id=bind_host_id))

                if not request.port_id:
                    port_id = uuids.fake
                    update_port_res = {'port': {
                        'id': port_id,
                        'mac_address': 'fakemac%i' % index}}
                    ports_in_requested_net_order.append(port_id)
                    if kwargs.get('_break') == 'mac' + request.network_id:
                        if populate_values:
                            mock_populate.side_effect = populate_values
                        if update_port_values:
                            mocked_client.update_port.side_effect = (
                                update_port_values)
                        raise test.TestingException()
                else:
                    ports_in_requested_net_order.append(request.port_id)
                    preexisting_port_ids.append(request.port_id)
                    port_id = request.port_id
                    update_port_res = {'port': ports[port_id]}

                new_mac = port_req_body['port'].get('mac_address')
                if new_mac:
                    update_port_res['port']['mac_address'] = new_mac

                update_port_values.append(update_port_res)
                expected_update_port_calls.append(
                    mock.call(port_id, port_req_body))

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
                        update_port_values.append(res_port_dns)
                        expected_update_port_calls.append(
                            mock.call(ports_in_requested_net_order[-1],
                                      port_req_body_dns))
                nets_in_requested_net_order.append(network)
            mock_get_nw.return_value = self._returned_nw_info
        except test.TestingException:
            pass

        mock_populate.side_effect = populate_values
        mocked_client.update_port.side_effect = update_port_values

        # Call the allocate_for_instance method
        nw_info = None
        if exception:
            self.assertRaises(exception, self.api.allocate_for_instance,
                              ctxt, self.instance,
                              requested_networks, bind_host_id=bind_host_id)
        else:
            nw_info = self.api.allocate_for_instance(
                ctxt, self.instance, requested_networks,
                bind_host_id=bind_host_id)

        mock_get_client.assert_has_calls([
            mock.call(ctxt), mock.call(ctxt, admin=True)],
            any_order=True)

        mock_refresh.assert_not_called()

        if requested_networks:
            mocked_client.show_port.assert_has_calls(expected_show_port_calls)
            self.assertEqual(len(expected_show_port_calls),
                             mocked_client.show_port.call_count)

        if kwargs.get('_break') == 'pre_list_networks':
            return nw_info, mocked_client

        mocked_client.list_networks.assert_has_calls(
            expected_list_networks_calls)
        self.assertEqual(len(expected_list_networks_calls),
                         mocked_client.list_networks.call_count)

        if pre_create_port:
            return nw_info, mocked_client

        mocked_client.create_port.assert_has_calls(
            expected_create_port_calls)
        self.assertEqual(len(expected_create_port_calls),
                         mocked_client.create_port.call_count)

        mocked_client.update_port.assert_has_calls(
            expected_update_port_calls)
        self.assertEqual(len(expected_update_port_calls),
                         mocked_client.update_port.call_count)

        mock_populate.assert_has_calls(expected_populate_calls)
        self.assertEqual(len(expected_populate_calls),
                         mock_populate.call_count)

        if mock_get_nw.return_value is None:
            mock_get_nw.assert_not_called()
        else:
            mock_get_nw.assert_called_once_with(
                mock.ANY, self.instance, networks=nets_in_requested_net_order,
                port_ids=ports_in_requested_net_order,
                admin_client=mocked_client,
                preexisting_port_ids=preexisting_port_ids)

        return nw_info, mocked_client

    def _stub_allocate_for_instance_show_port(self, nets, ports, fixed_ips,
            req_net_ids, ordered_networks, requested_networks,
            mocked_client, **kwargs):
        expected_show_port_calls = []

        if requested_networks:
            show_port_values = []
            for request in requested_networks:
                if request.port_id:
                    if request.port_id == uuids.portid_3:
                        show_port_values.append(
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
                    elif request.port_id == uuids.non_existent_uuid:
                        show_port_values.append(
                            exceptions.PortNotFoundClient(status_code=404))
                    else:
                        show_port_values.append(
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
                    expected_show_port_calls.append(mock.call(request.port_id))
                else:
                    fixed_ips[request.network_id] = request.address
                req_net_ids.append(request.network_id)
                ordered_networks.append(request)
            if show_port_values:
                mocked_client.show_port.side_effect = show_port_values
        else:
            for n in nets:
                ordered_networks.append(
                    objects.NetworkRequest(network_id=n['id']))

        return expected_show_port_calls

    def _stub_allocate_for_instance_list_networks(self, req_net_ids, nets,
                                                  mocked_client):
        if req_net_ids:
            expected_list_networks_calls = [mock.call(id=req_net_ids)]
            mocked_client.list_networks.return_value = {'networks': nets}
        else:
            expected_list_networks_calls = [
                mock.call(tenant_id=self.instance.project_id,
                          shared=False),
                mock.call(shared=True)]
            mocked_client.list_networks.side_effect = [
                {'networks': nets}, {'networks': []}]

        return expected_list_networks_calls

    def _stub_allocate_for_instance_create_port(self, ordered_networks,
            fixed_ips, nets, mocked_client):
        create_port_values = []
        expected_create_port_calls = []
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
                port_req_body_create['port']['network_id'] = (
                    request.network_id)
                port_req_body_create['port']['admin_state_up'] = True
                port_req_body_create['port']['tenant_id'] = (
                    self.instance.project_id)
                res_port = {'port': {'id': uuids.fake}}
                expected_create_port_calls.append(
                    mock.call(port_req_body_create))
                create_port_values.append(res_port)
        mocked_client.create_port.side_effect = create_port_values

        return expected_create_port_calls


class TestAPI(TestAPIBase):
    """Used to test Neutron V2 API."""

    @mock.patch.object(db_api, 'instance_info_cache_get')
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def _test_get_instance_nw_info(self, number, mock_get_client,
                                   mock_cache_update, mock_cache_get):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        port_data = number == 1 and self.port_data1 or self.port_data2
        net_info_cache = []
        for port in port_data:
            net_info_cache.append({"network": {"id": port['network_id']},
                                   "id": port['id']})

        list_ports_values = [{'ports': port_data}]
        expected_list_ports_calls = [mock.call(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid'])]

        net_ids = [port['network_id'] for port in port_data]
        nets = number == 1 and self.nets1 or self.nets2
        mocked_client.list_networks.return_value = {'networks': nets}

        list_subnets_values = []
        expected_list_subnets_calls = []
        list_floatingips_values = []
        expected_list_floatingips_calls = []

        for i in range(1, number + 1):
            float_data = number == 1 and self.float_data1 or self.float_data2
            for ip in port_data[i - 1]['fixed_ips']:
                float_data = [x for x in float_data
                              if x['fixed_ip_address'] == ip['ip_address']]
                list_floatingips_values.append({'floatingips': float_data})
                expected_list_floatingips_calls.append(
                    mock.call(fixed_ip_address=ip['ip_address'],
                              port_id=port_data[i - 1]['id']))
            subnet_data = i == 1 and self.subnet_data1 or self.subnet_data2
            list_subnets_values.append({'subnets': subnet_data})
            expected_list_subnets_calls.append(
                mock.call(id=['my_subid%s' % i]))
            list_ports_values.append({'ports': []})
            expected_list_ports_calls.append(mock.call(
                network_id=subnet_data[0]['network_id'],
                device_owner='network:dhcp'))

        mocked_client.list_ports.side_effect = list_ports_values
        mocked_client.list_subnets.side_effect = list_subnets_values
        mocked_client.list_floatingips.side_effect = list_floatingips_values

        self.instance['info_cache'] = self._fake_instance_info_cache(
            net_info_cache, self.instance['uuid'])
        mock_cache_get.return_value = self.instance['info_cache']
        instance = self._fake_instance_object_with_info_cache(self.instance)

        nw_inf = self.api.get_instance_nw_info(self.context, instance)

        mock_get_client.assert_any_call(mock.ANY, admin=True)
        mock_cache_update.assert_called_once_with(
            mock.ANY, self.instance['uuid'], mock.ANY)
        mock_cache_get.assert_called_once_with(mock.ANY, self.instance['uuid'])
        mocked_client.list_ports.assert_has_calls(expected_list_ports_calls)
        self.assertEqual(len(expected_list_ports_calls),
                         mocked_client.list_ports.call_count)
        mocked_client.list_subnets.assert_has_calls(
            expected_list_subnets_calls)
        self.assertEqual(len(expected_list_subnets_calls),
                         mocked_client.list_subnets.call_count)
        mocked_client.list_floatingips.assert_has_calls(
            expected_list_floatingips_calls)
        self.assertEqual(len(expected_list_floatingips_calls),
                         mocked_client.list_floatingips.call_count)
        mocked_client.list_networks.assert_called_once_with(id=net_ids)

        for i in range(0, number):
            self._verify_nw_info(nw_inf, i)

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

    def test_get_instance_nw_info_1(self):
        # Test to get one port in one network and subnet.
        self._test_get_instance_nw_info(1)

    def test_get_instance_nw_info_2(self):
        # Test to get one port in each of two networks and subnets.
        self._test_get_instance_nw_info(2)

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

        self._test_get_instance_nw_info_helper(
            network_cache, self.port_data2, networks=self.nets2,
            port_ids=[self.port_data2[1]['id']])

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

        self._test_get_instance_nw_info_helper(network_cache,
                                               self.port_data2)

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

        self._test_get_instance_nw_info_helper(network_cache,
                                               port_data2)

    def test_get_instance_nw_info_ignores_neutron_ports_empty_cache(self):
        # Tests that ports returned from neutron that match the same
        # instance_id/device_id are ignored when the instance info cache is
        # empty.
        port_data2 = copy.copy(self.port_data2)

        # set device_id on the ports to be the same.
        port_data2[1]['device_id'] = port_data2[0]['device_id']
        network_cache = {'info_cache': {'network_info': []}}

        self._test_get_instance_nw_info_helper(network_cache,
                                               port_data2)

    @mock.patch.object(db_api, 'instance_info_cache_get')
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def _test_get_instance_nw_info_helper(self, network_cache,
                                          current_neutron_ports,
                                          mock_get_client,
                                          mock_cache_update, mock_cache_get,
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
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client

        list_ports_values = [{'ports': current_neutron_ports}]
        expected_list_ports_calls = [
            mock.call(tenant_id=self.instance['project_id'],
                      device_id=self.instance['uuid'])]

        ifaces = network_cache['info_cache']['network_info']

        if port_ids is None:
            port_ids = [iface['id'] for iface in ifaces]
            net_ids = [iface['network']['id'] for iface in ifaces]
            nets = [{'id': iface['network']['id'],
                     'name': iface['network']['label'],
                     'tenant_id': iface['network']['meta']['tenant_id']}
                    for iface in ifaces]

        if networks is None:
            list_networks_values = []
            expected_list_networks_calls = []
            if ifaces:
                list_networks_values.append({'networks': nets})
                expected_list_networks_calls.append(mock.call(id=net_ids))
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
                list_networks_values.extend([
                    {'networks': non_shared_nets}, {'networks': shared_nets}])
                expected_list_networks_calls.extend([
                    mock.call(shared=False,
                              tenant_id=self.instance['project_id']),
                    mock.call(shared=True)])
            mocked_client.list_networks.side_effect = list_networks_values
        else:
            port_ids = [iface['id'] for iface in ifaces] + port_ids

        index = 0

        current_neutron_port_map = {}
        for current_neutron_port in current_neutron_ports:
            current_neutron_port_map[current_neutron_port['id']] = (
                current_neutron_port)

        list_floatingips_values = []
        expected_list_floatingips_calls = []
        list_subnets_values = []
        expected_list_subnets_calls = []

        for port_id in port_ids:
            current_neutron_port = current_neutron_port_map.get(port_id)
            if current_neutron_port:
                for ip in current_neutron_port['fixed_ips']:
                    list_floatingips_values.append(
                        {'floatingips': [self.float_data2[index]]})
                    expected_list_floatingips_calls.append(
                        mock.call(fixed_ip_address=ip['ip_address'],
                                  port_id=current_neutron_port['id']))
                    list_subnets_values.append(
                        {'subnets': [self.subnet_data_n[index]]})
                    expected_list_subnets_calls.append(
                        mock.call(id=[ip['subnet_id']]))
                    list_ports_values.append({'ports': self.dhcp_port_data1})
                    expected_list_ports_calls.append(
                        mock.call(
                            network_id=current_neutron_port['network_id'],
                            device_owner='network:dhcp'))
                    index += 1

        mocked_client.list_floatingips.side_effect = list_floatingips_values
        mocked_client.list_subnets.side_effect = list_subnets_values
        mocked_client.list_ports.side_effect = list_ports_values

        self.instance['info_cache'] = self._fake_instance_info_cache(
            network_cache['info_cache']['network_info'], self.instance['uuid'])
        mock_cache_get.return_value = self.instance['info_cache']

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

        mock_get_client.assert_any_call(mock.ANY, admin=True)
        mock_cache_update.assert_called_once_with(
            mock.ANY, self.instance['uuid'], mock.ANY)
        mock_cache_get.assert_called_once_with(mock.ANY, self.instance['uuid'])

        if networks is None:
            mocked_client.list_networks.assert_has_calls(
                expected_list_networks_calls)
            self.assertEqual(len(expected_list_networks_calls),
                             mocked_client.list_networks.call_count)

        mocked_client.list_floatingips.assert_has_calls(
            expected_list_floatingips_calls)
        self.assertEqual(len(expected_list_floatingips_calls),
                         mocked_client.list_floatingips.call_count)
        mocked_client.list_subnets.assert_has_calls(
            expected_list_subnets_calls)
        self.assertEqual(len(expected_list_subnets_calls),
                         mocked_client.list_subnets.call_count)
        mocked_client.list_ports.assert_has_calls(
            expected_list_ports_calls)
        self.assertEqual(len(expected_list_ports_calls),
                         mocked_client.list_ports.call_count)

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info',
                       return_value=(None, False))
    @mock.patch.object(db_api, 'instance_info_cache_get')
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def test_get_instance_nw_info_without_subnet(
            self, mock_get_client, mock_cache_update, mock_cache_get,
            mock_get_physnet):
        # Test get instance_nw_info for a port without subnet.
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        mocked_client.list_ports.return_value = {'ports': self.port_data3}
        mocked_client.list_networks.return_value = {'networks': self.nets1}

        net_info_cache = []
        for port in self.port_data3:
            net_info_cache.append({"network": {"id": port['network_id']},
                                   "id": port['id']})
        self.instance['info_cache'] = self._fake_instance_info_cache(
            net_info_cache, self.instance['uuid'])
        mock_cache_get.return_value = self.instance['info_cache']

        instance = self._fake_instance_object_with_info_cache(self.instance)
        nw_inf = self.api.get_instance_nw_info(self.context, instance)

        id_suffix = 3
        self.assertEqual(0, len(nw_inf.fixed_ips()))
        self.assertEqual('my_netname1', nw_inf[0]['network']['label'])
        self.assertEqual(uuids.portid_3, nw_inf[0]['id'])
        self.assertEqual('my_mac%s' % id_suffix, nw_inf[0]['address'])
        self.assertEqual(0, len(nw_inf[0]['network']['subnets']))

        mock_get_client.assert_has_calls([mock.call(mock.ANY, admin=True)] * 2,
                                         any_order=True)
        mock_cache_update.assert_called_once_with(
            mock.ANY, self.instance['uuid'], mock.ANY)
        mock_cache_get.assert_called_once_with(mock.ANY, self.instance['uuid'])
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid'])
        mocked_client.list_networks.assert_called_once_with(
            id=[self.port_data1[0]['network_id']])
        mock_get_physnet.assert_called_once_with(
            mock.ANY, mock.ANY, self.port_data1[0]['network_id'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_refresh_neutron_extensions_cache(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        mocked_client.list_extensions.return_value = {
            'extensions': [{'name': constants.QOS_QUEUE}]}
        self.api._refresh_neutron_extensions_cache(self.context)
        self.assertEqual(
            {constants.QOS_QUEUE: {'name': constants.QOS_QUEUE}},
            self.api.extensions)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_extensions.assert_called_once_with()

    @mock.patch.object(neutronapi, 'get_client')
    def test_populate_neutron_extension_values_rxtx_factor(
            self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        mocked_client.list_extensions.return_value = {
            'extensions': [{'name': constants.QOS_QUEUE}]}
        flavor = objects.Flavor.get_by_name(self.context, 'm1.small')
        flavor['rxtx_factor'] = 1
        instance = objects.Instance(system_metadata={})
        instance.flavor = flavor
        port_req_body = {'port': {}}
        self.api._populate_neutron_extension_values(self.context, instance,
                                                    None, port_req_body)
        self.assertEqual(1, port_req_body['port']['rxtx_factor'])
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_extensions.assert_called_once_with()

    def test_allocate_for_instance_1(self):
        # Allocate one port in one network env.
        self._test_allocate_for_instance_with_virtual_interface(1)

    def test_allocate_for_instance_2(self):
        # Allocate one port in two networks env.
        self._test_allocate_for_instance(
            net_idx=2, exception=exception.NetworkAmbiguous)

    def test_allocate_for_instance_accepts_only_portid(self):
        # Make sure allocate_for_instance works when only a portid is provided
        self._returned_nw_info = self.port_data1
        result, _ = self._test_allocate_for_instance_with_virtual_interface(
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

    def test_allocate_for_instance_without_requested_networks(self):
        self._test_allocate_for_instance(
            net_idx=3, exception=exception.NetworkAmbiguous)

    def test_allocate_for_instance_with_requested_non_available_network(self):
        """verify that a non available network is ignored.
        self.nets2 (net_idx=2) is composed of self.nets3[0] and self.nets3[1]
        Do not create a port on a non available network self.nets3[2].
       """
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets3[0], self.nets3[2], self.nets3[1])])
        requested_networks[0].tag = 'foo'
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=2, requested_networks=requested_networks)
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
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=3, requested_networks=requested_networks)

    def test_allocate_for_instance_with_no_subnet_defined(self):
        # net_id=4 does not specify subnet and does not set the option
        # port_security_disabled to True, so Neutron will not been
        # able to associate the default security group to the port
        # requested to be created. We expect an exception to be
        # raised.
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=4, exception=exception.SecurityGroupCannotBeApplied,
            _break='post_list_extensions')

    def test_allocate_for_instance_with_invalid_network_id(self):
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(
                network_id=uuids.non_existent_uuid)])
        self._test_allocate_for_instance(net_idx=9,
            requested_networks=requested_networks,
            exception=exception.NetworkNotFound,
            _break='post_list_networks')

    def test_allocate_for_instance_with_requested_networks_with_fixedip(self):
        # specify only first and last network
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=self.nets1[0]['id'],
                                            address='10.0.1.0')])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=1, requested_networks=requested_networks)

    def test_allocate_for_instance_with_requested_networks_with_port(self):
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=1, requested_networks=requested_networks)

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_for_instance_no_networks(self, mock_get_client):
        """verify the exception thrown when there are no networks defined."""
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        mocked_client.list_networks.return_value = {
            'networks': model.NetworkInfo([])}
        nwinfo = self.api.allocate_for_instance(self.context, self.instance,
                                                None)
        self.assertEqual(0, len(nwinfo))
        mock_get_client.assert_has_calls([
            mock.call(self.context),
            mock.call(self.context, admin=True)])
        mocked_client.list_networks.assert_has_calls([
            mock.call(tenant_id=self.instance.project_id, shared=False),
            mock.call(shared=True)])
        self.assertEqual(2, mocked_client.list_networks.call_count)

    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.network.neutron.API._populate_neutron_extension_values')
    @mock.patch('nova.network.neutron.API._create_ports_for_instance')
    @mock.patch('nova.network.neutron.API._unbind_ports')
    def test_allocate_for_instance_ex1(self, mock_unbind, mock_create_ports,
            mock_populate, mock_get_client):
        """Verify we will delete created ports if we fail to allocate all net
        resources.

        We mock to raise an exception when creating a second port.  In this
        case, the code should delete the first created port.
        """
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets2[0], self.nets2[1])])
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        mocked_client.list_networks.return_value = {'networks': self.nets2}
        mock_create_ports.return_value = [
            (request, (getattr(uuids, 'portid_%s' % request.network_id)))
            for request in requested_networks
        ]
        index = 0
        update_port_values = []
        expected_update_port_calls = []
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
                update_port_values.append({'port': port})
            else:
                update_port_values.append(exceptions.MacAddressInUseClient())
            expected_update_port_calls.append(mock.call(
                port_id, binding_port_req_body))
            index += 1
        mocked_client.update_port.side_effect = update_port_values

        self.assertRaises(exception.PortInUse,
                          self.api.allocate_for_instance,
                          self.context, self.instance,
                          requested_networks=requested_networks)
        mock_unbind.assert_called_once_with(self.context, [],
                                            mocked_client, mock.ANY)
        mock_get_client.assert_has_calls([
            mock.call(self.context),
            mock.call(self.context, admin=True)], any_order=True)
        mocked_client.list_networks.assert_called_once_with(
            id=[uuids.my_netid1, uuids.my_netid2])
        mocked_client.update_port.assert_has_calls(expected_update_port_calls)
        self.assertEqual(len(expected_update_port_calls),
                         mocked_client.update_port.call_count)
        mocked_client.delete_port.assert_has_calls([
            mock.call(getattr(uuids, 'portid_%s' % self.nets2[0]['id'])),
            mock.call(getattr(uuids, 'portid_%s' % self.nets2[1]['id']))])
        self.assertEqual(2, mocked_client.delete_port.call_count)

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_for_instance_ex2(self, mock_get_client):
        """verify we have no port to delete
        if we fail to allocate the first net resource.

        Mock to raise exception when creating the first port.
        In this case, the code should not delete any ports.
        """
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets2[0], self.nets2[1])])
        mocked_client.list_networks.return_value = {'networks': self.nets2}
        port_req_body = {
            'port': {
                'network_id': self.nets2[0]['id'],
                'admin_state_up': True,
                'device_id': self.instance.uuid,
                'tenant_id': self.instance.project_id,
            },
        }
        mocked_client.create_port.side_effect = Exception(
            "fail to create port")
        self.assertRaises(NEUTRON_CLIENT_EXCEPTION,
                          self.api.allocate_for_instance,
                          self.context, self.instance,
                          requested_networks=requested_networks)
        mock_get_client.assert_has_calls([
            mock.call(self.context),
            mock.call(self.context, admin=True)])
        mocked_client.list_networks.assert_called_once_with(
            id=[uuids.my_netid1, uuids.my_netid2])
        mocked_client.create_port.assert_called_once_with(port_req_body)

    @mock.patch.object(neutronapi.API, '_get_available_networks')
    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_for_instance_no_port_or_network(
            self, mock_get_client, mock_get_available):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        # Make sure we get an empty list and then bail out of the rest
        # of the function
        mock_get_available.side_effect = test.TestingException
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest()])
        self.assertRaises(test.TestingException,
                          self.api.allocate_for_instance, self.context,
                          self.instance, requested_networks)
        mock_get_client.assert_has_calls([
            mock.call(self.context),
            mock.call(self.context, admin=True)])
        mock_get_available.assert_called_once_with(
            self.context, self.instance.project_id, [],
            neutron=mocked_client, auto_allocate=False)

    def test_allocate_for_instance_second_time(self):
        # Make sure that allocate_for_instance only returns ports that it
        # allocated during _that_ run.
        new_port = {'id': uuids.fake}
        self._returned_nw_info = self.port_data1 + [new_port]
        nw_info, _ = self._test_allocate_for_instance_with_virtual_interface()
        self.assertEqual([new_port], nw_info)

    def test_allocate_for_instance_port_in_use(self):
        # If a port is already in use, an exception should be raised.
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._test_allocate_for_instance(
            requested_networks=requested_networks,
            exception=exception.PortInUse, _break='pre_list_networks',
            _device=True)

    def test_allocate_for_instance_port_not_found(self):
        # If a port is not found, an exception should be raised.
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.non_existent_uuid)])
        self._test_allocate_for_instance(
            requested_networks=requested_networks,
            exception=exception.PortNotFound,
            _break='pre_list_networks')

    def test_allocate_for_instance_port_invalid_tenantid(self):
        self.tenant_id = 'invalid_id'
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._test_allocate_for_instance(
            requested_networks=requested_networks,
            exception=exception.PortNotUsable,
            _break='pre_list_networks')

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_for_instance_with_externalnet_forbidden(
            self, mock_get_client):
        """Only one network is available, it's external, and the client
           is unauthorized to use it.
        """
        rules = {'network:attach_external_network': 'is_admin:True'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        mocked_client.list_networks.side_effect = [
            # no networks in the tenant
            {'networks': model.NetworkInfo([])},
            # external network is shared
            {'networks': self.nets8}]
        self.assertRaises(exception.ExternalNetworkAttachForbidden,
                          self.api.allocate_for_instance, self.context,
                          self.instance, None)
        mock_get_client.assert_has_calls([
            mock.call(self.context),
            mock.call(self.context, admin=True)])
        mocked_client.list_networks.assert_has_calls([
            mock.call(tenant_id=self.instance.project_id, shared=False),
            mock.call(shared=True)])
        self.assertEqual(2, mocked_client.list_networks.call_count)

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_for_instance_with_externalnet_multiple(
            self, mock_get_client):
        """Multiple networks are available, one the client is authorized
           to use, and an external one the client is unauthorized to use.
        """
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        mocked_client.list_networks.side_effect = [
            # network found in the tenant
            {'networks': self.nets1},
            # external network is shared
            {'networks': self.nets8}]
        self.assertRaises(
            exception.NetworkAmbiguous,
            self.api.allocate_for_instance,
            self.context, self.instance, None)
        mock_get_client.assert_has_calls([
            mock.call(self.context),
            mock.call(self.context, admin=True)])
        mocked_client.list_networks.assert_has_calls([
            mock.call(tenant_id=self.instance.project_id, shared=False),
            mock.call(shared=True)])
        self.assertEqual(2, mocked_client.list_networks.call_count)

    def test_allocate_for_instance_with_externalnet_admin_ctx(self):
        """Only one network is available, it's external, and the client
           is authorized.
        """
        admin_ctx = context.RequestContext('userid', uuids.my_tenant,
                                           is_admin=True)
        self._test_allocate_for_instance(net_idx=8, context=admin_ctx)

    def test_allocate_for_instance_with_external_shared_net(self):
        """Only one network is available, it's external and shared."""
        ctx = context.RequestContext('userid', uuids.my_tenant)
        self._test_allocate_for_instance(net_idx=10, context=ctx)

    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def _test_deallocate_for_instance(self, number, mock_get_client,
                                      mock_cache_update,
                                      requested_networks=None):
        # TODO(mriedem): Remove this conversion when all neutronv2 APIs are
        # converted to handling instance objects.
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        port_data = number == 1 and self.port_data1 or self.port_data2
        ports = {port['id'] for port in port_data}
        ret_data = copy.deepcopy(port_data)
        if requested_networks:
            if isinstance(requested_networks, objects.NetworkRequestList):
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
        mocked_client.list_ports.return_value = {'ports': ret_data}

        show_port_values = []
        expected_show_port_calls = []
        show_network_values = []
        expected_show_network_calls = []
        expected_update_port_calls = []
        if requested_networks:
            for net, fip, port, request_id in requested_networks:
                expected_show_port_calls.append(mock.call(
                    port, fields=['binding:profile', 'network_id']))
                show_port_values.append({'port': ret_data[0]})
                expected_show_network_calls.append(mock.call(
                    ret_data[0]['network_id'], fields=['dns_domain']))
                show_network_values.append(
                    {'network': {'id': ret_data[0]['network_id']}})
                expected_update_port_calls.append(mock.call(
                    port,
                    {'port': {
                        'device_owner': '',
                        'device_id': '',
                        'binding:host_id': None,
                        'binding:profile': {}}}))
        mocked_client.show_port.side_effect = show_port_values
        mocked_client.show_network.side_effect = show_network_values

        expected_delete_port_calls = []
        for port in ports:
            expected_delete_port_calls.append(mock.call(port))

        self.api.deallocate_for_instance(self.context, self.instance,
                                         requested_networks=requested_networks)

        mock_get_client.assert_has_calls([
            mock.call(self.context), mock.call(self.context, admin=True)],
            any_order=True)
        mocked_client.list_ports.assert_called_once_with(
            device_id=self.instance.uuid)
        mocked_client.show_port.assert_has_calls(expected_show_port_calls)
        self.assertEqual(len(expected_show_port_calls),
                         mocked_client.show_port.call_count)
        mocked_client.show_network.assert_has_calls(
            expected_show_network_calls)
        self.assertEqual(len(expected_show_network_calls),
                         mocked_client.show_network.call_count)
        mocked_client.update_port.assert_has_calls(expected_update_port_calls)
        self.assertEqual(len(expected_update_port_calls),
                         mocked_client.update_port.call_count)
        mocked_client.delete_port.assert_has_calls(expected_delete_port_calls,
                                                   any_order=True)
        self.assertEqual(len(expected_delete_port_calls),
                         mocked_client.delete_port.call_count)
        mock_cache_update.assert_called_once_with(
            self.context, self.instance.uuid, {'network_info': '[]'})

    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_1_with_requested(self, mock_preexisting):
        mock_preexisting.return_value = []
        requested = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='fake-net',
                                            address='1.2.3.4',
                                            port_id=uuids.portid_5)])
        # Test to deallocate in one port env.
        self._test_deallocate_for_instance(1, requested_networks=requested)
        mock_preexisting.assert_called_once_with(self.instance)

    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_2_with_requested(self, mock_preexisting):
        mock_preexisting.return_value = []
        requested = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='fake-net',
                                            address='1.2.3.4',
                                            port_id=uuids.portid_6)])
        # Test to deallocate in one port env.
        self._test_deallocate_for_instance(2, requested_networks=requested)
        mock_preexisting.assert_called_once_with(self.instance)

    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_1(self, mock_preexisting):
        mock_preexisting.return_value = []
        # Test to deallocate in one port env.
        self._test_deallocate_for_instance(1)
        mock_preexisting.assert_called_once_with(self.instance)

    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_2(self, mock_preexisting):
        mock_preexisting.return_value = []
        # Test to deallocate in two ports env.
        self._test_deallocate_for_instance(2)
        mock_preexisting.assert_called_once_with(self.instance)

    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    def test_deallocate_for_instance_port_not_found(self,
                                                    mock_preexisting,
                                                    mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        # TODO(mriedem): Remove this conversion when all neutronv2 APIs are
        # converted to handling instance objects.
        self.instance = fake_instance.fake_instance_obj(self.context,
                                                        **self.instance)
        mock_preexisting.return_value = []
        port_data = self.port_data1
        mocked_client.list_ports.return_value = {'ports': port_data}

        NeutronNotFound = exceptions.NeutronClientException(status_code=404)
        delete_port_values = []
        expected_delete_port_calls = []
        for port in reversed(port_data):
            delete_port_values.append(NeutronNotFound)
            expected_delete_port_calls.append(mock.call(port['id']))
        mocked_client.delete_port.side_effect = expected_delete_port_calls

        self.api.deallocate_for_instance(self.context, self.instance)

        mock_preexisting.assert_called_once_with(self.instance)
        mock_get_client.assert_has_calls([
            mock.call(self.context), mock.call(self.context, admin=True)],
            any_order=True)
        mocked_client.list_ports.assert_called_once_with(
            device_id=self.instance.uuid)
        mocked_client.delete_port.assert_has_calls(expected_delete_port_calls)
        self.assertEqual(len(expected_delete_port_calls),
                         mocked_client.delete_port.call_count)

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info',
                       return_value=(None, False))
    @mock.patch.object(db_api, 'instance_info_cache_get')
    @mock.patch.object(neutronapi, 'get_client')
    def _test_deallocate_port_for_instance(self, number, mock_get_client,
                                           mock_cache_get, mock_get_physnet):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client

        port_data = number == 1 and self.port_data1 or self.port_data2
        nets = number == 1 and self.nets1 or self.nets2
        mocked_client.show_port.return_value = {'port': port_data[0]}

        net_info_cache = []
        for port in port_data:
            net_info_cache.append({"network": {"id": port['network_id']},
                                   "id": port['id']})
        self.instance['info_cache'] = self._fake_instance_info_cache(
            net_info_cache, self.instance['uuid'])
        mocked_client.list_ports.return_value = {'ports': port_data[1:]}
        net_ids = [port['network_id'] for port in port_data]
        mocked_client.list_networks.return_value = {'networks': nets}

        list_floatingips_values = []
        expected_list_floatingips_calls = []
        float_data = number == 1 and self.float_data1 or self.float_data2
        for data in port_data[1:]:
            for ip in data['fixed_ips']:
                list_floatingips_values.append({'floatingips': float_data[1:]})
                expected_list_floatingips_calls.append(
                    mock.call(fixed_ip_address=ip['ip_address'],
                              port_id=data['id']))
        mocked_client.list_floatingips.side_effect = list_floatingips_values

        mocked_client.list_subnets.return_value = {}
        expected_list_subnets_calls = []
        for port in port_data[1:]:
            expected_list_subnets_calls.append(mock.call(id=['my_subid2']))

        mock_cache_get.return_value = self.instance['info_cache']

        instance = self._fake_instance_object_with_info_cache(self.instance)
        nwinfo, port_allocation = self.api.deallocate_port_for_instance(
            self.context, instance, port_data[0]['id'])
        self.assertEqual(len(port_data[1:]), len(nwinfo))
        if len(port_data) > 1:
            self.assertEqual(uuids.my_netid2, nwinfo[0]['network']['id'])

        mocked_client.delete_port.assert_called_once_with(port_data[0]['id'])
        mocked_client.show_port.assert_called_once_with(port_data[0]['id'])
        expected_get_client_calls = [
            mock.call(self.context), mock.call(self.context, admin=True)]
        if number == 2:
            expected_get_client_calls.append(mock.call(self.context,
                                                       admin=True))
        mock_get_client.assert_has_calls(expected_get_client_calls,
                                         any_order=True)
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid'])
        mocked_client.list_networks.assert_called_once_with(id=net_ids)
        mocked_client.list_floatingips.assert_has_calls(
            expected_list_floatingips_calls)
        self.assertEqual(len(expected_list_floatingips_calls),
                         mocked_client.list_floatingips.call_count)
        mock_cache_get.assert_called_once_with(mock.ANY, self.instance['uuid'])
        mocked_client.list_subnets.assert_has_calls(
            expected_list_subnets_calls)
        self.assertEqual(len(expected_list_subnets_calls),
                         mocked_client.list_subnets.call_count)
        if number == 2:
            mock_get_physnet.assert_called_once_with(mock.ANY, mock.ANY,
                                                     mock.ANY)
        else:
            mock_get_physnet.assert_not_called()

    def test_deallocate_port_for_instance_1(self):
        # Test to deallocate the first and only port
        self._test_deallocate_port_for_instance(1)

    def test_deallocate_port_for_instance_2(self):
        # Test to deallocate the first port of two
        self._test_deallocate_port_for_instance(2)

    @mock.patch.object(neutronapi, 'get_client')
    def test_list_ports(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        search_opts = {'parm': 'value'}

        self.api.list_ports(self.context, **search_opts)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_ports.assert_called_once_with(**search_opts)

    @mock.patch.object(neutronapi, 'get_client')
    def test_show_port(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        mocked_client.show_port.return_value = {'port': self.port_data1[0]}

        self.api.show_port(self.context, 'foo')

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_called_once_with('foo')

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = [(uuids.my_netid1, None, None, None),
                              (uuids.my_netid2, None, None, None)]
        ids = [uuids.my_netid1, uuids.my_netid2]
        mocked_client.list_networks.return_value = {'networks': self.nets2}
        mocked_client.show_quota.return_value = {'quota': {'port': 50}}
        mocked_client.list_ports.return_value = {'ports': []}

        self.api.validate_networks(self.context, requested_networks, 1)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(id=ids)
        mocked_client.show_quota.assert_called_once_with(uuids.my_tenant)
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=uuids.my_tenant, fields=['id'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_without_port_quota_on_network_side(
            self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = [(uuids.my_netid1, None, None, None),
                              (uuids.my_netid2, None, None, None)]
        ids = [uuids.my_netid1, uuids.my_netid2]
        mocked_client.list_networks.return_value = {'networks': self.nets2}
        mocked_client.show_quota.return_value = {'quota': {}}

        self.api.validate_networks(self.context, requested_networks, 1)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(id=ids)
        mocked_client.show_quota.assert_called_once_with(uuids.my_tenant)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_ex_1(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = [(uuids.my_netid1, None, None, None)]
        mocked_client.list_networks.return_value = {'networks': []}

        ex = self.assertRaises(exception.NetworkNotFound,
                               self.api.validate_networks, self.context,
                               requested_networks, 1)

        self.assertIn(uuids.my_netid1, six.text_type(ex))
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(
            id=[uuids.my_netid1])

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_ex_2(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = [(uuids.my_netid1, None, None, None),
                              (uuids.my_netid2, None, None, None),
                              (uuids.my_netid3, None, None, None)]
        ids = [uuids.my_netid1, uuids.my_netid2, uuids.my_netid3]
        mocked_client.list_networks.return_value = {'networks': self.nets1}

        ex = self.assertRaises(exception.NetworkNotFound,
                               self.api.validate_networks,
                               self.context, requested_networks, 1)

        self.assertIn(uuids.my_netid2, six.text_type(ex))
        self.assertIn(uuids.my_netid3, six.text_type(ex))
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(id=ids)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_duplicate_enable(self, mock_get_client):
        # Verify that no duplicateNetworks exception is thrown when duplicate
        # network ids are passed to validate_networks.
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(network_id=uuids.my_netid1)])
        ids = [uuids.my_netid1, uuids.my_netid1]
        mocked_client.list_networks.return_value = {'networks': self.nets1}
        mocked_client.show_quota.return_value = {'quota': {'port': 50}}
        mocked_client.list_ports.return_value = {'ports': []}

        self.api.validate_networks(self.context, requested_networks, 1)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(id=ids)
        mocked_client.show_quota.assert_called_once_with(uuids.my_tenant)
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=uuids.my_tenant, fields=['id'])

    def test_allocate_for_instance_with_requested_networks_duplicates(self):
        # specify a duplicate network to allocate to instance
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=net['id'])
                     for net in (self.nets6[0], self.nets6[1])])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=6, requested_networks=requested_networks)

    def test_allocate_for_instance_requested_networks_duplicates_port(self):
        # specify first port and last port that are in same network
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port['id'])
                     for port in (self.port_data1[0], self.port_data3[0])])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=6, requested_networks=requested_networks)

    def test_allocate_for_instance_requested_networks_duplicates_combo(self):
        # specify a combo net_idx=7 : net2, port in net1, net2, port in net1
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid2),
                     objects.NetworkRequest(port_id=self.port_data1[0]['id']),
                     objects.NetworkRequest(network_id=uuids.my_netid2),
                     objects.NetworkRequest(port_id=self.port_data3[0]['id'])])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=7, requested_networks=requested_networks)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_not_specified(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = objects.NetworkRequestList(objects=[])
        mocked_client.list_networks.side_effect = [
            {'networks': self.nets1}, {'networks': self.nets2}]
        self.assertRaises(exception.NetworkAmbiguous,
                          self.api.validate_networks,
                          self.context, requested_networks, 1)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_has_calls([
            mock.call(tenant_id=self.context.project_id, shared=False),
            mock.call(shared=True)])
        self.assertEqual(2, mocked_client.list_networks.call_count)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_port_not_found(self, mock_get_client):
        # Verify that the correct exception is thrown when a non existent
        # port is passed to validate_networks.
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(
                network_id=uuids.my_netid1,
                port_id=uuids.portid_1)])

        mocked_client.show_port.side_effect = exceptions.PortNotFoundClient
        self.assertRaises(exception.PortNotFound,
                          self.api.validate_networks,
                          self.context, requested_networks, 1)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_called_once_with(
            requested_networks[0].port_id)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_port_show_raises_non404(self, mock_get_client):
        # Verify that the correct exception is thrown when a non existent
        # port is passed to validate_networks.
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        fake_port_id = uuids.portid_1
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(
                network_id=uuids.my_netid1,
                port_id=fake_port_id)])
        mocked_client.show_port.side_effect = (
            exceptions.NeutronClientException(status_code=0))

        exc = self.assertRaises(exception.NovaException,
                                self.api.validate_networks,
                                self.context, requested_networks, 1)
        expected_exception_message = ('Failed to access port %(port_id)s: '
                                      'An unknown exception occurred.' %
                                      {'port_id': fake_port_id})
        self.assertEqual(expected_exception_message, str(exc))
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_called_once_with(
            requested_networks[0].port_id)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_port_in_use(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=self.port_data3[0]['id'])])
        mocked_client.show_port.return_value = {'port': self.port_data3[0]}

        self.assertRaises(exception.PortInUse,
                          self.api.validate_networks,
                          self.context, requested_networks, 1)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_called_once_with(
            self.port_data3[0]['id'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_port_no_subnet_id(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        port_a = self.port_data3[0]
        port_a['device_id'] = None
        port_a['device_owner'] = None

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port_a['id'])])
        mocked_client.show_port.return_value = {'port': port_a}

        self.assertRaises(exception.PortRequiresFixedIP,
                          self.api.validate_networks,
                          self.context, requested_networks, 1)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_called_once_with(port_a['id'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_no_subnet_id(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='his_netid4')])
        ids = ['his_netid4']
        mocked_client.list_networks.return_value = {'networks': self.nets4}
        self.assertRaises(exception.NetworkRequiresSubnet,
                          self.api.validate_networks,
                          self.context, requested_networks, 1)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(id=ids)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_ports_in_same_network_enable(self,
                                                            mock_get_client):
        # Verify that duplicateNetworks exception is not thrown when ports
        # on same duplicate network are passed to validate_networks.
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
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
        mocked_client.show_port.side_effect = [{'port': port_a},
                                               {'port': port_b}]

        self.api.validate_networks(self.context, requested_networks, 1)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_has_calls([mock.call(port_a['id']),
                                                  mock.call(port_b['id'])])
        self.assertEqual(2, mocked_client.show_port.call_count)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_ports_not_in_same_network(self,
                                                         mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
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
        mocked_client.show_port.side_effect = [{'port': port_a},
                                               {'port': port_b}]

        self.api.validate_networks(self.context, requested_networks, 1)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_has_calls([mock.call(port_a['id']),
                                                  mock.call(port_b['id'])])
        self.assertEqual(2, mocked_client.show_port.call_count)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_no_quota(self, mock_get_client):
        # Test validation for a request for one instance needing
        # two ports, where the quota is 2 and 2 ports are in use
        #  => instances which can be created = 0
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(network_id=uuids.my_netid2)])
        ids = [uuids.my_netid1, uuids.my_netid2]
        mocked_client.list_networks.return_value = {'networks': self.nets2}
        mocked_client.show_quota.return_value = {'quota': {'port': 2}}
        mocked_client.list_ports.return_value = {'ports': self.port_data2}

        max_count = self.api.validate_networks(self.context,
                                               requested_networks, 1)
        self.assertEqual(0, max_count)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(id=ids)
        mocked_client.show_quota.assert_called_once_with(uuids.my_tenant)
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=uuids.my_tenant, fields=['id'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_with_ports_and_networks(self, mock_get_client):
        # Test validation for a request for one instance needing
        # one port allocated via nova with another port being passed in.
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        port_b = self.port_data2[1]
        port_b['device_id'] = None
        port_b['device_owner'] = None
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(port_id=port_b['id'])])
        mocked_client.show_port.return_value = {'port': port_b}
        ids = [uuids.my_netid1]
        mocked_client.list_networks.return_value = {'networks': self.nets1}
        mocked_client.show_quota.return_value = {'quota': {'port': 5}}
        mocked_client.list_ports.return_value = {'ports': self.port_data2}

        max_count = self.api.validate_networks(self.context,
                                               requested_networks, 1)

        self.assertEqual(1, max_count)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_called_once_with(port_b['id'])
        mocked_client.list_networks.assert_called_once_with(id=ids)
        mocked_client.show_quota.assert_called_once_with(uuids.my_tenant)
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=uuids.my_tenant, fields=['id'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_one_port_and_no_networks(self, mock_get_client):
        # Test that show quota is not called if no networks are
        # passed in and only ports.
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        port_b = self.port_data2[1]
        port_b['device_id'] = None
        port_b['device_owner'] = None
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=port_b['id'])])
        mocked_client.show_port.return_value = {'port': port_b}

        max_count = self.api.validate_networks(self.context,
                                               requested_networks, 1)

        self.assertEqual(1, max_count)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_called_once_with(port_b['id'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_some_quota(self, mock_get_client):
        # Test validation for a request for two instance needing
        # two ports each, where the quota is 5 and 2 ports are in use
        #  => instances which can be created = 1
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(network_id=uuids.my_netid2)])
        ids = [uuids.my_netid1, uuids.my_netid2]
        mocked_client.list_networks.return_value = {'networks': self.nets2}
        mocked_client.show_quota.return_value = {'quota': {'port': 5}}
        mocked_client.list_ports.return_value = {'ports': self.port_data2}

        max_count = self.api.validate_networks(self.context,
                                               requested_networks, 2)

        self.assertEqual(1, max_count)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(id=ids)
        mocked_client.show_quota.assert_called_once_with(uuids.my_tenant)
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=uuids.my_tenant, fields=['id'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_unlimited_quota(self, mock_get_client):
        # Test validation for a request for two instance needing
        # two ports each, where the quota is -1 (unlimited)
        #  => instances which can be created = 1
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=uuids.my_netid1),
                     objects.NetworkRequest(network_id=uuids.my_netid2)])
        ids = [uuids.my_netid1, uuids.my_netid2]
        mocked_client.list_networks.return_value = {'networks': self.nets2}
        mocked_client.show_quota.return_value = {'quota': {'port': -1}}

        max_count = self.api.validate_networks(self.context,
                                               requested_networks, 2)

        self.assertEqual(2, max_count)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(id=ids)
        mocked_client.show_quota.assert_called_once_with(uuids.my_tenant)

    @mock.patch.object(neutronapi, 'get_client')
    def test_validate_networks_no_quota_but_ports_supplied(self,
                                                           mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
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
        mocked_client.show_port.side_effect = [{'port': port_a},
                                               {'port': port_b}]

        max_count = self.api.validate_networks(self.context,
                                               requested_networks, 1)

        self.assertEqual(1, max_count)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_port.assert_has_calls([mock.call(port_a['id']),
                                                  mock.call(port_b['id'])])
        self.assertEqual(2, mocked_client.show_port.call_count)

    @mock.patch.object(neutronapi, 'get_client')
    def _test_get_fixed_ip_by_address_with_exception(self, mock_get_client,
                                                     port_data=None,
                                                     exception=None):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        if port_data is None:
            port_data = self.port_data2
        mocked_client.list_ports.return_value = {'ports': port_data}

        result = None
        if exception:
            self.assertRaises(exception, self.api.get_fixed_ip_by_address,
                              self.context, self.port_address)
        else:
            result = self.api.get_fixed_ip_by_address(self.context,
                                                      self.port_address)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_ports.assert_called_once_with(
            fixed_ips='ip_address=%s' % self.port_address)

        return result

    def test_get_fixed_ip_by_address_fails_for_no_ports(self):
        self._test_get_fixed_ip_by_address_with_exception(
            port_data=[], exception=exception.FixedIpNotFoundForAddress)

    def test_get_fixed_ip_by_address_succeeds_for_1_port(self):
        result = self._test_get_fixed_ip_by_address_with_exception(
            port_data=self.port_data1)
        self.assertEqual(self.instance2['uuid'], result['instance_uuid'])

    def test_get_fixed_ip_by_address_fails_for_more_than_1_port(self):
        self._test_get_fixed_ip_by_address_with_exception(
            exception=exception.FixedIpAssociatedWithMultipleInstances)

    @mock.patch.object(neutronapi, 'get_client')
    def _test_get_available_networks(self, prv_nets, pub_nets, mock_get_client,
                                     req_ids=None, context=None):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        nets = prv_nets + pub_nets
        if req_ids:
            mocked_client.list_networks.return_value = {'networks': nets}
        else:
            mocked_client.list_networks.side_effect = [{'networks': prv_nets},
                                                       {'networks': pub_nets}]

        rets = self.api._get_available_networks(
            context if context else self.context,
            self.instance['project_id'],
            req_ids)

        self.assertEqual(nets, rets)
        mock_get_client.assert_called_once_with(self.context)
        if req_ids:
            mocked_client.list_networks.assert_called_once_with(id=req_ids)
        else:
            mocked_client.list_networks.assert_has_calls([
                mock.call(tenant_id=self.instance['project_id'], shared=False),
                mock.call(shared=True)])
            self.assertEqual(2, mocked_client.list_networks.call_count)

    def test_get_available_networks_all_private(self):
        self._test_get_available_networks(self.nets2, [])

    def test_get_available_networks_all_public(self):
        self._test_get_available_networks([], self.nets2)

    def test_get_available_networks_private_and_public(self):
        self._test_get_available_networks(self.nets1, self.nets4)

    def test_get_available_networks_with_network_ids(self):
        prv_nets = [self.nets3[0]]
        pub_nets = [self.nets3[-1]]
        # specify only first and last network
        req_ids = [net['id'] for net in (self.nets3[0], self.nets3[-1])]
        self._test_get_available_networks(prv_nets, pub_nets, req_ids=req_ids)

    def test_get_available_networks_with_custom_policy(self):
        rules = {'network:attach_external_network': ''}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        req_ids = [net['id'] for net in self.nets5]
        self._test_get_available_networks(self.nets5, [],
                                          req_ids=req_ids)

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_floating_ip_pools(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        search_opts = {'router:external': True}
        mocked_client.list_networks.return_value = {
            'networks': [self.fip_pool, self.fip_pool_nova]}

        pools = self.api.get_floating_ip_pools(self.context)

        expected = [self.fip_pool, self.fip_pool_nova]
        self.assertEqual(expected, pools)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(**search_opts)

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_floating_ip_by_address_not_found(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        address = self.fip_unassociated['floating_ip_address']
        mocked_client.list_floatingips.return_value = {'floatingips': []}
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          self.api.get_floating_ip_by_address,
                          self.context, address)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_floatingips.assert_called_once_with(
            floating_ip_address=address)

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_floating_ip_by_id_not_found(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        floating_ip_id = self.fip_unassociated['id']
        mocked_client.show_floatingip.side_effect = (
            exceptions.NeutronClientException(status_code=404))
        self.assertRaises(exception.FloatingIpNotFound,
                          self.api.get_floating_ip,
                          self.context, floating_ip_id)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_floatingip.assert_called_once_with(floating_ip_id)

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_floating_ip_raises_non404(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        floating_ip_id = self.fip_unassociated['id']
        mocked_client.show_floatingip.side_effect = (
            exceptions.NeutronClientException(status_code=0))
        self.assertRaises(exceptions.NeutronClientException,
                          self.api.get_floating_ip,
                          self.context, floating_ip_id)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.show_floatingip.assert_called_once_with(floating_ip_id)

    @mock.patch.object(neutronapi.API, '_refresh_neutron_extensions_cache')
    @mock.patch.object(neutronapi, 'get_client')
    def _test_get_floating_ip(
            self, fip_ext_enabled, has_port, mock_ntrn, mock_refresh):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        # NOTE(stephenfin): These are clearly not full responses
        mock_nc.show_floatingip.return_value = {
            'floatingip': {
                'id': uuids.fip_id,
                'floating_network_id': uuids.fip_net_id,
                'port_id': uuids.fip_port_id,
            }
        }
        mock_nc.show_network.return_value = {
            'network': {
                'id': uuids.fip_net_id,
            },
        }
        if has_port:
            mock_nc.show_port.return_value = {
                'port': {
                    'id': uuids.fip_port_id,
                },
            }
        else:
            mock_nc.show_port.side_effect = exceptions.PortNotFoundClient

        if fip_ext_enabled:
            self.api.extensions = [constants.FIP_PORT_DETAILS]
        else:
            self.api.extensions = []

        fip = self.api.get_floating_ip(self.context, uuids.fip_id)

        if fip_ext_enabled:
            mock_nc.show_port.assert_not_called()
            self.assertNotIn('port_details', fip)
        else:
            mock_nc.show_port.assert_called_once_with(uuids.fip_port_id)
            self.assertIn('port_details', fip)

            if has_port:
                self.assertIsNotNone(fip['port_details'])
            else:
                self.assertIsNone(fip['port_details'])

    def test_get_floating_ip_with_fip_port_details_ext(self):
        """Make sure we used embedded port details if available."""
        self._test_get_floating_ip(True, True)

    def test_get_floating_ip_without_fip_port_details_ext(self):
        """Make sure we make a second request for port details if necessary."""
        self._test_get_floating_ip(False, True)

    def test_get_floating_ip_without_port(self):
        """Make sure we don't fail for floating IPs without attached ports."""
        self._test_get_floating_ip(False, False)

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_floating_ip_by_address_multiple_found(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        address = self.fip_unassociated['floating_ip_address']
        mocked_client.list_floatingips.return_value = {
            'floatingips': [self.fip_unassociated] * 2}
        self.assertRaises(exception.FloatingIpMultipleFoundForAddress,
                          self.api.get_floating_ip_by_address,
                          self.context, address)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_floatingips.assert_called_once_with(
            floating_ip_address=address)

    @mock.patch.object(neutronapi.API, '_refresh_neutron_extensions_cache')
    @mock.patch.object(neutronapi, 'get_client')
    def _test_get_floating_ip_by_address(
            self, fip_ext_enabled, has_port, mock_ntrn, mock_refresh):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        # NOTE(stephenfin): These are clearly not full responses
        mock_nc.list_floatingips.return_value = {
            'floatingips': [
                {
                    'id': uuids.fip_id,
                    'floating_network_id': uuids.fip_net_id,
                    'port_id': uuids.fip_port_id,
                },
            ]
        }
        mock_nc.show_network.return_value = {
            'network': {
                'id': uuids.fip_net_id,
            },
        }
        if has_port:
            mock_nc.show_port.return_value = {
                'port': {
                    'id': uuids.fip_port_id,
                },
            }
        else:
            mock_nc.show_port.side_effect = exceptions.PortNotFoundClient

        if fip_ext_enabled:
            self.api.extensions = [constants.FIP_PORT_DETAILS]
        else:
            self.api.extensions = []

        fip = self.api.get_floating_ip_by_address(self.context, '172.1.2.3')

        if fip_ext_enabled:
            mock_nc.show_port.assert_not_called()
            self.assertNotIn('port_details', fip)
        else:
            mock_nc.show_port.assert_called_once_with(uuids.fip_port_id)
            self.assertIn('port_details', fip)

            if has_port:
                self.assertIsNotNone(fip['port_details'])
            else:
                self.assertIsNone(fip['port_details'])

    def test_get_floating_ip_by_address_with_fip_port_details_ext(self):
        """Make sure we used embedded port details if available."""
        self._test_get_floating_ip_by_address(True, True)

    def test_get_floating_ip_by_address_without_fip_port_details_ext(self):
        """Make sure we make a second request for port details if necessary."""
        self._test_get_floating_ip_by_address(False, True)

    def test_get_floating_ip_by_address_without_port(self):
        """Make sure we don't fail for floating IPs without attached ports."""
        self._test_get_floating_ip_by_address(False, False)

    @mock.patch.object(neutronapi, 'get_client')
    def _test_get_instance_id_by_floating_address(self, fip_data,
                                                  mock_get_client,
                                                  associated=False):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        address = fip_data['floating_ip_address']
        mocked_client.list_floatingips.return_value = {
            'floatingips': [fip_data]}
        if associated:
            mocked_client.show_port.return_value = {'port': self.port_data2[1]}
            expected = self.port_data2[1]['device_id']
        else:
            expected = None

        fip = self.api.get_instance_id_by_floating_address(self.context,
                                                           address)

        self.assertEqual(expected, fip)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_floatingips.assert_called_once_with(
            floating_ip_address=address)
        if associated:
            mocked_client.show_port.assert_called_once_with(
                fip_data['port_id'])

    def test_get_instance_id_by_floating_address(self):
        self._test_get_instance_id_by_floating_address(self.fip_unassociated)

    def test_get_instance_id_by_floating_address_associated(self):
        self._test_get_instance_id_by_floating_address(self.fip_associated,
                                                       associated=True)

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_floating_ip(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        pool_name = self.fip_pool['name']
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        mocked_client.list_networks.return_value = {
            'networks': [self.fip_pool]}
        mocked_client.create_floatingip.return_value = {
            'floatingip': self.fip_unassociated}

        fip = self.api.allocate_floating_ip(self.context, 'ext_net')

        self.assertEqual(self.fip_unassociated['floating_ip_address'], fip)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(**search_opts)
        mocked_client.create_floatingip.assert_called_once_with(
            {'floatingip': {'floating_network_id': pool_id}})

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_floating_ip_addr_gen_fail(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        pool_name = self.fip_pool['name']
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        mocked_client.list_networks.return_value = {
            'networks': [self.fip_pool]}
        mocked_client.create_floatingip.side_effect = (
            exceptions.IpAddressGenerationFailureClient)

        self.assertRaises(exception.NoMoreFloatingIps,
                          self.api.allocate_floating_ip, self.context,
                          'ext_net')
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(**search_opts)
        mocked_client.create_floatingip.assert_called_once_with(
            {'floatingip': {'floating_network_id': pool_id}})

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_floating_ip_exhausted_fail(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        pool_name = self.fip_pool['name']
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        mocked_client.list_networks.return_value = {
            'networks': [self.fip_pool]}
        mocked_client.create_floatingip.side_effect = (
            exceptions.ExternalIpAddressExhaustedClient)

        self.assertRaises(exception.NoMoreFloatingIps,
                          self.api.allocate_floating_ip, self.context,
                          'ext_net')
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(**search_opts)
        mocked_client.create_floatingip.assert_called_once_with(
            {'floatingip': {'floating_network_id': pool_id}})

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_floating_ip_with_pool_id(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'id': pool_id}
        mocked_client.list_networks.return_value = {
            'networks': [self.fip_pool]}
        mocked_client.create_floatingip.return_value = {
            'floatingip': self.fip_unassociated}

        fip = self.api.allocate_floating_ip(self.context, pool_id)

        self.assertEqual(self.fip_unassociated['floating_ip_address'], fip)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(**search_opts)
        mocked_client.create_floatingip.assert_called_once_with(
            {'floatingip': {'floating_network_id': pool_id}})

    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_floating_ip_with_default_pool(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        pool_name = self.fip_pool_nova['name']
        pool_id = self.fip_pool_nova['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        mocked_client.list_networks.return_value = {
            'networks': [self.fip_pool_nova]}
        mocked_client.create_floatingip.return_value = {
            'floatingip': self.fip_unassociated}

        fip = self.api.allocate_floating_ip(self.context)

        self.assertEqual(self.fip_unassociated['floating_ip_address'], fip)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_networks.assert_called_once_with(**search_opts)
        mocked_client.create_floatingip.assert_called_once_with(
            {'floatingip': {'floating_network_id': pool_id}})

    @mock.patch.object(neutronapi, 'get_client')
    def test_disassociate_and_release_floating_ip(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        address = self.fip_unassociated['floating_ip_address']
        fip_id = self.fip_unassociated['id']
        floating_ip = {'floating_ip_address': address}
        mocked_client.list_floatingips.return_value = {
            'floatingips': [self.fip_unassociated]}

        self.api.disassociate_and_release_floating_ip(self.context, None,
                                                      floating_ip)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_floatingips.assert_called_once_with(
            floating_ip_address=address)
        mocked_client.delete_floatingip.assert_called_once_with(fip_id)

    @mock.patch.object(neutronapi.API, '_get_instance_nw_info',
                       return_value=model.NetworkInfo())
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def test_disassociate_and_release_floating_ip_with_instance(
            self, mock_get_client, mock_cache_update, mock_get_nw):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        address = self.fip_unassociated['floating_ip_address']
        fip_id = self.fip_unassociated['id']
        floating_ip = {'floating_ip_address': address}
        instance = self._fake_instance_object(self.instance)
        mocked_client.list_floatingips.return_value = {
            'floatingips': [self.fip_unassociated]}

        self.api.disassociate_and_release_floating_ip(self.context, instance,
                                                      floating_ip)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_floatingips.assert_called_once_with(
            floating_ip_address=address)
        mocked_client.delete_floatingip.assert_called_once_with(fip_id)
        mock_cache_update.assert_called_once_with(mock.ANY, instance['uuid'],
                                                  mock.ANY)
        mock_get_nw.assert_called_once_with(mock.ANY, instance)

    @mock.patch.object(neutronapi.API, '_get_instance_nw_info',
                       return_value=model.NetworkInfo())
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def test_associate_floating_ip(self, mock_get_client, mock_cache_update,
                                   mock_get_nw):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        address = self.fip_unassociated['floating_ip_address']
        fixed_address = self.port_address2
        fip_id = self.fip_unassociated['id']
        instance = self._fake_instance_object(self.instance)

        mocked_client.list_ports.return_value = {'ports': [self.port_data2[1]]}
        mocked_client.list_floatingips.return_value = {
            'floatingips': [self.fip_unassociated]}

        self.api.associate_floating_ip(self.context, instance,
                                       address, fixed_address)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_ports.assert_called_once_with(
            **{'device_owner': 'compute:nova', 'device_id': instance.uuid})
        mocked_client.list_floatingips.assert_called_once_with(
            floating_ip_address=address)
        mocked_client.update_floatingip.assert_called_once_with(
            fip_id, {'floatingip': {'port_id': self.fip_associated['port_id'],
                                    'fixed_ip_address': fixed_address}})
        mock_cache_update.assert_called_once_with(mock.ANY, instance['uuid'],
                                                  mock.ANY)
        mock_get_nw.assert_called_once_with(mock.ANY, instance)

    @mock.patch.object(neutronapi.API, '_get_instance_nw_info',
                       return_value=model.NetworkInfo())
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_reassociate_floating_ip(self, mock_get, mock_get_client,
                                     mock_cache_update, mock_get_nw):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        address = self.fip_associated['floating_ip_address']
        new_fixed_address = self.port_address
        fip_id = self.fip_associated['id']

        mocked_client.list_ports.return_value = {'ports': [self.port_data2[0]]}
        mocked_client.list_floatingips.return_value = {
            'floatingips': [self.fip_associated]}
        mocked_client.show_port.return_value = {'port': self.port_data2[1]}
        mock_get.return_value = fake_instance.fake_instance_obj(
            self.context, **self.instance)
        instance2 = self._fake_instance_object(self.instance2)

        self.api.associate_floating_ip(self.context, instance2,
                                       address, new_fixed_address)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_ports.assert_called_once_with(
            **{'device_owner': 'compute:nova',
               'device_id': self.instance2['uuid']})
        mocked_client.list_floatingips.assert_called_once_with(
            floating_ip_address=address)
        mocked_client.update_floatingip.assert_called_once_with(
            fip_id, {'floatingip': {'port_id': uuids.portid_1,
                                    'fixed_ip_address': new_fixed_address}})
        mocked_client.show_port.assert_called_once_with(
            self.fip_associated['port_id'])
        mock_cache_update.assert_has_calls([
            mock.call(mock.ANY, mock_get.return_value['uuid'], mock.ANY),
            mock.call(mock.ANY, instance2['uuid'], mock.ANY)])
        self.assertEqual(2, mock_cache_update.call_count)
        mock_get_nw.assert_has_calls([
            mock.call(mock.ANY, mock_get.return_value),
            mock.call(mock.ANY, instance2)])
        self.assertEqual(2, mock_get_nw.call_count)

    @mock.patch.object(neutronapi, 'get_client')
    def test_associate_floating_ip_not_found_fixed_ip(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        instance = self._fake_instance_object(self.instance)
        address = self.fip_associated['floating_ip_address']
        fixed_address = self.fip_associated['fixed_ip_address']
        mocked_client.list_ports.return_value = {'ports': [self.port_data2[0]]}

        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          self.api.associate_floating_ip, self.context,
                          instance, address, fixed_address)
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_ports.assert_called_once_with(
            **{'device_owner': 'compute:nova',
               'device_id': self.instance['uuid']})

    @mock.patch.object(neutronapi.API, '_get_instance_nw_info',
                       return_value=model.NetworkInfo())
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def test_disassociate_floating_ip(self, mock_get_client,
                                      mock_cache_update, mock_get_nw):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        instance = self._fake_instance_object(self.instance)
        address = self.fip_associated['floating_ip_address']
        fip_id = self.fip_associated['id']
        mocked_client.list_floatingips.return_value = {
            'floatingips': [self.fip_associated]}

        self.api.disassociate_floating_ip(self.context, instance, address)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_floatingips.assert_called_once_with(
            floating_ip_address=address)
        mocked_client.update_floatingip.assert_called_once_with(
            fip_id, {'floatingip': {'port_id': None}})
        mock_cache_update.assert_called_once_with(mock.ANY, instance['uuid'],
                                                  mock.ANY)
        mock_get_nw.assert_called_once_with(mock.ANY, instance)

    @mock.patch.object(neutronapi.API, '_get_instance_nw_info',
                       return_value=model.NetworkInfo())
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def test_add_fixed_ip_to_instance(self, mock_get_client,
                                      mock_cache_update, mock_get_nw):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        instance = self._fake_instance_object(self.instance)
        network_id = uuids.my_netid1
        mocked_client.list_subnets.return_value = {
            'subnets': self.subnet_data_n}
        mocked_client.list_ports.return_value = {'ports': self.port_data1}
        port_req_body = {
            'port': {
                'fixed_ips': [{'subnet_id': 'my_subid1'},
                              {'subnet_id': 'my_subid1'}],
            },
        }
        port = self.port_data1[0]
        port['fixed_ips'] = [{'subnet_id': 'my_subid1'}]
        mocked_client.update_port.return_value = {'port': port}

        self.api.add_fixed_ip_to_instance(self.context,
                                          instance,
                                          network_id)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_subnets.assert_called_once_with(
            network_id=network_id)
        mocked_client.list_ports.assert_called_once_with(
            device_id=instance.uuid, device_owner='compute:nova',
            network_id=network_id)
        mocked_client.update_port.assert_called_once_with(uuids.portid_1,
                                                          port_req_body)
        mock_cache_update.assert_called_once_with(mock.ANY, instance['uuid'],
                                                  mock.ANY)
        mock_get_nw.assert_called_once_with(mock.ANY, instance)

    @mock.patch.object(neutronapi.API, '_get_instance_nw_info',
                       return_value=model.NetworkInfo())
    @mock.patch.object(db_api, 'instance_info_cache_update',
                       return_value=fake_info_cache)
    @mock.patch.object(neutronapi, 'get_client')
    def test_remove_fixed_ip_from_instance(self, mock_get_client,
                                           mock_cache_update, mock_get_nw):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        instance = self._fake_instance_object(self.instance)
        address = '10.0.0.3'
        zone = 'compute:%s' % self.instance['availability_zone']
        mocked_client.list_ports.return_value = {'ports': self.port_data1}
        port_req_body = {
            'port': {
                'fixed_ips': [],
            },
        }
        port = self.port_data1[0]
        port['fixed_ips'] = []
        mocked_client.update_port.return_value = {'port': port}

        self.api.remove_fixed_ip_from_instance(self.context, instance,
                                               address)

        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_ports.assert_called_once_with(
            device_id=self.instance['uuid'], device_owner=zone,
            fixed_ips='ip_address=%s' % address)
        mocked_client.update_port.assert_called_once_with(uuids.portid_1,
                                                          port_req_body)
        mock_cache_update.assert_called_once_with(mock.ANY, instance['uuid'],
                                                  mock.ANY)
        mock_get_nw.assert_called_once_with(mock.ANY, instance)

    def test_list_floating_ips_without_l3_support(self):
        mocked_client = mock.create_autospec(client.Client)
        mocked_client.list_floatingips.side_effect = exceptions.NotFound

        floatingips = self.api._get_floating_ips_by_fixed_and_port(
            mocked_client, '1.1.1.1', 1)

        self.assertEqual([], floatingips)
        mocked_client.list_floatingips.assert_called_once_with(
            fixed_ip_address='1.1.1.1', port_id=1)

    @mock.patch.object(neutronapi.API, '_get_floating_ips_by_fixed_and_port')
    def test_nw_info_get_ips(self, mock_get_floating):
        mocked_client = mock.create_autospec(client.Client)
        fake_port = {
            'fixed_ips': [
                {'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            }
        mock_get_floating.return_value = [{'floating_ip_address': '10.0.0.1'}]

        result = self.api._nw_info_get_ips(mocked_client, fake_port)

        self.assertEqual(1, len(result))
        self.assertEqual('1.1.1.1', result[0]['address'])
        self.assertEqual('10.0.0.1', result[0]['floating_ips'][0]['address'])
        mock_get_floating.assert_called_once_with(mocked_client, '1.1.1.1',
                                                  'port-id')

    @mock.patch.object(neutronapi.API, '_get_subnets_from_port')
    def test_nw_info_get_subnets(self, mock_get_subnets):
        fake_port = {
            'fixed_ips': [
                {'ip_address': '1.1.1.1'},
                {'ip_address': '2.2.2.2'}],
            'id': 'port-id',
            }
        fake_subnet = model.Subnet(cidr='1.0.0.0/8')
        fake_ips = [model.IP(x['ip_address']) for x in fake_port['fixed_ips']]
        mock_get_subnets.return_value = [fake_subnet]

        subnets = self.api._nw_info_get_subnets(self.context, fake_port,
                                                fake_ips)

        self.assertEqual(1, len(subnets))
        self.assertEqual(1, len(subnets[0]['ips']))
        self.assertEqual('1.1.1.1', subnets[0]['ips'][0]['address'])
        mock_get_subnets.assert_called_once_with(self.context, fake_port, None)

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info',
                       return_value=(None, False))
    @mock.patch.object(neutronapi, 'get_client')
    def _test_nw_info_build_network(self, vif_type, mock_get_client,
                                    mock_get_physnet):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        fake_port = {
            'fixed_ips': [{'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            'network_id': 'net-id',
            'binding:vif_type': vif_type,
            }
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [{'id': 'net-id', 'name': 'foo', 'tenant_id': 'tenant',
                      'mtu': 9000}]

        net, iid = self.api._nw_info_build_network(self.context, fake_port,
                                                   fake_nets, fake_subnets)

        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id', net['id'])
        self.assertEqual('foo', net['label'])
        self.assertEqual('tenant', net.get_meta('tenant_id'))
        self.assertEqual(9000, net.get_meta('mtu'))
        self.assertEqual(CONF.flat_injected, net.get_meta('injected'))

        mock_get_client.assert_called_once_with(mock.ANY, admin=True)
        mock_get_physnet.assert_called_once_with(self.context, mocked_client,
                                                 'net-id')

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

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info',
                       return_value=(None, False))
    @mock.patch.object(neutronapi, 'get_client')
    def test_nw_info_build_no_match(self, mock_get_client, mock_get_physnet):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        fake_port = {
            'fixed_ips': [{'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            'network_id': 'net-id1',
            'tenant_id': 'tenant',
            'binding:vif_type': model.VIF_TYPE_OVS,
            }
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [{'id': 'net-id2', 'name': 'foo', 'tenant_id': 'tenant'}]
        net, iid = self.api._nw_info_build_network(self.context, fake_port,
                                                   fake_nets, fake_subnets)
        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id1', net['id'])
        self.assertEqual('tenant', net['meta']['tenant_id'])
        mock_get_client.assert_called_once_with(mock.ANY, admin=True)
        mock_get_physnet.assert_called_once_with(self.context, mocked_client,
                                                 'net-id1')

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info',
                       return_value=(None, False))
    @mock.patch.object(neutronapi, 'get_client')
    def test_nw_info_build_network_vhostuser(self, mock_get_client,
                                             mock_get_physnet):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
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
        net, iid = self.api._nw_info_build_network(self.context, fake_port,
                                                   fake_nets, fake_subnets)
        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id', net['id'])
        self.assertEqual('foo', net['label'])
        self.assertEqual('tenant', net.get_meta('tenant_id'))
        self.assertEqual(CONF.flat_injected, net.get_meta('injected'))
        self.assertEqual(CONF.neutron.ovs_bridge, net['bridge'])
        self.assertNotIn('should_create_bridge', net)
        self.assertEqual('port-id', iid)
        mock_get_client.assert_called_once_with(mock.ANY, admin=True)
        mock_get_physnet.assert_called_once_with(self.context, mocked_client,
                                                 'net-id')

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info',
                       return_value=(None, False))
    @mock.patch.object(neutronapi, 'get_client')
    def test_nw_info_build_network_vhostuser_fp(self, mock_get_client,
                                                mock_get_physnet):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
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
        net, ovs_interfaceid = self.api._nw_info_build_network(
            self.context, fake_port, fake_nets, fake_subnets)
        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id', net['id'])
        self.assertEqual('foo', net['label'])
        self.assertEqual('tenant', net.get_meta('tenant_id'))
        self.assertEqual('brqnet-id', net['bridge'])
        self.assertIsNone(ovs_interfaceid)
        mock_get_client.assert_called_once_with(mock.ANY, admin=True)
        mock_get_physnet.assert_called_once_with(self.context, mocked_client,
                                                 'net-id')

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info',
                       return_value=(None, False))
    @mock.patch.object(neutronapi, 'get_client')
    def _test_nw_info_build_custom_bridge(self, vif_type, mock_get_client,
                                          mock_get_physnet,
                                          extra_details=None):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
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
        net, iid = self.api._nw_info_build_network(self.context, fake_port,
                                                   fake_nets, fake_subnets)
        self.assertNotEqual(CONF.neutron.ovs_bridge, net['bridge'])
        self.assertEqual('custom-bridge', net['bridge'])
        mock_get_client.assert_called_once_with(mock.ANY, admin=True)
        mock_get_physnet.assert_called_once_with(self.context, mocked_client,
                                                 'net-id')

    def test_nw_info_build_custom_ovs_bridge(self):
        self._test_nw_info_build_custom_bridge(model.VIF_TYPE_OVS)

    def test_nw_info_build_custom_ovs_bridge_vhostuser(self):
        self._test_nw_info_build_custom_bridge(model.VIF_TYPE_VHOSTUSER,
                extra_details={model.VIF_DETAILS_VHOSTUSER_OVS_PLUG: True})

    def test_nw_info_build_custom_lb_bridge(self):
        self._test_nw_info_build_custom_bridge(model.VIF_TYPE_BRIDGE)

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info',
                       return_value=(None, False))
    @mock.patch.object(neutronapi.API, '_get_preexisting_port_ids',
                       return_value=['port5'])
    @mock.patch.object(neutronapi.API, '_get_subnets_from_port',
                       return_value=[model.Subnet(cidr='1.0.0.0/8')])
    @mock.patch.object(neutronapi.API, '_get_floating_ips_by_fixed_and_port',
                       return_value=[{'floating_ip_address': '10.0.0.1'}])
    @mock.patch.object(neutronapi, 'get_client')
    def test_build_network_info_model(self, mock_get_client,
                                      mock_get_floating, mock_get_subnets,
                                      mock_get_preexisting, mock_get_physnet):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
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
             constants.BINDING_PROFILE: {'pci_vendor_info': '1137:0047',
                                         'pci_slot': '0000:0a:00.1',
                                         'physical_network': 'physnet1'},
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
             constants.BINDING_PROFILE: {'pci_vendor_info': '1137:0047',
                                         'pci_slot': '0000:0a:00.2',
                                         'physical_network': 'physnet1'},
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
        fake_nets = [
            {'id': 'net-id',
             'name': 'foo',
             'tenant_id': uuids.fake,
             }
            ]
        mocked_client.list_ports.return_value = {'ports': fake_ports}

        requested_ports = [fake_ports[2], fake_ports[0], fake_ports[1],
                           fake_ports[3], fake_ports[4], fake_ports[5]]
        expected_get_floating_calls = []
        for requested_port in requested_ports:
            expected_get_floating_calls.append(mock.call(mocked_client,
                                                         '1.1.1.1',
                                                         requested_port['id']))
        expected_get_subnets_calls = []
        for requested_port in requested_ports:
            expected_get_subnets_calls.append(
                mock.call(self.context, requested_port, mocked_client))

        fake_inst.info_cache = objects.InstanceInfoCache.new(
            self.context, uuids.instance)
        fake_inst.info_cache.network_info = model.NetworkInfo.hydrate([])

        nw_infos = self.api._build_network_info_model(
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
                requested_ports[index].get(
                    constants.BINDING_PROFILE) or {},
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

        mock_get_client.assert_has_calls([
            mock.call(self.context, admin=True)] * 7, any_order=True)
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=uuids.fake, device_id=uuids.instance)
        mock_get_floating.assert_has_calls(expected_get_floating_calls)
        self.assertEqual(len(expected_get_floating_calls),
                         mock_get_floating.call_count)
        mock_get_subnets.assert_has_calls(expected_get_subnets_calls)
        self.assertEqual(len(expected_get_subnets_calls),
                         mock_get_subnets.call_count)
        mock_get_preexisting.assert_called_once_with(fake_inst)
        mock_get_physnet.assert_has_calls([
            mock.call(self.context, mocked_client, 'net-id')] * 6)

    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.network.neutron.API._nw_info_get_subnets')
    @mock.patch('nova.network.neutron.API._nw_info_get_ips')
    @mock.patch('nova.network.neutron.API._nw_info_build_network')
    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    @mock.patch('nova.network.neutron.API._gather_port_ids_and_networks')
    def test_build_network_info_model_empty(
            self, mock_gather_port_ids_and_networks,
            mock_get_preexisting_port_ids,
            mock_nw_info_build_network,
            mock_nw_info_get_ips,
            mock_nw_info_get_subnets,
            mock_get_client):
        # An empty instance info network cache should not be populated from
        # ports found in Neutron.
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
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

        mocked_client.list_ports.return_value = {'ports': fake_ports}

        mock_gather_port_ids_and_networks.return_value = ([], [])
        mock_get_preexisting_port_ids.return_value = []
        mock_nw_info_build_network.return_value = (None, None)
        mock_nw_info_get_ips.return_value = []
        mock_nw_info_get_subnets.return_value = fake_subnets

        nw_infos = self.api._build_network_info_model(
            self.context, fake_inst)

        self.assertEqual(0, len(nw_infos))
        mock_get_client.assert_called_once_with(self.context, admin=True)
        mocked_client.list_ports.assert_called_once_with(
            tenant_id=uuids.fake, device_id=uuids.instance)

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_subnets_from_port(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        port_data = copy.copy(self.port_data1[0])
        # add another IP on the same subnet and verify the subnet is deduped
        port_data['fixed_ips'].append({'ip_address': '10.0.1.3',
                                       'subnet_id': 'my_subid1'})
        subnet_data1 = copy.copy(self.subnet_data1)
        subnet_data1[0]['host_routes'] = [
            {'destination': '192.168.0.0/24', 'nexthop': '1.0.0.10'}
        ]
        mocked_client.list_subnets.return_value = {'subnets': subnet_data1}
        mocked_client.list_ports.return_value = {'ports': []}

        subnets = self.api._get_subnets_from_port(self.context, port_data)

        self.assertEqual(1, len(subnets))
        self.assertEqual(1, len(subnets[0]['routes']))
        self.assertEqual(subnet_data1[0]['host_routes'][0]['destination'],
                         subnets[0]['routes'][0]['cidr'])
        self.assertEqual(subnet_data1[0]['host_routes'][0]['nexthop'],
                         subnets[0]['routes'][0]['gateway']['address'])
        mock_get_client.assert_called_once_with(self.context)
        mocked_client.list_subnets.assert_called_once_with(
            id=[port_data['fixed_ips'][0]['subnet_id']])
        mocked_client.list_ports.assert_called_once_with(
            network_id=subnet_data1[0]['network_id'],
            device_owner='network:dhcp')

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_subnets_from_port_enabled_dhcp(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client

        port_data = copy.copy(self.port_data1[0])
        # add another IP on the same subnet and verify the subnet is deduped
        port_data['fixed_ips'].append({'ip_address': '10.0.1.3',
                                       'subnet_id': 'my_subid1'})
        subnet_data1 = copy.copy(self.subnet_data1)
        subnet_data1[0]['enable_dhcp'] = True

        mocked_client.list_subnets.return_value = {'subnets': subnet_data1}
        mocked_client.list_ports.return_value = {'ports': self.dhcp_port_data1}

        subnets = self.api._get_subnets_from_port(self.context, port_data)

        self.assertEqual(self.dhcp_port_data1[0]['fixed_ips'][0]['ip_address'],
                         subnets[0]['meta']['dhcp_server'])

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_subnets_from_port_enabled_dhcp_no_dhcp_ports(self,
            mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client

        port_data = copy.copy(self.port_data1[0])
        # add another IP on the same subnet and verify the subnet is deduped
        port_data['fixed_ips'].append({'ip_address': '10.0.1.3',
                                       'subnet_id': 'my_subid1'})
        subnet_data1 = copy.copy(self.subnet_data1)
        subnet_data1[0]['enable_dhcp'] = True

        mocked_client.list_subnets.return_value = {'subnets': subnet_data1}
        mocked_client.list_ports.return_value = {'ports': []}

        subnets = self.api._get_subnets_from_port(self.context, port_data)

        self.assertEqual(subnet_data1[0]['gateway_ip'],
                         subnets[0]['meta']['dhcp_server'])

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_physnet_tunneled_info_multi_segment(self, mock_get_client):
        test_net = {'network': {'segments':
                                    [{'provider:physical_network': 'physnet10',
                                      'provider:segmentation_id': 1000,
                                      'provider:network_type': 'vlan'},
                                     {'provider:physical_network': None,
                                      'provider:segmentation_id': 153,
                                      'provider:network_type': 'vxlan'}]}}
        test_ext_list = {'extensions':
                            [{'name': 'Multi Provider Network',
                             'alias': 'multi-segments'}]}

        mock_client = mock_get_client.return_value
        mock_client.list_extensions.return_value = test_ext_list
        mock_client.show_network.return_value = test_net
        physnet_name, tunneled = self.api._get_physnet_tunneled_info(
            self.context, mock_client, 'test-net')

        mock_client.show_network.assert_called_once_with(
            'test-net', fields='segments')
        self.assertEqual('physnet10', physnet_name)
        self.assertFalse(tunneled)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_physnet_tunneled_info_vlan_with_multi_segment_ext(
            self, mock_get_client):
        test_net = {'network': {'provider:physical_network': 'physnet10',
                                'provider:segmentation_id': 1000,
                                'provider:network_type': 'vlan'}}
        test_ext_list = {'extensions':
                            [{'name': 'Multi Provider Network',
                             'alias': 'multi-segments'}]}

        mock_client = mock_get_client.return_value
        mock_client.list_extensions.return_value = test_ext_list
        mock_client.show_network.return_value = test_net
        physnet_name, tunneled = self.api._get_physnet_tunneled_info(
            self.context, mock_client, 'test-net')

        mock_client.show_network.assert_called_with(
            'test-net', fields=['provider:physical_network',
                                'provider:network_type'])
        self.assertEqual('physnet10', physnet_name)
        self.assertFalse(tunneled)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_physnet_tunneled_info_multi_segment_no_physnet(
            self, mock_get_client):
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

        mock_client = mock_get_client.return_value
        mock_client.list_extensions.return_value = test_ext_list
        mock_client.show_network.return_value = test_net
        self.assertRaises(exception.NovaException,
                          self.api._get_physnet_tunneled_info,
                          self.context, mock_client, 'test-net')

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_physnet_tunneled_info_tunneled(
            self, mock_get_client):
        test_net = {'network': {'provider:network_type': 'vxlan'}}
        test_ext_list = {'extensions': []}

        mock_client = mock_get_client.return_value
        mock_client.list_extensions.return_value = test_ext_list
        mock_client.show_network.return_value = test_net
        physnet_name, tunneled = self.api._get_physnet_tunneled_info(
            self.context, mock_client, 'test-net')

        mock_client.show_network.assert_called_once_with(
            'test-net', fields=['provider:physical_network',
                                'provider:network_type'])
        self.assertTrue(tunneled)
        self.assertIsNone(physnet_name)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_phynet_tunneled_info_non_tunneled(
            self, mock_get_client):
        test_net = {'network': {'provider:network_type': 'vlan'}}
        test_ext_list = {'extensions': []}

        mock_client = mock_get_client.return_value
        mock_client.list_extensions.return_value = test_ext_list
        mock_client.show_network.return_value = test_net
        physnet_name, tunneled = self.api._get_physnet_tunneled_info(
            self.context, mock_client, 'test-net')

        mock_client.show_network.assert_called_once_with(
            'test-net', fields=['provider:physical_network',
                                'provider:network_type'])
        self.assertFalse(tunneled)
        self.assertIsNone(physnet_name)

    def _test_get_port_vnic_info(self, mock_get_client,
                                 binding_vnic_type,
                                 expected_vnic_type,
                                 port_resource_request=None):
        test_port = {
            'port': {'id': 'my_port_id2',
                      'network_id': 'net-id',
                      },
            }

        if binding_vnic_type:
            test_port['port']['binding:vnic_type'] = binding_vnic_type
        if port_resource_request:
            test_port['port'][
                constants.RESOURCE_REQUEST] = port_resource_request

        mock_get_client.reset_mock()
        mock_client = mock_get_client.return_value
        mock_client.show_port.return_value = test_port

        vnic_type, trusted, network_id, resource_request = (
            self.api._get_port_vnic_info(
                self.context, mock_client, test_port['port']['id']))

        mock_client.show_port.assert_called_once_with(test_port['port']['id'],
            fields=['binding:vnic_type', 'binding:profile', 'network_id',
                    constants.RESOURCE_REQUEST])
        self.assertEqual(expected_vnic_type, vnic_type)
        self.assertEqual('net-id', network_id)
        self.assertIsNone(trusted)
        self.assertEqual(port_resource_request, resource_request)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.MagicMock())
    def test_get_port_vnic_info_1(self, mock_get_client):
        self._test_get_port_vnic_info(mock_get_client, model.VNIC_TYPE_DIRECT,
                                      model.VNIC_TYPE_DIRECT)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_port_vnic_info_2(self, mock_get_client):
        self._test_get_port_vnic_info(mock_get_client, model.VNIC_TYPE_NORMAL,
                                      model.VNIC_TYPE_NORMAL)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_port_vnic_info_3(self, mock_get_client):
        self._test_get_port_vnic_info(mock_get_client, None,
                                      model.VNIC_TYPE_NORMAL)

    @mock.patch.object(neutronapi, 'get_client')
    def test_get_port_vnic_info_requested_resources(self, mock_get_client):
        self._test_get_port_vnic_info(
            mock_get_client, None, model.VNIC_TYPE_NORMAL,
            port_resource_request={
                "resources": {
                    "NET_BW_EGR_KILOBIT_PER_SEC": 6000,
                    "NET_BW_IGR_KILOBIT_PER_SEC": 6000,
                     },
                "required": [
                    "CUSTOM_PHYSNET_PHYSNET0",
                    "CUSTOM_VNIC_TYPE_NORMAL"
                ]
            }
        )

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_get_port_vnic_info_trusted(self, mock_get_client):
        test_port = {
            'port': {'id': 'my_port_id1',
                     'network_id': 'net-id',
                     'binding:vnic_type': model.VNIC_TYPE_DIRECT,
                     'binding:profile': {"trusted": "Yes"},
            },
        }
        test_ext_list = {'extensions': []}

        mock_client = mock_get_client.return_value
        mock_client.show_port.return_value = test_port
        mock_client.list_extensions.return_value = test_ext_list
        result = self.api._get_port_vnic_info(
            self.context, mock_client, test_port['port']['id'])
        vnic_type, trusted, network_id, resource_requests = result

        mock_client.show_port.assert_called_once_with(test_port['port']['id'],
            fields=['binding:vnic_type', 'binding:profile', 'network_id',
                    constants.RESOURCE_REQUEST])
        self.assertEqual(model.VNIC_TYPE_DIRECT, vnic_type)
        self.assertEqual('net-id', network_id)
        self.assertTrue(trusted)
        self.assertIsNone(resource_requests)

    @mock.patch('nova.network.neutron.API._show_port')
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

    @mock.patch('nova.network.neutron.API._show_port')
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

    @mock.patch('nova.network.neutron.LOG')
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
    @mock.patch('nova.network.neutron.update_instance_cache_with_nw_info')
    def test_get_instance_nw_info(self, mock_update, mock_get, mock_lock):
        fake_result = mock.sentinel.get_nw_info_result
        mock_get.return_value = fake_result
        instance = fake_instance.fake_instance_obj(self.context)
        result = self.api.get_instance_nw_info(self.context, instance)
        mock_get.assert_called_once_with(self.context, instance)
        mock_update.assert_called_once_with(self.api, self.context, instance,
                                            nw_info=fake_result)
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
            show_quota_mock.assert_called_once_with(uuids.my_tenant)

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

                            ({'tenant_id': uuids.my_tenant, 'fields': ['id']},
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
                  'tenant_id': uuids.my_tenant}]

        requested_networks = [(uuids.my_netid1, '10.0.1.2', None, None)]
        ids = [uuids.my_netid1]
        list_port_values = [({'network_id': uuids.my_netid1,
                              'fixed_ips': 'ip_address=10.0.1.2',
                              'fields': 'device_id'},
                             {'ports': []}),
                            ({'tenant_id': uuids.my_tenant, 'fields': ['id']},
                             {'ports': []})]
        self._test_validate_networks_fixed_ip_no_dup(nets1, requested_networks,
                                                     ids, list_port_values)

    def test_validate_networks_fixed_ip_no_dup2(self):
        # Test validation for a request for a network with a
        # fixed ip that is not already in use because not used on this net id

        nets2 = [{'id': uuids.my_netid1,
                  'name': 'my_netname1',
                  'subnets': ['mysubnid1'],
                  'tenant_id': uuids.my_tenant},
                 {'id': uuids.my_netid2,
                  'name': 'my_netname2',
                  'subnets': ['mysubnid2'],
                  'tenant_id': uuids.my_tenant}]

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

                            ({'tenant_id': uuids.my_tenant, 'fields': ['id']},
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

    @mock.patch('nova.network.neutron.get_client')
    @mock.patch('nova.network.neutron.API._get_floating_ip_by_address',
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

    @mock.patch('nova.network.neutron.get_client')
    @mock.patch('nova.network.neutron.API._get_floating_ip_by_address',
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

    @mock.patch('nova.network.neutron.get_client')
    @mock.patch('nova.network.neutron.API._get_floating_ip_by_address',
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
       side_effect=exceptions.IpAddressAlreadyAllocatedClient())
    def test_create_port_minimal_raise_ip_already_allocated(self,
            create_port_mock):
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

    def test_create_port_minimal_raise_qos_not_supported(self):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_client = mock.MagicMock()
        mock_client.create_port.return_value = {'port': {
            'id': uuids.port_id,
            constants.RESOURCE_REQUEST: {
                'resources': {'CUSTOM_RESOURCE_CLASS': 42}}
        }}

        exc = self.assertRaises(exception.NetworksWithQoSPolicyNotSupported,
                                self.api._create_port_minimal,
                                mock_client, instance, uuids.my_netid1)
        expected_exception_msg = ('Using networks with QoS policy is not '
                                  'supported for instance %(instance)s. '
                                  '(Network ID is %(net_id)s)' %
                                  {'instance': instance.uuid,
                                   'net_id': uuids.my_netid1})
        self.assertEqual(expected_exception_msg, six.text_type(exc))
        mock_client.delete_port.assert_called_once_with(uuids.port_id)

    @mock.patch('nova.network.neutron.LOG')
    def test_create_port_minimal_raise_qos_not_supported_cleanup_fails(
            self, mock_log):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_client = mock.MagicMock()
        mock_client.create_port.return_value = {'port': {
            'id': uuids.port_id,
            constants.RESOURCE_REQUEST: {
                'resources': {'CUSTOM_RESOURCE_CLASS': 42}}
        }}
        mock_client.delete_port.side_effect = \
            exceptions.NeutronClientException()

        exc = self.assertRaises(exception.NetworksWithQoSPolicyNotSupported,
                                self.api._create_port_minimal,
                                mock_client, instance, uuids.my_netid1)
        expected_exception_msg = ('Using networks with QoS policy is not '
                                  'supported for instance %(instance)s. '
                                  '(Network ID is %(net_id)s)' %
                                  {'instance': instance.uuid,
                                   'net_id': uuids.my_netid1})
        self.assertEqual(expected_exception_msg, six.text_type(exc))
        mock_client.delete_port.assert_called_once_with(uuids.port_id)
        self.assertTrue(mock_log.exception.called)

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

    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    @mock.patch('nova.network.neutron.API.'
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

    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    def test_deallocate_port_for_instance_fails(self, mock_preexisting):
        mock_preexisting.return_value = []
        mock_client = mock.Mock()
        mock_client.show_port.side_effect = exceptions.Unauthorized()
        api = neutronapi.API()
        with test.nested(
            mock.patch.object(neutronapi, 'get_client',
                              return_value=mock_client),
            mock.patch.object(api, 'get_instance_nw_info')
        ) as (
            get_client, get_nw_info
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
        fake_network = {
            'network': {'id': uuids.instance, 'name': 'fake-network'}
        }

        with mock.patch.object(client.Client, 'show_network') as mock_show:
            mock_show.return_value = fake_network
            rsp = api.get(self.context, uuids.instance)
            self.assertEqual(fake_network['network'], rsp)

    def test_get_all_networks(self):
        api = neutronapi.API()
        fake_networks = {
            'networks': [
                {'id': uuids.network_1, 'name': 'fake-network1'},
                {'id': uuids.network_2, 'name': 'fake-network2'},
            ],
        }
        with mock.patch.object(client.Client, 'list_networks') as mock_list:
            mock_list.return_value = fake_networks
            rsp = api.get_all(self.context)
            self.assertEqual(fake_networks['networks'], rsp)

    @mock.patch.object(neutronapi.API, "_refresh_neutron_extensions_cache")
    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_instance_vnic_index(self, mock_get_client,
                                        mock_refresh_extensions):
        api = neutronapi.API()
        api.extensions = set([constants.VNIC_INDEX_EXT])
        mock_client = mock_get_client.return_value
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
        # remove the portbinding_profile if there is one.
        binding_profile = {'fake_profile': 'fake_data',
                           constants.MIGRATING_ATTR: 'my-dest-host'}
        fake_ports = {'ports': [
                        {'id': 'fake-port-1',
                         constants.BINDING_PROFILE: binding_profile,
                         constants.BINDING_HOST_ID: instance.host}]}
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
            'fake-port-1', {'port': {
                constants.BINDING_HOST_ID: 'my-host',
                                    'device_owner':
                                        'compute:%s' %
                                        instance.availability_zone,
                constants.BINDING_PROFILE: {
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
                         constants.BINDING_PROFILE: None,
                         constants.BINDING_HOST_ID: instance.host}]}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock

        self.api._update_port_binding_for_instance(self.context, instance,
                                                   'my-host')
        # Assert that update_port was called on the port with a
        # different host but with no binding profile.
        update_port_mock.assert_called_once_with(
            uuids.portid, {'port': {
                constants.BINDING_HOST_ID: 'my-host',
                                    'device_owner':
                                        'compute:%s' %
                                        instance.availability_zone}})

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_same_host(self,
                                                         get_client_mock):
        instance = fake_instance.fake_instance_obj(self.context)

        # We test two ports, one with the same host as the host passed in and
        # one where binding:host_id isn't set, so we update that port.
        fake_ports = {'ports': [
                        {'id': 'fake-port-1',
                         constants.BINDING_HOST_ID: instance.host},
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
            {'port': {constants.BINDING_HOST_ID: instance.host,
                      'device_owner': 'compute:%s' %
                                      instance.availability_zone}})

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
                         constants.BINDING_HOST_ID: 'fake-host-old',
                         constants.BINDING_PROFILE:
                            {'pci_slot': '0000:0a:00.1',
                             'physical_network': 'old_phys_net',
                             'pci_vendor_info': 'old_pci_vendor_info'}},
                        {'id': 'fake-port-2',
                         constants.BINDING_HOST_ID: instance.host}]}
        migration = objects.Migration(
            status='confirmed', migration_type='migration')
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
                    {
                        constants.BINDING_HOST_ID: 'fake-host',
                     'device_owner': 'compute:%s' % instance.availability_zone,
                        constants.BINDING_PROFILE:
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
                         constants.BINDING_HOST_ID: 'fake-host-old',
                         constants.BINDING_PROFILE:
                            {'pci_slot': '0000:0a:00.1',
                             'physical_network': 'old_phys_net',
                             'pci_vendor_info': 'old_pci_vendor_info'}}]}
        migration = objects.Migration(
            status='confirmed', migration_type='migration')
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
                         constants.BINDING_HOST_ID: instance.host,
                         constants.BINDING_PROFILE:
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

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_same_host_failed_vif_type(
        self, get_client_mock):
        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        list_ports_mock = mock.Mock()
        update_port_mock = mock.Mock()

        FAILED_VIF_TYPES = (model.VIF_TYPE_UNBOUND,
                            model.VIF_TYPE_BINDING_FAILED)
        for vif_type in FAILED_VIF_TYPES:
            binding_profile = {'fake_profile': 'fake_data',
                               constants.MIGRATING_ATTR: 'my-dest-host'}
            fake_ports = {'ports': [
                            {'id': 'fake-port-1',
                             'binding:vif_type': 'fake-vif-type',
                             constants.BINDING_PROFILE: binding_profile,
                             constants.BINDING_HOST_ID: instance.host},
                            {'id': 'fake-port-2',
                             'binding:vif_type': vif_type,
                             constants.BINDING_PROFILE: binding_profile,
                             constants.BINDING_HOST_ID: instance.host}
            ]}

            list_ports_mock.return_value = fake_ports
            get_client_mock.return_value.list_ports = list_ports_mock
            get_client_mock.return_value.update_port = update_port_mock
            update_port_mock.reset_mock()
            self.api._update_port_binding_for_instance(self.context, instance,
                                                       instance.host)
            # Assert that update_port was called on the port with a
            # failed vif_type and MIGRATING_ATTR is removed
            update_port_mock.assert_called_once_with(
                'fake-port-2',
                {'port': {constants.BINDING_HOST_ID: instance.host,
                          constants.BINDING_PROFILE: {
                              'fake_profile': 'fake_data'},
                          'device_owner': 'compute:%s' %
                                          instance.availability_zone
                          }})

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_diff_host_unbound_vif_type(
        self, get_client_mock):
        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)

        binding_profile = {'fake_profile': 'fake_data',
                           constants.MIGRATING_ATTR: 'my-dest-host'}
        fake_ports = {'ports': [
                        {'id': 'fake-port-1',
                         'binding:vif_type': model.VIF_TYPE_UNBOUND,
                         constants.BINDING_PROFILE: binding_profile,
                         constants.BINDING_HOST_ID: instance.host},
        ]}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock

        self.api._update_port_binding_for_instance(self.context, instance,
                                                   'my-host')

        # Assert that update_port was called on the port with a
        # 'unbound' vif_type, host updated and MIGRATING_ATTR is removed
        update_port_mock.assert_called_once_with(
            'fake-port-1', {'port': {
                constants.BINDING_HOST_ID: 'my-host',
                constants.BINDING_PROFILE: {
                                         'fake_profile': 'fake_data'},
                                     'device_owner': 'compute:%s' %
                                         instance.availability_zone
                }})

    @mock.patch.object(neutronapi.API, '_get_pci_mapping_for_migration')
    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_live_migration(
            self,
            get_client_mock,
            get_devspec_mock,
            get_pci_mapping_mock):

        devspec = mock.Mock()
        devspec.get_tags.return_value = {'physical_network': 'physnet1'}
        get_devspec_mock.return_value = devspec

        instance = fake_instance.fake_instance_obj(self.context)
        fake_ports = {'ports': [
            {'id': 'fake-port-1',
             'binding:vnic_type': 'direct',
             constants.BINDING_HOST_ID: 'old-host',
             constants.BINDING_PROFILE:
                 {'pci_slot': '0000:0a:00.1',
                  'physical_network': 'phys_net',
                  'pci_vendor_info': 'vendor_info'}}]}
        migration = objects.Migration(
            status='confirmed', migration_type='live-migration')
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock

        self.api._update_port_binding_for_instance(self.context, instance,
                                                   'new-host', migration)
        # Assert _get_pci_mapping_for_migration was not called
        self.assertFalse(get_pci_mapping_mock.called)

        # Assert that update_port() does not update binding:profile
        # and that it updates host ID
        called_port_id = update_port_mock.call_args[0][0]
        called_port_attributes = update_port_mock.call_args[0][1]
        self.assertEqual(called_port_id, fake_ports['ports'][0]['id'])
        self.assertNotIn(
            constants.BINDING_PROFILE, called_port_attributes['port'])
        self.assertEqual(
            called_port_attributes['port'][
                constants.BINDING_HOST_ID],
            'new-host')

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_resource_req(
            self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        fake_ports = {'ports': [
            {'id': 'fake-port-1',
             'binding:vnic_type': 'normal',
             constants.BINDING_HOST_ID: 'old-host',
             constants.BINDING_PROFILE:
                 {'allocation': uuids.source_compute_rp},
             'resource_request': mock.sentinel.resource_request}]}
        migration = objects.Migration(
            status='confirmed', migration_type='migration')
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock

        self.api._update_port_binding_for_instance(
            self.context, instance, 'new-host', migration,
            {'fake-port-1': [uuids.dest_compute_rp]})
        get_client_mock.return_value.update_port.assert_called_once_with(
            'fake-port-1',
            {'port': {'device_owner': 'compute:None',
                      'binding:profile': {'allocation': uuids.dest_compute_rp},
                      'binding:host_id': 'new-host'}})

    @mock.patch.object(neutronapi, 'get_client')
    def test_update_port_bindings_for_instance_with_resource_req_unshelve(
            self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        fake_ports = {'ports': [
            {'id': 'fake-port-1',
             'binding:vnic_type': 'normal',
             constants.BINDING_HOST_ID: 'old-host',
             constants.BINDING_PROFILE: {
                 'allocation': uuids.source_compute_rp},
             'resource_request': mock.sentinel.resource_request}]}
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock

        # NOTE(gibi): during unshelve migration object is not created
        self.api._update_port_binding_for_instance(
            self.context, instance, 'new-host', None,
            {'fake-port-1': [uuids.dest_compute_rp]})
        get_client_mock.return_value.update_port.assert_called_once_with(
            'fake-port-1',
            {'port': {'device_owner': 'compute:None',
                      'binding:profile': {'allocation': uuids.dest_compute_rp},
                      'binding:host_id': 'new-host'}})

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_resource_req_no_mapping(
            self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        fake_ports = {'ports': [
            {'id': 'fake-port-1',
             'binding:vnic_type': 'normal',
             constants.BINDING_HOST_ID: 'old-host',
             constants.BINDING_PROFILE:
                 {'allocation': uuids.source_compute_rp},
             'resource_request': mock.sentinel.resource_request}]}
        migration = objects.Migration(
            status='confirmed', migration_type='migration')
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock

        ex = self.assertRaises(
            exception.PortUpdateFailed,
            self.api._update_port_binding_for_instance, self.context,
            instance, 'new-host', migration, provider_mappings=None)
        self.assertIn(
            "Provider mappings are not available to the compute service but "
            "are required for ports with a resource request.",
            six.text_type(ex))

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_bindings_for_instance_with_resource_req_live_mig(
            self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        fake_ports = {'ports': [
            {'id': 'fake-port-1',
             'binding:vnic_type': 'normal',
             constants.BINDING_HOST_ID: 'old-host',
             constants.BINDING_PROFILE:
                 {'allocation': uuids.dest_compute_rp},
             'resource_request': mock.sentinel.resource_request}]}
        migration = objects.Migration(
            status='confirmed', migration_type='live-migration')
        list_ports_mock = mock.Mock(return_value=fake_ports)
        get_client_mock.return_value.list_ports = list_ports_mock

        # No mapping is passed in as during live migration the conductor
        # already created the binding and added the allocation key
        self.api._update_port_binding_for_instance(
            self.context, instance, 'new-host', migration, {})

        # Note that binding:profile is not updated
        get_client_mock.return_value.update_port.assert_called_once_with(
            'fake-port-1',
            {'port': {'device_owner': 'compute:None',
                      'binding:host_id': 'new-host'}})

    def test_get_pci_mapping_for_migration(self):
        instance = fake_instance.fake_instance_obj(self.context)
        instance.migration_context = objects.MigrationContext()
        migration = objects.Migration(status='confirmed')

        with mock.patch.object(instance.migration_context,
                               'get_pci_mapping_for_migration') as map_func:
            self.api._get_pci_mapping_for_migration(instance, migration)
            map_func.assert_called_with(False)

    def test_get_pci_mapping_for_migration_reverted(self):
        instance = fake_instance.fake_instance_obj(self.context)
        instance.migration_context = objects.MigrationContext()
        migration = objects.Migration(status='reverted')

        with mock.patch.object(instance.migration_context,
                               'get_pci_mapping_for_migration') as map_func:
            self.api._get_pci_mapping_for_migration(instance, migration)
            map_func.assert_called_with(True)

    def test_get_pci_mapping_for_migration_no_migration_context(self):
        instance = fake_instance.fake_instance_obj(self.context)
        instance.migration_context = None
        pci_mapping = self.api._get_pci_mapping_for_migration(
            instance, None)
        self.assertDictEqual({}, pci_mapping)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_profile_for_migration_teardown_false(
        self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        # We test with an instance host and destination_host where the
        # port will be moving.
        get_ports = {'ports': [
                        {'id': uuids.port_id,
                         constants.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock
        migrate_profile = {
            constants.MIGRATING_ATTR: 'my-new-host'}
        port_data = {'port':
                        {
                            constants.BINDING_PROFILE: migrate_profile}}

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
                 constants.BINDING_HOST_ID: instance.host,
                 constants.BINDING_PROFILE: None}
            ]
        }
        self.api.list_ports = mock.Mock(return_value=get_ports)
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock
        migrate_profile = {
            constants.MIGRATING_ATTR: 'my-new-host'}
        port_data = {
            'port': {
                constants.BINDING_PROFILE: migrate_profile
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
                         constants.BINDING_HOST_ID: instance.host}]}
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
                         constants.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        self.api._setup_migration_port_profile = mock.Mock()
        self.api._clear_migration_port_profile = mock.Mock()
        self.api.setup_networks_on_host(self.context,
                                        instance,
                                        host=instance.host,
                                        teardown=False)
        self.api._setup_migration_port_profile.assert_not_called()
        self.api._clear_migration_port_profile.assert_not_called()

    def test__setup_migration_port_profile_no_update(self):
        """Tests the case that the port binding profile already has the
        "migrating_to" attribute set to the provided host so the port update
        call is skipped.
        """
        ports = [{
            constants.BINDING_HOST_ID: 'source-host',
            constants.BINDING_PROFILE: {
                constants.MIGRATING_ATTR: 'dest-host'
            }
        }] * 2
        with mock.patch.object(self.api, '_update_port_with_migration_profile',
                               new_callable=mock.NonCallableMock):
            self.api._setup_migration_port_profile(
                self.context, mock.sentinel.instance, 'dest-host',
                mock.sentinel.admin_client, ports)

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_profile_for_migration_teardown_true_with_profile(
        self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        migrate_profile = {
            constants.MIGRATING_ATTR: 'new-host'}
        # Pass a port with an migration porfile attribute.
        port_id = uuids.port_id
        get_ports = {'ports': [
                        {'id': port_id,
                         constants.BINDING_PROFILE: migrate_profile,
                         constants.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock
        with mock.patch.object(self.api, 'delete_port_binding') as del_binding:
            with mock.patch.object(self.api, 'supports_port_binding_extension',
                                   return_value=True):
                self.api.setup_networks_on_host(self.context,
                                                instance,
                                                host='new-host',
                                                teardown=True)
        update_port_mock.assert_called_once_with(
            port_id, {'port': {
                constants.BINDING_PROFILE: migrate_profile}})
        del_binding.assert_called_once_with(
            self.context, port_id, 'new-host')

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_profile_for_migration_teardown_true_with_profile_exc(
        self, get_client_mock):
        """Tests that delete_port_binding raises PortBindingDeletionFailed
        which is raised through to the caller.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        migrate_profile = {
            constants.MIGRATING_ATTR: 'new-host'}
        # Pass a port with an migration porfile attribute.
        get_ports = {
            'ports': [
                {'id': uuids.port1,
                 constants.BINDING_PROFILE: migrate_profile,
                 constants.BINDING_HOST_ID: instance.host},
                {'id': uuids.port2,
                 constants.BINDING_PROFILE: migrate_profile,
                 constants.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        self.api._clear_migration_port_profile = mock.Mock()
        with mock.patch.object(
                self.api, 'delete_port_binding',
                side_effect=exception.PortBindingDeletionFailed(
                    port_id=uuids.port1, host='new-host')) as del_binding:
            with mock.patch.object(self.api, 'supports_port_binding_extension',
                                   return_value=True):
                ex = self.assertRaises(
                    exception.PortBindingDeletionFailed,
                    self.api.setup_networks_on_host,
                    self.context, instance, host='new-host', teardown=True)
                # Make sure both ports show up in the exception message.
                self.assertIn(uuids.port1, six.text_type(ex))
                self.assertIn(uuids.port2, six.text_type(ex))
        self.api._clear_migration_port_profile.assert_called_once_with(
            self.context, instance, get_client_mock.return_value,
            get_ports['ports'])
        del_binding.assert_has_calls([
            mock.call(self.context, uuids.port1, 'new-host'),
            mock.call(self.context, uuids.port2, 'new-host')])

    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_update_port_profile_for_migration_teardown_true_no_profile(
        self, get_client_mock):

        instance = fake_instance.fake_instance_obj(self.context)
        self.api._has_port_binding_extension = mock.Mock(return_value=True)
        # Pass a port without any migration porfile attribute.
        get_ports = {'ports': [
                        {'id': uuids.port_id,
                         constants.BINDING_HOST_ID: instance.host}]}
        self.api.list_ports = mock.Mock(return_value=get_ports)
        update_port_mock = mock.Mock()
        get_client_mock.return_value.update_port = update_port_mock
        with mock.patch.object(self.api, 'supports_port_binding_extension',
                               return_value=False):
            self.api.setup_networks_on_host(self.context,
                                            instance,
                                            host=instance.host,
                                            teardown=True)
        update_port_mock.assert_not_called()

    def test__update_port_with_migration_profile_raise_exception(self):

        instance = fake_instance.fake_instance_obj(self.context)
        port_id = uuids.port_id
        migrate_profile = {'fake-attribute': 'my-new-host'}
        port_profile = {'port': {
            constants.BINDING_PROFILE: migrate_profile}}
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

    @mock.patch('nova.network.neutron.get_client')
    def test_unbind_ports_get_client_binding_extension(self,
                                                       mock_neutron):
        self._test_unbind_ports_get_client(mock_neutron)

    @mock.patch('nova.network.neutron.get_client')
    def test_unbind_ports_get_client(self, mock_neutron):
        self._test_unbind_ports_get_client(mock_neutron)

    @mock.patch('nova.network.neutron.API._show_port')
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
        body['port'][constants.BINDING_HOST_ID] = None
        body['port'][constants.BINDING_PROFILE] = {}
        update_port_calls = []
        for p in ports:
            update_port_calls.append(mock.call(p, body))

        self.assertEqual(3, mock_update_port.call_count)
        mock_update_port.assert_has_calls(update_port_calls)

    @mock.patch('nova.network.neutron.get_client')
    def test_unbind_ports_binding_ext(self, mock_neutron):
        self._test_unbind_ports(mock_neutron)

    @mock.patch('nova.network.neutron.get_client')
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

    @mock.patch('nova.network.neutron.API.get_instance_nw_info')
    @mock.patch('nova.network.neutron.excutils')
    @mock.patch('nova.network.neutron.API._delete_ports')
    @mock.patch('nova.network.neutron.API._check_external_network_attach')
    @mock.patch('nova.network.neutron.LOG')
    @mock.patch('nova.network.neutron.API._unbind_ports')
    @mock.patch('nova.network.neutron.API._populate_neutron_extension_values')
    @mock.patch('nova.network.neutron.API._get_available_networks')
    @mock.patch('nova.network.neutron.get_client')
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

        self.api.allocate_for_instance(mock.sentinel.ctx, mock_inst,
                                       requested_networks=nw_req)

        mock_unbind.assert_called_once_with(mock.sentinel.ctx,
                                            [uuids.portid_1, uuids.portid_2],
                                            mock.ANY,
                                            mock.ANY)

    @mock.patch('nova.network.neutron.LOG')
    @mock.patch('nova.network.neutron.API._delete_ports')
    @mock.patch('nova.network.neutron.API._unbind_ports')
    @mock.patch('nova.network.neutron.API._get_preexisting_port_ids')
    @mock.patch('nova.network.neutron.get_client')
    @mock.patch.object(objects.VirtualInterface, 'delete_by_instance_uuid')
    def test_preexisting_deallocate_for_instance(self, mock_delete_vifs,
                                                 mock_ntrn,
                                                 mock_gppids,
                                                 mock_unbind,
                                                 mock_deletep,
                                                 mock_log):
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

    @mock.patch('nova.network.neutron.API._delete_nic_metadata')
    @mock.patch('nova.network.neutron.API.get_instance_nw_info')
    @mock.patch('nova.network.neutron.API._unbind_ports')
    @mock.patch('nova.objects.Instance.get_network_info')
    @mock.patch('nova.network.neutron.get_client')
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
        mock_client.show_port.return_value = {'port': {}}
        mock_ntrn.return_value = mock_client
        vif = objects.VirtualInterface()
        vif.destroy = mock.MagicMock()
        mock_get_vif_by_uuid.return_value = vif
        _, port_allocation = self.api.deallocate_port_for_instance(
            mock.sentinel.ctx, mock_inst, '2')
        mock_unbind.assert_called_once_with(mock.sentinel.ctx, ['2'],
                                            mock_client)
        mock_get_vif_by_uuid.assert_called_once_with(mock.sentinel.ctx, '2')
        mock_del_nic_meta.assert_called_once_with(mock_inst, vif)
        vif.destroy.assert_called_once_with()
        self.assertEqual({}, port_allocation)

    @mock.patch('nova.network.neutron.API.get_instance_nw_info')
    @mock.patch('nova.network.neutron.API._delete_nic_metadata')
    @mock.patch.object(objects.VirtualInterface, 'get_by_uuid')
    @mock.patch('nova.network.neutron.get_client')
    def test_deallocate_port_for_instance_port_with_allocation(
            self, mock_get_client, mock_get_vif_by_uuid, mock_del_nic_meta,
            mock_netinfo):
        mock_inst = mock.Mock(project_id="proj-1",
                              availability_zone='zone-1',
                              uuid='inst-1')
        mock_inst.get_network_info.return_value = [
            model.VIF(id=uuids.port_uid, preserve_on_delete=True)
        ]
        vif = objects.VirtualInterface()
        vif.tag = 'foo'
        vif.destroy = mock.MagicMock()
        mock_get_vif_by_uuid.return_value = vif

        mock_client = mock.Mock()
        mock_client.show_port.return_value = {
            'port': {
                constants.RESOURCE_REQUEST: {
                    'resources': {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 1000
                    }
                },
                'binding:profile': {
                    'allocation': uuids.rp1
                }
            }
        }
        mock_get_client.return_value = mock_client

        _, port_allocation = self.api.deallocate_port_for_instance(
            mock.sentinel.ctx, mock_inst, uuids.port_id)

        self.assertEqual(
            {
                uuids.rp1: {
                    'NET_BW_EGR_KILOBIT_PER_SEC': 1000
                }
            },
            port_allocation)

    @mock.patch('nova.network.neutron.API.get_instance_nw_info')
    @mock.patch('nova.network.neutron.API._delete_nic_metadata')
    @mock.patch.object(objects.VirtualInterface, 'get_by_uuid')
    @mock.patch('nova.network.neutron.get_client')
    def test_deallocate_port_for_instance_port_already_deleted(
            self, mock_get_client, mock_get_vif_by_uuid, mock_del_nic_meta,
            mock_netinfo):
        mock_inst = mock.Mock(project_id="proj-1",
                              availability_zone='zone-1',
                              uuid='inst-1')
        network_info = [
            model.VIF(
                id=uuids.port_id, preserve_on_delete=True,
                profile={'allocation': uuids.rp1})
        ]
        mock_inst.get_network_info.return_value = network_info
        vif = objects.VirtualInterface()
        vif.destroy = mock.MagicMock()
        mock_get_vif_by_uuid.return_value = vif

        mock_client = mock.Mock()
        mock_client.show_port.side_effect = exception.PortNotFound(
            port_id=uuids.port_id)
        mock_get_client.return_value = mock_client

        _, port_allocation = self.api.deallocate_port_for_instance(
            mock.sentinel.ctx, mock_inst, uuids.port_id)

        self.assertEqual({}, port_allocation)
        self.assertIn(
            'Resource allocation for this port may be leaked',
            self.stdlog.logger.output)

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

    def test_delete_nic_metadata_no_metadata(self):
        vif = objects.VirtualInterface(address='aa:bb:cc:dd:ee:ff', tag='foo')
        instance = fake_instance.fake_instance_obj(self.context)
        instance.device_metadata = None
        instance.save = mock.Mock()
        self.api._delete_nic_metadata(instance, vif)
        instance.save.assert_not_called()

    @mock.patch('nova.network.neutron.API._check_external_network_attach')
    @mock.patch('nova.network.neutron.API._populate_neutron_extension_values')
    @mock.patch('nova.network.neutron.API._get_available_networks')
    @mock.patch('nova.network.neutron.get_client')
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
                          mock_inst, None)
        mock_nc.delete_port.assert_called_once_with(uuids.portid_1)

    @mock.patch('nova.network.neutron.API._show_port')
    @mock.patch('nova.network.neutron.get_client')
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
                          mock.sentinel.ctx, mock_inst,
                          requested_networks=nw_req)

    @mock.patch('nova.objects.virtual_interface.VirtualInterface.create')
    @mock.patch('nova.network.neutron.API._check_external_network_attach')
    @mock.patch('nova.network.neutron.API._show_port')
    @mock.patch('nova.network.neutron.API._update_port')
    @mock.patch('nova.network.neutron.get_client')
    def test_port_with_resource_request_has_allocation_in_binding(
            self, mock_get_client, mock_update_port, mock_show_port,
            mock_check_external, mock_vif_create):

        nw_req = objects.NetworkRequestList(
            objects = [objects.NetworkRequest(port_id=uuids.portid_1)])
        mock_inst = mock.Mock(
            uuid=uuids.instance_uuid,
            project_id=uuids.project_id,
            availability_zone='nova',
        )
        port = {
            'id': uuids.portid_1,
            'tenant_id': uuids.project_id,
            'network_id': uuids.networkid_1,
            'mac_address': 'fake-mac',
            constants.RESOURCE_REQUEST: 'fake-request'
        }
        mock_show_port.return_value = port
        mock_get_client.return_value.list_networks.return_value = {
            "networks": [{'id': uuids.networkid_1,
                          'port_security_enabled': False}]}
        mock_update_port.return_value = port

        with mock.patch.object(self.api, 'get_instance_nw_info'):
            self.api.allocate_for_instance(
                mock.sentinel.ctx, mock_inst,
                requested_networks=nw_req,
                resource_provider_mapping={uuids.portid_1: [uuids.rp1]})

        mock_update_port.assert_called_once_with(
            mock_get_client.return_value, mock_inst, uuids.portid_1,
            {
                'port': {
                    'binding:host_id': None,
                    'device_id': uuids.instance_uuid,
                    'binding:profile': {
                        'allocation': uuids.rp1},
                    'device_owner': 'compute:nova'}})
        mock_show_port.assert_called_once_with(
            mock.sentinel.ctx, uuids.portid_1,
            neutron_client=mock_get_client.return_value)

    @mock.patch('nova.network.neutron.get_client')
    def test_get_floating_ip_by_address_not_found_neutron_not_found(self,
                                                                mock_ntrn):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_floatingips.side_effect = exceptions.NotFound()
        address = '172.24.4.227'
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          self.api.get_floating_ip_by_address,
                          self.context, address)

    @mock.patch('nova.network.neutron.get_client')
    def test_get_floating_ip_by_address_not_found_neutron_raises_non404(self,
                                                                mock_ntrn):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_floatingips.side_effect = exceptions.InternalServerError()
        address = '172.24.4.227'
        self.assertRaises(exceptions.InternalServerError,
                          self.api.get_floating_ip_by_address,
                          self.context, address)

    @mock.patch('nova.network.neutron.get_client')
    def test_get_floating_ips_by_project_not_found(self, mock_ntrn):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_floatingips.side_effect = exceptions.NotFound()
        fips = self.api.get_floating_ips_by_project(self.context)
        self.assertEqual([], fips)

    @mock.patch('nova.network.neutron.get_client')
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

    @mock.patch('nova.network.neutron.get_client')
    def test_get_floating_ips_by_project_raises_non404(self, mock_ntrn):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        mock_nc.list_floatingips.side_effect = exceptions.InternalServerError()
        self.assertRaises(exceptions.InternalServerError,
                          self.api.get_floating_ips_by_project,
                          self.context)

    @mock.patch.object(neutronapi.API, '_refresh_neutron_extensions_cache')
    @mock.patch.object(neutronapi, 'get_client')
    def _test_get_floating_ips_by_project(
            self, fip_ext_enabled, has_ports, mock_ntrn, mock_refresh):
        mock_nc = mock.Mock()
        mock_ntrn.return_value = mock_nc
        # NOTE(stephenfin): These are clearly not full responses
        mock_nc.list_floatingips.return_value = {
            'floatingips': [
                {
                    'id': uuids.fip_id,
                    'floating_network_id': uuids.fip_net_id,
                    'port_id': uuids.fip_port_id,
                }
            ]
        }
        mock_nc.list_networks.return_value = {
            'networks': [
                {
                    'id': uuids.fip_net_id,
                },
            ],
        }
        if has_ports:
            mock_nc.list_ports.return_value = {
                'ports': [
                    {
                        'id': uuids.fip_port_id,
                    },
                ],
            }
        else:
            mock_nc.list_ports.return_value = {'ports': []}

        if fip_ext_enabled:
            self.api.extensions = [constants.FIP_PORT_DETAILS]
        else:
            self.api.extensions = []

        fips = self.api.get_floating_ips_by_project(self.context)

        mock_nc.list_networks.assert_called_once_with(
            id=[uuids.fip_net_id])
        self.assertEqual(1, len(fips))

        if fip_ext_enabled:
            mock_nc.list_ports.assert_not_called()
            self.assertNotIn('port_details', fips[0])
        else:
            mock_nc.list_ports.assert_called_once_with(
                tenant_id=self.context.project_id)
            self.assertIn('port_details', fips[0])

            if has_ports:
                self.assertIsNotNone(fips[0]['port_details'])
            else:
                self.assertIsNone(fips[0]['port_details'])

    def test_get_floating_ips_by_project_with_fip_port_details_ext(self):
        """Make sure we used embedded port details if available."""
        self._test_get_floating_ips_by_project(True, True)

    def test_get_floating_ips_by_project_without_fip_port_details_ext(self):
        """Make sure we make a second request for port details if necessary."""
        self._test_get_floating_ips_by_project(False, True)

    def test_get_floating_ips_by_project_without_ports(self):
        """Make sure we don't fail for floating IPs without attached ports."""
        self._test_get_floating_ips_by_project(False, False)

    @mock.patch('nova.network.neutron.API._show_port')
    def test_unbind_ports_reset_dns_name_by_admin(self, mock_show):
        neutron = mock.Mock()
        neutron.show_network.return_value = {
            'network': {
                'id': 'net1',
                'dns_domain': None
            }
        }
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
        neutron.update_port.assert_not_called()

    @mock.patch('nova.network.neutron.API._show_port')
    def test_unbind_ports_reset_dns_name_by_non_admin(self, mock_show):
        neutron = mock.Mock()
        neutron.show_network.return_value = {
            'network': {
                'id': 'net1',
                'dns_domain': 'test.domain'
            }
        }
        port_client = mock.Mock()
        self.api.extensions = [constants.DNS_INTEGRATION]
        ports = [uuids.port_id]
        mock_show.return_value = {'id': uuids.port}
        self.api._unbind_ports(self.context, ports, neutron, port_client)
        admin_port_req_body = {'port': {'binding:host_id': None,
                                        'binding:profile': {},
                                        'device_id': '',
                                        'device_owner': ''}}
        non_admin_port_req_body = {'port': {'dns_name': ''}}
        port_client.update_port.assert_called_once_with(
            uuids.port_id, admin_port_req_body)
        neutron.update_port.assert_called_once_with(
            uuids.port_id, non_admin_port_req_body)

    @mock.patch('nova.network.neutron.API._show_port')
    def test_unbind_ports_reset_allocation_in_port_binding(self, mock_show):
        neutron = mock.Mock()
        port_client = mock.Mock()
        ports = [uuids.port_id]
        mock_show.return_value = {'id': uuids.port,
                                  'binding:profile': {'allocation': uuids.rp1}}
        self.api._unbind_ports(self.context, ports, neutron, port_client)
        port_req_body = {'port': {'binding:host_id': None,
                                  'binding:profile': {},
                                  'device_id': '',
                                  'device_owner': ''}}
        port_client.update_port.assert_called_once_with(
            uuids.port_id, port_req_body)

    @mock.patch('nova.network.neutron.API._show_port')
    def test_unbind_ports_reset_binding_profile(self, mock_show):
        neutron = mock.Mock()
        port_client = mock.Mock()
        ports = [uuids.port_id]
        mock_show.return_value = {
            'id': uuids.port,
            'binding:profile': {'pci_vendor_info': '1377:0047',
                                'pci_slot': '0000:0a:00.1',
                                'physical_network': 'physnet1',
                                'capabilities': ['switchdev']}
            }
        self.api._unbind_ports(self.context, ports, neutron, port_client)
        port_req_body = {'port': {'binding:host_id': None,
                                  'binding:profile':
                                    {'physical_network': 'physnet1',
                                     'capabilities': ['switchdev']},
                                  'device_id': '',
                                  'device_owner': ''}
                        }
        port_client.update_port.assert_called_once_with(
            uuids.port_id, port_req_body)

    @mock.patch('nova.network.neutron.API._populate_neutron_extension_values')
    @mock.patch('nova.network.neutron.API._update_port',
                # called twice, fails on the 2nd call and triggers the cleanup
                side_effect=(mock.MagicMock(),
                             exception.PortInUse(
                                 port_id=uuids.created_port_id)))
    @mock.patch.object(objects.VirtualInterface, 'create')
    @mock.patch.object(objects.VirtualInterface, 'destroy')
    @mock.patch('nova.network.neutron.API._unbind_ports')
    @mock.patch('nova.network.neutron.API._delete_ports')
    def test_update_ports_for_instance_fails_rollback_ports_and_vifs(self,
            mock_delete_ports,
            mock_unbind_ports,
            mock_vif_destroy,
            mock_vif_create,
            mock_update_port,
            mock_populate_ext_values):
        """Makes sure we rollback ports and VIFs if we fail updating ports"""
        instance = fake_instance.fake_instance_obj(self.context)
        ntrn = mock.Mock(spec=client.Client)
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
                          requested_ports_dict=None)
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

    @mock.patch('nova.network.neutron.API._get_floating_ip_by_address',
                return_value={"port_id": "1"})
    @mock.patch('nova.network.neutron.API._show_port',
                side_effect=exception.PortNotFound(port_id='1'))
    def test_get_instance_id_by_floating_address_port_not_found(self,
                                                                mock_show,
                                                                mock_get):
        api = neutronapi.API()
        fip = api.get_instance_id_by_floating_address(self.context,
                                                      '172.24.4.227')
        self.assertIsNone(fip)

    @mock.patch('nova.network.neutron.API._show_port',
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
            fields=['binding:profile', 'network_id'],
            neutron_client=mock.ANY)
        mock_log.assert_not_called()

    @mock.patch('nova.network.neutron.API._show_port',
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

    @mock.patch('nova.network.neutron.API._show_port')
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

    @mock.patch('nova.network.neutron.API._show_port')
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
    def test_create_resource_requests_no_allocate(self, mock_get_client):
        """Ensure physnet info is not retrieved when networks are not to be
        allocated.
        """
        requested_networks = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id=net_req_obj.NETWORK_ID_NONE)
        ])
        pci_requests = objects.InstancePCIRequests()
        api = neutronapi.API()

        result = api.create_resource_requests(
            self.context, requested_networks, pci_requests)
        network_metadata, port_resource_requests = result

        self.assertFalse(mock_get_client.called)
        self.assertIsNone(network_metadata)
        self.assertEqual([], port_resource_requests)

    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info')
    @mock.patch.object(neutronapi, 'get_client', return_value=mock.Mock())
    def test_create_resource_requests_auto_allocated(self, mock_get_client,
            mock_get_physnet_tunneled_info):
        """Ensure physnet info is not retrieved for auto-allocated networks.

        This isn't possible so we shouldn't attempt to do it.
        """
        requested_networks = objects.NetworkRequestList(objects=[
            objects.NetworkRequest(network_id=net_req_obj.NETWORK_ID_AUTO)
        ])
        pci_requests = objects.InstancePCIRequests()
        api = neutronapi.API()

        result = api.create_resource_requests(
            self.context, requested_networks, pci_requests)
        network_metadata, port_resource_requests = result

        mock_get_physnet_tunneled_info.assert_not_called()
        self.assertEqual(set(), network_metadata.physnets)
        self.assertFalse(network_metadata.tunneled)
        self.assertEqual([], port_resource_requests)

    @mock.patch('nova.objects.request_spec.RequestGroup.from_port_request')
    @mock.patch.object(neutronapi.API, '_get_physnet_tunneled_info')
    @mock.patch.object(neutronapi.API, "_get_port_vnic_info")
    @mock.patch.object(neutronapi, 'get_client')
    def test_create_resource_requests(self, getclient,
            mock_get_port_vnic_info, mock_get_physnet_tunneled_info,
            mock_from_port_request):
        requested_networks = objects.NetworkRequestList(
            objects = [
                objects.NetworkRequest(port_id=uuids.portid_1),
                objects.NetworkRequest(network_id='net1'),
                objects.NetworkRequest(port_id=uuids.portid_2),
                objects.NetworkRequest(port_id=uuids.portid_3),
                objects.NetworkRequest(port_id=uuids.portid_4),
                objects.NetworkRequest(port_id=uuids.portid_5),
                objects.NetworkRequest(port_id=uuids.trusted_port)])
        pci_requests = objects.InstancePCIRequests(requests=[])
        # _get_port_vnic_info should be called for every NetworkRequest with a
        # port_id attribute (so six times)
        mock_get_port_vnic_info.side_effect = [
            (model.VNIC_TYPE_DIRECT, None, 'netN', None),
            (model.VNIC_TYPE_NORMAL, None, 'netN',
             mock.sentinel.resource_request1),
            (model.VNIC_TYPE_MACVTAP, None, 'netN', None),
            (model.VNIC_TYPE_MACVTAP, None, 'netN', None),
            (model.VNIC_TYPE_DIRECT_PHYSICAL, None, 'netN', None),
            (model.VNIC_TYPE_DIRECT, True, 'netN',
             mock.sentinel.resource_request2),
        ]
        # _get_physnet_tunneled_info should be called for every NetworkRequest
        # (so seven times)
        mock_get_physnet_tunneled_info.side_effect = [
            ('physnet1', False), ('physnet1', False), ('', True),
            ('physnet1', False), ('physnet2', False), ('physnet3', False),
            ('physnet4', False),
        ]
        api = neutronapi.API()

        mock_from_port_request.side_effect = [
            mock.sentinel.request_group1,
            mock.sentinel.request_group2,
        ]

        result = api.create_resource_requests(
            self.context, requested_networks, pci_requests)
        network_metadata, port_resource_requests = result

        self.assertEqual([
                mock.sentinel.request_group1,
                mock.sentinel.request_group2],
            port_resource_requests)
        self.assertEqual(5, len(pci_requests.requests))
        has_pci_request_id = [net.pci_request_id is not None for net in
                              requested_networks.objects]
        self.assertEqual(pci_requests.requests[3].spec[0]["dev_type"],
                         "type-PF")
        expected_results = [True, False, False, True, True, True, True]
        self.assertEqual(expected_results, has_pci_request_id)
        # Make sure only the trusted VF has the 'trusted' tag set in the spec.
        for pci_req in pci_requests.requests:
            spec = pci_req.spec[0]
            if spec[pci_request.PCI_NET_TAG] == 'physnet4':
                # trusted should be true in the spec for this request
                self.assertIn(pci_request.PCI_TRUSTED_TAG, spec)
                self.assertEqual('True', spec[pci_request.PCI_TRUSTED_TAG])
            else:
                self.assertNotIn(pci_request.PCI_TRUSTED_TAG, spec)

        # Only the port with a resource_request will have pci_req.requester_id.
        self.assertEqual(
            [None, None, None, None, uuids.trusted_port],
            [pci_req.requester_id for pci_req in pci_requests.requests])

        self.assertCountEqual(
            ['physnet1', 'physnet2', 'physnet3', 'physnet4'],
            network_metadata.physnets)
        self.assertTrue(network_metadata.tunneled)
        mock_from_port_request.assert_has_calls([
            mock.call(
                context=None,
                port_uuid=uuids.portid_2,
                port_resource_request=mock.sentinel.resource_request1),
            mock.call(
                context=None,
                port_uuid=uuids.trusted_port,
                port_resource_request=mock.sentinel.resource_request2),
        ])

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

    @mock.patch('nova.network.neutron.get_client')
    @mock.patch('nova.network.neutron.LOG.warning')
    @mock.patch('nova.network.neutron.update_instance_cache_with_nw_info')
    def test_associate_floating_ip_refresh_error_trap(self, mock_update_cache,
                                                      mock_log_warning,
                                                      mock_get_client):
        """Tests that when _update_inst_info_cache_for_disassociated_fip
        raises an exception, associate_floating_ip traps and logs it but
        does not re-raise.
        """
        ctxt = context.get_context()
        instance = fake_instance.fake_instance_obj(ctxt)
        floating_addr = '172.24.5.15'
        fixed_addr = '10.1.0.9'
        fip = {'id': uuids.floating_ip_id, 'port_id': uuids.old_port_id}
        # Setup the mocks.
        with test.nested(
            mock.patch.object(self.api, '_get_port_id_by_fixed_address',
                              return_value=uuids.new_port_id),
            mock.patch.object(self.api, '_get_floating_ip_by_address',
                              return_value=fip),
            mock.patch.object(self.api,
                              '_update_inst_info_cache_for_disassociated_fip',
                              side_effect=exception.PortNotFound(
                                  port_id=uuids.old_port_id))
        ) as (
            _get_port_id_by_fixed_address,
            _get_floating_ip_by_address,
            _update_inst_info_cache_for_disassociated_fip
        ):
            # Run the code.
            self.api.associate_floating_ip(
                ctxt, instance, floating_addr, fixed_addr)
        # Assert the calls.
        mock_get_client.assert_called_once_with(ctxt)
        mock_client = mock_get_client.return_value
        _get_port_id_by_fixed_address.assert_called_once_with(
            mock_client, instance, fixed_addr)
        _get_floating_ip_by_address.assert_called_once_with(
            mock_client, floating_addr)
        mock_client.update_floatingip.assert_called_once_with(
            uuids.floating_ip_id, test.MatchType(dict))
        _update_inst_info_cache_for_disassociated_fip.assert_called_once_with(
            ctxt, instance, mock_client, fip)
        mock_log_warning.assert_called_once()
        self.assertIn('An error occurred while trying to refresh the '
                      'network info cache for an instance associated '
                      'with port', mock_log_warning.call_args[0][0])
        mock_update_cache.assert_called_once_with(  # from @refresh_cache
            self.api, ctxt, instance, nw_info=None)

    @mock.patch('nova.network.neutron.update_instance_cache_with_nw_info')
    def test_update_inst_info_cache_for_disassociated_fip_other_cell(
            self, mock_update_cache):
        """Tests a scenario where a floating IP is associated to an instance
        in another cell from the one in which it's currently associated
        and the network info cache on the original instance is refreshed.
        """
        ctxt = context.get_context()
        mock_client = mock.Mock()
        new_instance = fake_instance.fake_instance_obj(ctxt)
        cctxt = context.get_context()
        old_instance = fake_instance.fake_instance_obj(cctxt)
        fip = {'id': uuids.floating_ip_id,
               'port_id': uuids.old_port_id,
               'floating_ip_address': '172.24.5.15'}
        # Setup the mocks.
        with test.nested(
            mock.patch.object(self.api, '_show_port',
                              return_value={
                                  'device_id': old_instance.uuid}),
            mock.patch.object(self.api, '_get_instance_by_uuid_using_api_db',
                              return_value=old_instance)
        ) as (
            _show_port, _get_instance_by_uuid_using_api_db
        ):
            # Run the code.
            self.api._update_inst_info_cache_for_disassociated_fip(
                ctxt, new_instance, mock_client, fip)
        # Assert the calls.
        _show_port.assert_called_once_with(
            ctxt, uuids.old_port_id, neutron_client=mock_client)
        _get_instance_by_uuid_using_api_db.assert_called_once_with(
            ctxt, old_instance.uuid)
        mock_update_cache.assert_called_once_with(
            self.api, cctxt, old_instance)

    @mock.patch('nova.network.neutron.LOG.info')
    @mock.patch('nova.network.neutron.update_instance_cache_with_nw_info')
    def test_update_inst_info_cache_for_disassociated_fip_inst_not_found(
            self, mock_update_cache, mock_log_info):
        """Tests the case that a floating IP is re-associated to an instance
        in another cell but the original instance cannot be found.
        """
        ctxt = context.get_context()
        mock_client = mock.Mock()
        new_instance = fake_instance.fake_instance_obj(ctxt)
        fip = {'id': uuids.floating_ip_id,
               'port_id': uuids.old_port_id,
               'floating_ip_address': '172.24.5.15'}
        # Setup the mocks.
        with test.nested(
            mock.patch.object(self.api, '_show_port',
                              return_value={
                                  'device_id': uuids.original_inst_uuid}),
            mock.patch.object(self.api,
                              '_get_instance_by_uuid_using_api_db',
                              return_value=None)
        ) as (
            _show_port, _get_instance_by_uuid_using_api_db
        ):
            # Run the code.
            self.api._update_inst_info_cache_for_disassociated_fip(
                ctxt, new_instance, mock_client, fip)
        # Assert the calls.
        _show_port.assert_called_once_with(
            ctxt, uuids.old_port_id, neutron_client=mock_client)
        _get_instance_by_uuid_using_api_db.assert_called_once_with(
            ctxt, uuids.original_inst_uuid)
        mock_update_cache.assert_not_called()
        self.assertEqual(2, mock_log_info.call_count)
        self.assertIn('If the instance still exists, its info cache may '
                      'be healed automatically.',
                      mock_log_info.call_args[0][0])

    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_get_instance_by_uuid_using_api_db_current_cell(
            self, mock_get_map, mock_get_inst):
        """Tests that _get_instance_by_uuid_using_api_db finds the
        instance in the cell currently targeted by the context.
        """
        ctxt = context.get_context()
        instance = fake_instance.fake_instance_obj(ctxt)
        mock_get_inst.return_value = instance
        inst = self.api._get_instance_by_uuid_using_api_db(ctxt, instance.uuid)
        self.assertIs(inst, instance)
        mock_get_inst.assert_called_once_with(ctxt, instance.uuid)
        mock_get_map.assert_not_called()

    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_get_instance_by_uuid_using_api_db_other_cell(
            self, mock_get_map, mock_get_inst):
        """Tests that _get_instance_by_uuid_using_api_db finds the
        instance in another cell different from the currently targeted context.
        """
        ctxt = context.get_context()
        instance = fake_instance.fake_instance_obj(ctxt)
        mock_get_map.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping(
                uuid=uuids.cell_mapping_uuid,
                database_connection=
                self.cell_mappings['cell1'].database_connection,
                transport_url='none://fake'))
        # Mock get_by_uuid to not find the instance in the first call, but
        # do find it in the second. Target the instance context as well so
        # we can assert that we used a different context for the 2nd call.

        def stub_inst_get_by_uuid(_context, instance_uuid, *args, **kwargs):
            if not mock_get_map.called:
                # First call, raise InstanceNotFound.
                self.assertIs(_context, ctxt)
                raise exception.InstanceNotFound(instance_id=instance_uuid)
            # Else return the instance with a newly targeted context.
            self.assertIsNot(_context, ctxt)
            instance._context = _context
            return instance
        mock_get_inst.side_effect = stub_inst_get_by_uuid

        inst = self.api._get_instance_by_uuid_using_api_db(ctxt, instance.uuid)
        # The instance's internal context should still be targeted and not
        # the original context.
        self.assertIsNot(inst._context, ctxt)
        self.assertIsNotNone(inst._context.db_connection)
        mock_get_map.assert_called_once_with(ctxt, instance.uuid)
        mock_get_inst.assert_has_calls([
            mock.call(ctxt, instance.uuid),
            mock.call(inst._context, instance.uuid)])

    @mock.patch('nova.objects.Instance.get_by_uuid',
                side_effect=exception.InstanceNotFound(instance_id=uuids.inst))
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_get_instance_by_uuid_using_api_db_other_cell_never_found(
            self, mock_get_map, mock_get_inst):
        """Tests that _get_instance_by_uuid_using_api_db does not find the
        instance in either the current cell or another cell.
        """
        ctxt = context.get_context()
        instance = fake_instance.fake_instance_obj(ctxt, uuid=uuids.inst)
        mock_get_map.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping(
                uuid=uuids.cell_mapping_uuid,
                database_connection=
                self.cell_mappings['cell1'].database_connection,
                transport_url='none://fake'))
        self.assertIsNone(
            self.api._get_instance_by_uuid_using_api_db(ctxt, instance.uuid))
        mock_get_map.assert_called_once_with(ctxt, instance.uuid)
        mock_get_inst.assert_has_calls([
            mock.call(ctxt, instance.uuid),
            mock.call(test.MatchType(context.RequestContext), instance.uuid)])

    @mock.patch('nova.objects.Instance.get_by_uuid',
                side_effect=exception.InstanceNotFound(instance_id=uuids.inst))
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid',
                side_effect=exception.InstanceMappingNotFound(uuid=uuids.inst))
    def test_get_instance_by_uuid_using_api_db_other_cell_map_not_found(
            self, mock_get_map, mock_get_inst):
        """Tests that _get_instance_by_uuid_using_api_db does not find an
        instance mapping for the instance.
        """
        ctxt = context.get_context()
        instance = fake_instance.fake_instance_obj(ctxt, uuid=uuids.inst)
        self.assertIsNone(
            self.api._get_instance_by_uuid_using_api_db(ctxt, instance.uuid))
        mock_get_inst.assert_called_once_with(ctxt, instance.uuid)
        mock_get_map.assert_called_once_with(ctxt, instance.uuid)

    @mock.patch('nova.network.neutron._get_ksa_client',
                new_callable=mock.NonCallableMock)  # asserts not called
    def test_migrate_instance_start_no_binding_ext(self, get_client_mock):
        """Tests that migrate_instance_start exits early if neutron doesn't
        have the binding-extended API extension.
        """
        with mock.patch.object(self.api, 'supports_port_binding_extension',
                               return_value=False):
            self.api.migrate_instance_start(
                self.context, mock.sentinel.instance, {})

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_migrate_instance_start_activate(self, get_client_mock):
        """Tests the happy path for migrate_instance_start where the binding
        for the port(s) attached to the instance are activated on the
        destination host.
        """
        binding = {'binding': {'status': 'INACTIVE'}}
        resp = fake_req.FakeResponse(200, content=jsonutils.dumps(binding))
        get_client_mock.return_value.get.return_value = resp
        # Just create a simple instance with a single port.
        instance = objects.Instance(info_cache=objects.InstanceInfoCache(
            network_info=model.NetworkInfo([model.VIF(uuids.port_id)])))
        migration = objects.Migration(
            source_compute='source', dest_compute='dest')
        with mock.patch.object(self.api, 'activate_port_binding') as activate:
            with mock.patch.object(self.api, 'supports_port_binding_extension',
                                   return_value=True):
                self.api.migrate_instance_start(
                    self.context, instance, migration)
        activate.assert_called_once_with(self.context, uuids.port_id, 'dest')
        get_client_mock.return_value.get.assert_called_once_with(
            '/v2.0/ports/%s/bindings/dest' % uuids.port_id, raise_exc=False,
            global_request_id=self.context.global_id)

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_migrate_instance_start_already_active(self, get_client_mock):
        """Tests the case that the destination host port binding is already
        ACTIVE when migrate_instance_start is called so we don't try to
        activate it again, which would result in a 409 from Neutron.
        """
        binding = {'binding': {'status': 'ACTIVE'}}
        resp = fake_req.FakeResponse(200, content=jsonutils.dumps(binding))
        get_client_mock.return_value.get.return_value = resp
        # Just create a simple instance with a single port.
        instance = objects.Instance(info_cache=objects.InstanceInfoCache(
            network_info=model.NetworkInfo([model.VIF(uuids.port_id)])))
        migration = objects.Migration(
            source_compute='source', dest_compute='dest')
        with mock.patch.object(self.api, 'activate_port_binding',
                               new_callable=mock.NonCallableMock):
            with mock.patch.object(self.api, 'supports_port_binding_extension',
                                   return_value=True):
                self.api.migrate_instance_start(
                    self.context, instance, migration)
        get_client_mock.return_value.get.assert_called_once_with(
            '/v2.0/ports/%s/bindings/dest' % uuids.port_id, raise_exc=False,
            global_request_id=self.context.global_id)

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_migrate_instance_start_no_bindings(self, get_client_mock):
        """Tests the case that migrate_instance_start is running against new
        enough neutron for the binding-extended API but the ports don't have
        a binding resource against the destination host, so no activation
        happens.
        """
        get_client_mock.return_value.get.return_value = (
            fake_req.FakeResponse(404))
        # Create an instance with two ports so we can test the short circuit
        # when we find that the first port doesn't have a dest host binding.
        instance = objects.Instance(info_cache=objects.InstanceInfoCache(
            network_info=model.NetworkInfo([
                model.VIF(uuids.port1), model.VIF(uuids.port2)])))
        migration = objects.Migration(
            source_compute='source', dest_compute='dest')
        with mock.patch.object(self.api, 'activate_port_binding',
                               new_callable=mock.NonCallableMock):
            with mock.patch.object(self.api, 'supports_port_binding_extension',
                                   return_value=True):
                self.api.migrate_instance_start(
                    self.context, instance, migration)
        get_client_mock.return_value.get.assert_called_once_with(
            '/v2.0/ports/%s/bindings/dest' % uuids.port1, raise_exc=False,
            global_request_id=self.context.global_id)

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_migrate_instance_start_get_error(self, get_client_mock):
        """Tests the case that migrate_instance_start is running against new
        enough neutron for the binding-extended API but getting the port
        binding information results in an error response from neutron.
        """
        get_client_mock.return_value.get.return_value = (
            fake_req.FakeResponse(500))
        instance = objects.Instance(info_cache=objects.InstanceInfoCache(
            network_info=model.NetworkInfo([
                model.VIF(uuids.port1), model.VIF(uuids.port2)])))
        migration = objects.Migration(
            source_compute='source', dest_compute='dest')
        with mock.patch.object(self.api, 'activate_port_binding',
                               new_callable=mock.NonCallableMock):
            with mock.patch.object(self.api, 'supports_port_binding_extension',
                                   return_value=True):
                self.api.migrate_instance_start(
                    self.context, instance, migration)
        self.assertEqual(2, get_client_mock.return_value.get.call_count)
        get_client_mock.return_value.get.assert_has_calls([
            mock.call(
                '/v2.0/ports/%s/bindings/dest' % uuids.port1,
                raise_exc=False,
                global_request_id=self.context.global_id),
            mock.call(
                '/v2.0/ports/%s/bindings/dest' % uuids.port2,
                raise_exc=False,
                global_request_id=self.context.global_id)])

    @mock.patch('nova.network.neutron.get_client')
    def test_get_requested_resource_for_instance_no_resource_request(
            self, mock_get_client):
        mock_client = mock_get_client.return_value

        ports = {'ports': [
            {
                'id': uuids.port1,
                'device_id': uuids.isnt1,
            }
        ]}
        mock_client.list_ports.return_value = ports

        request_groups = self.api.get_requested_resource_for_instance(
            self.context, uuids.inst1)

        mock_client.list_ports.assert_called_with(
            device_id=uuids.inst1, fields=['id', 'resource_request'])
        self.assertEqual([], request_groups)

    @mock.patch('nova.network.neutron.get_client')
    def test_get_requested_resource_for_instance_no_ports(
            self, mock_get_client):
        mock_client = mock_get_client.return_value

        ports = {'ports': []}
        mock_client.list_ports.return_value = ports

        request_groups = self.api.get_requested_resource_for_instance(
            self.context, uuids.inst1)

        mock_client.list_ports.assert_called_with(
            device_id=uuids.inst1, fields=['id', 'resource_request'])
        self.assertEqual([], request_groups)

    @mock.patch('nova.network.neutron.get_client')
    def test_get_requested_resource_for_instance_with_multiple_ports(
            self, mock_get_client):
        mock_client = mock_get_client.return_value

        ports = {'ports': [
            {
                'id': uuids.port1,
                'device_id': uuids.isnt1,
                'resource_request': {
                    'resources': {'NET_BW_EGR_KILOBIT_PER_SEC': 10000}}
            },
            {
                'id': uuids.port2,
                'device_id': uuids.isnt1,
                'resource_request': {}
            },
        ]}
        mock_client.list_ports.return_value = ports

        request_groups = self.api.get_requested_resource_for_instance(
            self.context, uuids.inst1)

        mock_client.list_ports.assert_called_with(
            device_id=uuids.inst1, fields=['id', 'resource_request'])
        self.assertEqual(1, len(request_groups))
        self.assertEqual(
            {'NET_BW_EGR_KILOBIT_PER_SEC': 10000},
            request_groups[0].resources)
        self.assertEqual(
            uuids.port1,
            request_groups[0].requester_id)

        mock_get_client.assert_called_once_with(self.context, admin=True)


class TestAPIModuleMethods(test.NoDBTestCase):

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
        networks = [1, 2, 3]

        neutronapi._ensure_requested_network_ordering(
            lambda x: x,
            networks,
            None)

    def test_ensure_requested_network_ordering_no_preference_hashes(self):
        networks = [{'id': 3}, {'id': 1}, {'id': 2}]

        neutronapi._ensure_requested_network_ordering(
            lambda x: x['id'],
            networks,
            None)

        self.assertEqual(networks, [{'id': 3}, {'id': 1}, {'id': 2}])

    def test_ensure_requested_network_ordering_with_preference(self):
        networks = [{'id': 3}, {'id': 1}, {'id': 2}]

        neutronapi._ensure_requested_network_ordering(
            lambda x: x['id'],
            networks,
            [1, 2, 3])

        self.assertEqual(networks, [{'id': 1}, {'id': 2}, {'id': 3}])


class TestAPIPortbinding(TestAPIBase):

    def test_allocate_for_instance_portbinding(self):
        self._test_allocate_for_instance_with_virtual_interface(
            1, bind_host_id=self.instance.get('host'))

    @mock.patch.object(neutronapi, 'get_client')
    def test_populate_neutron_extension_values_binding(self, mock_get_client):
        mocked_client = mock.create_autospec(client.Client)
        mock_get_client.return_value = mocked_client
        mocked_client.list_extensions.return_value = {'extensions': []}
        host_id = 'my_host_id'
        instance = {'host': host_id}
        port_req_body = {'port': {}}
        self.api._populate_neutron_extension_values(
            self.context, instance, None, port_req_body,
            bind_host_id=host_id)
        self.assertEqual(host_id,
                         port_req_body['port'][
                             constants.BINDING_HOST_ID])
        self.assertFalse(port_req_body['port'].get(
            constants.BINDING_PROFILE))
        mock_get_client.assert_called_once_with(mock.ANY)
        mocked_client.list_extensions.assert_called_once_with()

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_populate_neutron_extension_values_binding_sriov(self,
                                         mock_get_instance_pci_devs,
                                         mock_get_pci_device_devspec):
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
                   'physical_network': 'physnet1',
                  }

        mock_get_instance_pci_devs.return_value = [mydev]
        devspec = mock.Mock()
        devspec.get_tags.return_value = {'physical_network': 'physnet1'}
        mock_get_pci_device_devspec.return_value = devspec
        self.api._populate_neutron_binding_profile(instance,
                                                   pci_req_id, port_req_body)

        self.assertEqual(profile,
                         port_req_body['port'][
                             constants.BINDING_PROFILE])

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_populate_neutron_extension_values_binding_sriov_with_cap(self,
                                         mock_get_instance_pci_devs,
                                         mock_get_pci_device_devspec):
        host_id = 'my_host_id'
        instance = {'host': host_id}
        port_req_body = {'port': {
                             constants.BINDING_PROFILE: {
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
                   'physical_network': 'physnet1',
                   'capabilities': ['switchdev'],
                  }

        mock_get_instance_pci_devs.return_value = [mydev]
        devspec = mock.Mock()
        devspec.get_tags.return_value = {'physical_network': 'physnet1'}
        mock_get_pci_device_devspec.return_value = devspec
        self.api._populate_neutron_binding_profile(instance,
                                                   pci_req_id, port_req_body)

        self.assertEqual(profile,
                         port_req_body['port'][
                             constants.BINDING_PROFILE])

    @mock.patch.object(pci_whitelist.Whitelist, 'get_devspec')
    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_populate_neutron_extension_values_binding_sriov_fail(
        self, mock_get_instance_pci_devs, mock_get_pci_device_devspec):
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
            exception.PciDeviceNotFound,
            self.api._populate_neutron_binding_profile,
            instance, pci_req_id, port_req_body)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs', return_value=[])
    def test_populate_neutron_binding_profile_pci_dev_not_found(
            self, mock_get_instance_pci_devs):
        api = neutronapi.API()
        instance = objects.Instance(pci_devices=objects.PciDeviceList())
        port_req_body = {'port': {}}
        pci_req_id = 'my_req_id'
        self.assertRaises(exception.PciDeviceNotFound,
                          api._populate_neutron_binding_profile,
                          instance, pci_req_id, port_req_body)
        mock_get_instance_pci_devs.assert_called_once_with(
            instance, pci_req_id)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    def test_pci_parse_whitelist_called_once(self,
                                             mock_get_instance_pci_devs):
        white_list = [
            '{"address":"0000:0a:00.1","physical_network":"default"}']
        cfg.CONF.set_override('passthrough_whitelist', white_list, 'pci')

        # NOTE(takashin): neutronapi.API must be initialized
        # after the 'passthrough_whitelist' is set in this test case.
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
        instance, pf, vf = self._populate_pci_mac_address_fakes()

        port_req_body = {'port': {}}
        mock_get_instance_pci_devs.return_value = [pf]
        mock_get_mac_by_pci_address.return_value = 'fake-mac-address'
        expected_port_req_body = {'port': {'mac_address': 'fake-mac-address'}}
        req = port_req_body.copy()
        self.api._populate_pci_mac_address(instance, 0, req)
        self.assertEqual(expected_port_req_body, req)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    @mock.patch.object(pci_utils, 'get_mac_by_pci_address')
    def test_populate_pci_mac_address_vf(self, mock_get_mac_by_pci_address,
                                         mock_get_instance_pci_devs):
        instance, pf, vf = self._populate_pci_mac_address_fakes()

        port_req_body = {'port': {}}
        mock_get_instance_pci_devs.return_value = [vf]
        req = port_req_body.copy()
        self.api._populate_pci_mac_address(instance, 42, port_req_body)
        self.assertEqual(port_req_body, req)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    @mock.patch.object(pci_utils, 'get_mac_by_pci_address')
    def test_populate_pci_mac_address_vf_fail(self,
                                              mock_get_mac_by_pci_address,
                                              mock_get_instance_pci_devs):
        instance, pf, vf = self._populate_pci_mac_address_fakes()

        port_req_body = {'port': {}}
        mock_get_instance_pci_devs.return_value = [vf]
        mock_get_mac_by_pci_address.side_effect = (
            exception.PciDeviceNotFoundById)
        req = port_req_body.copy()
        self.api._populate_pci_mac_address(instance, 42, port_req_body)
        self.assertEqual(port_req_body, req)

    @mock.patch.object(pci_manager, 'get_instance_pci_devs')
    @mock.patch('nova.network.neutron.LOG.error')
    def test_populate_pci_mac_address_no_device(self, mock_log_error,
                                                mock_get_instance_pci_devs):
        instance, pf, vf = self._populate_pci_mac_address_fakes()

        port_req_body = {'port': {}}
        mock_get_instance_pci_devs.return_value = []
        req = port_req_body.copy()
        self.api._populate_pci_mac_address(instance, 42, port_req_body)
        self.assertEqual(port_req_body, req)
        self.assertEqual(42, mock_log_error.call_args[0][1])

    def _test_update_port_binding_true(self, expected_bind_host,
                                       func_name, *args):
        func = getattr(self.api, func_name)

        search_opts = {'device_id': self.instance['uuid'],
                       'tenant_id': self.instance['project_id']}
        ports = {'ports': [{'id': 'test1'}]}
        port_req_body = {'port':
                         {constants.BINDING_HOST_ID: expected_bind_host,
                          'device_owner': 'compute:%s' %
                                          self.instance['availability_zone']}}
        mocked_client = mock.create_autospec(client.Client)
        mocked_client.list_ports.return_value = ports
        mocked_client.update_port.return_value = None
        with mock.patch.object(neutronapi, 'get_client',
                return_value=mocked_client) as mock_get_client:
            func(*args)

        mock_get_client.assert_called_once_with(mock.ANY, admin=True)
        mocked_client.list_ports.assert_called_once_with(**search_opts)
        mocked_client.update_port.assert_called_once_with(
            'test1', port_req_body)

    def _test_update_port_true_exception(self, expected_bind_host,
                                         func_name, *args):
        func = getattr(self.api, func_name)

        search_opts = {'device_id': self.instance['uuid'],
                       'tenant_id': self.instance['project_id']}
        ports = {'ports': [{'id': 'test1'}]}
        port_req_body = {'port':
                         {constants.BINDING_HOST_ID: expected_bind_host,
                          'device_owner': 'compute:%s' %
                                          self.instance['availability_zone']}}
        mocked_client = mock.create_autospec(client.Client)
        mocked_client.list_ports.return_value = ports
        mocked_client.update_port.side_effect = Exception(
            "fail to update port")
        with mock.patch.object(neutronapi, 'get_client',
                return_value=mocked_client) as mock_get_client:
            self.assertRaises(NEUTRON_CLIENT_EXCEPTION,
                              func,
                              *args)

        mock_get_client.assert_called_once_with(mock.ANY, admin=True)
        mocked_client.list_ports.assert_called_once_with(**search_opts)
        mocked_client.update_port.assert_called_once_with(
            'test1', port_req_body)

    def test_migrate_instance_finish_binding_true(self):
        migration = objects.Migration(source_compute=self.instance.get('host'),
                                      dest_compute='dest_host')
        instance = self._fake_instance_object(self.instance)
        self._test_update_port_binding_true('dest_host',
                                            'migrate_instance_finish',
                                            self.context,
                                            instance,
                                            migration,
                                            {})

    def test_migrate_instance_finish_binding_true_exception(self):
        migration = objects.Migration(source_compute=self.instance.get('host'),
                                      dest_compute='dest_host')
        instance = self._fake_instance_object(self.instance)
        self._test_update_port_true_exception('dest_host',
                                              'migrate_instance_finish',
                                              self.context,
                                              instance,
                                              migration,
                                              {})

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

    @mock.patch('nova.network.neutron._get_ksa_client',
                new_callable=mock.NonCallableMock)
    def test_bind_ports_to_host_no_ports(self, mock_client):
        self.assertDictEqual({},
                             self.api.bind_ports_to_host(
                                 mock.sentinel.context,
                                 objects.Instance(info_cache=None),
                                 'fake-host'))

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_bind_ports_to_host(self, mock_client):
        """Tests a single port happy path where everything is successful."""
        def post_side_effect(*args, **kwargs):
            self.assertDictEqual(binding, kwargs['json'])
            return mock.DEFAULT

        nwinfo = model.NetworkInfo([model.VIF(uuids.port)])
        inst = objects.Instance(
            info_cache=objects.InstanceInfoCache(network_info=nwinfo))
        ctxt = context.get_context()
        binding = {'binding': {'host': 'fake-host',
                               'vnic_type': 'normal',
                               'profile': {'foo': 'bar'}}}

        resp = fake_req.FakeResponse(200, content=jsonutils.dumps(binding))
        mock_client.return_value.post.return_value = resp
        mock_client.return_value.post.side_effect = post_side_effect
        result = self.api.bind_ports_to_host(
            ctxt, inst, 'fake-host', {uuids.port: 'normal'},
            {uuids.port: {'foo': 'bar'}})
        self.assertEqual(1, mock_client.return_value.post.call_count)
        self.assertDictEqual({uuids.port: binding['binding']}, result)

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_bind_ports_to_host_with_vif_profile_and_vnic(self, mock_client):
        """Tests bind_ports_to_host with default/non-default parameters."""
        def post_side_effect(*args, **kwargs):
            self.assertDictEqual(binding, kwargs['json'])
            return mock.DEFAULT

        ctxt = context.get_context()
        vif_profile = {'foo': 'default'}
        nwinfo = model.NetworkInfo([model.VIF(id=uuids.port,
                                              vnic_type="direct",
                                              profile=vif_profile)])
        inst = objects.Instance(
            info_cache=objects.InstanceInfoCache(network_info=nwinfo))
        binding = {'binding': {'host': 'fake-host',
                               'vnic_type': 'direct',
                               'profile': vif_profile}}
        resp = fake_req.FakeResponse(200, content=jsonutils.dumps(binding))
        mock_client.return_value.post.return_value = resp
        mock_client.return_value.post.side_effect = post_side_effect
        result = self.api.bind_ports_to_host(ctxt, inst, 'fake-host')
        self.assertEqual(1, mock_client.return_value.post.call_count)
        self.assertDictEqual({uuids.port: binding['binding']}, result)

        # assert that that if vnic_type and profile are set in VIF object
        # the provided vnic_type and profile take precedence.

        nwinfo = model.NetworkInfo([model.VIF(id=uuids.port,
                                              vnic_type='direct',
                                              profile=vif_profile)])
        inst = objects.Instance(
            info_cache=objects.InstanceInfoCache(network_info=nwinfo))
        vif_profile_per_port = {uuids.port: {'foo': 'overridden'}}
        vnic_type_per_port = {uuids.port: "direct-overridden"}
        binding = {'binding': {'host': 'fake-host',
                               'vnic_type': 'direct-overridden',
                               'profile': {'foo': 'overridden'}}}
        resp = fake_req.FakeResponse(200, content=jsonutils.dumps(binding))
        mock_client.return_value.post.return_value = resp
        result = self.api.bind_ports_to_host(
            ctxt, inst, 'fake-host', vnic_type_per_port, vif_profile_per_port)
        self.assertEqual(2, mock_client.return_value.post.call_count)
        self.assertDictEqual({uuids.port: binding['binding']}, result)

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_bind_ports_to_host_rollback(self, mock_client):
        """Tests a scenario where an instance has two ports, and binding the
        first is successful but binding the second fails, so the code will
        rollback the binding for the first port.
        """
        nwinfo = model.NetworkInfo([
            model.VIF(uuids.ok), model.VIF(uuids.fail)])
        inst = objects.Instance(
            info_cache=objects.InstanceInfoCache(network_info=nwinfo))

        def fake_post(url, *args, **kwargs):
            if uuids.ok in url:
                mock_response = fake_req.FakeResponse(
                    200, content='{"binding": {"host": "fake-host"}}')
            else:
                mock_response = fake_req.FakeResponse(500, content='error')
            return mock_response

        mock_client.return_value.post.side_effect = fake_post
        with mock.patch.object(self.api, 'delete_port_binding',
                               # This will be logged but not re-raised.
                               side_effect=exception.PortBindingDeletionFailed(
                                   port_id=uuids.ok, host='fake-host'
                               )) as mock_delete:
            self.assertRaises(exception.PortBindingFailed,
                              self.api.bind_ports_to_host,
                              self.context, inst, 'fake-host')
        # assert that post was called twice and delete once
        self.assertEqual(2, mock_client.return_value.post.call_count)
        mock_delete.assert_called_once_with(self.context, uuids.ok,
                                            'fake-host')

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_delete_port_binding(self, mock_client):
        # Create three ports where:
        # - one is successfully unbound
        # - one is not found
        # - one fails to be unbound
        def fake_delete(url, *args, **kwargs):
            if uuids.ok in url:
                return fake_req.FakeResponse(204)
            else:
                status_code = 404 if uuids.notfound in url else 500
                return fake_req.FakeResponse(status_code)

        mock_client.return_value.delete.side_effect = fake_delete
        for port_id in (uuids.ok, uuids.notfound, uuids.fail):
            if port_id == uuids.fail:
                self.assertRaises(exception.PortBindingDeletionFailed,
                                  self.api.delete_port_binding,
                                  self.context, port_id, 'fake-host')
            else:
                self.api.delete_port_binding(self.context, port_id,
                                             'fake-host')

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_activate_port_binding(self, mock_client):
        """Tests the happy path of activating an inactive port binding."""
        resp = fake_req.FakeResponse(200)
        mock_client.return_value.put.return_value = resp
        self.api.activate_port_binding(self.context, uuids.port_id,
                                       'fake-host')
        mock_client.return_value.put.assert_called_once_with(
            '/v2.0/ports/%s/bindings/fake-host/activate' % uuids.port_id,
            raise_exc=False,
            global_request_id=self.context.global_id)

    @mock.patch('nova.network.neutron._get_ksa_client')
    @mock.patch('nova.network.neutron.LOG.warning')
    def test_activate_port_binding_already_active(
            self, mock_log_warning, mock_client):
        """Tests the 409 case of activating an already active port binding."""
        mock_client.return_value.put.return_value = fake_req.FakeResponse(409)
        self.api.activate_port_binding(self.context, uuids.port_id,
                                       'fake-host')
        mock_client.return_value.put.assert_called_once_with(
            '/v2.0/ports/%s/bindings/fake-host/activate' % uuids.port_id,
            raise_exc=False,
            global_request_id=self.context.global_id)
        self.assertEqual(1, mock_log_warning.call_count)
        self.assertIn('is already active', mock_log_warning.call_args[0][0])

    @mock.patch('nova.network.neutron._get_ksa_client')
    def test_activate_port_binding_fails(self, mock_client):
        """Tests the unknown error case of binding activation."""
        mock_client.return_value.put.return_value = fake_req.FakeResponse(500)
        self.assertRaises(exception.PortBindingActivationFailed,
                          self.api.activate_port_binding,
                          self.context, uuids.port_id, 'fake-host')
        mock_client.return_value.put.assert_called_once_with(
            '/v2.0/ports/%s/bindings/fake-host/activate' % uuids.port_id,
            raise_exc=False,
            global_request_id=self.context.global_id)


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
            api.allocate_for_instance, self.context, self.instance, None)

    @mock.patch.object(neutronapi.API, 'get_instance_nw_info')
    @mock.patch.object(neutronapi.API, '_update_ports_for_instance')
    @mock.patch.object(neutronapi.API, '_create_ports_for_instance')
    @mock.patch.object(neutronapi.API, '_process_security_groups')
    @mock.patch.object(neutronapi.API, '_clean_security_groups')
    @mock.patch.object(neutronapi.API, '_validate_requested_network_ids')
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    def test_allocate_for_instance_minimal_args(self, mock_get_client,
            mock_validate_ports, mock_validate_nets, mock_clean_sg, mock_sg,
            mock_create_ports, mock_update_ports, mock_gni):

        api = neutronapi.API()
        mock_get_client.side_effect = ["user", "admin"]
        mock_validate_ports.return_value = ({}, "ordered_nets")
        mock_validate_nets.return_value = "nets"
        mock_clean_sg.return_value = "security_groups"
        mock_sg.return_value = "security_group_ids"
        mock_create_ports.return_value = "requests_and_created_ports"
        mock_update_ports.return_value = (
            "nets", "ports", [uuids.preexist], [uuids.created])
        mock_gni.return_value = [
            {"id": uuids.created}, {"id": uuids.preexist}, {"id": "foo"}
        ]

        result = api.allocate_for_instance(self.context, self.instance, None)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"id": uuids.created})
        self.assertEqual(result[1], {"id": uuids.preexist})

        mock_validate_ports.assert_called_once_with(
            self.context, self.instance, "admin", None)

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
        rules = {'network:attach_external_network': 'is_admin:True'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
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
                bind_host_id, requested_ports_dict)

        self.assertEqual([net1, net2], ordered_nets, "ordered_nets")
        self.assertEqual([uuids.port1, uuids.port2], ordered_ports,
            "ordered_ports")
        self.assertEqual([uuids.port2], preexisting_port_ids, "preexisting")
        self.assertEqual([uuids.port1], created_port_ids, "created")
        mock_admin.update_port.assert_called_with(uuids.port2,
            {'port': {
                'device_owner': 'compute:test_az',
                constants.BINDING_HOST_ID: bind_host_id,
                'device_id': self.instance.uuid}})


class TestAPINeutronHostnameDNS(TestAPIBase):

    def test_allocate_for_instance_create_port(self):
        # The port's dns_name attribute should be set by the port create
        # request in allocate_for_instance
        self._test_allocate_for_instance_with_virtual_interface(
            1, dns_extension=True)

    def test_allocate_for_instance_with_requested_port(self):
        # The port's dns_name attribute should be set by the port update
        # request in allocate_for_instance
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=1, dns_extension=True,
            requested_networks=requested_networks)

    def test_allocate_for_instance_port_dns_name_preset_equal_hostname(self):
        # The port's dns_name attribute should be set by the port update
        # request in allocate_for_instance. The port's dns_name was preset by
        # the user with a value equal to the instance's hostname
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=1, dns_extension=True,
            requested_networks=requested_networks,
            _dns_name='test-instance')

    def test_allocate_for_instance_port_dns_name_preset_noteq_hostname(self):
        # If a pre-existing port has dns_name set, an exception should be
        # raised if dns_name is not equal to the instance's hostname
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._test_allocate_for_instance(
            requested_networks=requested_networks,
            exception=exception.PortNotUsableDNS,
            dns_extension=True,
            _break='pre_list_networks',
            _dns_name='my-instance')


class TestAPINeutronHostnameDNSPortbinding(TestAPIBase):

    def test_allocate_for_instance_create_port(self):
        # The port's dns_name attribute should be set by the port create
        # request in allocate_for_instance
        self._test_allocate_for_instance_with_virtual_interface(
            1, dns_extension=True, bind_host_id=self.instance.get('host'))

    def test_allocate_for_instance_with_requested_port(self):
        # The port's dns_name attribute should be set by the port update
        # request in allocate_for_instance
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=1, dns_extension=True,
            bind_host_id=self.instance.get('host'),
            requested_networks=requested_networks)

    def test_allocate_for_instance_create_port_with_dns_domain(self):
        # The port's dns_name attribute should be set by the port update
        # request in _update_port_dns_name. This should happen only when the
        # port binding extension is enabled and the port's network has a
        # non-blank dns_domain attribute
        self._test_allocate_for_instance_with_virtual_interface(
            11, dns_extension=True, bind_host_id=self.instance.get('host'))

    def test_allocate_for_instance_with_requested_port_with_dns_domain(self):
        # The port's dns_name attribute should be set by the port update
        # request in _update_port_dns_name. This should happen only when the
        # port binding extension is enabled and the port's network has a
        # non-blank dns_domain attribute
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=uuids.portid_1)])
        self._test_allocate_for_instance_with_virtual_interface(
            net_idx=11, dns_extension=True,
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

        self.flags(endpoint_override='http://anyhost/', group='neutron')
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
            CONF.neutron.endpoint_override,
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
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_no_security_groups_requested(
            self, mock_vif, mock_get_client,
            mock_validate_requested_port_ids,
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

        mock_validate_requested_port_ids.return_value = [{}, onets]
        mock_get_available_networks.return_value = nets
        mock_process_security_groups.return_value = []

        api = neutronapi.API()
        mock_create_port.return_value = {'id': 'foo', 'mac_address': 'bar'}
        api.allocate_for_instance(
            'context', instance, requested_networks=onets,
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
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_security_groups_requested(
            self, mock_vif, mock_get_client,
            mock_validate_requested_port_ids,
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

        mock_validate_requested_port_ids.return_value = [{}, onets]
        mock_get_available_networks.return_value = nets
        mock_process_security_groups.return_value = ['default-uuid',
                                                     'secgrp-uuid1',
                                                     'secgrp-uuid2']

        api = neutronapi.API()
        mock_create_port.return_value = {'id': 'foo', 'mac_address': 'bar'}
        api.allocate_for_instance(
            'context', instance, requested_networks=onets,
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
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_port_security_disabled_no_security_groups_requested(
            self, mock_vif, mock_get_client,
            mock_validate_requested_port_ids,
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

        mock_validate_requested_port_ids.return_value = [{}, onets]
        mock_get_available_networks.return_value = nets
        mock_process_security_groups.return_value = []

        api = neutronapi.API()
        mock_create_port.return_value = {'id': 'foo', 'mac_address': 'bar'}
        api.allocate_for_instance(
            'context', instance, requested_networks=onets,
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
    @mock.patch.object(neutronapi.API, '_validate_requested_port_ids')
    @mock.patch.object(neutronapi, 'get_client')
    @mock.patch('nova.objects.VirtualInterface')
    def test_port_security_disabled_and_security_groups_requested(
            self, mock_vif, mock_get_client,
            mock_validate_requested_port_ids,
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

        mock_validate_requested_port_ids.return_value = [{}, onets]
        mock_get_available_networks.return_value = nets
        mock_process_security_groups.return_value = ['default-uuid',
                                                     'secgrp-uuid1',
                                                     'secgrp-uuid2']

        api = neutronapi.API()
        self.assertRaises(
            exception.SecurityGroupCannotBeApplied,
            api.allocate_for_instance,
            'context', instance, requested_networks=onets,
            security_groups=secgroups)

        mock_process_security_groups.assert_called_once_with(
            instance, mock.ANY, ['default', 'secgrp1', 'secgrp2'])


class TestAPIAutoAllocateNetwork(test.NoDBTestCase):
    """Tests auto-allocation scenarios"""

    def setUp(self):
        super(TestAPIAutoAllocateNetwork, self).setUp()
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

        @mock.patch('nova.network.neutron.get_client', return_value=ntrn)
        @mock.patch.object(self.api, '_auto_allocate_network',
                           return_value=fake_network)
        @mock.patch.object(self.api, '_check_external_network_attach')
        @mock.patch.object(self.api, '_populate_neutron_extension_values')
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
                    populate_ext_values_mock,
                    check_external_net_attach_mock,
                    auto_allocate_mock,
                    get_client_mock):
            instance = fake_instance.fake_instance_obj(self.context)
            net_req = objects.NetworkRequest(
                network_id=net_req_obj.NETWORK_ID_AUTO)
            requested_networks = objects.NetworkRequestList(objects=[net_req])

            nw_info = self.api.allocate_for_instance(
                self.context, instance, requested_networks)
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


class TestGetInstanceNetworkInfo(test.NoDBTestCase):
    """Tests rebuilding the network_info cache."""

    def setUp(self):
        super(TestGetInstanceNetworkInfo, self).setUp()
        self.api = neutronapi.API()
        self.context = context.RequestContext(uuids.user_id, uuids.project_id)
        self.instance = fake_instance.fake_instance_obj(self.context)
        client_mock = mock.patch('nova.network.neutron.get_client')
        self.client = client_mock.start().return_value
        self.addCleanup(client_mock.stop)
        # This is a no-db set of tests and we don't care about refreshing the
        # info_cache from the database so just mock it out.
        refresh_info_cache_for_instance = mock.patch(
            'nova.compute.utils.refresh_info_cache_for_instance')
        refresh_info_cache_for_instance.start()
        self.addCleanup(refresh_info_cache_for_instance.stop)

    @staticmethod
    def _get_vif_in_cache(info_cache, vif_id):
        for vif in info_cache:
            if vif['id'] == vif_id:
                return vif

    @staticmethod
    def _get_fake_info_cache(vif_ids, **kwargs):
        """Returns InstanceInfoCache based on the list of provided VIF IDs"""
        nwinfo = model.NetworkInfo(
            [model.VIF(vif_id, **kwargs) for vif_id in vif_ids])
        return objects.InstanceInfoCache(network_info=nwinfo)

    @staticmethod
    def _get_fake_port(port_id, **kwargs):
        network_id = kwargs.get('network_id', uuids.network_id)
        return {'id': port_id, 'network_id': network_id}

    @staticmethod
    def _get_fake_vif(context, **kwargs):
        """Returns VirtualInterface based on provided VIF ID"""
        return obj_vif.VirtualInterface(context=context, **kwargs)

    def test_get_nw_info_refresh_vif_id_add_vif(self):
        """Tests that a network-changed event occurred on a single port
        which is not already in the cache so it's added.
        """
        # The cache has one existing port.
        self.instance.info_cache = self._get_fake_info_cache([uuids.old_port])
        # The instance has two ports, one old, one new.
        self.client.list_ports.return_value = {
            'ports': [self._get_fake_port(uuids.old_port),
                      self._get_fake_port(uuids.new_port)]}
        with test.nested(
            mock.patch.object(self.api, '_get_available_networks',
                              return_value=[{'id': uuids.network_id}]),
            mock.patch.object(self.api, '_build_vif_model',
                              return_value=model.VIF(uuids.new_port)),
            # We should not get as far as calling _gather_port_ids_and_networks
            mock.patch.object(self.api, '_gather_port_ids_and_networks',
                              new_callable=mock.NonCallableMock)
        ) as (
            get_nets, build_vif, gather_ports
        ):
            nwinfo = self.api._get_instance_nw_info(
                self.context, self.instance, refresh_vif_id=uuids.new_port)
        get_nets.assert_called_once_with(
            self.context, self.instance.project_id,
            [uuids.network_id], self.client)
        # Assert that the old and new ports are in the cache.
        for port_id in (uuids.old_port, uuids.new_port):
            self.assertIsNotNone(self._get_vif_in_cache(nwinfo, port_id))

    def test_get_nw_info_refresh_vif_id_update_vif(self):
        """Tests that a network-changed event occurred on a single port
        which is already in the cache so it's updated.
        """
        # The cache has two existing active VIFs.
        self.instance.info_cache = self._get_fake_info_cache(
            [uuids.old_port, uuids.new_port], active=True)
        # The instance has two ports, one old, one new.
        self.client.list_ports.return_value = {
            'ports': [self._get_fake_port(uuids.old_port),
                      self._get_fake_port(uuids.new_port)]}
        with test.nested(
            mock.patch.object(self.api, '_get_available_networks',
                              return_value=[{'id': uuids.network_id}]),
            # Fake that the port is no longer active.
            mock.patch.object(self.api, '_build_vif_model',
                              return_value=model.VIF(
                                  uuids.new_port, active=False)),
            # We should not get as far as calling _gather_port_ids_and_networks
            mock.patch.object(self.api, '_gather_port_ids_and_networks',
                              new_callable=mock.NonCallableMock)
        ) as (
            get_nets, build_vif, gather_ports
        ):
            nwinfo = self.api._get_instance_nw_info(
                self.context, self.instance, refresh_vif_id=uuids.new_port)
        get_nets.assert_called_once_with(
            self.context, self.instance.project_id,
            [uuids.network_id], self.client)
        # Assert that the old and new ports are in the cache and that the
        # old port is still active and the new port is not active.
        old_vif = self._get_vif_in_cache(nwinfo, uuids.old_port)
        self.assertIsNotNone(old_vif)
        self.assertTrue(old_vif['active'])
        new_vif = self._get_vif_in_cache(nwinfo, uuids.new_port)
        self.assertIsNotNone(new_vif)
        self.assertFalse(new_vif['active'])

    def test_get_nw_info_refresh_vif_id_remove_vif(self):
        """Tests that a network-changed event occurred on a single port
        which is already in the cache but not in the current list of ports
        for the instance, so it's removed from the cache.
        """
        # The cache has two existing VIFs.
        self.instance.info_cache = self._get_fake_info_cache(
            [uuids.old_port, uuids.removed_port])
        # The instance has one remaining port.
        self.client.list_ports.return_value = {
            'ports': [self._get_fake_port(uuids.old_port)]}
        # We should not get as far as calling _gather_port_ids_and_networks
        with mock.patch.object(
                self.api, '_gather_port_ids_and_networks',
                new_callable=mock.NonCallableMock):
            nwinfo = self.api._get_instance_nw_info(
                self.context, self.instance, refresh_vif_id=uuids.removed_port)
        # Assert that only the old port is still in the cache.
        old_vif = self._get_vif_in_cache(nwinfo, uuids.old_port)
        self.assertIsNotNone(old_vif)
        removed_vif = self._get_vif_in_cache(nwinfo, uuids.removed_port)
        self.assertIsNone(removed_vif)

    def test_get_instance_nw_info_force_refresh(self):
        """Tests a full refresh of the instance info cache using information
        from neutron rather than the instance's current info cache data.
        """
        # Fake out an empty cache.
        self.instance.info_cache = self._get_fake_info_cache([])
        # The instance has one attached port in neutron.
        self.client.list_ports.return_value = {
            'ports': [self._get_fake_port(uuids.port_id)]}
        ordered_port_list = [uuids.port_id]

        with test.nested(
            mock.patch.object(self.api, '_get_available_networks',
                              return_value=[{'id': uuids.network_id}]),
            mock.patch.object(self.api, '_build_vif_model',
                              return_value=model.VIF(uuids.port_id)),
            # We should not call _gather_port_ids_and_networks since that uses
            # the existing instance.info_cache when no ports/networks are
            # passed to _build_network_info_model and what we want is a full
            # refresh of the ports based on what neutron says is current.
            mock.patch.object(self.api, '_gather_port_ids_and_networks',
                              new_callable=mock.NonCallableMock),
            mock.patch.object(self.api, '_get_ordered_port_list',
                              return_value=ordered_port_list)
        ) as (
            get_nets, build_vif, gather_ports, mock_port_map
        ):
            nwinfo = self.api._get_instance_nw_info(
                self.context, self.instance, force_refresh=True)
        get_nets.assert_called_once_with(
            self.context, self.instance.project_id,
            [uuids.network_id], self.client)
        # Assert that the port is in the cache now.
        self.assertIsNotNone(self._get_vif_in_cache(nwinfo, uuids.port_id))

    def test__get_ordered_port_list(self):
        """This test if port_list is sorted by VirtualInterface id
        sequence.
        """
        nova_vifs = [
            self._get_fake_vif(self.context,
                               uuid=uuids.port_id_1, id=0),
            self._get_fake_vif(self.context,
                               uuid=uuids.port_id_2, id=1),
            self._get_fake_vif(self.context,
                               uuid=uuids.port_id_3, id=2),
        ]
        # Random order.
        current_neutron_ports = [
            self._get_fake_port(uuids.port_id_2),
            self._get_fake_port(uuids.port_id_1),
            self._get_fake_port(uuids.port_id_3),
        ]
        expected_port_list = [uuids.port_id_1,
                              uuids.port_id_2,
                              uuids.port_id_3]
        with mock.patch.object(self.api, 'get_vifs_by_instance',
                               return_value=nova_vifs):
            port_list = self.api._get_ordered_port_list(
               self.context, self.instance, current_neutron_ports)
            self.assertEqual(expected_port_list,
                             port_list)

    def test__get_ordered_port_list_new_port(self):
        """This test if port_list is sorted by VirtualInterface id
        sequence while new port appears.
        """
        nova_vifs = [
            self._get_fake_vif(self.context,
                               uuid=uuids.port_id_1, id=0),
            self._get_fake_vif(self.context,
                               uuid=uuids.port_id_3, id=2),
        ]
        # New port appears.
        current_neutron_ports = [
            self._get_fake_port(uuids.port_id_1),
            self._get_fake_port(uuids.port_id_4),
            self._get_fake_port(uuids.port_id_3)
        ]
        expected_port_list = [uuids.port_id_1,
                              uuids.port_id_3,
                              uuids.port_id_4]
        with mock.patch.object(self.api, 'get_vifs_by_instance',
                               return_value=nova_vifs):
            port_list = self.api._get_ordered_port_list(
               self.context, self.instance, current_neutron_ports)
            self.assertEqual(expected_port_list,
                             port_list)

    def test__get_ordered_port_list_new_port_and_deleted_vif(self):
        """This test if port_list is sorted by VirtualInterface id
        sequence while new port appears along with deleted old
        VirtualInterface objects.
        """
        # Display also deleted VirtualInterface.
        nova_vifs = [
            self._get_fake_vif(self.context,
                               uuid=uuids.port_id_1, id=0,
                               deleted=True),
            self._get_fake_vif(self.context,
                               uuid=uuids.port_id_2, id=3),
            self._get_fake_vif(self.context,
                               uuid=uuids.port_id_3, id=5),
        ]
        # Random order and new port.
        current_neutron_ports = [
            self._get_fake_port(uuids.port_id_4),
            self._get_fake_port(uuids.port_id_3),
            self._get_fake_port(uuids.port_id_2),
        ]
        expected_port_list = [uuids.port_id_2,
                              uuids.port_id_3,
                              uuids.port_id_4]
        with mock.patch.object(self.api, 'get_vifs_by_instance',
                               return_value=nova_vifs):
            port_list = self.api._get_ordered_port_list(
               self.context, self.instance, current_neutron_ports)
            self.assertEqual(expected_port_list,
                             port_list)
