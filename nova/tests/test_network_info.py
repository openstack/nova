# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from nova import exception
from nova import log as logging
from nova.network import model
from nova import test
from nova.tests import fake_network_cache_model

LOG = logging.getLogger('nova.tests.network')


class RouteTests(test.TestCase):
    def test_create_route_with_attrs(self):
        route = fake_network_cache_model.new_route()
        ip = fake_network_cache_model.new_ip(dict(address='192.168.1.1'))
        self.assertEqual(route['cidr'], '0.0.0.0/24')
        self.assertEqual(route['gateway']['address'], '192.168.1.1')
        self.assertEqual(route['interface'], 'eth0')

    def test_routes_equal(self):
        route1 = fake_network_cache_model.new_route()
        route2 = fake_network_cache_model.new_route()
        self.assertEqual(route1, route2)

    def test_routes_not_equal(self):
        route1 = fake_network_cache_model.new_route()
        route2 = fake_network_cache_model.new_route(dict(cidr='1.1.1.1/24'))
        self.assertNotEqual(route1, route2)

    def test_hydrate(self):
        route = model.Route.hydrate(
                {'gateway': fake_network_cache_model.new_ip(
                                dict(address='192.168.1.1'))})
        self.assertEqual(route['cidr'], None)
        self.assertEqual(route['gateway']['address'], '192.168.1.1')
        self.assertEqual(route['interface'], None)


class FixedIPTests(test.TestCase):
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

    def test_hydrate(self):
        fixed_ip = model.FixedIP.hydrate({})
        self.assertEqual(fixed_ip['floating_ips'], [])
        self.assertEqual(fixed_ip['address'], None)
        self.assertEqual(fixed_ip['type'], 'fixed')
        self.assertEqual(fixed_ip['version'], None)

    def test_add_floating_ip(self):
        fixed_ip = model.FixedIP(address='192.168.1.100')
        fixed_ip.add_floating_ip('192.168.1.101')
        self.assertEqual(fixed_ip['floating_ips'], ['192.168.1.101'])

    def test_add_floating_ip_repeatedly_only_one_instance(self):
        fixed_ip = model.FixedIP(address='192.168.1.100')
        for i in xrange(10):
            fixed_ip.add_floating_ip('192.168.1.101')
        self.assertEqual(fixed_ip['floating_ips'], ['192.168.1.101'])


class SubnetTests(test.TestCase):
    def test_create_subnet_with_attrs(self):
        subnet = fake_network_cache_model.new_subnet()

        route1 = fake_network_cache_model.new_route()

        self.assertEqual(subnet['cidr'], '255.255.255.0')
        self.assertEqual(subnet['dns'],
                [fake_network_cache_model.new_ip(dict(address='1.2.3.4')),
                 fake_network_cache_model.new_ip(dict(address='2.3.4.5'))])
        self.assertEqual(subnet['gateway']['address'], '192.168.1.1')
        self.assertEqual(subnet['ips'],
                [fake_network_cache_model.new_ip(
                        dict(address='192.168.1.100')),
                 fake_network_cache_model.new_ip(
                            dict(address='192.168.1.101'))])
        self.assertEqual(subnet['routes'], [route1])
        self.assertEqual(subnet['version'], 4)

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
                [fake_network_cache_model.new_ip(
                        dict(address='192.168.1.100')),
                 fake_network_cache_model.new_ip(
                        dict(address='192.168.1.101')),
                 fake_network_cache_model.new_ip(
                        dict(address='192.168.1.102'))])

    def test_add_ip_a_lot(self):
        subnet = fake_network_cache_model.new_subnet()
        for i in xrange(10):
            subnet.add_ip(fake_network_cache_model.new_ip(
                        dict(address='192.168.1.102')))
        self.assertEqual(subnet['ips'],
                [fake_network_cache_model.new_ip(
                        dict(address='192.168.1.100')),
                 fake_network_cache_model.new_ip(
                        dict(address='192.168.1.101')),
                 fake_network_cache_model.new_ip(
                        dict(address='192.168.1.102'))])

    def test_hydrate(self):
        subnet_dict = {
            'cidr': '255.255.255.0',
            'dns': [fake_network_cache_model.new_ip(dict(address='1.1.1.1'))],
            'ips': [fake_network_cache_model.new_ip(dict(address='2.2.2.2'))],
            'routes': [fake_network_cache_model.new_route()],
            'version': 4,
            'gateway': fake_network_cache_model.new_ip(
                            dict(address='3.3.3.3'))}
        subnet = model.Subnet.hydrate(subnet_dict)

        self.assertEqual(subnet['cidr'], '255.255.255.0')
        self.assertEqual(subnet['dns'], [fake_network_cache_model.new_ip(
                                         dict(address='1.1.1.1'))])
        self.assertEqual(subnet['gateway']['address'], '3.3.3.3')
        self.assertEqual(subnet['ips'], [fake_network_cache_model.new_ip(
                                         dict(address='2.2.2.2'))])
        self.assertEqual(subnet['routes'], [
                    fake_network_cache_model.new_route()])
        self.assertEqual(subnet['version'], 4)


