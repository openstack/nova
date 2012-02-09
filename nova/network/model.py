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

import json
import netaddr

from nova import exception


class Model(dict):
    """Defines some necessary structures for most of the network models"""
    def __repr__(self):
        return self.__class__.__name__ + '(' + dict.__repr__(self) + ')'

    def set_meta(self, kwargs):
        # pull meta out of kwargs if it's there
        self['meta'] = kwargs.pop('meta', {})
        # update meta with any additional kwargs that may exist
        self['meta'].update(kwargs)


class IP(Model):
    """Represents an IP address in Nova"""
    def __init__(self, address=None, type=None, **kwargs):
        super(IP, self).__init__()

        self['address'] = address
        self['type'] = type
        self['version'] = kwargs.pop('version', None)

        self.set_meta(kwargs)

        # determine version from address if not passed in
        if self['address'] and not self['version']:
            try:
                self['version'] = netaddr.IPAddress(self['address']).version
            except netaddr.AddrFormatError, e:
                raise exception.InvalidIpAddressError(self['address'])

    def __eq__(self, other):
        return self['address'] == other['address']

    def is_in_subnet(self, subnet):
        if self['address'] and subnet['cidr']:
            return (netaddr.IPAddress(self['address']) in
                    netaddr.IPNetwork(subnet['cidr']))
        else:
            return False

    @classmethod
    def hydrate(cls, ip):
        if ip:
            return IP(**ip)
        return None


class FixedIP(IP):
    """Represents a Fixed IP address in Nova"""
    def __init__(self, floating_ips=None, **kwargs):
        super(FixedIP, self).__init__(**kwargs)
        self['floating_ips'] = floating_ips or []

        if not self['type']:
            self['type'] = 'fixed'

    def add_floating_ip(self, floating_ip):
        if floating_ip not in self['floating_ips']:
            self['floating_ips'].append(floating_ip)

    def floating_ip_addresses(self):
        return [ip['address'] for ip in self['floating_ips']]

    @classmethod
    def hydrate(cls, fixed_ip):
        fixed_ip = FixedIP(**fixed_ip)
        fixed_ip['floating_ips'] = [IP.hydrate(floating_ip)
                                   for floating_ip in fixed_ip['floating_ips']]
        return fixed_ip


class Route(Model):
    """Represents an IP Route in Nova"""
    def __init__(self, cidr=None, gateway=None, interface=None, **kwargs):
        super(Route, self).__init__()

        self['cidr'] = cidr
        self['gateway'] = gateway
        self['interface'] = interface

        self.set_meta(kwargs)

    @classmethod
    def hydrate(cls, route):
        route = Route(**route)
        route['gateway'] = IP.hydrate(route['gateway'])
        return route


class Subnet(Model):
    """Represents a Subnet in Nova"""
    def __init__(self, cidr=None, dns=None, gateway=None, ips=None,
                 routes=None, **kwargs):
        super(Subnet, self).__init__()

        self['cidr'] = cidr
        self['dns'] = dns or []
        self['gateway'] = gateway
        self['ips'] = ips or []
        self['routes'] = routes or []
        self['version'] = kwargs.pop('version', None)

        self.set_meta(kwargs)

        if self['cidr'] and not self['version']:
            self['version'] = netaddr.IPNetwork(self['cidr']).version

    def __eq__(self, other):
        return self['cidr'] == other['cidr']

    def add_route(self, new_route):
        if new_route not in self['routes']:
            self['routes'].append(new_route)

    def add_dns(self, dns):
        if dns not in self['dns']:
            self['dns'].append(dns)

    def add_ip(self, ip):
        if ip not in self['ips']:
            self['ips'].append(ip)

    def as_netaddr(self):
        """Convience function to get cidr as a netaddr object"""
        return netaddr.IPNetwork(self['cidr'])

    @classmethod
    def hydrate(cls, subnet):
        subnet = Subnet(**subnet)
        subnet['dns'] = [IP.hydrate(dns) for dns in subnet['dns']]
        subnet['ips'] = [FixedIP.hydrate(ip) for ip in subnet['ips']]
        subnet['routes'] = [Route.hydrate(route) for route in subnet['routes']]
        subnet['gateway'] = IP.hydrate(subnet['gateway'])
        return subnet


class Network(Model):
    """Represents a Network in Nova"""
    def __init__(self, id=None, bridge=None, label=None,
                 subnets=None, **kwargs):
        super(Network, self).__init__()

        self['id'] = id
        self['bridge'] = bridge
        self['label'] = label
        self['subnets'] = subnets or []

        self.set_meta(kwargs)

    def add_subnet(self, subnet):
        if subnet not in self['subnets']:
            self['subnets'].append(subnet)

    @classmethod
    def hydrate(cls, network):
        if network:
            network = Network(**network)
            network['subnets'] = [Subnet.hydrate(subnet)
                                  for subnet in network['subnets']]
        return network


class VIF(Model):
    """Represents a Virtual Interface in Nova"""
    def __init__(self, id=None, address=None, network=None, **kwargs):
        super(VIF, self).__init__()

        self['id'] = id
        self['address'] = address
        self['network'] = network or None

        self.set_meta(kwargs)

    def __eq__(self, other):
        return self['id'] == other['id']

    def fixed_ips(self):
        return [fixed_ip for subnet in self['network']['subnets']
                         for fixed_ip in subnet['ips']]

    def floating_ips(self):
        return [floating_ip for fixed_ip in self.fixed_ips()
                            for floating_ip in fixed_ip['floating_ips']]

    def labeled_ips(self):
        """ returns the list of all IPs in this flat structure:
        {'network_label': 'my_network',
         'network_id': 'n8v29837fn234782f08fjxk3ofhb84',
         'ips': [{'address': '123.123.123.123',
                  'version': 4,
                  'type: 'fixed',
                  'meta': {...}},
                 {'address': '124.124.124.124',
                  'version': 4,
                  'type': 'floating',
                  'meta': {...}},
                 {'address': 'fe80::4',
                  'version': 6,
                  'type': 'fixed',
                  'meta': {...}}]"""
        if self['network']:
            # remove unecessary fields on fixed_ips
            ips = [IP(**ip) for ip in self.fixed_ips()]
            for ip in ips:
                # remove floating ips from IP, since this is a flat structure
                # of all IPs
                del ip['meta']['floating_ips']
            # add floating ips to list (if any)
            ips.extend(self.floating_ips())
            return {'network_label': self['network']['label'],
                    'network_id': self['network']['id'],
                    'ips': ips}
        return []

    @classmethod
    def hydrate(cls, vif):
        vif = VIF(**vif)
        vif['network'] = Network.hydrate(vif['network'])
        return vif


class NetworkInfo(list):
    """Stores and manipulates network information for a Nova instance"""

    # NetworkInfo is a list of VIFs

    def fixed_ips(self):
        """Returns all fixed_ips without floating_ips attached"""
        return [ip for vif in self for ip in vif.fixed_ips()]

    def floating_ips(self):
        """Returns all floating_ips"""
        return [ip for vif in self for ip in vif.floating_ips()]

    @classmethod
    def hydrate(cls, network_info):
        if isinstance(network_info, basestring):
            network_info = json.loads(network_info)
        return NetworkInfo([VIF.hydrate(vif) for vif in network_info])

    def as_cache(self):
        return json.dumps(self)
