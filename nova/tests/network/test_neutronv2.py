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
import copy
import uuid

import mock
import mox
from neutronclient.common import exceptions
from neutronclient.v2_0 import client
from oslo.config import cfg
import six

from nova.compute import flavors
from nova.conductor import api as conductor_api
from nova import context
from nova import exception
from nova.network import model
from nova.network import neutronv2
from nova.network.neutronv2 import api as neutronapi
from nova.network.neutronv2 import constants
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import local
from nova import test
from nova import utils

CONF = cfg.CONF

#NOTE: Neutron client raises Exception which is discouraged by HACKING.
#      We set this variable here and use it for assertions below to avoid
#      the hacking checks until we can make neutron client throw a custom
#      exception class instead.
NEUTRON_CLIENT_EXCEPTION = Exception


class MyComparator(mox.Comparator):
    def __init__(self, lhs):
        self.lhs = lhs

    def _com_dict(self, lhs, rhs):
        if len(lhs) != len(rhs):
            return False
        for key, value in lhs.iteritems():
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


class TestNeutronClient(test.TestCase):
    def test_withtoken(self):
        self.flags(neutron_url='http://anyhost/')
        self.flags(neutron_url_timeout=30)
        my_context = context.RequestContext('userid',
                                            'my_tenantid',
                                            auth_token='token')
        self.mox.StubOutWithMock(client.Client, "__init__")
        client.Client.__init__(
            auth_strategy=CONF.neutron_auth_strategy,
            endpoint_url=CONF.neutron_url,
            token=my_context.auth_token,
            timeout=CONF.neutron_url_timeout,
            insecure=False,
            ca_cert=None).AndReturn(None)
        self.mox.ReplayAll()
        neutronv2.get_client(my_context)

    def test_withouttoken(self):
        my_context = context.RequestContext('userid', 'my_tenantid')
        self.assertRaises(exceptions.Unauthorized,
                          neutronv2.get_client,
                          my_context)

    def test_withtoken_context_is_admin(self):
        self.flags(neutron_url='http://anyhost/')
        self.flags(neutron_url_timeout=30)
        my_context = context.RequestContext('userid',
                                            'my_tenantid',
                                            auth_token='token',
                                            is_admin=True)
        self.mox.StubOutWithMock(client.Client, "__init__")
        client.Client.__init__(
            auth_strategy=CONF.neutron_auth_strategy,
            endpoint_url=CONF.neutron_url,
            token=my_context.auth_token,
            timeout=CONF.neutron_url_timeout,
            insecure=False,
            ca_cert=None).AndReturn(None)
        self.mox.ReplayAll()
        # Note that although we have admin set in the context we
        # are not asking for an admin client, and so we auth with
        # our own token
        neutronv2.get_client(my_context)

    def test_withouttoken_keystone_connection_error(self):
        self.flags(neutron_auth_strategy='keystone')
        self.flags(neutron_url='http://anyhost/')
        my_context = context.RequestContext('userid', 'my_tenantid')
        self.assertRaises(NEUTRON_CLIENT_EXCEPTION,
                          neutronv2.get_client,
                          my_context)