class NetworkTests(test.TestCase):
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

    def test_hydrate(self):
        new_network = dict(
            id=1,
            bridge='br0',
            label='public',
            subnets=[fake_network_cache_model.new_subnet(),
                fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255'))])
        network = model.Network.hydrate(fake_network_cache_model.new_network())

        self.assertEqual(network['id'], 1)
        self.assertEqual(network['bridge'], 'br0')
        self.assertEqual(network['label'], 'public')
        self.assertEqual(network['subnets'],
                [fake_network_cache_model.new_subnet(),
                 fake_network_cache_model.new_subnet(
                        dict(cidr='255.255.255.255'))])


class VIFTests(test.TestCase):
    def test_create_vif(self):
        vif = fake_network_cache_model.new_vif()
        self.assertEqual(vif['id'], 1)
        self.assertEqual(vif['address'], 'aa:aa:aa:aa:aa:aa')
        self.assertEqual(vif['network'],
                fake_network_cache_model.new_network())

    def test_vif_get_fixed_ips(self):
        vif = fake_network_cache_model.new_vif()
        fixed_ips = vif.fixed_ips()
        ips = [fake_network_cache_model.new_ip(dict(address='192.168.1.100')),
                fake_network_cache_model.new_ip(
                        dict(address='192.168.1.101'))] * 2
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
                        {'address': '192.168.1.100'}),
                    fake_network_cache_model.new_ip(
                        {'address': '192.168.1.101'})] * 2,
            'network_label': 'public'}
        self.assertEqual(labeled_ips, ip_dict)

    def test_hydrate(self):
        new_vif = dict(
            id=1,
            address='127.0.0.1',
            network=fake_network_cache_model.new_network())
        vif = model.VIF.hydrate(fake_network_cache_model.new_vif())
        self.assertEqual(vif['id'], 1)
        self.assertEqual(vif['address'], 'aa:aa:aa:aa:aa:aa')
        self.assertEqual(vif['network'],
                fake_network_cache_model.new_network())


class NetworkInfoTests(test.TestCase):
    def test_create_model(self):
        ninfo = model.NetworkInfo([fake_network_cache_model.new_vif(),
                fake_network_cache_model.new_vif(
                    {'address':'bb:bb:bb:bb:bb:bb'})])
        self.assertEqual(ninfo.fixed_ips(),
                [fake_network_cache_model.new_ip({'address': '192.168.1.100'}),
                 fake_network_cache_model.new_ip(
                    {'address': '192.168.1.101'})] * 4)

    def test_get_floating_ips(self):
        vif = fake_network_cache_model.new_vif()
        vif['network']['subnets'][0]['ips'][0].add_floating_ip('192.168.1.1')
        ninfo = model.NetworkInfo([vif,
                fake_network_cache_model.new_vif(
                    {'address':'bb:bb:bb:bb:bb:bb'})])
        self.assertEqual(ninfo.floating_ips(), ['192.168.1.1'])

    def test_hydrate(self):
        ninfo = model.NetworkInfo([fake_network_cache_model.new_vif(),
                fake_network_cache_model.new_vif(
                        {'address':'bb:bb:bb:bb:bb:bb'})])
        deserialized = model.NetworkInfo.hydrate(ninfo)
        self.assertEqual(ninfo.fixed_ips(),
                [fake_network_cache_model.new_ip({'address': '192.168.1.100'}),
                 fake_network_cache_model.new_ip(
                        {'address': '192.168.1.101'})] * 4)
