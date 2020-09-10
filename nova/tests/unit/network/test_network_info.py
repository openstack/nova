# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
# Copyright 2013 IBM Corp.
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

from oslo_config import cfg
from oslo_utils.fixture import uuidsentinel as uuids

from nova import exception
from nova.network import model
from nova import objects
from nova import test
from nova.tests.unit import fake_network_cache_model
from nova.virt import netutils


class RouteTests(test.NoDBTestCase):
    def test_create_route_with_attrs(self):
        route = fake_network_cache_model.new_route()
        self.assertEqual('0.0.0.0/24', route['cidr'])
        self.assertEqual('192.168.1.1', route['gateway']['address'])
        self.assertEqual('eth0', route['interface'])

    def test_routes_equal(self):
        route1 = model.Route()
        route2 = model.Route()
        self.assertEqual(route1, route2)

    def test_routes_not_equal(self):
        route1 = model.Route(cidr='1.1.1.0/24')
        route2 = model.Route(cidr='2.2.2.0/24')
        self.assertNotEqual(route1, route2)

        route1 = model.Route(cidr='1.1.1.1/24', gateway='1.1.1.1')
        route2 = model.Route(cidr='1.1.1.1/24', gateway='1.1.1.2')
        self.assertNotEqual(route1, route2)

        route1 = model.Route(cidr='1.1.1.1/24', interface='tap0')
        route2 = model.Route(cidr='1.1.1.1/24', interface='tap1')
        self.assertNotEqual(route1, route2)

    def test_hydrate(self):
        route = model.Route.hydrate(
                {'gateway': fake_network_cache_model.new_ip(
                                dict(address='192.168.1.1'))})
        self.assertIsNone(route['cidr'])
        self.assertEqual('192.168.1.1', route['gateway']['address'])
        self.assertIsNone(route['interface'])


class IPTests(test.NoDBTestCase):
    def test_ip_equal(self):
        ip1 = model.IP(address='127.0.0.1')
        ip2 = model.IP(address='127.0.0.1')
        self.assertEqual(ip1, ip2)

    def test_ip_not_equal(self):
        ip1 = model.IP(address='127.0.0.1')
        ip2 = model.IP(address='172.0.0.3')
        self.assertNotEqual(ip1, ip2)

        ip1 = model.IP(address='127.0.0.1', type=1)
        ip2 = model.IP(address='172.0.0.1', type=2)
        self.assertNotEqual(ip1, ip2)

        ip1 = model.IP(address='127.0.0.1', version=4)
        ip2 = model.IP(address='172.0.0.1', version=6)
        self.assertNotEqual(ip1, ip2)


class FixedIPTests(test.NoDBTestCase):
    def test_createnew_fixed_ip_with_attrs(self):
        fixed_ip = model.FixedIP(address='192.168.1.100')
        self.assertEqual('192.168.1.100', fixed_ip['address'])
        self.assertEqual([], fixed_ip['floating_ips'])
        self.assertEqual('fixed', fixed_ip['type'])
        self.assertEqual(4, fixed_ip['version'])

    def test_create_fixed_ipv6(self):
        fixed_ip = model.FixedIP(address='::1')
        self.assertEqual('::1', fixed_ip['address'])
        self.assertEqual([], fixed_ip['floating_ips'])
        self.assertEqual('fixed', fixed_ip['type'])
        self.assertEqual(6, fixed_ip['version'])

    def test_create_fixed_bad_ip_fails(self):
        self.assertRaises(exception.InvalidIpAddressError,
                          model.FixedIP,
                          address='picklespicklespickles')

    def test_equate_two_fixed_ips(self):
        fixed_ip = model.FixedIP(address='::1')
        fixed_ip2 = model.FixedIP(address='::1')
        self.assertEqual(fixed_ip, fixed_ip2)

    def test_equate_two_dissimilar_fixed_ips_fails(self):
        fixed_ip = model.FixedIP(address='::1')
        fixed_ip2 = model.FixedIP(address='::2')
        self.assertNotEqual(fixed_ip, fixed_ip2)

        fixed_ip = model.FixedIP(address='::1', type='1')
        fixed_ip2 = model.FixedIP(address='::1', type='2')
        self.assertNotEqual(fixed_ip, fixed_ip2)

        fixed_ip = model.FixedIP(address='::1', version='6')
        fixed_ip2 = model.FixedIP(address='::1', version='4')
        self.assertNotEqual(fixed_ip, fixed_ip2)

        fixed_ip = model.FixedIP(address='::1', floating_ips='1.1.1.1')
        fixed_ip2 = model.FixedIP(address='::1', floating_ips='8.8.8.8')
        self.assertNotEqual(fixed_ip, fixed_ip2)

    def test_hydrate(self):
        fixed_ip = model.FixedIP.hydrate({})
        self.assertEqual([], fixed_ip['floating_ips'])
        self.assertIsNone(fixed_ip['address'])
        self.assertEqual('fixed', fixed_ip['type'])
        self.assertIsNone(fixed_ip['version'])

    def test_add_floating_ip(self):
        fixed_ip = model.FixedIP(address='192.168.1.100')
        fixed_ip.add_floating_ip('192.168.1.101')
        self.assertEqual(['192.168.1.101'], fixed_ip['floating_ips'])

    def test_add_floating_ip_repeatedly_only_one_instance(self):
        fixed_ip = model.FixedIP(address='192.168.1.100')
        for i in range(10):
            fixed_ip.add_floating_ip('192.168.1.101')
        self.assertEqual(['192.168.1.101'], fixed_ip['floating_ips'])