class TestNeutronv2Base(test.TestCase):

    def setUp(self):
        super(TestNeutronv2Base, self).setUp()
        self.context = context.RequestContext('userid', 'my_tenantid')
        setattr(self.context,
                'auth_token',
                'bff4a5a6b9eb4ea2a6efec6eefb77936')
        self.instance = {'project_id': '9d049e4b60b64716978ab415e6fbd5c0',
                         'uuid': str(uuid.uuid4()),
                         'display_name': 'test_instance',
                         'availability_zone': 'nova',
                         'host': 'some_host',
                         'security_groups': []}
        self.instance2 = {'project_id': '9d049e4b60b64716978ab415e6fbd5c0',
                         'uuid': str(uuid.uuid4()),
                         'display_name': 'test_instance2',
                         'availability_zone': 'nova',
                         'security_groups': []}
        self.nets1 = [{'id': 'my_netid1',
                      'name': 'my_netname1',
                      'subnets': ['mysubnid1'],
                      'tenant_id': 'my_tenantid'}]
        self.nets2 = []
        self.nets2.append(self.nets1[0])
        self.nets2.append({'id': 'my_netid2',
                           'name': 'my_netname2',
                           'subnets': ['mysubnid2'],
                           'tenant_id': 'my_tenantid'})
        self.nets3 = self.nets2 + [{'id': 'my_netid3',
                                    'name': 'my_netname3',
                                    'tenant_id': 'my_tenantid'}]
        self.nets4 = [{'id': 'his_netid4',
                      'name': 'his_netname4',
                      'tenant_id': 'his_tenantid'}]
        # A network request with external networks
        self.nets5 = self.nets1 + [{'id': 'the-external-one',
                                    'name': 'out-of-this-world',
                                    'router:external': True,
                                    'tenant_id': 'should-be-an-admin'}]
        self.nets = [self.nets1, self.nets2, self.nets3,
                     self.nets4, self.nets5]

        self.port_address = '10.0.1.2'
        self.port_data1 = [{'network_id': 'my_netid1',
                           'device_id': self.instance2['uuid'],
                           'device_owner': 'compute:nova',
                           'id': 'my_portid1',
                           'status': 'DOWN',
                           'admin_state_up': True,
                           'fixed_ips': [{'ip_address': self.port_address,
                                          'subnet_id': 'my_subid1'}],
                           'mac_address': 'my_mac1', }]
        self.float_data1 = [{'port_id': 'my_portid1',
                             'fixed_ip_address': self.port_address,
                             'floating_ip_address': '172.0.1.2'}]
        self.dhcp_port_data1 = [{'fixed_ips': [{'ip_address': '10.0.1.9',
                                               'subnet_id': 'my_subid1'}],
                                 'status': 'ACTIVE',
                                 'admin_state_up': True}]
        self.port_address2 = '10.0.2.2'
        self.port_data2 = []
        self.port_data2.append(self.port_data1[0])
        self.port_data2.append({'network_id': 'my_netid2',
                                'device_id': self.instance['uuid'],
                                'admin_state_up': True,
                                'status': 'ACTIVE',
                                'device_owner': 'compute:nova',
                                'id': 'my_portid2',
                                'fixed_ips':
                                        [{'ip_address': self.port_address2,
                                          'subnet_id': 'my_subid2'}],
                                'mac_address': 'my_mac2', })
        self.float_data2 = []
        self.float_data2.append(self.float_data1[0])
        self.float_data2.append({'port_id': 'my_portid2',
                                 'fixed_ip_address': '10.0.2.2',
                                 'floating_ip_address': '172.0.2.2'})
        self.port_data3 = [{'network_id': 'my_netid1',
                           'device_id': 'device_id3',
                           'status': 'DOWN',
                           'admin_state_up': True,
                           'device_owner': 'compute:nova',
                           'id': 'my_portid3',
                           'fixed_ips': [],  # no fixed ip
                           'mac_address': 'my_mac3', }]
        self.subnet_data1 = [{'id': 'my_subid1',
                             'cidr': '10.0.1.0/24',
                             'network_id': 'my_netid1',
                             'gateway_ip': '10.0.1.1',
                             'dns_nameservers': ['8.8.1.1', '8.8.1.2']}]
        self.subnet_data2 = []
        self.subnet_data_n = [{'id': 'my_subid1',
                               'cidr': '10.0.1.0/24',
                               'network_id': 'my_netid1',
                               'gateway_ip': '10.0.1.1',
                               'dns_nameservers': ['8.8.1.1', '8.8.1.2']},
                              {'id': 'my_subid2',
                               'cidr': '20.0.1.0/24',
                              'network_id': 'my_netid2',
                              'gateway_ip': '20.0.1.1',
                              'dns_nameservers': ['8.8.1.1', '8.8.1.2']}]
        self.subnet_data2.append({'id': 'my_subid2',
                                  'cidr': '10.0.2.0/24',
                                  'network_id': 'my_netid2',
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
        self.fip_unassociated = {'tenant_id': 'my_tenantid',
                                 'id': 'fip_id1',
                                 'floating_ip_address': '172.24.4.227',
                                 'floating_network_id': self.fip_pool['id'],
                                 'port_id': None,
                                 'fixed_ip_address': None,
                                 'router_id': None}
        fixed_ip_address = self.port_data2[1]['fixed_ips'][0]['ip_address']
        self.fip_associated = {'tenant_id': 'my_tenantid',
                               'id': 'fip_id2',
                               'floating_ip_address': '172.24.4.228',
                               'floating_network_id': self.fip_pool['id'],
                               'port_id': self.port_data2[1]['id'],
                               'fixed_ip_address': fixed_ip_address,
                               'router_id': 'router_id1'}
        self._returned_nw_info = []
        self.mox.StubOutWithMock(neutronv2, 'get_client')
        self.moxed_client = self.mox.CreateMock(client.Client)
        self.addCleanup(CONF.reset)
        self.addCleanup(self.mox.VerifyAll)
        self.addCleanup(self.mox.UnsetStubs)
        self.addCleanup(self.stubs.UnsetAll)

    def _stub_allocate_for_instance(self, net_idx=1, **kwargs):
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, 'get_instance_nw_info')
        has_portbinding = False
        has_extra_dhcp_opts = False
        dhcp_options = kwargs.get('dhcp_options')
        if dhcp_options is not None:
            has_extra_dhcp_opts = True

        if kwargs.get('portbinding'):
            has_portbinding = True
            api.extensions[constants.PORTBINDING_EXT] = 1
            self.mox.StubOutWithMock(api, '_refresh_neutron_extensions_cache')
            neutronv2.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
                self.moxed_client)
            neutronv2.get_client(
                mox.IgnoreArg(), admin=True).MultipleTimes().AndReturn(
                self.moxed_client)
            api._refresh_neutron_extensions_cache(mox.IgnoreArg())
        else:
            self.mox.StubOutWithMock(api, '_populate_neutron_extension_values')
        self.mox.StubOutWithMock(api, '_has_port_binding_extension')
        # Net idx is 1-based for compatibility with existing unit tests
        nets = self.nets[net_idx - 1]
        ports = {}
        fixed_ips = {}
        macs = kwargs.get('macs')
        if macs:
            macs = set(macs)
        req_net_ids = []
        if 'requested_networks' in kwargs:
            for id, fixed_ip, port_id in kwargs['requested_networks']:
                if port_id:
                    self.moxed_client.show_port(port_id).AndReturn(
                        {'port': {'id': 'my_portid1',
                                  'network_id': 'my_netid1',
                                  'mac_address': 'my_mac1',
                                  'device_id': kwargs.get('_device') and
                                               self.instance2['uuid'] or ''}})

                    ports['my_netid1'] = self.port_data1[0]
                    id = 'my_netid1'
                    if macs is not None:
                        macs.discard('my_mac1')
                else:
                    fixed_ips[id] = fixed_ip
                req_net_ids.append(id)
            expected_network_order = req_net_ids
        else:
            expected_network_order = [n['id'] for n in nets]
        if kwargs.get('_break') == 'pre_list_networks':
            self.mox.ReplayAll()
            return api
        search_ids = [net['id'] for net in nets if net['id'] in req_net_ids]

        if search_ids:
            mox_list_params = {'id': mox.SameElementsAs(search_ids)}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': nets})
        else:
            mox_list_params = {'tenant_id': self.instance['project_id'],
                               'shared': False}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': nets})
            mox_list_params = {'shared': True}
            self.moxed_client.list_networks(
                **mox_list_params).AndReturn({'networks': []})

        ports_in_requested_net_order = []
        for net_id in expected_network_order:
            port_req_body = {
                'port': {
                    'device_id': self.instance['uuid'],
                    'device_owner': 'compute:nova',
                },
            }
            if has_portbinding:
                port_req_body['port']['binding:host_id'] = (
                    self.instance.get('host'))
            port = ports.get(net_id, None)
            if not has_portbinding:
                api._populate_neutron_extension_values(mox.IgnoreArg(),
                    self.instance, mox.IgnoreArg()).AndReturn(None)
            else:
                # since _populate_neutron_extension_values() will call
                # _has_port_binding_extension()
                api._has_port_binding_extension(mox.IgnoreArg()).\
                                                     AndReturn(has_portbinding)
            api._has_port_binding_extension(mox.IgnoreArg()).\
                                                 AndReturn(has_portbinding)
            if port:
                port_id = port['id']
                self.moxed_client.update_port(port_id,
                                              MyComparator(port_req_body)
                                              ).AndReturn(
                                                  {'port': port})
                ports_in_requested_net_order.append(port_id)
            else:
                fixed_ip = fixed_ips.get(net_id)
                if fixed_ip:
                    port_req_body['port']['fixed_ips'] = [{'ip_address':
                                                           fixed_ip}]
                port_req_body['port']['network_id'] = net_id
                port_req_body['port']['admin_state_up'] = True
                port_req_body['port']['tenant_id'] = \
                    self.instance['project_id']
                if macs:
                    port_req_body['port']['mac_address'] = macs.pop()
                if has_portbinding:
                    port_req_body['port']['binding:host_id'] = (
                        self.instance.get('host'))
                res_port = {'port': {'id': 'fake'}}
                if has_extra_dhcp_opts:
                    port_req_body['port']['extra_dhcp_opts'] = dhcp_options
                if kwargs.get('_break') == 'mac' + net_id:
                    self.mox.ReplayAll()
                    return api
                self.moxed_client.create_port(
                    MyComparator(port_req_body)).AndReturn(res_port)
                ports_in_requested_net_order.append(res_port['port']['id'])

        api.get_instance_nw_info(mox.IgnoreArg(),
                                 self.instance,
                                 networks=nets,
                                 port_ids=ports_in_requested_net_order
                                ).AndReturn(self._returned_nw_info)
        self.mox.ReplayAll()
        return api

    def _verify_nw_info(self, nw_inf, index=0):
        id_suffix = index + 1
        self.assertEqual('10.0.%s.2' % id_suffix,
                         nw_inf.fixed_ips()[index]['address'])
        self.assertEqual('172.0.%s.2' % id_suffix,
            nw_inf.fixed_ips()[index].floating_ip_addresses()[0])
        self.assertEqual('my_netname%s' % id_suffix,
                         nw_inf[index]['network']['label'])
        self.assertEqual('my_portid%s' % id_suffix, nw_inf[index]['id'])
        self.assertEqual('my_mac%s' % id_suffix, nw_inf[index]['address'])
        self.assertEqual('10.0.%s.0/24' % id_suffix,
            nw_inf[index]['network']['subnets'][0]['cidr'])
        self.assertTrue(model.IP(address='8.8.%s.1' % id_suffix,
                                 version=4, type='dns') in
                        nw_inf[index]['network']['subnets'][0]['dns'])

    def _get_instance_nw_info(self, number):
        api = neutronapi.API()
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(mox.IgnoreArg(),
                                          self.instance['uuid'],
                                          mox.IgnoreArg())
        port_data = number == 1 and self.port_data1 or self.port_data2
        nets = number == 1 and self.nets1 or self.nets2
        net_info_cache = []
        for port in port_data:
            net_info_cache.append({"network": {"id": port['network_id']},
                                   "id": port['id']})

        instance = copy.copy(self.instance)
        # This line here does not wrap net_info_cache in jsonutils.dumps()
        # intentionally to test the other code path when it's not unicode.
        instance['info_cache'] = {'network_info': net_info_cache}

        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': port_data})
        net_ids = [port['network_id'] for port in port_data]
        nets = number == 1 and self.nets1 or self.nets2
        self.moxed_client.list_networks(
            id=net_ids).AndReturn({'networks': nets})
        for i in xrange(1, number + 1):
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
        self.mox.ReplayAll()
        nw_inf = api.get_instance_nw_info(self.context, instance)
        for i in xrange(0, number):
            self._verify_nw_info(nw_inf, i)

    def _allocate_for_instance(self, net_idx=1, **kwargs):
        api = self._stub_allocate_for_instance(net_idx, **kwargs)
        return api.allocate_for_instance(self.context, self.instance, **kwargs)


