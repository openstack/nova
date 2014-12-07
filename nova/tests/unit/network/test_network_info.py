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

from nova import exception
from nova.network import model
from nova import test
from nova.tests.unit import fake_network_cache_model
from nova.virt import netutils


class RouteTests(test.NoDBTestCase):
    def test_create_route_with_attrs(self):
        route = fake_network_cache_model.new_route()
        fake_network_cache_model.new_ip(dict(address='192.168.1.1'))
        self.assertEqual(route['cidr'], '0.0.0.0/24')
        self.assertEqual(route['gateway']['address'], '192.168.1.1')
        self.assertEqual(route['interface'], 'eth0')

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
        self.assertEqual(route['gateway']['address'], '192.168.1.1')
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
        self.assertEqual(fixed_ip['address'], '192.168.1.100')
        self.assertEqual(fixed_ip['floating_ips'], [])
        self.assertEqual(fixed_ip['type'], 'fixed')
        self.assertEqual(fixed_ip['version'], 4)

    def test_create_fixed_ipv6(self):
        fixed_ip = model.FixedIP(address='::1')
        self.assertEqual(fixed_ip['address'], '::1')
        self.assertEqual(fixed_ip['floating_ips'], [])
        self.assertEqual(fixed_ip['type'], 'fixed')
        self.assertEqual(fixed_ip['version'], 6)

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
        self.assertEqual(fixed_ip['floating_ips'], [])
        self.assertIsNone(fixed_ip['address'])
        self.assertEqual(fixed_ip['type'], 'fixed')
        self.assertIsNone(fixed_ip['version'])

    def test_add_floating_ip(self):
        fixed_ip = model.FixedIP(address='192.168.1.100')
        fixed_ip.add_floating_ip('192.168.1.101')
        self.assertEqual(fixed_ip['floating_ips'], ['192.168.1.101'])

    def test_add_floating_ip_repeatedly_only_one_instance(self):
        fixed_ip = model.FixedIP(address='192.168.1.100')
        for i in xrange(10):
            fixed_ip.add_floating_ip('192.168.1.101')
        self.assertEqual(fixed_ip['floating_ips'], ['192.168.1.101'])


class SubnetTests(test.NoDBTestCase):
    def test_create_subnet_with_attrs(self):
        subnet = fake_network_cache_model.new_subnet()

        route1 = fake_network_cache_model.new_route()

        self.assertEqual(subnet['cidr'], '10.10.0.0/24')
        self.assertEqual(subnet['dns'],
                [fake_network_cache_model.new_ip(dict(address='1.2.3.4')),
                 fake_network_cache_model.new_ip(dict(address='2.3.4.5'))])
        self.assertEqual(subnet['gateway']['address'], '10.10.0.1')
        self.assertEqual(subnet['ips'],
                [fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.2')),
                 fake_network_cache_model.new_fixed_ip(
                            dict(address='10.10.0.3'))])
        self.assertEqual(subnet['routes'], [route1])
        self.assertEqual(subnet['version'], 4)

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
        self.assertEqual(subnet['routes'], [route1, route2])

    def test_add_route_a_lot(self):
        subnet = fake_network_cache_model.new_subnet()
        route1 = fake_network_cache_model.new_route()
        route2 = fake_network_cache_model.new_route({'cidr': '1.1.1.1/24'})
        for i in xrange(10):
            subnet.add_route(route2)
        self.assertEqual(subnet['routes'], [route1, route2])

    def test_add_dns(self):
        subnet = fake_network_cache_model.new_subnet()
        dns = fake_network_cache_model.new_ip(dict(address='9.9.9.9'))
        subnet.add_dns(dns)
        self.assertEqual(subnet['dns'],
                [fake_network_cache_model.new_ip(dict(address='1.2.3.4')),
                 fake_network_cache_model.new_ip(dict(address='2.3.4.5')),
                 fake_network_cache_model.new_ip(dict(address='9.9.9.9'))])

    def test_add_dns_a_lot(self):
        subnet = fake_network_cache_model.new_subnet()
        for i in xrange(10):
            subnet.add_dns(fake_network_cache_model.new_ip(
                    dict(address='9.9.9.9')))
        self.assertEqual(subnet['dns'],
                [fake_network_cache_model.new_ip(dict(address='1.2.3.4')),
                 fake_network_cache_model.new_ip(dict(address='2.3.4.5')),
                 fake_network_cache_model.new_ip(dict(address='9.9.9.9'))])

    def test_add_ip(self):
        subnet = fake_network_cache_model.new_subnet()
        subnet.add_ip(fake_network_cache_model.new_ip(
                dict(address='192.168.1.102')))
        self.assertEqual(subnet['ips'],
                [fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.2')),
                 fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.3')),
                 fake_network_cache_model.new_ip(
                        dict(address='192.168.1.102'))])

    def test_add_ip_a_lot(self):
        subnet = fake_network_cache_model.new_subnet()
        for i in xrange(10):
            subnet.add_ip(fake_network_cache_model.new_fixed_ip(
                        dict(address='192.168.1.102')))
        self.assertEqual(subnet['ips'],
                [fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.2')),
                 fake_network_cache_model.new_fixed_ip(
                        dict(address='10.10.0.3')),
                 fake_network_cache_model.new_fixed_ip(
                        dict(address='192.168.1.102'))])

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

        self.assertEqual(subnet['cidr'], '255.255.255.0')
        self.assertEqual(subnet['dns'], [fake_network_cache_model.new_ip(
                                         dict(address='1.1.1.1'))])
        self.assertEqual(subnet['gateway']['address'], '3.3.3.3')
        self.assertEqual(subnet['ips'], [fake_network_cache_model.new_fixed_ip(
                                         dict(address='2.2.2.2'))])
        self.assertEqual(subnet['routes'], [
                    fake_network_cache_model.new_route()])
        self.assertEqual(subnet['version'], 4)


