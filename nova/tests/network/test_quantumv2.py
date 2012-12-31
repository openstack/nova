# Copyright 2012 OpenStack LLC.
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
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import mox

from nova import context
from nova import exception
from nova.network import model
from nova.network import quantumv2
from nova.network.quantumv2 import api as quantumapi
from nova.openstack.common import cfg
from nova import test
from nova import utils
from quantumclient.v2_0 import client


FLAGS = cfg.CONF
#NOTE: Quantum client raises Exception which is discouraged by HACKING.
#      We set this variable here and use it for assertions below to avoid
#      the hacking checks until we can make quantum client throw a custom
#      exception class instead.
QUANTUM_CLIENT_EXCEPTION = Exception


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


class TestQuantumClient(test.TestCase):
    def setUp(self):
        super(TestQuantumClient, self).setUp()

    def test_withtoken(self):
        self.flags(quantum_url='http://anyhost/')
        self.flags(quantum_url_timeout=30)
        my_context = context.RequestContext('userid',
                                            'my_tenantid',
                                            auth_token='token')
        self.mox.StubOutWithMock(client.Client, "__init__")
        client.Client.__init__(
            endpoint_url=FLAGS.quantum_url,
            token=my_context.auth_token,
            timeout=FLAGS.quantum_url_timeout).AndReturn(None)
        self.mox.ReplayAll()
        quantumv2.get_client(my_context)

    def test_withouttoken_keystone_connection_error(self):
        self.flags(quantum_auth_strategy='keystone')
        self.flags(quantum_url='http://anyhost/')
        my_context = context.RequestContext('userid', 'my_tenantid')
        self.assertRaises(QUANTUM_CLIENT_EXCEPTION,
                          quantumv2.get_client,
                          my_context)

    def test_withouttoken_keystone_not_auth(self):
        # self.flags(quantum_auth_strategy=None) fail to work
        old_quantum_auth_strategy = FLAGS.quantum_auth_strategy
        setattr(FLAGS, 'quantum_auth_strategy', None)
        self.flags(quantum_url='http://anyhost/')
        self.flags(quantum_url_timeout=30)
        my_context = context.RequestContext('userid', 'my_tenantid')
        self.mox.StubOutWithMock(client.Client, "__init__")
        client.Client.__init__(
            endpoint_url=FLAGS.quantum_url,
            auth_strategy=None,
            timeout=FLAGS.quantum_url_timeout).AndReturn(None)
        self.mox.ReplayAll()
        try:
            quantumv2.get_client(my_context)
        finally:
            setattr(FLAGS, 'quantum_auth_strategy',
                    old_quantum_auth_strategy)