class SubnetTests(test.NoDBTestCase):
    def test_create_subnet_with_attrs(self):
        subnet = fake_network_cache_model.new_subnet()

        route1 = fake_network_cache_model.new_route()

        self.assertEqual('10.10.0.0/24', subnet['cidr'])
        self.assertEqual(
            [fake_network_cache_model.new_ip(dict(address='1.2.3.4')),
             fake_network_cache_model.new_ip(dict(address='2.3.4.5'))],
            subnet['dns'])
        self.assertEqual('10.10.0.1', subnet['gateway']['address'])
        self.assertEqual(
                [fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.2')),
                 fake_network_cache_model.new_fixed_ip(
                            dict(address='10.10.0.3'))], subnet['ips'])
        self.assertEqual([route1], subnet['routes'])
        self.assertEqual(4, subnet['version'])

    def test_subnet_equal(self):
        subnet1 = fake_network_cache_model.new_subnet()
        subnet2 = fake_network_cache_model.new_subnet()
        self.assertEqual(subnet1, subnet2)

    def test_subnet_not_equal(self):
        subnet1 = model.Subnet(cidr='1.1.1.0/24')
        subnet2 = model.Subnet(cidr='2.2.2.0/24')
        self.assertNotEqual(subnet1, subnet2)

        subnet1 = model.Subnet(dns='1.1.1.0/24')
        subnet2 = model.Subnet(dns='2.2.2.0/24')
        self.assertNotEqual(subnet1, subnet2)

        subnet1 = model.Subnet(gateway='1.1.1.1/24')
        subnet2 = model.Subnet(gateway='2.2.2.1/24')
        self.assertNotEqual(subnet1, subnet2)

        subnet1 = model.Subnet(ips='1.1.1.0/24')
        subnet2 = model.Subnet(ips='2.2.2.0/24')
        self.assertNotEqual(subnet1, subnet2)

        subnet1 = model.Subnet(routes='1.1.1.0/24')
        subnet2 = model.Subnet(routes='2.2.2.0/24')
        self.assertNotEqual(subnet1, subnet2)

        subnet1 = model.Subnet(version='4')
        subnet2 = model.Subnet(version='6')
        self.assertNotEqual(subnet1, subnet2)

    def test_add_route(self):
        subnet = fake_network_cache_model.new_subnet()
        route1 = fake_network_cache_model.new_route()
        route2 = fake_network_cache_model.new_route({'cidr': '1.1.1.1/24'})
        subnet.add_route(route2)
        self.assertEqual([route1, route2], subnet['routes'])

    def test_add_route_a_lot(self):
        subnet = fake_network_cache_model.new_subnet()
        route1 = fake_network_cache_model.new_route()
        route2 = fake_network_cache_model.new_route({'cidr': '1.1.1.1/24'})
        for i in range(10):
            subnet.add_route(route2)
        self.assertEqual([route1, route2], subnet['routes'])

    def test_add_dns(self):
        subnet = fake_network_cache_model.new_subnet()
        dns = fake_network_cache_model.new_ip(dict(address='9.9.9.9'))
        subnet.add_dns(dns)
        self.assertEqual(
                [fake_network_cache_model.new_ip(dict(address='1.2.3.4')),
                 fake_network_cache_model.new_ip(dict(address='2.3.4.5')),
                 fake_network_cache_model.new_ip(dict(address='9.9.9.9'))],
                subnet['dns'])

    def test_add_dns_a_lot(self):
        subnet = fake_network_cache_model.new_subnet()
        for i in range(10):
            subnet.add_dns(fake_network_cache_model.new_ip(
                    dict(address='9.9.9.9')))
        self.assertEqual(
                [fake_network_cache_model.new_ip(dict(address='1.2.3.4')),
                 fake_network_cache_model.new_ip(dict(address='2.3.4.5')),
                 fake_network_cache_model.new_ip(dict(address='9.9.9.9'))],
                subnet['dns'])

    def test_add_ip(self):
        subnet = fake_network_cache_model.new_subnet()
        subnet.add_ip(fake_network_cache_model.new_ip(
                dict(address='192.168.1.102')))
        self.assertEqual(
                [fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.2')),
                 fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.3')),
                 fake_network_cache_model.new_ip(
                        dict(address='192.168.1.102'))], subnet['ips'])

    def test_add_ip_a_lot(self):
        subnet = fake_network_cache_model.new_subnet()
        for i in range(10):
            subnet.add_ip(fake_network_cache_model.new_fixed_ip(
                        dict(address='192.168.1.102')))
        self.assertEqual(
                [fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.2')),
                 fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.3')),
                 fake_network_cache_model.new_fixed_ip(
                        dict(address='192.168.1.102'))], subnet['ips'])

    def test_hydrate(self):
        subnet_dict = {
            'cidr': '255.255.255.0',
            'dns': [fake_network_cache_model.new_ip(dict(address='1.1.1.1'))],
            'ips': [fake_network_cache_model.new_fixed_ip(
                    dict(address='2.2.2.2'))],
            'routes': [fake_network_cache_model.new_route()],
            'version': 4,
            'gateway': fake_network_cache_model.new_ip(
                            dict(address='3.3.3.3'))}
        subnet = model.Subnet.hydrate(subnet_dict)

        self.assertEqual('255.255.255.0', subnet['cidr'])
        self.assertEqual([fake_network_cache_model.new_ip(
            dict(address='1.1.1.1'))], subnet['dns'])
        self.assertEqual('3.3.3.3', subnet['gateway']['address'])
        self.assertEqual([fake_network_cache_model.new_fixed_ip(
            dict(address='2.2.2.2'))], subnet['ips'])
        self.assertEqual([fake_network_cache_model.new_route()],
                         subnet['routes'])
        self.assertEqual(4, subnet['version'])