class TestNeutronv2(TestNeutronv2Base):

    def setUp(self):
        super(TestNeutronv2, self).setUp()
        neutronv2.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)

    def test_get_instance_nw_info_1(self):
        # Test to get one port in one network and subnet.
        neutronv2.get_client(mox.IgnoreArg(),
                             admin=True).MultipleTimes().AndReturn(
            self.moxed_client)
        self._get_instance_nw_info(1)

    def test_get_instance_nw_info_2(self):
        # Test to get one port in each of two networks and subnets.
        neutronv2.get_client(mox.IgnoreArg(),
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

    def test_get_instance_nw_info_ignores_neturon_ports(self):
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
            self.instance['uuid'], mox.IgnoreArg())
        neutronv2.get_client(mox.IgnoreArg(),
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
            self.moxed_client.list_networks(
                id=net_ids).AndReturn({'networks': nets})
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
        self.mox.ReplayAll()

        self.instance['info_cache'] = network_cache
        instance = copy.copy(self.instance)
        instance['info_cache'] = network_cache['info_cache']
        nw_infs = api.get_instance_nw_info(self.context,
                                           instance,
                                           networks=original_networks,
                                           port_ids=original_port_ids)

        self.assertEqual(index, len(nw_infs))
        # ensure that nic ordering is preserved
        for iface_index in range(index):
            self.assertEqual(nw_infs[iface_index]['id'],
                             port_ids[iface_index])

    def test_get_instance_nw_info_without_subnet(self):
        # Test get instance_nw_info for a port without subnet.
        api = neutronapi.API()
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(
            mox.IgnoreArg(),
            self.instance['uuid'], mox.IgnoreArg())
        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': self.port_data3})
        self.moxed_client.list_networks(
            id=[self.port_data1[0]['network_id']]).AndReturn(
                {'networks': self.nets1})
        neutronv2.get_client(mox.IgnoreArg(),
                             admin=True).MultipleTimes().AndReturn(
            self.moxed_client)

        self.mox.StubOutWithMock(conductor_api.API,
                                 'instance_get_by_uuid')

        net_info_cache = []
        for port in self.port_data3:
            net_info_cache.append({"network": {"id": port['network_id']},
                                   "id": port['id']})
        instance = copy.copy(self.instance)
        instance['info_cache'] = {'network_info':
                                  six.text_type(
                                    jsonutils.dumps(net_info_cache))}

        self.mox.ReplayAll()

        nw_inf = api.get_instance_nw_info(self.context,
                                          instance)

        id_suffix = 3
        self.assertEqual(0, len(nw_inf.fixed_ips()))
        self.assertEqual('my_netname1', nw_inf[0]['network']['label'])
        self.assertEqual('my_portid%s' % id_suffix, nw_inf[0]['id'])
        self.assertEqual('my_mac%s' % id_suffix, nw_inf[0]['address'])
        self.assertEqual(0, len(nw_inf[0]['network']['subnets']))

    def test_refresh_neutron_extensions_cache(self):
        api = neutronapi.API()

        # Note: Don't want the default get_client from setUp()
        self.mox.ResetAll()
        neutronv2.get_client(mox.IgnoreArg()).AndReturn(
            self.moxed_client)
        self.moxed_client.list_extensions().AndReturn(
            {'extensions': [{'name': 'nvp-qos'}]})
        self.mox.ReplayAll()
        api._refresh_neutron_extensions_cache(mox.IgnoreArg())
        self.assertEqual({'nvp-qos': {'name': 'nvp-qos'}}, api.extensions)

    def test_populate_neutron_extension_values_rxtx_factor(self):
        api = neutronapi.API()

        # Note: Don't want the default get_client from setUp()
        self.mox.ResetAll()
        neutronv2.get_client(mox.IgnoreArg()).AndReturn(
            self.moxed_client)
        self.moxed_client.list_extensions().AndReturn(
            {'extensions': [{'name': 'nvp-qos'}]})
        self.mox.ReplayAll()
        flavor = flavors.get_default_flavor()
        flavor['rxtx_factor'] = 1
        sys_meta = utils.dict_to_metadata(
            flavors.save_flavor_info({}, flavor))
        instance = {'system_metadata': sys_meta}
        port_req_body = {'port': {}}
        api._populate_neutron_extension_values(self.context, instance,
                                               port_req_body)
        self.assertEqual(port_req_body['port']['rxtx_factor'], 1)

    def test_allocate_for_instance_1(self):
        # Allocate one port in one network env.
        self._allocate_for_instance(1)

    def test_allocate_for_instance_2(self):
        # Allocate one port in two networks env.
        self._allocate_for_instance(2)

    def test_allocate_for_instance_accepts_macs_kwargs_None(self):
        # The macs kwarg should be accepted as None.
        self._allocate_for_instance(1, macs=None)

    def test_allocate_for_instance_accepts_macs_kwargs_set(self):
        # The macs kwarg should be accepted, as a set, the
        # _allocate_for_instance helper checks that the mac is used to create a
        # port.
        self._allocate_for_instance(1, macs=set(['ab:cd:ef:01:23:45']))

    def test_allocate_for_instance_accepts_only_portid(self):
        # Make sure allocate_for_instance works when only a portid is provided
        self._returned_nw_info = self.port_data1
        result = self._allocate_for_instance(
            requested_networks=[(None, None, 'my_portid1')])
        self.assertEqual(self.port_data1, result)

    def test_allocate_for_instance_not_enough_macs_via_ports(self):
        # using a hypervisor MAC via a pre-created port will stop it being
        # used to dynamically create a port on a network. We put the network
        # first in requested_networks so that if the code were to not pre-check
        # requested ports, it would incorrectly assign the mac and not fail.
        requested_networks = [
            (self.nets2[1]['id'], None, None),
            (None, None, 'my_portid1')]
        api = self._stub_allocate_for_instance(
            net_idx=2, requested_networks=requested_networks,
            macs=set(['my_mac1']),
            _break='mac' + self.nets2[1]['id'])
        self.assertRaises(exception.PortNotFree,
                          api.allocate_for_instance, self.context,
                          self.instance, requested_networks=requested_networks,
                          macs=set(['my_mac1']))

    def test_allocate_for_instance_not_enough_macs(self):
        # If not enough MAC addresses are available to allocate to networks, an
        # error should be raised.
        # We could pass in macs=set(), but that wouldn't tell us that
        # allocate_for_instance tracks used macs properly, so we pass in one
        # mac, and ask for two networks.
        requested_networks = [
            (self.nets2[1]['id'], None, None),
            (self.nets2[0]['id'], None, None)]
        api = self._stub_allocate_for_instance(
            net_idx=2, requested_networks=requested_networks,
            macs=set(['my_mac2']),
            _break='mac' + self.nets2[0]['id'])
        self.assertRaises(exception.PortNotFree,
                          api.allocate_for_instance, self.context,
                          self.instance, requested_networks=requested_networks,
                          macs=set(['my_mac2']))

    def test_allocate_for_instance_two_macs_two_networks(self):
        # If two MACs are available and two networks requested, two new ports
        # get made and no exceptions raised.
        requested_networks = [
            (self.nets2[1]['id'], None, None),
            (self.nets2[0]['id'], None, None)]
        self._allocate_for_instance(
            net_idx=2, requested_networks=requested_networks,
            macs=set(['my_mac2', 'my_mac1']))

    def test_allocate_for_instance_mac_conflicting_requested_port(self):
        # specify only first and last network
        requested_networks = [(None, None, 'my_portid1')]
        api = self._stub_allocate_for_instance(
            net_idx=1, requested_networks=requested_networks,
            macs=set(['unknown:mac']),
            _break='pre_list_networks')
        self.assertRaises(exception.PortNotUsable,
                          api.allocate_for_instance, self.context,
                          self.instance, requested_networks=requested_networks,
                          macs=set(['unknown:mac']))

    def test_allocate_for_instance_with_requested_networks(self):
        # specify only first and last network
        requested_networks = [
            (net['id'], None, None)
            for net in (self.nets3[1], self.nets3[0], self.nets3[2])]
        self._allocate_for_instance(net_idx=3,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_with_requested_networks_with_fixedip(self):
        # specify only first and last network
        requested_networks = [(self.nets1[0]['id'], '10.0.1.0/24', None)]
        self._allocate_for_instance(net_idx=1,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_with_requested_networks_with_port(self):
        requested_networks = [(None, None, 'myportid1')]
        self._allocate_for_instance(net_idx=1,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_no_networks(self):
        """verify the exception thrown when there are no networks defined."""
        api = neutronapi.API()
        self.moxed_client.list_networks(
            tenant_id=self.instance['project_id'],
            shared=False).AndReturn(
                {'networks': model.NetworkInfo([])})
        self.moxed_client.list_networks(shared=True).AndReturn(
            {'networks': model.NetworkInfo([])})
        self.mox.ReplayAll()
        nwinfo = api.allocate_for_instance(self.context, self.instance)
        self.assertEqual(len(nwinfo), 0)

    def test_allocate_for_instance_ex1(self):
        """verify we will delete created ports
        if we fail to allocate all net resources.

        Mox to raise exception when creating a second port.
        In this case, the code should delete the first created port.
        """
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, '_populate_neutron_extension_values')
        self.mox.StubOutWithMock(api, '_has_port_binding_extension')
        api._has_port_binding_extension(mox.IgnoreArg()).MultipleTimes().\
                                                         AndReturn(False)
        self.moxed_client.list_networks(
            tenant_id=self.instance['project_id'],
            shared=False).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_networks(shared=True).AndReturn(
                {'networks': []})
        index = 0
        for network in self.nets2:
            binding_port_req_body = {
                'port': {
                    'device_id': self.instance['uuid'],
                    'device_owner': 'compute:nova',
                },
            }
            port_req_body = {
                'port': {
                    'network_id': network['id'],
                    'admin_state_up': True,
                    'tenant_id': self.instance['project_id'],
                },
            }
            port_req_body['port'].update(binding_port_req_body['port'])
            port = {'id': 'portid_' + network['id']}

            api._populate_neutron_extension_values(self.context,
                self.instance, binding_port_req_body).AndReturn(None)
            if index == 0:
                self.moxed_client.create_port(
                    MyComparator(port_req_body)).AndReturn({'port': port})
            else:
                NeutronOverQuota = exceptions.NeutronClientException(
                            message="Quota exceeded for resources: ['port']",
                            status_code=409)
                self.moxed_client.create_port(
                    MyComparator(port_req_body)).AndRaise(NeutronOverQuota)
            index += 1
        self.moxed_client.delete_port('portid_' + self.nets2[0]['id'])
        self.mox.ReplayAll()
        self.assertRaises(exception.PortLimitExceeded,
                          api.allocate_for_instance,
                          self.context, self.instance)

    def test_allocate_for_instance_ex2(self):
        """verify we have no port to delete
        if we fail to allocate the first net resource.

        Mox to raise exception when creating the first port.
        In this case, the code should not delete any ports.
        """
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, '_populate_neutron_extension_values')
        self.mox.StubOutWithMock(api, '_has_port_binding_extension')
        api._has_port_binding_extension(mox.IgnoreArg()).MultipleTimes().\
                                                         AndReturn(False)
        self.moxed_client.list_networks(
            tenant_id=self.instance['project_id'],
            shared=False).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_networks(shared=True).AndReturn(
                {'networks': []})
        binding_port_req_body = {
            'port': {
                'device_id': self.instance['uuid'],
                'device_owner': 'compute:nova',
            },
        }
        port_req_body = {
            'port': {
                'network_id': self.nets2[0]['id'],
                'admin_state_up': True,
                'device_id': self.instance['uuid'],
                'tenant_id': self.instance['project_id'],
            },
        }
        api._populate_neutron_extension_values(self.context,
            self.instance, binding_port_req_body).AndReturn(None)
        self.moxed_client.create_port(
            MyComparator(port_req_body)).AndRaise(
                Exception("fail to create port"))
        self.mox.ReplayAll()
        self.assertRaises(NEUTRON_CLIENT_EXCEPTION, api.allocate_for_instance,
                          self.context, self.instance)

    def test_allocate_for_instance_no_port_or_network(self):
        class BailOutEarly(Exception):
            pass
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, '_get_available_networks')
        # Make sure we get an empty list and then bail out of the rest
        # of the function
        api._get_available_networks(self.context, self.instance['project_id'],
                                    []).AndRaise(BailOutEarly)
        self.mox.ReplayAll()
        self.assertRaises(BailOutEarly,
                          api.allocate_for_instance,
                              self.context, self.instance,
                              requested_networks=[(None, None, None)])

    def test_allocate_for_instance_second_time(self):
        # Make sure that allocate_for_instance only returns ports that it
        # allocated during _that_ run.
        new_port = {'id': 'fake'}
        self._returned_nw_info = self.port_data1 + [new_port]
        nw_info = self._allocate_for_instance()
        self.assertEqual(nw_info, [new_port])

    def test_allocate_for_instance_port_in_use(self):
        # If a port is already in use, an exception should be raised.
        requested_networks = [(None, None, 'my_portid1')]
        api = self._stub_allocate_for_instance(
            requested_networks=requested_networks,
            _break='pre_list_networks',
            _device=True)
        self.assertRaises(exception.PortInUse,
                          api.allocate_for_instance, self.context,
                          self.instance, requested_networks=requested_networks)

    def _deallocate_for_instance(self, number, requested_networks=None):
        api = neutronapi.API()
        port_data = number == 1 and self.port_data1 or self.port_data2
        ret_data = copy.deepcopy(port_data)
        if requested_networks:
            for net, fip, port in requested_networks:
                ret_data.append({'network_id': net,
                                 'device_id': self.instance['uuid'],
                                 'device_owner': 'compute:nova',
                                 'id': port,
                                 'status': 'DOWN',
                                 'admin_state_up': True,
                                 'fixed_ips': [],
                                 'mac_address': 'fake_mac', })
        self.moxed_client.list_ports(
            device_id=self.instance['uuid']).AndReturn(
                {'ports': ret_data})
        if requested_networks:
            for net, fip, port in requested_networks:
                self.moxed_client.update_port(port)
        for port in reversed(port_data):
            self.moxed_client.delete_port(port['id'])

        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(self.context,
                                          self.instance['uuid'],
                                          {'network_info': '[]'})
        self.mox.ReplayAll()

        api = neutronapi.API()
        api.deallocate_for_instance(self.context, self.instance,
                                    requested_networks=requested_networks)

    def test_deallocate_for_instance_1_with_requested(self):
        requested = [('fake-net', 'fake-fip', 'fake-port')]
        # Test to deallocate in one port env.
        self._deallocate_for_instance(1, requested_networks=requested)

    def test_deallocate_for_instance_2_with_requested(self):
        requested = [('fake-net', 'fake-fip', 'fake-port')]
        # Test to deallocate in one port env.
        self._deallocate_for_instance(2, requested_networks=requested)

    def test_deallocate_for_instance_1(self):
        # Test to deallocate in one port env.
        self._deallocate_for_instance(1)

    def test_deallocate_for_instance_2(self):
        # Test to deallocate in two ports env.
        self._deallocate_for_instance(2)

    def test_deallocate_for_instance_port_not_found(self):
        port_data = self.port_data1
        self.moxed_client.list_ports(
            device_id=self.instance['uuid']).AndReturn(
                {'ports': port_data})

        NeutronNotFound = neutronv2.exceptions.NeutronClientException(
                                                            status_code=404)
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
        instance = copy.copy(self.instance)
        instance['info_cache'] = {'network_info':
                                  six.text_type(
                                    jsonutils.dumps(net_info_cache))}
        api = neutronapi.API()
        neutronv2.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': port_data[1:]})
        neutronv2.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)
        net_ids = [port['network_id'] for port in port_data]
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

        self.mox.ReplayAll()

        nwinfo = api.deallocate_port_for_instance(self.context, instance,
                                                  port_data[0]['id'])
        self.assertEqual(len(nwinfo), len(port_data[1:]))
        if len(port_data) > 1:
            self.assertEqual(nwinfo[0]['network']['id'], 'my_netid2')

    def test_deallocate_port_for_instance_1(self):
        # Test to deallocate the first and only port
        self._test_deallocate_port_for_instance(1)

    def test_deallocate_port_for_instance_2(self):
        # Test to deallocate the first port of two
        self._test_deallocate_port_for_instance(2)

    def test_list_ports(self):
        search_opts = {'parm': 'value'}
        self.moxed_client.list_ports(**search_opts)
        self.mox.ReplayAll()
        neutronapi.API().list_ports(self.context, **search_opts)

    def test_show_port(self):
        self.moxed_client.show_port('foo')
        self.mox.ReplayAll()
        neutronapi.API().show_port(self.context, 'foo')

    def test_validate_networks(self):
        requested_networks = [('my_netid1', 'test', None),
                              ('my_netid2', 'test2', None)]
        ids = ['my_netid1', 'my_netid2']
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_ports(tenant_id='my_tenantid').AndReturn(
                    {'ports': []})
        self.moxed_client.show_quota(
            tenant_id='my_tenantid').AndReturn(
                    {'quota': {'port': 50}})
        self.mox.ReplayAll()
        api = neutronapi.API()
        api.validate_networks(self.context, requested_networks, 1)

    def test_validate_networks_without_port_quota_on_network_side(self):
        requested_networks = [('my_netid1', None, None),
                              ('my_netid2', None, None)]
        ids = ['my_netid1', 'my_netid2']
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_ports(tenant_id='my_tenantid').AndReturn(
                    {'ports': []})
        self.moxed_client.show_quota(
            tenant_id='my_tenantid').AndReturn(
                    {'quota': {}})
        self.mox.ReplayAll()
        api = neutronapi.API()
        api.validate_networks(self.context, requested_networks, 1)

    def test_validate_networks_ex_1(self):
        requested_networks = [('my_netid1', 'test', None)]
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(['my_netid1'])).AndReturn(
                {'networks': self.nets1})
        self.moxed_client.list_ports(tenant_id='my_tenantid').AndReturn(
                    {'ports': []})
        self.moxed_client.show_quota(
            tenant_id='my_tenantid').AndReturn(
                    {'quota': {'port': 50}})
        self.mox.ReplayAll()
        api = neutronapi.API()
        try:
            api.validate_networks(self.context, requested_networks, 1)
        except exception.NetworkNotFound as ex:
            self.assertIn("my_netid2", str(ex))

    def test_validate_networks_ex_2(self):
        requested_networks = [('my_netid1', 'test', None),
                              ('my_netid2', 'test2', None),
                              ('my_netid3', 'test3', None)]
        ids = ['my_netid1', 'my_netid2', 'my_netid3']
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets1})
        self.mox.ReplayAll()
        api = neutronapi.API()
        try:
            api.validate_networks(self.context, requested_networks, 1)
        except exception.NetworkNotFound as ex:
            self.assertIn("my_netid2, my_netid3", str(ex))

    def test_validate_networks_duplicate(self):
        """Verify that the correct exception is thrown when duplicate
           network ids are passed to validate_networks.
        """
        requested_networks = [('my_netid1', None, None),
                              ('my_netid1', None, None)]
        self.mox.ReplayAll()
        # Expected call from setUp.
        neutronv2.get_client(None)
        api = neutronapi.API()
        self.assertRaises(exception.NetworkDuplicated,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_not_specified(self):
        requested_networks = []
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

        requested_networks = [('my_netid1', None, '3123-ad34-bc43-32332ca33e')]

        NeutronNotFound = neutronv2.exceptions.NeutronClientException(
                                                            status_code=404)
        self.moxed_client.show_port(requested_networks[0][2]).AndRaise(
                                                        NeutronNotFound)
        self.mox.ReplayAll()
        # Expected call from setUp.
        neutronv2.get_client(None)
        api = neutronapi.API()
        self.assertRaises(exception.PortNotFound,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_port_show_rasies_non404(self):
        # Verify that the correct exception is thrown when a non existent
        # port is passed to validate_networks.

        requested_networks = [('my_netid1', None, '3123-ad34-bc43-32332ca33e')]

        NeutronNotFound = neutronv2.exceptions.NeutronClientException(
                                                            status_code=0)
        self.moxed_client.show_port(requested_networks[0][2]).AndRaise(
                                                        NeutronNotFound)
        self.mox.ReplayAll()
        # Expected call from setUp.
        neutronv2.get_client(None)
        api = neutronapi.API()
        self.assertRaises(neutronv2.exceptions.NeutronClientException,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_port_in_use(self):
        requested_networks = [(None, None, self.port_data3[0]['id'])]
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

        requested_networks = [(None, None, port_a['id'])]
        self.moxed_client.show_port(port_a['id']).AndReturn({'port': port_a})

        self.mox.ReplayAll()

        api = neutronapi.API()
        self.assertRaises(exception.PortRequiresFixedIP,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_no_subnet_id(self):
        requested_networks = [('his_netid4', None, None)]
        ids = ['his_netid4']
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets4})
        self.mox.ReplayAll()
        api = neutronapi.API()
        self.assertRaises(exception.NetworkRequiresSubnet,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_ports_in_same_network(self):
        port_a = self.port_data3[0]
        port_a['fixed_ips'] = {'ip_address': '10.0.0.2',
                               'subnet_id': 'subnet_id'}
        port_b = self.port_data1[0]
        self.assertEqual(port_a['network_id'], port_b['network_id'])
        for port in [port_a, port_b]:
            port['device_id'] = None
            port['device_owner'] = None

        requested_networks = [(None, None, port_a['id']),
                              (None, None, port_b['id'])]
        self.moxed_client.show_port(port_a['id']).AndReturn({'port': port_a})
        self.moxed_client.show_port(port_b['id']).AndReturn({'port': port_b})

        self.mox.ReplayAll()

        api = neutronapi.API()
        self.assertRaises(exception.NetworkDuplicated,
                          api.validate_networks,
                          self.context, requested_networks, 1)

    def test_validate_networks_ports_not_in_same_network(self):
        port_a = self.port_data3[0]
        port_a['fixed_ips'] = {'ip_address': '10.0.0.2',
                               'subnet_id': 'subnet_id'}
        port_b = self.port_data2[1]
        self.assertNotEqual(port_a['network_id'], port_b['network_id'])
        for port in [port_a, port_b]:
            port['device_id'] = None
            port['device_owner'] = None

        requested_networks = [(None, None, port_a['id']),
                              (None, None, port_b['id'])]
        self.moxed_client.show_port(port_a['id']).AndReturn({'port': port_a})
        self.moxed_client.show_port(port_b['id']).AndReturn({'port': port_b})

        search_opts = {'id': [port_a['network_id'], port_b['network_id']]}
        self.moxed_client.list_networks(
            **search_opts).AndReturn({'networks': self.nets2})
        self.moxed_client.list_ports(tenant_id='my_tenantid').AndReturn(
                    {'ports': []})
        self.moxed_client.show_quota(
            tenant_id='my_tenantid').AndReturn(
                    {'quota': {'port': 50}})

        self.mox.ReplayAll()

        api = neutronapi.API()
        api.validate_networks(self.context, requested_networks, 1)

    def test_validate_networks_no_quota(self):
        # Test validation for a request for one instance needing
        # two ports, where the quota is 2 and 2 ports are in use
        #  => instances which can be created = 0
        requested_networks = [('my_netid1', 'test', None),
                              ('my_netid2', 'test2', None)]
        ids = ['my_netid1', 'my_netid2']
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_ports(tenant_id='my_tenantid').AndReturn(
                    {'ports': self.port_data2})
        self.moxed_client.show_quota(
            tenant_id='my_tenantid').AndReturn(
                    {'quota': {'port': 2}})
        self.mox.ReplayAll()
        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 1)
        self.assertEqual(max_count, 0)

    def test_validate_networks_some_quota(self):
        # Test validation for a request for two instance needing
        # two ports each, where the quota is 5 and 2 ports are in use
        #  => instances which can be created = 1
        requested_networks = [('my_netid1', 'test', None),
                              ('my_netid2', 'test2', None)]
        ids = ['my_netid1', 'my_netid2']
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_ports(tenant_id='my_tenantid').AndReturn(
                    {'ports': self.port_data2})
        self.moxed_client.show_quota(
            tenant_id='my_tenantid').AndReturn(
                    {'quota': {'port': 5}})
        self.mox.ReplayAll()
        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 2)
        self.assertEqual(max_count, 1)

    def test_validate_networks_unlimited_quota(self):
        # Test validation for a request for two instance needing
        # two ports each, where the quota is -1 (unlimited)
        #  => instances which can be created = 1
        requested_networks = [('my_netid1', 'test', None),
                              ('my_netid2', 'test2', None)]
        ids = ['my_netid1', 'my_netid2']
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(ids)).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_ports(tenant_id='my_tenantid').AndReturn(
                    {'ports': self.port_data2})
        self.moxed_client.show_quota(
            tenant_id='my_tenantid').AndReturn(
                    {'quota': {'port': -1}})
        self.mox.ReplayAll()
        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 2)
        self.assertEqual(max_count, 2)

    def test_validate_networks_no_quota_but_ports_supplied(self):
        # Test validation for a request for one instance needing
        # two ports, where the quota is 2 and 2 ports are in use
        # but the request includes a port to be used
        #  => instances which can be created = 1
        port_a = self.port_data3[0]
        port_a['fixed_ips'] = {'ip_address': '10.0.0.2',
                               'subnet_id': 'subnet_id'}
        port_b = self.port_data2[1]
        self.assertNotEqual(port_a['network_id'], port_b['network_id'])
        for port in [port_a, port_b]:
            port['device_id'] = None
            port['device_owner'] = None

        requested_networks = [(None, None, port_a['id']),
                              (None, None, port_b['id'])]
        self.moxed_client.show_port(port_a['id']).AndReturn({'port': port_a})
        self.moxed_client.show_port(port_b['id']).AndReturn({'port': port_b})

        search_opts = {'id': [port_a['network_id'], port_b['network_id']]}
        self.moxed_client.list_networks(
            **search_opts).AndReturn({'networks': self.nets2})
        self.moxed_client.list_ports(tenant_id='my_tenantid').AndReturn(
                    {'ports': self.port_data2})
        self.moxed_client.show_quota(
            tenant_id='my_tenantid').AndReturn(
                    {'quota': {'port': 2}})

        self.mox.ReplayAll()

        api = neutronapi.API()
        max_count = api.validate_networks(self.context,
                                          requested_networks, 1)
        self.assertEqual(max_count, 1)

    def _mock_list_ports(self, port_data=None):
        if port_data is None:
            port_data = self.port_data2
        address = self.port_address
        self.moxed_client.list_ports(
            fixed_ips=MyComparator('ip_address=%s' % address)).AndReturn(
                {'ports': port_data})
        self.mox.ReplayAll()
        return address

    def test_get_instance_uuids_by_ip_filter(self):
        self._mock_list_ports()
        filters = {'ip': '^10\\.0\\.1\\.2$'}
        api = neutronapi.API()
        result = api.get_instance_uuids_by_ip_filter(self.context, filters)
        self.assertEqual(self.instance2['uuid'], result[0]['instance_uuid'])
        self.assertEqual(self.instance['uuid'], result[1]['instance_uuid'])

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
        self.assertEqual(rets, nets)

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

    def test_get_available_networks_with_externalnet_fails(self):
        req_ids = [net['id'] for net in self.nets5]
        self.assertRaises(
            exception.ExternalNetworkAttachForbidden,
            self._get_available_networks,
            self.nets5, pub_nets=[], req_ids=req_ids)

    def test_get_available_networks_with_externalnet_admin_ctx(self):
        admin_ctx = context.RequestContext('userid', 'my_tenantid',
                                           is_admin=True)
        req_ids = [net['id'] for net in self.nets5]
        self._get_available_networks(self.nets5, pub_nets=[],
                                     req_ids=req_ids, context=admin_ctx)

    def test_get_floating_ip_pools(self):
        api = neutronapi.API()
        search_opts = {'router:external': True}
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool, self.fip_pool_nova]})
        self.mox.ReplayAll()
        pools = api.get_floating_ip_pools(self.context)
        expected = [{'name': self.fip_pool['name']},
                    {'name': self.fip_pool_nova['name']}]
        self.assertEqual(expected, pools)

    def _get_expected_fip_model(self, fip_data, idx=0):
        expected = {'id': fip_data['id'],
                    'address': fip_data['floating_ip_address'],
                    'pool': self.fip_pool['name'],
                    'project_id': fip_data['tenant_id'],
                    'fixed_ip_id': fip_data['port_id'],
                    'fixed_ip':
                        {'address': fip_data['fixed_ip_address']},
                    'instance': ({'uuid': self.port_data2[idx]['device_id']}
                                 if fip_data['port_id']
                                 else None)}
        return expected

    def _test_get_floating_ip(self, fip_data, idx=0, by_address=False):
        api = neutronapi.API()
        fip_id = fip_data['id']
        net_id = fip_data['floating_network_id']
        address = fip_data['floating_ip_address']
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
        self.assertEqual(expected, fip)

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
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': []})
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          api.get_floating_ip_by_address,
                          self.context, address)

    def test_get_floating_ip_by_id_not_found(self):
        api = neutronapi.API()
        NeutronNotFound = neutronv2.exceptions.NeutronClientException(
            status_code=404)
        floating_ip_id = self.fip_unassociated['id']
        self.moxed_client.show_floatingip(floating_ip_id).\
            AndRaise(NeutronNotFound)
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpNotFound,
                          api.get_floating_ip,
                          self.context, floating_ip_id)

    def test_get_floating_ip_raises_non404(self):
        api = neutronapi.API()
        NeutronNotFound = neutronv2.exceptions.NeutronClientException(
            status_code=0)
        floating_ip_id = self.fip_unassociated['id']
        self.moxed_client.show_floatingip(floating_ip_id).\
            AndRaise(NeutronNotFound)
        self.mox.ReplayAll()
        self.assertRaises(neutronv2.exceptions.NeutronClientException,
                          api.get_floating_ip,
                          self.context, floating_ip_id)

    def test_get_floating_ip_by_address_multiple_found(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated] * 2})
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpMultipleFoundForAddress,
                          api.get_floating_ip_by_address,
                          self.context, address)

    def test_get_floating_ips_by_project(self):
        api = neutronapi.API()
        project_id = self.context.project_id
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
        self.assertEqual(expected, fips)

    def _test_get_instance_id_by_floating_address(self, fip_data,
                                                  associated=False):
        api = neutronapi.API()
        address = fip_data['floating_ip_address']
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
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool]})
        self.moxed_client.create_floatingip(
            {'floatingip': {'floating_network_id': pool_id}}).\
            AndReturn({'floatingip': self.fip_unassociated})
        self.mox.ReplayAll()
        fip = api.allocate_floating_ip(self.context, 'ext_net')
        self.assertEqual(fip, self.fip_unassociated['floating_ip_address'])

    def test_allocate_floating_ip_addr_gen_fail(self):
        api = neutronapi.API()
        pool_name = self.fip_pool['name']
        pool_id = self.fip_pool['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
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
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool]})
        self.moxed_client.create_floatingip(
            {'floatingip': {'floating_network_id': pool_id}}).\
            AndReturn({'floatingip': self.fip_unassociated})
        self.mox.ReplayAll()
        fip = api.allocate_floating_ip(self.context, pool_id)
        self.assertEqual(fip, self.fip_unassociated['floating_ip_address'])

    def test_allocate_floating_ip_with_default_pool(self):
        api = neutronapi.API()
        pool_name = self.fip_pool_nova['name']
        pool_id = self.fip_pool_nova['id']
        search_opts = {'router:external': True,
                       'fields': 'id',
                       'name': pool_name}
        self.moxed_client.list_networks(**search_opts).\
            AndReturn({'networks': [self.fip_pool_nova]})
        self.moxed_client.create_floatingip(
            {'floatingip': {'floating_network_id': pool_id}}).\
            AndReturn({'floatingip': self.fip_unassociated})
        self.mox.ReplayAll()
        fip = api.allocate_floating_ip(self.context)
        self.assertEqual(fip, self.fip_unassociated['floating_ip_address'])

    def test_release_floating_ip(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        fip_id = self.fip_unassociated['id']

        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated]})
        self.moxed_client.delete_floatingip(fip_id)
        self.mox.ReplayAll()
        api.release_floating_ip(self.context, address)

    def test_disassociate_and_release_floating_ip(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        fip_id = self.fip_unassociated['id']
        floating_ip = {'address': address}

        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated]})
        self.moxed_client.delete_floatingip(fip_id)
        self.mox.ReplayAll()
        api.disassociate_and_release_floating_ip(self.context, None,
                                               floating_ip)

    def test_release_floating_ip_associated(self):
        api = neutronapi.API()
        address = self.fip_associated['floating_ip_address']

        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_associated]})
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpAssociated,
                          api.release_floating_ip, self.context, address)

    def _setup_mock_for_refresh_cache(self, api, instances):
        nw_info = self.mox.CreateMock(model.NetworkInfo)
        self.mox.StubOutWithMock(api, '_get_instance_nw_info')
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        for instance in instances:
            nw_info.json()
            api._get_instance_nw_info(mox.IgnoreArg(), instance).\
                AndReturn(nw_info)
            api.db.instance_info_cache_update(mox.IgnoreArg(),
                                              instance['uuid'],
                                              mox.IgnoreArg())

    def test_associate_floating_ip(self):
        api = neutronapi.API()
        address = self.fip_unassociated['floating_ip_address']
        fixed_address = self.port_address2
        fip_id = self.fip_unassociated['id']

        search_opts = {'device_owner': 'compute:nova',
                       'device_id': self.instance['uuid']}
        self.moxed_client.list_ports(**search_opts).\
            AndReturn({'ports': [self.port_data2[1]]})
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated]})
        self.moxed_client.update_floatingip(
            fip_id, {'floatingip': {'port_id': self.fip_associated['port_id'],
                                    'fixed_ip_address': fixed_address}})
        self._setup_mock_for_refresh_cache(api, [self.instance])

        self.mox.ReplayAll()
        api.associate_floating_ip(self.context, self.instance,
                                  address, fixed_address)

    def test_reassociate_floating_ip(self):
        api = neutronapi.API()
        address = self.fip_associated['floating_ip_address']
        new_fixed_address = self.port_address
        fip_id = self.fip_associated['id']

        search_opts = {'device_owner': 'compute:nova',
                       'device_id': self.instance2['uuid']}
        self.moxed_client.list_ports(**search_opts).\
            AndReturn({'ports': [self.port_data2[0]]})
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_associated]})
        self.moxed_client.update_floatingip(
            fip_id, {'floatingip': {'port_id': 'my_portid1',
                                    'fixed_ip_address': new_fixed_address}})
        self.moxed_client.show_port(self.fip_associated['port_id']).\
                AndReturn({'port': self.port_data2[1]})
        self.mox.StubOutWithMock(api.db, 'instance_get_by_uuid')
        api.db.instance_get_by_uuid(mox.IgnoreArg(),
                                   self.instance['uuid']).\
             AndReturn(self.instance)
        self._setup_mock_for_refresh_cache(api, [self.instance,
                                                 self.instance2])

        self.mox.ReplayAll()
        api.associate_floating_ip(self.context, self.instance2,
                                  address, new_fixed_address)

    def test_associate_floating_ip_not_found_fixed_ip(self):
        api = neutronapi.API()
        address = self.fip_associated['floating_ip_address']
        fixed_address = self.fip_associated['fixed_ip_address']

        search_opts = {'device_owner': 'compute:nova',
                       'device_id': self.instance['uuid']}
        self.moxed_client.list_ports(**search_opts).\
            AndReturn({'ports': [self.port_data2[0]]})

        self.mox.ReplayAll()
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          api.associate_floating_ip, self.context,
                          self.instance, address, fixed_address)

    def test_disassociate_floating_ip(self):
        api = neutronapi.API()
        address = self.fip_associated['floating_ip_address']
        fip_id = self.fip_associated['id']

        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_associated]})
        self.moxed_client.update_floatingip(
            fip_id, {'floatingip': {'port_id': None}})
        self._setup_mock_for_refresh_cache(api, [self.instance])

        self.mox.ReplayAll()
        api.disassociate_floating_ip(self.context, self.instance, address)

    def test_add_fixed_ip_to_instance(self):
        api = neutronapi.API()
        self._setup_mock_for_refresh_cache(api, [self.instance])
        network_id = 'my_netid1'
        search_opts = {'network_id': network_id}
        self.moxed_client.list_subnets(
            **search_opts).AndReturn({'subnets': self.subnet_data_n})

        search_opts = {'device_id': self.instance['uuid'],
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
        self.moxed_client.update_port('my_portid1',
            MyComparator(port_req_body)).AndReturn({'port': port})

        self.mox.ReplayAll()
        api.add_fixed_ip_to_instance(self.context, self.instance, network_id)

    def test_remove_fixed_ip_from_instance(self):
        api = neutronapi.API()
        self._setup_mock_for_refresh_cache(api, [self.instance])
        address = '10.0.0.3'
        zone = 'compute:%s' % self.instance['availability_zone']
        search_opts = {'device_id': self.instance['uuid'],
                       'device_owner': zone,
                       'fixed_ips': 'ip_address=%s' % address}
        self.moxed_client.list_ports(
            **search_opts).AndReturn({'ports': self.port_data1})
        port_req_body = {
            'port': {
                'fixed_ips': [],
            },
        }
        port = self.port_data1[0]
        port['fixed_ips'] = []
        self.moxed_client.update_port('my_portid1',
            MyComparator(port_req_body)).AndReturn({'port': port})

        self.mox.ReplayAll()
        api.remove_fixed_ip_from_instance(self.context, self.instance, address)

    def test_list_floating_ips_without_l3_support(self):
        api = neutronapi.API()
        NeutronNotFound = exceptions.NeutronClientException(
            status_code=404)
        self.moxed_client.list_floatingips(
            fixed_ip_address='1.1.1.1', port_id=1).AndRaise(NeutronNotFound)
        self.mox.ReplayAll()
        neutronv2.get_client('fake')
        floatingips = api._get_floating_ips_by_fixed_and_port(
            self.moxed_client, '1.1.1.1', 1)
        self.assertEqual(floatingips, [])

    def test_nw_info_get_ips(self):
        fake_port = {
            'fixed_ips': [
                {'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            }
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, '_get_floating_ips_by_fixed_and_port')
        api._get_floating_ips_by_fixed_and_port(
            self.moxed_client, '1.1.1.1', 'port-id').AndReturn(
                [{'floating_ip_address': '10.0.0.1'}])
        self.mox.ReplayAll()
        neutronv2.get_client('fake')
        result = api._nw_info_get_ips(self.moxed_client, fake_port)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['address'], '1.1.1.1')
        self.assertEqual(result[0]['floating_ips'][0]['address'], '10.0.0.1')

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
        api._get_subnets_from_port(self.context, fake_port).AndReturn(
            [fake_subnet])
        self.mox.ReplayAll()
        neutronv2.get_client('fake')
        subnets = api._nw_info_get_subnets(self.context, fake_port, fake_ips)
        self.assertEqual(len(subnets), 1)
        self.assertEqual(len(subnets[0]['ips']), 1)
        self.assertEqual(subnets[0]['ips'][0]['address'], '1.1.1.1')

    def _test_nw_info_build_network(self, vif_type):
        fake_port = {
            'fixed_ips': [{'ip_address': '1.1.1.1'}],
            'id': 'port-id',
            'network_id': 'net-id',
            'binding:vif_type': vif_type,
            }
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [{'id': 'net-id', 'name': 'foo', 'tenant_id': 'tenant'}]
        api = neutronapi.API()
        self.mox.ReplayAll()
        neutronv2.get_client('fake')
        net, iid = api._nw_info_build_network(fake_port, fake_nets,
                                              fake_subnets)
        self.assertEqual(net['subnets'], fake_subnets)
        self.assertEqual(net['id'], 'net-id')
        self.assertEqual(net['label'], 'foo')
        self.assertEqual(net.get_meta('tenant_id'), 'tenant')
        self.assertEqual(net.get_meta('injected'), CONF.flat_injected)
        return net, iid

    def test_nw_info_build_network_ovs(self):
        net, iid = self._test_nw_info_build_network(model.VIF_TYPE_OVS)
        self.assertEqual(net['bridge'], CONF.neutron_ovs_bridge)
        self.assertNotIn('should_create_bridge', net)
        self.assertEqual(iid, 'port-id')

    def test_nw_info_build_network_bridge(self):
        net, iid = self._test_nw_info_build_network(model.VIF_TYPE_BRIDGE)
        self.assertEqual(net['bridge'], 'brqnet-id')
        self.assertTrue(net['should_create_bridge'])
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
        self.mox.ReplayAll()
        neutronv2.get_client('fake')
        net, iid = api._nw_info_build_network(fake_port, fake_nets,
                                              fake_subnets)
        self.assertEqual(fake_subnets, net['subnets'])
        self.assertEqual('net-id1', net['id'])
        self.assertEqual('net-id1', net['id'])
        self.assertEqual('tenant', net['meta']['tenant_id'])

    def test_build_network_info_model(self):
        api = neutronapi.API()
        fake_inst = {'project_id': 'fake', 'uuid': 'uuid',
                     'info_cache': {'network_info': []}}
        fake_ports = [
            # admin_state_up=True and status='ACTIVE' thus vif.active=True
            {'id': 'port1',
             'network_id': 'net-id',
             'admin_state_up': True,
             'status': 'ACTIVE',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:01',
             'binding:vif_type': model.VIF_TYPE_BRIDGE,
             },
            # admin_state_up=False and status='DOWN' thus vif.active=True
            {'id': 'port2',
             'network_id': 'net-id',
             'admin_state_up': False,
             'status': 'DOWN',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:02',
             'binding:vif_type': model.VIF_TYPE_BRIDGE,
             },
            # admin_state_up=True and status='DOWN' thus vif.active=False
             {'id': 'port0',
             'network_id': 'net-id',
             'admin_state_up': True,
             'status': 'DOWN',
             'fixed_ips': [{'ip_address': '1.1.1.1'}],
             'mac_address': 'de:ad:be:ef:00:03',
             'binding:vif_type': model.VIF_TYPE_BRIDGE,
             },
            # This does not match the networks we provide below,
            # so it should be ignored (and is here to verify that)
            {'id': 'port3',
             'network_id': 'other-net-id',
             'admin_state_up': True,
             'status': 'DOWN',
             },
            ]
        fake_subnets = [model.Subnet(cidr='1.0.0.0/8')]
        fake_nets = [
            {'id': 'net-id',
             'name': 'foo',
             'tenant_id': 'fake',
             }
            ]
        neutronv2.get_client(mox.IgnoreArg(), admin=True).MultipleTimes(
            ).AndReturn(self.moxed_client)
        self.moxed_client.list_ports(
            tenant_id='fake', device_id='uuid').AndReturn(
                {'ports': fake_ports})

        self.mox.StubOutWithMock(api, '_get_floating_ips_by_fixed_and_port')
        self.mox.StubOutWithMock(api, '_get_subnets_from_port')
        requested_ports = [fake_ports[2], fake_ports[0], fake_ports[1]]
        for requested_port in requested_ports:
            api._get_floating_ips_by_fixed_and_port(
                self.moxed_client, '1.1.1.1', requested_port['id']).AndReturn(
                    [{'floating_ip_address': '10.0.0.1'}])
        for requested_port in requested_ports:
            api._get_subnets_from_port(self.context, requested_port
                ).AndReturn(fake_subnets)

        self.mox.ReplayAll()
        neutronv2.get_client('fake')
        nw_infos = api._build_network_info_model(self.context, fake_inst,
                                                 fake_nets,
                                                 [fake_ports[2]['id'],
                                                  fake_ports[0]['id'],
                                                  fake_ports[1]['id']])
        self.assertEqual(len(nw_infos), 3)
        index = 0
        for nw_info in nw_infos:
            self.assertEqual(nw_info['address'],
                             requested_ports[index]['mac_address'])
            self.assertEqual(nw_info['devname'], 'tapport' + str(index))
            self.assertIsNone(nw_info['ovs_interfaceid'])
            self.assertEqual(nw_info['type'], model.VIF_TYPE_BRIDGE)
            self.assertEqual(nw_info['network']['bridge'], 'brqnet-id')
            index += 1

        self.assertEqual(nw_infos[0]['active'], False)
        self.assertEqual(nw_infos[1]['active'], True)
        self.assertEqual(nw_infos[2]['active'], True)

        self.assertEqual(nw_infos[0]['id'], 'port0')
        self.assertEqual(nw_infos[1]['id'], 'port1')
        self.assertEqual(nw_infos[2]['id'], 'port2')

    def test_get_all_empty_list_networks(self):
        api = neutronapi.API()
        self.moxed_client.list_networks().AndReturn({'networks': []})
        self.mox.ReplayAll()
        networks = api.get_all(self.context)
        self.assertEqual(networks, [])

    def test_get_floating_ips_by_fixed_address(self):
        # NOTE(lbragstad): We need to reset the mocks in order to assert
        # a NotImplementedError is raised when calling the method under test.
        self.mox.ResetAll()
        fake_fixed = '192.168.1.4'
        api = neutronapi.API()
        self.assertRaises(NotImplementedError,
                          api.get_floating_ips_by_fixed_address,
                          self.context, fake_fixed)


class TestNeutronv2WithMock(test.TestCase):
    """Used to test Neutron V2 API with mock."""

    def setUp(self):
        super(TestNeutronv2WithMock, self).setUp()
        self.api = neutronapi.API()
        self.context = context.RequestContext(
            'fake-user', 'fake-project',
            auth_token='bff4a5a6b9eb4ea2a6efec6eefb77936')

    @mock.patch('nova.openstack.common.lockutils.lock')
    def test_get_instance_nw_info_locks_per_instance(self, mock_lock):
        instance = instance_obj.Instance(uuid=uuid.uuid4())
        api = neutronapi.API()
        mock_lock.side_effect = test.TestingException
        self.assertRaises(test.TestingException,
                          api.get_instance_nw_info, 'context', instance)
        mock_lock.assert_called_once_with('refresh_cache-%s' % instance.uuid)


class TestNeutronv2ModuleMethods(test.TestCase):

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
        self._allocate_for_instance(1, portbinding=True)

    def test_populate_neutron_extension_values_binding(self):
        api = neutronapi.API()
        neutronv2.get_client(mox.IgnoreArg()).AndReturn(
                self.moxed_client)
        self.moxed_client.list_extensions().AndReturn(
            {'extensions': [{'name': constants.PORTBINDING_EXT}]})
        self.mox.ReplayAll()
        host_id = 'my_host_id'
        instance = {'host': host_id}
        port_req_body = {'port': {}}
        api._populate_neutron_extension_values(self.context, instance,
                                               port_req_body)
        self.assertEqual(port_req_body['port']['binding:host_id'], host_id)

    def test_migrate_instance_finish_binding_false(self):
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, '_has_port_binding_extension')
        api._has_port_binding_extension(mox.IgnoreArg(),
                                        refresh_cache=True).AndReturn(False)
        self.mox.ReplayAll()
        api.migrate_instance_finish(self.context, None, None)

    def test_migrate_instance_finish_binding_true(self):
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, '_has_port_binding_extension')
        api._has_port_binding_extension(mox.IgnoreArg(),
                                        refresh_cache=True).AndReturn(True)
        neutronv2.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        search_opts = {'device_id': self.instance['uuid'],
                       'tenant_id': self.instance['project_id']}
        ports = {'ports': [{'id': 'test1'}]}
        self.moxed_client.list_ports(**search_opts).AndReturn(ports)
        migration = {'source_compute': self.instance.get('host'),
                     'dest_compute': 'dest_host', }
        port_req_body = {'port':
                         {'binding:host_id': migration['dest_compute']}}
        self.moxed_client.update_port('test1',
                                      port_req_body).AndReturn(None)
        self.mox.ReplayAll()
        api.migrate_instance_finish(self.context, self.instance, migration)

    def test_migrate_instance_finish_binding_true_exception(self):
        api = neutronapi.API()
        self.mox.StubOutWithMock(api, '_has_port_binding_extension')
        api._has_port_binding_extension(mox.IgnoreArg(),
                                        refresh_cache=True).AndReturn(True)
        neutronv2.get_client(mox.IgnoreArg(), admin=True).AndReturn(
            self.moxed_client)
        search_opts = {'device_id': self.instance['uuid'],
                       'tenant_id': self.instance['project_id']}
        ports = {'ports': [{'id': 'test1'}]}
        self.moxed_client.list_ports(**search_opts).AndReturn(ports)
        migration = {'source_compute': self.instance.get('host'),
                     'dest_compute': 'dest_host', }
        port_req_body = {'port':
                         {'binding:host_id': migration['dest_compute']}}
        self.moxed_client.update_port('test1',
                                      port_req_body).AndRaise(
            Exception("fail to update port"))
        self.mox.ReplayAll()
        self.assertRaises(NEUTRON_CLIENT_EXCEPTION,
                          api.migrate_instance_finish,
                          self.context, self.instance, migration)

    def test_associate_not_implemented(self):
        api = neutronapi.API()
        self.assertRaises(NotImplementedError,
                          api.associate,
                          self.context, 'id')