class TestQuantumv2(test.TestCase):

    def setUp(self):
        super(TestQuantumv2, self).setUp()
        self.mox.StubOutWithMock(quantumv2, 'get_client')
        self.moxed_client = self.mox.CreateMock(client.Client)
        quantumv2.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)
        self.context = context.RequestContext('userid', 'my_tenantid')
        setattr(self.context,
                'auth_token',
                'bff4a5a6b9eb4ea2a6efec6eefb77936')
        self.instance = {'project_id': '9d049e4b60b64716978ab415e6fbd5c0',
                         'uuid': str(utils.gen_uuid()),
                         'display_name': 'test_instance',
                         'security_groups': []}
        self.nets1 = [{'id': 'my_netid1',
                      'name': 'my_netname1',
                      'tenant_id': 'my_tenantid'}]
        self.nets2 = []
        self.nets2.append(self.nets1[0])
        self.nets2.append({'id': 'my_netid2',
                           'name': 'my_netname2',
                           'tenant_id': 'my_tenantid'})
        self.nets3 = self.nets2 + [{'id': 'my_netid3',
                                    'name': 'my_netname3',
                                    'tenant_id': 'my_tenantid'}]
        self.nets4 = [{'id': 'his_netid4',
                      'name': 'his_netname4',
                      'tenant_id': 'his_tenantid'}]

        self.nets = [self.nets1, self.nets2, self.nets3, self.nets4]

        self.port_address = '10.0.1.2'
        self.port_data1 = [{'network_id': 'my_netid1',
                           'device_id': 'device_id1',
                           'device_owner': 'compute:nova',
                           'id': 'my_portid1',
                           'fixed_ips': [{'ip_address': self.port_address,
                                          'subnet_id': 'my_subid1'}],
                           'mac_address': 'my_mac1', }]
        self.dhcp_port_data1 = [{'fixed_ips': [{'ip_address': '10.0.1.9',
                                               'subnet_id': 'my_subid1'}]}]
        self.port_data2 = []
        self.port_data2.append(self.port_data1[0])
        self.port_data2.append({'network_id': 'my_netid2',
                                'device_id': 'device_id2',
                                'device_owner': 'compute:nova',
                                'id': 'my_portid2',
                                'fixed_ips': [{'ip_address': '10.0.2.2',
                                               'subnet_id': 'my_subid2'}],
                                'mac_address': 'my_mac2', })
        self.port_data3 = [{'network_id': 'my_netid1',
                           'device_id': 'device_id3',
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

    def tearDown(self):
        try:
            self.mox.UnsetStubs()
            self.mox.VerifyAll()
        finally:
            FLAGS.reset()

    def _verify_nw_info(self, nw_inf, index=0):
        id_suffix = index + 1
        self.assertEquals('10.0.%s.2' % id_suffix,
                          nw_inf.fixed_ips()[index]['address'])
        self.assertEquals('my_netname%s' % id_suffix,
                          nw_inf[index]['network']['label'])
        self.assertEquals('my_portid%s' % id_suffix, nw_inf[index]['id'])
        self.assertEquals('my_mac%s' % id_suffix, nw_inf[index]['address'])
        self.assertEquals('10.0.%s.0/24' % id_suffix,
            nw_inf[index]['network']['subnets'][0]['cidr'])
        self.assertTrue(model.IP(address='8.8.%s.1' % id_suffix) in
                        nw_inf[index]['network']['subnets'][0]['dns'])

    def _get_instance_nw_info(self, number):
        api = quantumapi.API()
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(mox.IgnoreArg(),
                                          self.instance['uuid'],
                                          mox.IgnoreArg())
        port_data = number == 1 and self.port_data1 or self.port_data2
        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': port_data})
        nets = number == 1 and self.nets1 or self.nets2
        self.moxed_client.list_networks(
            tenant_id=self.instance['project_id'],
            shared=False).AndReturn({'networks': nets})
        self.moxed_client.list_networks(
            shared=True).AndReturn({'networks': []})
        for i in xrange(1, number + 1):
            subnet_data = i == 1 and self.subnet_data1 or self.subnet_data2
            self.moxed_client.list_subnets(
                id=mox.SameElementsAs(['my_subid%s' % i])).AndReturn(
                    {'subnets': subnet_data})
            self.moxed_client.list_ports(
                network_id=subnet_data[0]['network_id'],
                device_owner='network:dhcp').AndReturn(
                    {'ports': []})
        self.mox.ReplayAll()
        nw_inf = api.get_instance_nw_info(self.context, self.instance)
        for i in xrange(0, number):
            self._verify_nw_info(nw_inf, i)

    def test_get_instance_nw_info_1(self):
        """Test to get one port in one network and subnet."""
        self._get_instance_nw_info(1)

    def test_get_instance_nw_info_2(self):
        """Test to get one port in each of two networks and subnets."""
        self._get_instance_nw_info(2)

    def test_get_instance_nw_info_with_nets(self):
        """Test get instance_nw_info with networks passed in."""
        api = quantumapi.API()
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(
            mox.IgnoreArg(),
            self.instance['uuid'], mox.IgnoreArg())
        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': self.port_data1})
        self.moxed_client.list_subnets(
            id=mox.SameElementsAs(['my_subid1'])).AndReturn(
                {'subnets': self.subnet_data1})
        self.moxed_client.list_ports(
            network_id='my_netid1',
            device_owner='network:dhcp').AndReturn(
                {'ports': self.dhcp_port_data1})
        self.mox.ReplayAll()
        nw_inf = api.get_instance_nw_info(self.context,
                                          self.instance,
                                          networks=self.nets1)
        self._verify_nw_info(nw_inf, 0)

    def test_get_instance_nw_info_without_subnet(self):
        """Test get instance_nw_info for a port without subnet."""
        api = quantumapi.API()
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(
            mox.IgnoreArg(),
            self.instance['uuid'], mox.IgnoreArg())
        self.moxed_client.list_ports(
            tenant_id=self.instance['project_id'],
            device_id=self.instance['uuid']).AndReturn(
                {'ports': self.port_data3})
        self.moxed_client.list_networks(
            shared=False,
            tenant_id=self.instance['project_id']).AndReturn(
                {'networks': self.nets1})
        self.moxed_client.list_networks(
            shared=True).AndReturn({'networks': []})
        self.mox.ReplayAll()

        nw_inf = api.get_instance_nw_info(self.context,
                                          self.instance)

        id_suffix = 3
        self.assertEquals(0, len(nw_inf.fixed_ips()))
        self.assertEquals('my_netname1', nw_inf[0]['network']['label'])
        self.assertEquals('my_portid%s' % id_suffix, nw_inf[0]['id'])
        self.assertEquals('my_mac%s' % id_suffix, nw_inf[0]['address'])
        self.assertEquals(0, len(nw_inf[0]['network']['subnets']))

    def _allocate_for_instance(self, net_idx=1, **kwargs):
        api = quantumapi.API()
        self.mox.StubOutWithMock(api, 'get_instance_nw_info')
        # Net idx is 1-based for compatibility with existing unit tests
        nets = self.nets[net_idx - 1]
        api.get_instance_nw_info(mox.IgnoreArg(),
                                 self.instance,
                                 networks=nets).AndReturn(None)

        ports = {}
        fixed_ips = {}
        req_net_ids = []
        if 'requested_networks' in kwargs:
            for id, fixed_ip, port_id in kwargs['requested_networks']:
                if port_id:
                    self.moxed_client.show_port(port_id).AndReturn(
                        {'port': {'id': 'my_portid1',
                         'network_id': 'my_netid1'}})
                    ports['my_netid1'] = self.port_data1[0]
                    id = 'my_netid1'
                else:
                    fixed_ips[id] = fixed_ip
                req_net_ids.append(id)
            expected_network_order = req_net_ids
        else:
            expected_network_order = [n['id'] for n in nets]
        search_ids = [net['id'] for net in nets if net['id'] in req_net_ids]

        mox_list_network_params = dict(tenant_id=self.instance['project_id'],
                                       shared=False)
        if search_ids:
            mox_list_network_params['id'] = mox.SameElementsAs(search_ids)
        self.moxed_client.list_networks(
            **mox_list_network_params).AndReturn({'networks': nets})

        mox_list_network_params = dict(shared=True)
        if search_ids:
            mox_list_network_params['id'] = mox.SameElementsAs(search_ids)
        self.moxed_client.list_networks(
            **mox_list_network_params).AndReturn({'networks': []})

        for net_id in expected_network_order:
            port_req_body = {
                'port': {
                    'device_id': self.instance['uuid'],
                    'device_owner': 'compute:nova',
                },
            }
            port = ports.get(net_id, None)
            if port:
                port_id = port['id']
                self.moxed_client.update_port(port_id,
                                              MyComparator(port_req_body)
                                              ).AndReturn(
                                                  {'port': port})
            else:
                fixed_ip = fixed_ips.get(net_id)
                if fixed_ip:
                    port_req_body['port']['fixed_ips'] = [{'ip_address':
                                                           fixed_ip}]
                port_req_body['port']['network_id'] = net_id
                port_req_body['port']['admin_state_up'] = True
                port_req_body['port']['tenant_id'] = \
                    self.instance['project_id']
                res_port = {'port': {'id': 'fake'}}
                self.moxed_client.create_port(
                    MyComparator(port_req_body)).AndReturn(res_port)
        self.mox.ReplayAll()
        api.allocate_for_instance(self.context, self.instance, **kwargs)

    def test_allocate_for_instance_1(self):
        """Allocate one port in one network env."""
        self._allocate_for_instance(1)

    def test_allocate_for_instance_2(self):
        """Allocate one port in two networks env."""
        self._allocate_for_instance(2)

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
        # specify only first and last network
        requested_networks = [(None, None, 'myportid1')]
        self._allocate_for_instance(net_idx=1,
                                    requested_networks=requested_networks)

    def test_allocate_for_instance_ex1(self):
        """verify we will delete created ports
        if we fail to allocate all net resources.

        Mox to raise exception when creating a second port.
        In this case, the code should delete the first created port.
        """
        api = quantumapi.API()
        self.moxed_client.list_networks(
            tenant_id=self.instance['project_id'],
            shared=False).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_networks(shared=True).AndReturn(
                {'networks': []})
        index = 0
        for network in self.nets2:
            port_req_body = {
                'port': {
                    'network_id': network['id'],
                    'admin_state_up': True,
                    'device_id': self.instance['uuid'],
                    'device_owner': 'compute:nova',
                    'tenant_id': self.instance['project_id'],
                },
            }
            port = {'id': 'portid_' + network['id']}
            if index == 0:
                self.moxed_client.create_port(
                    MyComparator(port_req_body)).AndReturn({'port': port})
            else:
                self.moxed_client.create_port(
                    MyComparator(port_req_body)).AndRaise(
                        Exception("fail to create port"))
            index += 1
        self.moxed_client.delete_port('portid_' + self.nets2[0]['id'])
        self.mox.ReplayAll()
        self.assertRaises(QUANTUM_CLIENT_EXCEPTION, api.allocate_for_instance,
                          self.context, self.instance)

    def test_allocate_for_instance_ex2(self):
        """verify we have no port to delete
        if we fail to allocate the first net resource.

        Mox to raise exception when creating the first port.
        In this case, the code should not delete any ports.
        """
        api = quantumapi.API()
        self.moxed_client.list_networks(
            tenant_id=self.instance['project_id'],
            shared=False).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_networks(shared=True).AndReturn(
                {'networks': []})
        port_req_body = {
            'port': {
                'network_id': self.nets2[0]['id'],
                'admin_state_up': True,
                'device_id': self.instance['uuid'],
                'tenant_id': self.instance['project_id'],
            },
        }
        self.moxed_client.create_port(
            MyComparator(port_req_body)).AndRaise(
                Exception("fail to create port"))
        self.mox.ReplayAll()
        self.assertRaises(QUANTUM_CLIENT_EXCEPTION, api.allocate_for_instance,
                          self.context, self.instance)

    def _deallocate_for_instance(self, number):
        port_data = number == 1 and self.port_data1 or self.port_data2
        self.moxed_client.list_ports(
            device_id=self.instance['uuid']).AndReturn(
                {'ports': port_data})
        for port in port_data:
            self.moxed_client.delete_port(port['id'])
        self.mox.ReplayAll()
        api = quantumapi.API()
        api.deallocate_for_instance(self.context, self.instance)

    def test_deallocate_for_instance_1(self):
        """Test to deallocate in one port env."""
        self._deallocate_for_instance(1)

    def test_deallocate_for_instance_2(self):
        """Test to deallocate in two ports env."""
        self._deallocate_for_instance(2)

    def test_validate_networks(self):
        requested_networks = [('my_netid1', 'test', None),
                              ('my_netid2', 'test2', None)]
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(['my_netid1', 'my_netid2']),
            tenant_id=self.context.project_id,
            shared=False).AndReturn(
                {'networks': self.nets2})
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(['my_netid1', 'my_netid2']),
            shared=True).AndReturn(
                {'networks': []})
        self.mox.ReplayAll()
        api = quantumapi.API()
        api.validate_networks(self.context, requested_networks)

    def test_validate_networks_ex_1(self):
        requested_networks = [('my_netid1', 'test', None),
                              ('my_netid2', 'test2', None)]
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(['my_netid1', 'my_netid2']),
            tenant_id=self.context.project_id,
            shared=False).AndReturn(
                {'networks': self.nets1})
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(['my_netid1', 'my_netid2']),
            shared=True).AndReturn(
                {'networks': []})
        self.mox.ReplayAll()
        api = quantumapi.API()
        try:
            api.validate_networks(self.context, requested_networks)
        except exception.NetworkNotFound as ex:
            self.assertTrue("my_netid2" in str(ex))

    def test_validate_networks_ex_2(self):
        requested_networks = [('my_netid1', 'test', None),
                              ('my_netid2', 'test2', None),
                              ('my_netid3', 'test3', None)]
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(['my_netid1', 'my_netid2', 'my_netid3']),
            tenant_id=self.context.project_id,
            shared=False).AndReturn(
                {'networks': self.nets1})
        self.moxed_client.list_networks(
            id=mox.SameElementsAs(['my_netid1', 'my_netid2', 'my_netid3']),
            shared=True).AndReturn(
                {'networks': []})
        self.mox.ReplayAll()
        api = quantumapi.API()
        try:
            api.validate_networks(self.context, requested_networks)
        except exception.NetworkNotFound as ex:
            self.assertTrue("my_netid2, my_netid3" in str(ex))

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
        api = quantumapi.API()
        result = api.get_instance_uuids_by_ip_filter(self.context, filters)
        self.assertEquals('device_id1', result[0]['instance_uuid'])
        self.assertEquals('device_id2', result[1]['instance_uuid'])

    def test_get_fixed_ip_by_address_fails_for_no_ports(self):
        address = self._mock_list_ports(port_data=[])
        api = quantumapi.API()
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          api.get_fixed_ip_by_address,
                          self.context, address)

    def test_get_fixed_ip_by_address_succeeds_for_1_port(self):
        address = self._mock_list_ports(port_data=self.port_data1)
        api = quantumapi.API()
        result = api.get_fixed_ip_by_address(self.context, address)
        self.assertEquals('device_id1', result['instance_uuid'])

    def test_get_fixed_ip_by_address_fails_for_more_than_1_port(self):
        address = self._mock_list_ports()
        api = quantumapi.API()
        self.assertRaises(exception.FixedIpAssociatedWithMultipleInstances,
                          api.get_fixed_ip_by_address,
                          self.context, address)

    def _get_available_networks(self, prv_nets, pub_nets, req_ids=None):
        api = quantumapi.API()
        nets = prv_nets + pub_nets
        mox_list_network_params = dict(tenant_id=self.instance['project_id'],
                                       shared=False)
        if req_ids:
            mox_list_network_params['id'] = req_ids
        self.moxed_client.list_networks(
            **mox_list_network_params).AndReturn({'networks': prv_nets})
        mox_list_network_params = dict(shared=True)
        if req_ids:
            mox_list_network_params['id'] = req_ids
        self.moxed_client.list_networks(
            **mox_list_network_params).AndReturn({'networks': pub_nets})

        self.mox.ReplayAll()
        rets = api._get_available_networks(self.context,
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

    def test_get_floating_ip_pools(self):
        api = quantumapi.API()
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
        api = quantumapi.API()
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
        api = quantumapi.API()
        address = self.fip_unassociated['floating_ip_address']
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': []})
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          api.get_floating_ip_by_address,
                          self.context, address)

    def test_get_floating_ip_by_address_multiple_found(self):
        api = quantumapi.API()
        address = self.fip_unassociated['floating_ip_address']
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated] * 2})
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpMultipleFoundForAddress,
                          api.get_floating_ip_by_address,
                          self.context, address)

    def test_get_floating_ips_by_project(self):
        api = quantumapi.API()
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
        api = quantumapi.API()
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
        api = quantumapi.API()
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

    def test_allocate_floating_ip_with_pool_id(self):
        api = quantumapi.API()
        pool_name = self.fip_pool['name']
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
        api = quantumapi.API()
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
        api = quantumapi.API()
        address = self.fip_unassociated['floating_ip_address']
        fip_id = self.fip_unassociated['id']

        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_unassociated]})
        self.moxed_client.delete_floatingip(fip_id)
        self.mox.ReplayAll()
        api.release_floating_ip(self.context, address)

    def test_release_floating_ip_associated(self):
        api = quantumapi.API()
        address = self.fip_associated['floating_ip_address']
        fip_id = self.fip_associated['id']

        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_associated]})
        self.mox.ReplayAll()
        self.assertRaises(exception.FloatingIpAssociated,
                          api.release_floating_ip, self.context, address)

    def _setup_mock_for_refresh_cache(self, api):
        nw_info = self.mox.CreateMock(model.NetworkInfo)
        nw_info.json()
        self.mox.StubOutWithMock(api, '_get_instance_nw_info')
        api._get_instance_nw_info(mox.IgnoreArg(), self.instance).\
            AndReturn(nw_info)
        self.mox.StubOutWithMock(api.db, 'instance_info_cache_update')
        api.db.instance_info_cache_update(mox.IgnoreArg(),
                                          self.instance['uuid'],
                                          mox.IgnoreArg())

    def test_associate_floating_ip(self):
        api = quantumapi.API()
        address = self.fip_associated['floating_ip_address']
        fixed_address = self.fip_associated['fixed_ip_address']
        fip_id = self.fip_associated['id']

        search_opts = {'device_owner': 'compute:nova',
                       'device_id': self.instance['uuid']}
        self.moxed_client.list_ports(**search_opts).\
            AndReturn({'ports': [self.port_data2[1]]})
        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_associated]})
        self.moxed_client.update_floatingip(
            fip_id, {'floatingip': {'port_id': self.fip_associated['port_id'],
                                    'fixed_ip_address': fixed_address}})
        self._setup_mock_for_refresh_cache(api)

        self.mox.ReplayAll()
        api.associate_floating_ip(self.context, self.instance,
                                  address, fixed_address)

    def test_associate_floating_ip_not_found_fixed_ip(self):
        api = quantumapi.API()
        address = self.fip_associated['floating_ip_address']
        fixed_address = self.fip_associated['fixed_ip_address']
        fip_id = self.fip_associated['id']

        search_opts = {'device_owner': 'compute:nova',
                       'device_id': self.instance['uuid']}
        self.moxed_client.list_ports(**search_opts).\
            AndReturn({'ports': [self.port_data2[0]]})

        self.mox.ReplayAll()
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          api.associate_floating_ip, self.context,
                          self.instance, address, fixed_address)

    def test_disassociate_floating_ip(self):
        api = quantumapi.API()
        address = self.fip_associated['floating_ip_address']
        fip_id = self.fip_associated['id']

        self.moxed_client.list_floatingips(floating_ip_address=address).\
            AndReturn({'floatingips': [self.fip_associated]})
        self.moxed_client.update_floatingip(
            fip_id, {'floatingip': {'port_id': None}})
        self._setup_mock_for_refresh_cache(api)

        self.mox.ReplayAll()
        api.disassociate_floating_ip(self.context, self.instance, address)


class TestQuantumv2ModuleMethods(test.TestCase):
    def test_ensure_requested_network_ordering_no_preference(self):
        l = [1, 2, 3]

        quantumapi._ensure_requested_network_ordering(
            lambda x: x,
            l,
            None)

    def test_ensure_requested_network_ordering_no_preference(self):
        l = [{'id': 3}, {'id': 1}, {'id': 2}]

        quantumapi._ensure_requested_network_ordering(
            lambda x: x['id'],
            l,
            None)

        self.assertEqual(l, [{'id': 3}, {'id': 1}, {'id': 2}])

    def test_ensure_requested_network_ordering_with_preference(self):
        l = [{'id': 3}, {'id': 1}, {'id': 2}]

        quantumapi._ensure_requested_network_ordering(
            lambda x: x['id'],
            l,
            [1, 2, 3])

        self.assertEqual(l, [{'id': 1}, {'id': 2}, {'id': 3}])