class NetworkTests(test.NoDBTestCase):
    def test_create_network(self):
        network = fake_network_cache_model.new_network()
        self.assertEqual(uuids.network_id, network['id'])
        self.assertEqual('br0', network['bridge'])
        self.assertEqual('public', network['label'])
        self.assertEqual(
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255'))], network['subnets'])

    def test_add_subnet(self):
        network = fake_network_cache_model.new_network()
        network.add_subnet(fake_network_cache_model.new_subnet(
                    dict(cidr='0.0.0.0')))
        self.assertEqual(
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255')),
                 fake_network_cache_model.new_subnet(dict(cidr='0.0.0.0'))],
                network['subnets'])

    def test_add_subnet_a_lot(self):
        network = fake_network_cache_model.new_network()
        for i in range(10):
            network.add_subnet(fake_network_cache_model.new_subnet(
                    dict(cidr='0.0.0.0')))
        self.assertEqual(
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255')),
                 fake_network_cache_model.new_subnet(dict(cidr='0.0.0.0'))],
                network['subnets'])

    def test_network_equal(self):
        network1 = model.Network()
        network2 = model.Network()
        self.assertEqual(network1, network2)

    def test_network_not_equal(self):
        network1 = model.Network(id='1')
        network2 = model.Network(id='2')
        self.assertNotEqual(network1, network2)

        network1 = model.Network(bridge='br-int')
        network2 = model.Network(bridge='br0')
        self.assertNotEqual(network1, network2)

        network1 = model.Network(label='net1')
        network2 = model.Network(label='net2')
        self.assertNotEqual(network1, network2)

        network1 = model.Network(subnets='1.1.1.0/24')
        network2 = model.Network(subnets='2.2.2.0/24')
        self.assertNotEqual(network1, network2)

    def test_hydrate(self):
        network = model.Network.hydrate(fake_network_cache_model.new_network())

        self.assertEqual(uuids.network_id, network['id'])
        self.assertEqual('br0', network['bridge'])
        self.assertEqual('public', network['label'])
        self.assertEqual(
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255'))], network['subnets'])


class VIFTests(test.NoDBTestCase):
    def test_create_vif(self):
        vif = fake_network_cache_model.new_vif()
        self.assertEqual(uuids.vif_id, vif['id'])
        self.assertEqual('aa:aa:aa:aa:aa:aa', vif['address'])
        self.assertEqual(fake_network_cache_model.new_network(),
                         vif['network'])

    def test_vif_equal(self):
        vif1 = model.VIF()
        vif2 = model.VIF()
        self.assertEqual(vif1, vif2)

    def test_vif_not_equal(self):
        vif1 = model.VIF(id=1)
        vif2 = model.VIF(id=2)
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(address='00:00:00:00:00:11')
        vif2 = model.VIF(address='00:00:00:00:00:22')
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(network='net1')
        vif2 = model.VIF(network='net2')
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(type='ovs')
        vif2 = model.VIF(type='linuxbridge')
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(devname='ovs1234')
        vif2 = model.VIF(devname='linuxbridge1234')
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(qbh_params=1)
        vif2 = model.VIF(qbh_params=None)
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(qbg_params=1)
        vif2 = model.VIF(qbg_params=None)
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(active=True)
        vif2 = model.VIF(active=False)
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(vnic_type=model.VNIC_TYPE_NORMAL)
        vif2 = model.VIF(vnic_type=model.VNIC_TYPE_DIRECT)
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(profile={'pci_slot': '0000:0a:00.1'})
        vif2 = model.VIF(profile={'pci_slot': '0000:0a:00.2'})
        self.assertNotEqual(vif1, vif2)

        vif1 = model.VIF(preserve_on_delete=True)
        vif2 = model.VIF(preserve_on_delete=False)
        self.assertNotEqual(vif1, vif2)

    def test_create_vif_with_type(self):
        vif_dict = dict(
            id=uuids.vif_id,
            address='aa:aa:aa:aa:aa:aa',
            network=fake_network_cache_model.new_network(),
            type='bridge')
        vif = fake_network_cache_model.new_vif(vif_dict)
        self.assertEqual(uuids.vif_id, vif['id'])
        self.assertEqual('aa:aa:aa:aa:aa:aa', vif['address'])
        self.assertEqual('bridge', vif['type'])
        self.assertEqual(fake_network_cache_model.new_network(),
                         vif['network'])

    def test_vif_get_fixed_ips(self):
        vif = fake_network_cache_model.new_vif()
        fixed_ips = vif.fixed_ips()
        ips = [
            fake_network_cache_model.new_fixed_ip(dict(address='10.10.0.2')),
            fake_network_cache_model.new_fixed_ip(dict(address='10.10.0.3'))
        ] * 2
        self.assertEqual(fixed_ips, ips)

    def test_vif_get_fixed_ips_network_is_none(self):
        vif = model.VIF()
        fixed_ips = vif.fixed_ips()
        self.assertEqual([], fixed_ips)

    def test_vif_get_floating_ips(self):
        vif = fake_network_cache_model.new_vif()
        vif['network']['subnets'][0]['ips'][0].add_floating_ip('192.168.1.1')
        floating_ips = vif.floating_ips()
        self.assertEqual(['192.168.1.1'], floating_ips)

    def test_vif_get_labeled_ips(self):
        vif = fake_network_cache_model.new_vif()
        labeled_ips = vif.labeled_ips()
        ip_dict = {
            'network_id': uuids.network_id,
            'ips': [fake_network_cache_model.new_ip(
                        {'address': '10.10.0.2', 'type': 'fixed'}),
                    fake_network_cache_model.new_ip(
                        {'address': '10.10.0.3', 'type': 'fixed'})] * 2,
            'network_label': 'public'}
        self.assertEqual(ip_dict, labeled_ips)

    def test_hydrate(self):
        vif = model.VIF.hydrate(fake_network_cache_model.new_vif())
        self.assertEqual(uuids.vif_id, vif['id'])
        self.assertEqual('aa:aa:aa:aa:aa:aa', vif['address'])
        self.assertEqual(fake_network_cache_model.new_network(),
                         vif['network'])

    def test_hydrate_vif_with_type(self):
        vif_dict = dict(
            id=uuids.vif_id,
            address='aa:aa:aa:aa:aa:aa',
            network=fake_network_cache_model.new_network(),
            type='bridge')
        vif = model.VIF.hydrate(fake_network_cache_model.new_vif(vif_dict))
        self.assertEqual(uuids.vif_id, vif['id'])
        self.assertEqual('aa:aa:aa:aa:aa:aa', vif['address'])
        self.assertEqual('bridge', vif['type'])
        self.assertEqual(fake_network_cache_model.new_network(),
                         vif['network'])


class NetworkInfoTests(test.NoDBTestCase):
    def test_create_model(self):
        ninfo = model.NetworkInfo([fake_network_cache_model.new_vif(),
                fake_network_cache_model.new_vif(
                    {'address': 'bb:bb:bb:bb:bb:bb'})])
        self.assertEqual(
                [fake_network_cache_model.new_fixed_ip(
                     {'address': '10.10.0.2'}),
                 fake_network_cache_model.new_fixed_ip(
                    {'address': '10.10.0.3'})] * 4, ninfo.fixed_ips())

    def test_create_async_model(self):
        def async_wrapper():
            return model.NetworkInfo(
                    [fake_network_cache_model.new_vif(),
                     fake_network_cache_model.new_vif(
                            {'address': 'bb:bb:bb:bb:bb:bb'})])

        ninfo = model.NetworkInfoAsyncWrapper(async_wrapper)
        self.assertEqual(
                [fake_network_cache_model.new_fixed_ip(
                    {'address': '10.10.0.2'}),
                 fake_network_cache_model.new_fixed_ip(
                    {'address': '10.10.0.3'})] * 4, ninfo.fixed_ips())

    def test_create_async_model_exceptions(self):
        def async_wrapper():
            raise test.TestingException()

        ninfo = model.NetworkInfoAsyncWrapper(async_wrapper)
        self.assertRaises(test.TestingException, ninfo.wait)
        # 2nd one doesn't raise
        self.assertIsNone(ninfo.wait())
        # Test that do_raise=False works on .wait()
        ninfo = model.NetworkInfoAsyncWrapper(async_wrapper)
        self.assertIsNone(ninfo.wait(do_raise=False))
        # Test we also raise calling a method
        ninfo = model.NetworkInfoAsyncWrapper(async_wrapper)
        self.assertRaises(test.TestingException, ninfo.fixed_ips)

    def test_get_floating_ips(self):
        vif = fake_network_cache_model.new_vif()
        vif['network']['subnets'][0]['ips'][0].add_floating_ip('192.168.1.1')
        ninfo = model.NetworkInfo([vif,
                fake_network_cache_model.new_vif(
                    {'address': 'bb:bb:bb:bb:bb:bb'})])
        self.assertEqual(['192.168.1.1'], ninfo.floating_ips())

    def test_hydrate(self):
        ninfo = model.NetworkInfo([fake_network_cache_model.new_vif(),
                fake_network_cache_model.new_vif(
                        {'address': 'bb:bb:bb:bb:bb:bb'})])
        model.NetworkInfo.hydrate(ninfo)
        self.assertEqual(
                [fake_network_cache_model.new_fixed_ip(
                    {'address': '10.10.0.2'}),
                 fake_network_cache_model.new_fixed_ip(
                        {'address': '10.10.0.3'})] * 4, ninfo.fixed_ips())

    def _setup_injected_network_scenario(self, should_inject=True,
                                        use_ipv4=True, use_ipv6=False,
                                        gateway=True, dns=True,
                                        two_interfaces=False,
                                        libvirt_virt_type=None):
        """Check that netutils properly decides whether to inject based on
           whether the supplied subnet is static or dynamic.
        """
        network = fake_network_cache_model.new_network({'subnets': []})

        subnet_dict = {}
        if not gateway:
            subnet_dict['gateway'] = None

        if not dns:
            subnet_dict['dns'] = None

        if not should_inject:
            subnet_dict['dhcp_server'] = '10.10.0.1'

        if use_ipv4:
            network.add_subnet(
                fake_network_cache_model.new_subnet(subnet_dict))

        if should_inject and use_ipv6:
            gateway_ip = fake_network_cache_model.new_ip(dict(
                address='1234:567::1'))
            ip = fake_network_cache_model.new_ip(dict(
                address='1234:567::2'))
            ipv6_subnet_dict = dict(
                cidr='1234:567::/48',
                gateway=gateway_ip,
                dns=[fake_network_cache_model.new_ip(
                        dict(address='2001:4860:4860::8888')),
                     fake_network_cache_model.new_ip(
                         dict(address='2001:4860:4860::8844'))],
                ips=[ip])
            if not gateway:
                ipv6_subnet_dict['gateway'] = None
            network.add_subnet(fake_network_cache_model.new_subnet(
                ipv6_subnet_dict))

        # Behave as though CONF.flat_injected is True
        network['meta']['injected'] = True
        vif = fake_network_cache_model.new_vif({'network': network})
        vifs = [vif]
        if two_interfaces:
            vifs.append(vif)

        nwinfo = model.NetworkInfo(vifs)
        return netutils.get_injected_network_template(
            nwinfo, libvirt_virt_type=libvirt_virt_type)

    def test_injection_dynamic(self):
        expected = None
        template = self._setup_injected_network_scenario(should_inject=False)
        self.assertEqual(expected, template)

    def test_injection_static(self):
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    gateway 10.10.0.1
    dns-nameservers 1.2.3.4 2.3.4.5
"""
        template = self._setup_injected_network_scenario()
        self.assertEqual(expected, template)

    def test_injection_static_no_gateway(self):
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    dns-nameservers 1.2.3.4 2.3.4.5
"""
        template = self._setup_injected_network_scenario(gateway=False)
        self.assertEqual(expected, template)

    def test_injection_static_no_dns(self):
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    gateway 10.10.0.1
"""
        template = self._setup_injected_network_scenario(dns=False)
        self.assertEqual(expected, template)

    def test_injection_static_overridden_template(self):
        cfg.CONF.set_override(
            'injected_network_template',
            'nova/tests/unit/network/interfaces-override.template')
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    gateway 10.10.0.1
    dns-nameservers 1.2.3.4 2.3.4.5
    post-up ip route add 0.0.0.0/24 via 192.168.1.1 dev eth0
    pre-down ip route del 0.0.0.0/24 via 192.168.1.1 dev eth0
"""
        template = self._setup_injected_network_scenario()
        self.assertEqual(expected, template)

    def test_injection_static_ipv6(self):
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    gateway 10.10.0.1
    dns-nameservers 1.2.3.4 2.3.4.5
iface eth0 inet6 static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 1234:567::2
    netmask 48
    gateway 1234:567::1
    dns-nameservers 2001:4860:4860::8888 2001:4860:4860::8844
"""
        template = self._setup_injected_network_scenario(use_ipv6=True)
        self.assertEqual(expected, template)

    def test_injection_static_ipv6_no_gateway(self):
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    dns-nameservers 1.2.3.4 2.3.4.5
iface eth0 inet6 static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 1234:567::2
    netmask 48
    dns-nameservers 2001:4860:4860::8888 2001:4860:4860::8844
"""
        template = self._setup_injected_network_scenario(use_ipv6=True,
                                                         gateway=False)
        self.assertEqual(expected, template)

    def test_injection_static_with_ipv4_off(self):
        expected = None
        template = self._setup_injected_network_scenario(use_ipv4=False)
        self.assertEqual(expected, template)

    def test_injection_ipv6_two_interfaces(self):
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    gateway 10.10.0.1
    dns-nameservers 1.2.3.4 2.3.4.5
iface eth0 inet6 static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 1234:567::2
    netmask 48
    gateway 1234:567::1
    dns-nameservers 2001:4860:4860::8888 2001:4860:4860::8844

auto eth1
iface eth1 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    gateway 10.10.0.1
    dns-nameservers 1.2.3.4 2.3.4.5
iface eth1 inet6 static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 1234:567::2
    netmask 48
    gateway 1234:567::1
    dns-nameservers 2001:4860:4860::8888 2001:4860:4860::8844
"""
        template = self._setup_injected_network_scenario(use_ipv6=True,
                                                         two_interfaces=True)
        self.assertEqual(expected, template)

    def test_injection_ipv6_with_lxc(self):
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    gateway 10.10.0.1
    dns-nameservers 1.2.3.4 2.3.4.5
    post-up ip -6 addr add 1234:567::2/48 dev ${IFACE}
    post-up ip -6 route add default via 1234:567::1 dev ${IFACE}

auto eth1
iface eth1 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    gateway 10.10.0.1
    dns-nameservers 1.2.3.4 2.3.4.5
    post-up ip -6 addr add 1234:567::2/48 dev ${IFACE}
    post-up ip -6 route add default via 1234:567::1 dev ${IFACE}
"""
        template = self._setup_injected_network_scenario(
                use_ipv6=True, two_interfaces=True, libvirt_virt_type='lxc')
        self.assertEqual(expected, template)

    def test_injection_ipv6_with_lxc_no_gateway(self):
        expected = """\
# Injected by Nova on instance boot
#
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

# The loopback network interface
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    dns-nameservers 1.2.3.4 2.3.4.5
    post-up ip -6 addr add 1234:567::2/48 dev ${IFACE}

auto eth1
iface eth1 inet static
    hwaddress ether aa:aa:aa:aa:aa:aa
    address 10.10.0.2
    netmask 255.255.255.0
    broadcast 10.10.0.255
    dns-nameservers 1.2.3.4 2.3.4.5
    post-up ip -6 addr add 1234:567::2/48 dev ${IFACE}
"""
        template = self._setup_injected_network_scenario(
                use_ipv6=True, gateway=False, two_interfaces=True,
                libvirt_virt_type='lxc')
        self.assertEqual(expected, template)

    def test_get_events(self):
        network_info = model.NetworkInfo([
            model.VIF(
                id=uuids.hybrid_vif,
                details={'ovs_hybrid_plug': True}),
            model.VIF(
                id=uuids.normal_vif,
                details={'ovs_hybrid_plug': False})])
        same_host = objects.Migration(source_compute='fake-host',
                                      dest_compute='fake-host')
        diff_host = objects.Migration(source_compute='fake-host1',
                                      dest_compute='fake-host2')
        # Same-host migrations will have all events be plug-time.
        self.assertCountEqual(
            [('network-vif-plugged', uuids.normal_vif),
             ('network-vif-plugged', uuids.hybrid_vif)],
            network_info.get_plug_time_events(same_host))
        # Same host migration will have no plug-time events.
        self.assertEqual([], network_info.get_bind_time_events(same_host))
        # Diff-host migration + OVS hybrid plug = bind-time events
        self.assertEqual(
            [('network-vif-plugged', uuids.hybrid_vif)],
            network_info.get_bind_time_events(diff_host))
        # Diff-host migration + normal OVS = plug-time events
        self.assertEqual(
            [('network-vif-plugged', uuids.normal_vif)],
            network_info.get_plug_time_events(diff_host))

    def test_has_port_with_allocation(self):
        network_info = model.NetworkInfo([])
        self.assertFalse(network_info.has_port_with_allocation())

        network_info.append(
            model.VIF(id=uuids.port_without_profile))
        self.assertFalse(network_info.has_port_with_allocation())

        network_info.append(
            model.VIF(id=uuids.port_no_allocation, profile={'foo': 'bar'}))
        self.assertFalse(network_info.has_port_with_allocation())

        network_info.append(
            model.VIF(
                id=uuids.port_empty_alloc, profile={'allocation': None}))
        self.assertFalse(network_info.has_port_with_allocation())

        network_info.append(
            model.VIF(
                id=uuids.port_with_alloc, profile={'allocation': uuids.rp}))
        self.assertTrue(network_info.has_port_with_allocation())


class TestNetworkMetadata(test.NoDBTestCase):
    def setUp(self):
        super(TestNetworkMetadata, self).setUp()
        self.netinfo = self._new_netinfo()

    def _new_netinfo(self, vif_type='ethernet'):
        netinfo = model.NetworkInfo([fake_network_cache_model.new_vif(
            {'type': vif_type})])

        # Give this vif ipv4 and ipv6 dhcp subnets
        ipv4_subnet = fake_network_cache_model.new_subnet(version=4)
        ipv6_subnet = fake_network_cache_model.new_subnet(version=6)

        netinfo[0]['network']['subnets'][0] = ipv4_subnet
        netinfo[0]['network']['subnets'][1] = ipv6_subnet
        netinfo[0]['network']['meta']['mtu'] = 1500
        return netinfo

    def test_get_network_metadata_json(self):

        net_metadata = netutils.get_network_metadata(self.netinfo)

        # Physical Ethernet
        self.assertEqual(
            {
                'id': 'interface0',
                'type': 'phy',
                'ethernet_mac_address': 'aa:aa:aa:aa:aa:aa',
                'vif_id': uuids.vif_id,
                'mtu': 1500
            },
            net_metadata['links'][0])

        # IPv4 Network
        self.assertEqual(
            {
                'id': 'network0',
                'link': 'interface0',
                'type': 'ipv4',
                'ip_address': '10.10.0.2',
                'netmask': '255.255.255.0',
                'routes': [
                    {
                        'network': '0.0.0.0',
                        'netmask': '0.0.0.0',
                        'gateway': '10.10.0.1'
                    },
                    {
                        'network': '0.0.0.0',
                        'netmask': '255.255.255.0',
                        'gateway': '192.168.1.1'
                    }
                ],
                'services': [{'address': '1.2.3.4', 'type': 'dns'},
                             {'address': '2.3.4.5', 'type': 'dns'}],
                'network_id': uuids.network_id
            },
            net_metadata['networks'][0])

        self.assertEqual(
            {
                'id': 'network1',
                'link': 'interface0',
                'type': 'ipv6',
                'ip_address': 'fd00::2',
                'netmask': 'ffff:ffff:ffff::',
                'routes': [
                    {
                        'network': '::',
                        'netmask': '::',
                        'gateway': 'fd00::1'
                    },
                    {
                        'network': '::',
                        'netmask': 'ffff:ffff:ffff::',
                        'gateway': 'fd00::1:1'
                    }
                ],
                'services': [{'address': '1:2:3:4::', 'type': 'dns'},
                             {'address': '2:3:4:5::', 'type': 'dns'}],
                'network_id': uuids.network_id
            },
            net_metadata['networks'][1])

    def test_get_network_metadata_json_dhcp(self):
        ipv4_subnet = fake_network_cache_model.new_subnet(
            subnet_dict=dict(dhcp_server='1.1.1.1'), version=4)
        ipv6_subnet = fake_network_cache_model.new_subnet(
            subnet_dict=dict(dhcp_server='1234:567::'), version=6)

        self.netinfo[0]['network']['subnets'][0] = ipv4_subnet
        self.netinfo[0]['network']['subnets'][1] = ipv6_subnet
        net_metadata = netutils.get_network_metadata(self.netinfo)

        # IPv4 Network
        self.assertEqual(
            {
                'id': 'network0',
                'link': 'interface0',
                'type': 'ipv4_dhcp',
                'network_id': uuids.network_id
            },
            net_metadata['networks'][0])

        # IPv6 Network
        self.assertEqual(
            {
                'id': 'network1',
                'link': 'interface0',
                'type': 'ipv6_dhcp',
                'network_id': uuids.network_id
            },
            net_metadata['networks'][1])

    def _test_get_network_metadata_json_ipv6_addr_mode(self, mode):
        ipv6_subnet = fake_network_cache_model.new_subnet(
            subnet_dict=dict(dhcp_server='1234:567::',
                             ipv6_address_mode=mode), version=6)

        self.netinfo[0]['network']['subnets'][1] = ipv6_subnet
        net_metadata = netutils.get_network_metadata(self.netinfo)

        self.assertEqual(
            {
                'id': 'network1',
                'link': 'interface0',
                'ip_address': 'fd00::2',
                'netmask': 'ffff:ffff:ffff::',
                'routes': [
                    {
                        'network': '::',
                        'netmask': '::',
                        'gateway': 'fd00::1'
                    },
                    {
                        'network': '::',
                        'netmask': 'ffff:ffff:ffff::',
                        'gateway': 'fd00::1:1'
                    }
                ],
                'services': [
                    {'address': '1:2:3:4::', 'type': 'dns'},
                    {'address': '2:3:4:5::', 'type': 'dns'}
                ],
                'type': 'ipv6_%s' % mode,
                'network_id': uuids.network_id
            },
            net_metadata['networks'][1])

    def test_get_network_metadata_json_ipv6_addr_mode_slaac(self):
        self._test_get_network_metadata_json_ipv6_addr_mode('slaac')

    def test_get_network_metadata_json_ipv6_addr_mode_stateful(self):
        self._test_get_network_metadata_json_ipv6_addr_mode('dhcpv6-stateful')

    def test_get_network_metadata_json_ipv6_addr_mode_stateless(self):
        self._test_get_network_metadata_json_ipv6_addr_mode('dhcpv6-stateless')

    def test__get_nets(self):
        expected_net = {
            'id': 'network0',
            'ip_address': '10.10.0.2',
            'link': 1,
            'netmask': '255.255.255.0',
            'network_id': uuids.network_id,
            'routes': [
                {
                    'gateway': '10.10.0.1',
                    'netmask': '0.0.0.0',
                    'network': '0.0.0.0'},
                {
                    'gateway': '192.168.1.1',
                    'netmask': '255.255.255.0',
                    'network': '0.0.0.0'}],
                'services': [
                    {'address': '1.2.3.4', 'type': 'dns'},
                    {'address': '2.3.4.5', 'type': 'dns'}
                ],
            'type': 'ipv4'
        }
        net = netutils._get_nets(
            self.netinfo[0], self.netinfo[0]['network']['subnets'][0], 4, 0, 1)
        self.assertEqual(expected_net, net)

    def test__get_eth_link(self):
        expected_link = {
            'id': 'interface0',
            'vif_id': uuids.vif_id,
            'type': 'vif',
            'ethernet_mac_address': 'aa:aa:aa:aa:aa:aa',
            'mtu': 1500
        }
        self.netinfo[0]['type'] = 'vif'
        link = netutils._get_eth_link(self.netinfo[0], 0)
        self.assertEqual(expected_link, link)

    def test__get_eth_link_physical(self):
        expected_link = {
            'id': 'interface1',
            'vif_id': uuids.vif_id,
            'type': 'phy',
            'ethernet_mac_address': 'aa:aa:aa:aa:aa:aa',
            'mtu': 1500
        }
        link = netutils._get_eth_link(self.netinfo[0], 1)
        self.assertEqual(expected_link, link)

    def test__get_default_route(self):
        v4_expected = [{
            'network': '0.0.0.0',
            'netmask': '0.0.0.0',
            'gateway': '10.10.0.1',
        }]
        v6_expected = [{
            'network': '::',
            'netmask': '::',
            'gateway': 'fd00::1'
        }]
        v4 = netutils._get_default_route(
            4, self.netinfo[0]['network']['subnets'][0])
        self.assertEqual(v4_expected, v4)

        v6 = netutils._get_default_route(
            6, self.netinfo[0]['network']['subnets'][1])
        self.assertEqual(v6_expected, v6)

        # Test for no gateway
        self.netinfo[0]['network']['subnets'][0]['gateway'] = None
        no_route = netutils._get_default_route(
            4, self.netinfo[0]['network']['subnets'][0])
        self.assertEqual([], no_route)

    def test__get_dns_services(self):
        expected_dns = [
            {'type': 'dns', 'address': '1.2.3.4'},
            {'type': 'dns', 'address': '2.3.4.5'},
            {'type': 'dns', 'address': '3.4.5.6'}
        ]
        subnet = fake_network_cache_model.new_subnet(version=4)
        subnet['dns'].append(fake_network_cache_model.new_ip(
            {'address': '3.4.5.6'}))
        dns = netutils._get_dns_services(subnet)
        self.assertEqual(expected_dns, dns)

    def test_get_network_metadata(self):
        expected_json = {
            "links": [
                {
                    "ethernet_mac_address": "aa:aa:aa:aa:aa:aa",
                    "id": "interface0",
                    "type": "phy",
                    "vif_id": uuids.vif_id,
                    "mtu": 1500
                },
                {
                    "ethernet_mac_address": "aa:aa:aa:aa:aa:ab",
                    "id": "interface1",
                    "type": "phy",
                    "vif_id": uuids.vif_id,
                    "mtu": 1500
                },
            ],
            "networks": [
                {
                    "id": "network0",
                    "ip_address": "10.10.0.2",
                    "link": "interface0",
                    "netmask": "255.255.255.0",
                    "network_id":
                        "00000000-0000-0000-0000-000000000000",
                    "routes": [
                        {
                            "gateway": "10.10.0.1",
                            "netmask": "0.0.0.0",
                            "network": "0.0.0.0"
                        },
                        {
                            "gateway": "192.168.1.1",
                            "netmask": "255.255.255.0",
                            "network": "0.0.0.0"
                        }
                    ],
                   'services': [{'address': '1.2.3.4', 'type': 'dns'},
                                {'address': '2.3.4.5', 'type': 'dns'}],
                    "type": "ipv4"
                },
                {
                   'id': 'network1',
                   'ip_address': 'fd00::2',
                   'link': 'interface0',
                   'netmask': 'ffff:ffff:ffff::',
                   'network_id': '00000000-0000-0000-0000-000000000000',
                   'routes': [{'gateway': 'fd00::1',
                               'netmask': '::',
                               'network': '::'},
                              {'gateway': 'fd00::1:1',
                               'netmask': 'ffff:ffff:ffff::',
                               'network': '::'}],
                   'services': [{'address': '1:2:3:4::', 'type': 'dns'},
                                {'address': '2:3:4:5::', 'type': 'dns'}],
                   'type': 'ipv6'
                },
                {
                    "id": "network2",
                    "ip_address": "192.168.0.2",
                    "link": "interface1",
                    "netmask": "255.255.255.0",
                    "network_id":
                        "11111111-1111-1111-1111-111111111111",
                    "routes": [
                        {
                            "gateway": "192.168.0.1",
                            "netmask": "0.0.0.0",
                            "network": "0.0.0.0"
                        }
                    ],
                   'services': [{'address': '1.2.3.4', 'type': 'dns'},
                                {'address': '2.3.4.5', 'type': 'dns'}],
                    "type": "ipv4"
                }
            ],
            'services': [
                {'address': '1.2.3.4', 'type': 'dns'},
                {'address': '2.3.4.5', 'type': 'dns'},
                {'address': '1:2:3:4::', 'type': 'dns'},
                {'address': '2:3:4:5::', 'type': 'dns'}
            ]
        }

        self.netinfo[0]['network']['id'] = (
            '00000000-0000-0000-0000-000000000000')

        # Add a second NIC
        self.netinfo.append(fake_network_cache_model.new_vif({
            'type': 'ethernet', 'address': 'aa:aa:aa:aa:aa:ab'}))

        address = fake_network_cache_model.new_ip({'address': '192.168.0.2'})
        gateway_address = fake_network_cache_model.new_ip(
            {'address': '192.168.0.1'})

        ipv4_subnet = fake_network_cache_model.new_subnet(
            {'cidr': '192.168.0.0/24', 'gateway': gateway_address,
             'ips': [address], 'routes': []})

        self.netinfo[1]['network']['id'] = (
            '11111111-1111-1111-1111-111111111111')

        self.netinfo[1]['network']['subnets'][0] = ipv4_subnet
        self.netinfo[1]['network']['meta']['mtu'] = 1500

        network_json = netutils.get_network_metadata(self.netinfo)
        self.assertEqual(expected_json, network_json)

    def test_get_network_metadata_no_ipv4(self):
        expected_json = {
            "services": [
                {
                    "type": "dns",
                    "address": "1:2:3:4::"
                },
                {
                    "type": "dns",
                    "address": "2:3:4:5::"
                }
            ],
            "networks": [
                {
                    "network_id": uuids.network_id,
                    "type": "ipv6",
                    "netmask": "ffff:ffff:ffff::",
                    "link": "interface0",
                    "routes": [
                        {
                            "netmask": "::",
                            "network": "::",
                            "gateway": "fd00::1"
                        },
                        {
                            "netmask": "ffff:ffff:ffff::",
                            "network": "::",
                            "gateway": "fd00::1:1"
                        }
                    ],
                   'services': [{'address': '1:2:3:4::', 'type': 'dns'},
                                {'address': '2:3:4:5::', 'type': 'dns'}],
                    "ip_address": "fd00::2",
                    "id": "network0"
                }
            ],
            "links": [
                {
                    "ethernet_mac_address": "aa:aa:aa:aa:aa:aa",
                    "mtu": 1500,
                    "type": "phy",
                    "id": "interface0",
                    "vif_id": uuids.vif_id
                }
            ]
        }

        # drop the ipv4 subnet
        self.netinfo[0]['network']['subnets'].pop(0)
        network_json = netutils.get_network_metadata(self.netinfo)
        self.assertEqual(expected_json, network_json)

    def test_legacy_vif_types_type_passed_through(self):
        legacy_types = [
            model.VIF_TYPE_BRIDGE,
            model.VIF_TYPE_DVS,
            model.VIF_TYPE_HW_VEB,
            model.VIF_TYPE_HYPERV,
            model.VIF_TYPE_OVS,
            model.VIF_TYPE_TAP,
            model.VIF_TYPE_VHOSTUSER,
            model.VIF_TYPE_VIF,
        ]
        link_types = []
        for vif_type in legacy_types:
            network_json = netutils.get_network_metadata(
                self._new_netinfo(vif_type=vif_type))
            link_types.append(network_json["links"][0]["type"])

        self.assertEqual(legacy_types, link_types)

    def test_new_vif_types_get_type_phy(self):
        new_types = ["whizbang_nvf", "vswitch9"]
        link_types = []
        for vif_type in new_types:
            network_json = netutils.get_network_metadata(
                self._new_netinfo(vif_type=vif_type))
            link_types.append(network_json["links"][0]["type"])

        self.assertEqual(["phy"] * len(new_types), link_types)