class NetworkTests(test.NoDBTestCase):
    def test_create_network(self):
        network = fake_network_cache_model.new_network()
        self.assertEqual(network['id'], 1)
        self.assertEqual(network['bridge'], 'br0')
        self.assertEqual(network['label'], 'public')
        self.assertEqual(network['subnets'],
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255'))])

    def test_add_subnet(self):
        network = fake_network_cache_model.new_network()
        network.add_subnet(fake_network_cache_model.new_subnet(
                    dict(cidr='0.0.0.0')))
        self.assertEqual(network['subnets'],
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255')),
                 fake_network_cache_model.new_subnet(dict(cidr='0.0.0.0'))])

    def test_add_subnet_a_lot(self):
        network = fake_network_cache_model.new_network()
        for i in xrange(10):
            network.add_subnet(fake_network_cache_model.new_subnet(
                    dict(cidr='0.0.0.0')))
        self.assertEqual(network['subnets'],
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255')),
                 fake_network_cache_model.new_subnet(dict(cidr='0.0.0.0'))])

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
        fake_network_cache_model.new_subnet()
        fake_network_cache_model.new_subnet(dict(cidr='255.255.255.255'))
        network = model.Network.hydrate(fake_network_cache_model.new_network())

        self.assertEqual(network['id'], 1)
        self.assertEqual(network['bridge'], 'br0')
        self.assertEqual(network['label'], 'public')
        self.assertEqual(network['subnets'],
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255'))])


class VIFTests(test.NoDBTestCase):
    def test_create_vif(self):
        vif = fake_network_cache_model.new_vif()
        self.assertEqual(vif['id'], 1)
        self.assertEqual(vif['address'], 'aa:aa:aa:aa:aa:aa')
        self.assertEqual(vif['network'],
                fake_network_cache_model.new_network())

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

    def test_create_vif_with_type(self):
        vif_dict = dict(
            id=1,
            address='aa:aa:aa:aa:aa:aa',
            network=fake_network_cache_model.new_network(),
            type='bridge')
        vif = fake_network_cache_model.new_vif(vif_dict)
        self.assertEqual(vif['id'], 1)
        self.assertEqual(vif['address'], 'aa:aa:aa:aa:aa:aa')
        self.assertEqual(vif['type'], 'bridge')
        self.assertEqual(vif['network'],
                fake_network_cache_model.new_network())

    def test_vif_get_fixed_ips(self):
        vif = fake_network_cache_model.new_vif()
        fixed_ips = vif.fixed_ips()
        ips = [
            fake_network_cache_model.new_fixed_ip(dict(address='10.10.0.2')),
            fake_network_cache_model.new_fixed_ip(dict(address='10.10.0.3'))
        ] * 2
        self.assertEqual(fixed_ips, ips)

    def test_vif_get_floating_ips(self):
        vif = fake_network_cache_model.new_vif()
        vif['network']['subnets'][0]['ips'][0].add_floating_ip('192.168.1.1')
        floating_ips = vif.floating_ips()
        self.assertEqual(floating_ips, ['192.168.1.1'])

    def test_vif_get_labeled_ips(self):
        vif = fake_network_cache_model.new_vif()
        labeled_ips = vif.labeled_ips()
        ip_dict = {
            'network_id': 1,
            'ips': [fake_network_cache_model.new_ip(
                        {'address': '10.10.0.2', 'type': 'fixed'}),
                    fake_network_cache_model.new_ip(
                        {'address': '10.10.0.3', 'type': 'fixed'})] * 2,
            'network_label': 'public'}
        self.assertEqual(labeled_ips, ip_dict)

    def test_hydrate(self):
        fake_network_cache_model.new_network()
        vif = model.VIF.hydrate(fake_network_cache_model.new_vif())
        self.assertEqual(vif['id'], 1)
        self.assertEqual(vif['address'], 'aa:aa:aa:aa:aa:aa')
        self.assertEqual(vif['network'],
                fake_network_cache_model.new_network())

    def test_hydrate_vif_with_type(self):
        vif_dict = dict(
            id=1,
            address='aa:aa:aa:aa:aa:aa',
            network=fake_network_cache_model.new_network(),
            type='bridge')
        vif = model.VIF.hydrate(fake_network_cache_model.new_vif(vif_dict))
        self.assertEqual(vif['id'], 1)
        self.assertEqual(vif['address'], 'aa:aa:aa:aa:aa:aa')
        self.assertEqual(vif['type'], 'bridge')
        self.assertEqual(vif['network'],
                fake_network_cache_model.new_network())


class NetworkInfoTests(test.NoDBTestCase):
    def test_create_model(self):
        ninfo = model.NetworkInfo([fake_network_cache_model.new_vif(),
                fake_network_cache_model.new_vif(
                    {'address': 'bb:bb:bb:bb:bb:bb'})])
        self.assertEqual(ninfo.fixed_ips(),
                [fake_network_cache_model.new_fixed_ip(
                     {'address': '10.10.0.2'}),
                 fake_network_cache_model.new_fixed_ip(
                    {'address': '10.10.0.3'})] * 4)

    def test_create_async_model(self):
        def async_wrapper():
            return model.NetworkInfo(
                    [fake_network_cache_model.new_vif(),
                     fake_network_cache_model.new_vif(
                            {'address': 'bb:bb:bb:bb:bb:bb'})])

        ninfo = model.NetworkInfoAsyncWrapper(async_wrapper)
        self.assertEqual(ninfo.fixed_ips(),
                [fake_network_cache_model.new_fixed_ip(
                    {'address': '10.10.0.2'}),
                 fake_network_cache_model.new_fixed_ip(
                    {'address': '10.10.0.3'})] * 4)

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
        self.assertEqual(ninfo.floating_ips(), ['192.168.1.1'])

    def test_hydrate(self):
        ninfo = model.NetworkInfo([fake_network_cache_model.new_vif(),
                fake_network_cache_model.new_vif(
                        {'address': 'bb:bb:bb:bb:bb:bb'})])
        model.NetworkInfo.hydrate(ninfo)
        self.assertEqual(ninfo.fixed_ips(),
                [fake_network_cache_model.new_fixed_ip(
                    {'address': '10.10.0.2'}),
                 fake_network_cache_model.new_fixed_ip(
                        {'address': '10.10.0.3'})] * 4)

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
                nwinfo, use_ipv6=use_ipv6, libvirt_virt_type=libvirt_virt_type)

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
