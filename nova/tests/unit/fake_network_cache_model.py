# Copyright 2011 OpenStack Foundation
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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.network import model


def new_ip(ip_dict=None, version=4):
    if version == 6:
        new_ip = dict(address='fd00::1:100', version=6)
    elif version == 4:
        new_ip = dict(address='192.168.1.100')
    ip_dict = ip_dict or {}
    new_ip.update(ip_dict)
    return model.IP(**new_ip)


def new_fixed_ip(ip_dict=None, version=4):
    if version == 6:
        new_fixed_ip = dict(address='fd00::1:100', version=6)
    elif version == 4:
        new_fixed_ip = dict(address='192.168.1.100')
    ip_dict = ip_dict or {}
    new_fixed_ip.update(ip_dict)
    return model.FixedIP(**new_fixed_ip)


def new_route(route_dict=None, version=4):
    if version == 6:
        new_route = dict(
            cidr='::/48',
            gateway=new_ip(dict(address='fd00::1:1'), version=6),
            interface='eth0')
    elif version == 4:
        new_route = dict(
            cidr='0.0.0.0/24',
            gateway=new_ip(dict(address='192.168.1.1')),
            interface='eth0')

    route_dict = route_dict or {}
    new_route.update(route_dict)
    return model.Route(**new_route)


def new_subnet(subnet_dict=None, version=4):
    if version == 6:
        new_subnet = dict(
            cidr='fd00::/48',
            dns=[new_ip(dict(address='1:2:3:4::'), version=6),
                    new_ip(dict(address='2:3:4:5::'), version=6)],
            gateway=new_ip(dict(address='fd00::1'), version=6),
            ips=[new_fixed_ip(dict(address='fd00::2'), version=6),
                    new_fixed_ip(dict(address='fd00::3'), version=6)],
            routes=[new_route(version=6)],
            version=6)
    elif version == 4:
        new_subnet = dict(
            cidr='10.10.0.0/24',
            dns=[new_ip(dict(address='1.2.3.4')),
                    new_ip(dict(address='2.3.4.5'))],
            gateway=new_ip(dict(address='10.10.0.1')),
            ips=[new_fixed_ip(dict(address='10.10.0.2')),
                    new_fixed_ip(dict(address='10.10.0.3'))],
            routes=[new_route()])
    subnet_dict = subnet_dict or {}
    new_subnet.update(subnet_dict)
    return model.Subnet(**new_subnet)


def new_network(network_dict=None, version=4):
    if version == 6:
        new_net = dict(
            id=uuids.network_id,
            bridge='br0',
            label='public',
            subnets=[new_subnet(version=6),
                     new_subnet(dict(cidr='ffff:ffff:ffff:ffff::'),
                                version=6)])
    elif version == 4:
        new_net = dict(
            id=uuids.network_id,
            bridge='br0',
            label='public',
            subnets=[new_subnet(), new_subnet(dict(cidr='255.255.255.255'))])
    network_dict = network_dict or {}
    new_net.update(network_dict)
    return model.Network(**new_net)


def new_vif(vif_dict=None, version=4):
    vif = dict(
        id=uuids.vif_id,
        address='aa:aa:aa:aa:aa:aa',
        type='bridge',
        network=new_network(version=version))
    vif_dict = vif_dict or {}
    vif.update(vif_dict)
    return model.VIF(**vif)