class TestNeutronv2ExtraDhcpOpts(TestNeutronv2Base):
    def setUp(self):
        super(TestNeutronv2ExtraDhcpOpts, self).setUp()
        neutronv2.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)

    def test_allocate_for_instance_1_with_extra_dhcp_opts_turned_off(self):
        self._allocate_for_instance(1, extra_dhcp_opts=False)

    def test_allocate_for_instance_extradhcpopts(self):
        dhcp_opts = [{'opt_name': 'bootfile-name',
                          'opt_value': 'pxelinux.0'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '123.123.123.123'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '123.123.123.456'}]

        self._allocate_for_instance(1, dhcp_options=dhcp_opts)


class TestNeutronClientForAdminScenarios(test.TestCase):
    def test_get_cached_neutron_client_for_admin(self):
        self.flags(neutron_url='http://anyhost/')
        self.flags(neutron_url_timeout=30)
        my_context = context.RequestContext('userid',
                                            'my_tenantid',
                                            auth_token='token')

        # Make multiple calls and ensure we get the same
        # client back again and again
        client = neutronv2.get_client(my_context, True)
        client2 = neutronv2.get_client(my_context, True)
        client3 = neutronv2.get_client(my_context, True)
        self.assertEqual(client, client2)
        self.assertEqual(client, client3)

        # clear the cache
        local.strong_store.neutron_client = None

        # A new client should be created now
        client4 = neutronv2.get_client(my_context, True)
        self.assertNotEqual(client, client4)

    def test_get_neutron_client_for_non_admin(self):
        self.flags(neutron_url='http://anyhost/')
        self.flags(neutron_url_timeout=30)
        my_context = context.RequestContext('userid',
                                            'my_tenantid',
                                            auth_token='token')

        # Multiple calls should return different clients
        client = neutronv2.get_client(my_context)
        client2 = neutronv2.get_client(my_context)
        self.assertNotEqual(client, client2)

    def test_get_neutron_client_for_non_admin_and_no_token(self):
        self.flags(neutron_url='http://anyhost/')
        self.flags(neutron_url_timeout=30)
        my_context = context.RequestContext('userid',
                                            'my_tenantid')

        self.assertRaises(exceptions.Unauthorized,
                          neutronv2.get_client,
                          my_context)

    def _test_get_client_for_admin(self, use_id=False, admin_context=False):

        self.flags(neutron_auth_strategy=None)
        self.flags(neutron_url='http://anyhost/')
        self.flags(neutron_url_timeout=30)
        if use_id:
            self.flags(neutron_admin_tenant_id='admin_tenant_id')

        if admin_context:
            my_context = context.get_admin_context()
        else:
            my_context = context.RequestContext('userid', 'my_tenantid',
                                            auth_token='token')
        self.mox.StubOutWithMock(client.Client, "__init__")
        kwargs = {
            'auth_url': CONF.neutron_admin_auth_url,
            'password': CONF.neutron_admin_password,
            'username': CONF.neutron_admin_username,
            'endpoint_url': CONF.neutron_url,
            'auth_strategy': None,
            'timeout': CONF.neutron_url_timeout,
            'insecure': False,
            'ca_cert': None}
        if use_id:
            kwargs['tenant_id'] = CONF.neutron_admin_tenant_id
        else:
            kwargs['tenant_name'] = CONF.neutron_admin_tenant_name
        client.Client.__init__(**kwargs).AndReturn(None)
        self.mox.ReplayAll()

        # clear the cache
        if hasattr(local.strong_store, 'neutron_client'):
            delattr(local.strong_store, 'neutron_client')

        if admin_context:
            # Note that the context does not contain a token but is
            # an admin context  which will force an elevation to admin
            # credentials.
            neutronv2.get_client(my_context)
        else:
            # Note that the context is not elevated, but the True is passed in
            # which will force an elevation to admin credentials even though
            # the context has an auth_token.
            neutronv2.get_client(my_context, True)

    def test_get_client_for_admin(self):
        self._test_get_client_for_admin()

    def test_get_client_for_admin_with_id(self):
        self._test_get_client_for_admin(use_id=True)

    def test_get_client_for_admin_context(self):
        self._test_get_client_for_admin(admin_context=True)

    def test_get_client_for_admin_context_with_id(self):
        self._test_get_client_for_admin(use_id=True, admin_context=True)
