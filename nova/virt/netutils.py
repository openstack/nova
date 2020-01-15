# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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


"""Network-related utilities for supporting libvirt connection code."""

import os

import jinja2
import netaddr
from oslo_utils import strutils

import nova.conf
from nova.network import model

CONF = nova.conf.CONF


def get_net_and_mask(cidr):
    net = netaddr.IPNetwork(cidr)
    return str(net.ip), str(net.netmask)


def get_net_and_prefixlen(cidr):
    net = netaddr.IPNetwork(cidr)
    return str(net.ip), str(net._prefixlen)


def get_ip_version(cidr):
    net = netaddr.IPNetwork(cidr)
    return int(net.version)


def _get_first_network(network, version):
    # Using a generator expression with a next() call for the first element
    # of a list since we don't want to evaluate the whole list as we can
    # have a lot of subnets
    try:
        return next(i for i in network['subnets']
                    if i['version'] == version)
    except StopIteration:
        pass


def get_injected_network_template(network_info, template=None,
                                  libvirt_virt_type=None):
    """Returns a rendered network template for the given network_info.

    :param network_info: `nova.network.models.NetworkInfo` object describing
        the network metadata.
    :param template: Path to the interfaces template file.
    :param libvirt_virt_type: The Libvirt `virt_type`, will be `None` for
        other hypervisors..
    """
    if not template:
        template = CONF.injected_network_template

    if not (network_info and template):
        return

    nets = []
    ifc_num = -1
    ipv6_is_available = False

    for vif in network_info:
        if not vif['network'] or not vif['network']['subnets']:
            continue

        network = vif['network']
        # NOTE(bnemec): The template only supports a single subnet per
        # interface and I'm not sure how/if that can be fixed, so this
        # code only takes the first subnet of the appropriate type.
        subnet_v4 = _get_first_network(network, 4)
        subnet_v6 = _get_first_network(network, 6)

        ifc_num += 1

        if not network.get_meta('injected'):
            continue

        hwaddress = vif.get('address')
        address = None
        netmask = None
        gateway = ''
        broadcast = None
        dns = None
        routes = []
        if subnet_v4:
            if subnet_v4.get_meta('dhcp_server') is not None:
                continue

            if subnet_v4['ips']:
                ip = subnet_v4['ips'][0]
                address = ip['address']
                netmask = model.get_netmask(ip, subnet_v4)
                if subnet_v4['gateway']:
                    gateway = subnet_v4['gateway']['address']
                broadcast = str(subnet_v4.as_netaddr().broadcast)
                dns = ' '.join([i['address'] for i in subnet_v4['dns']])
                for route_ref in subnet_v4['routes']:
                    (net, mask) = get_net_and_mask(route_ref['cidr'])
                    route = {'gateway': str(route_ref['gateway']['address']),
                             'cidr': str(route_ref['cidr']),
                             'network': net,
                             'netmask': mask}
                    routes.append(route)

        address_v6 = None
        gateway_v6 = ''
        netmask_v6 = None
        dns_v6 = None
        if subnet_v6:
            if subnet_v6.get_meta('dhcp_server') is not None:
                continue

            if subnet_v6['ips']:
                ipv6_is_available = True
                ip_v6 = subnet_v6['ips'][0]
                address_v6 = ip_v6['address']
                netmask_v6 = model.get_netmask(ip_v6, subnet_v6)
                if subnet_v6['gateway']:
                    gateway_v6 = subnet_v6['gateway']['address']
                dns_v6 = ' '.join([i['address'] for i in subnet_v6['dns']])

        net_info = {'name': 'eth%d' % ifc_num,
                    'hwaddress': hwaddress,
                    'address': address,
                    'netmask': netmask,
                    'gateway': gateway,
                    'broadcast': broadcast,
                    'dns': dns,
                    'routes': routes,
                    'address_v6': address_v6,
                    'gateway_v6': gateway_v6,
                    'netmask_v6': netmask_v6,
                    'dns_v6': dns_v6,
                   }
        nets.append(net_info)

    if not nets:
        return

    tmpl_path, tmpl_file = os.path.split(template)
    env = jinja2.Environment(  # nosec
        loader=jinja2.FileSystemLoader(tmpl_path),  # nosec
        trim_blocks=True)
    template = env.get_template(tmpl_file)
    return template.render({'interfaces': nets,
                            'use_ipv6': ipv6_is_available,
                            'libvirt_virt_type': libvirt_virt_type})


def get_network_metadata(network_info):
    """Gets a more complete representation of the instance network information.

    This data is exposed as network_data.json in the metadata service and
    the config drive.

    :param network_info: `nova.network.models.NetworkInfo` object describing
        the network metadata.
    """
    if not network_info:
        return

    # IPv4 or IPv6 networks
    nets = []
    # VIFs, physical NICs, or VLANs. Physical NICs will have type 'phy'.
    links = []
    # Non-network bound services, such as DNS
    services = []
    ifc_num = -1
    net_num = -1

    for vif in network_info:
        if not vif.get('network') or not vif['network'].get('subnets'):
            continue

        network = vif['network']
        # NOTE(JoshNang) currently, only supports the first IPv4 and first
        # IPv6 subnet on network, a limitation that also exists in the
        # network template.
        subnet_v4 = _get_first_network(network, 4)
        subnet_v6 = _get_first_network(network, 6)

        ifc_num += 1
        link = None

        # Get the VIF or physical NIC data
        if subnet_v4 or subnet_v6:
            link = _get_eth_link(vif, ifc_num)
            links.append(link)

        # Add IPv4 and IPv6 networks if they exist
        if subnet_v4 and subnet_v4.get('ips'):
            net_num += 1
            nets.append(_get_nets(vif, subnet_v4, 4, net_num, link['id']))
            services += [dns for dns in _get_dns_services(subnet_v4)
                         if dns not in services]
        if subnet_v6 and subnet_v6.get('ips'):
            net_num += 1
            nets.append(_get_nets(vif, subnet_v6, 6, net_num, link['id']))
            services += [dns for dns in _get_dns_services(subnet_v6)
                         if dns not in services]

    return {
        "links": links,
        "networks": nets,
        "services": services
    }


def get_ec2_ip_info(network_info):
    if not isinstance(network_info, model.NetworkInfo):
        network_info = model.NetworkInfo.hydrate(network_info)

    ip_info = {}
    fixed_ips = network_info.fixed_ips()
    ip_info['fixed_ips'] = [
        ip['address'] for ip in fixed_ips if ip['version'] == 4]
    ip_info['fixed_ip6s'] = [
        ip['address'] for ip in fixed_ips if ip['version'] == 6]
    ip_info['floating_ips'] = [
        ip['address'] for ip in network_info.floating_ips()]

    return ip_info


def _get_eth_link(vif, ifc_num):
    """Get a VIF or physical NIC representation.

    :param vif: Neutron VIF
    :param ifc_num: Interface index for generating name if the VIF's
        'devname' isn't defined.
    :return: A dict with 'id', 'vif_id', 'type', 'mtu' and
        'ethernet_mac_address' as keys
    """
    link_id = vif.get('devname')
    if not link_id:
        link_id = 'interface%d' % ifc_num

    # Use 'phy' for physical links. Ethernet can be confusing
    if vif.get('type') in model.LEGACY_EXPOSED_VIF_TYPES:
        nic_type = vif.get('type')
    else:
        nic_type = 'phy'

    link = {
        'id': link_id,
        'vif_id': vif['id'],
        'type': nic_type,
        'mtu': vif['network']['meta'].get('mtu'),
        'ethernet_mac_address': vif.get('address'),
    }
    return link


def _get_nets(vif, subnet, version, net_num, link_id):
    """Get networks for the given VIF and subnet

    :param vif: Neutron VIF
    :param subnet: Neutron subnet
    :param version: IP version as an int, either '4' or '6'
    :param net_num: Network index for generating name of each network
    :param link_id: Arbitrary identifier for the link the networks are
        attached to
    """
    net_type = ''
    if subnet.get_meta('ipv6_address_mode') is not None:
        net_type = '_%s' % subnet.get_meta('ipv6_address_mode')
    elif subnet.get_meta('dhcp_server') is not None:
        net_info = {
            'id': 'network%d' % net_num,
            'type': 'ipv%d_dhcp' % version,
            'link': link_id,
            'network_id': vif['network']['id']
        }
        return net_info

    ip = subnet['ips'][0]
    address = ip['address']
    if version == 4:
        netmask = model.get_netmask(ip, subnet)
    elif version == 6:
        netmask = str(subnet.as_netaddr().netmask)

    net_info = {
        'id': 'network%d' % net_num,
        'type': 'ipv%d%s' % (version, net_type),
        'link': link_id,
        'ip_address': address,
        'netmask': netmask,
        'routes': _get_default_route(version, subnet),
        'network_id': vif['network']['id']
    }

    # Add any additional routes beyond the default route
    for route in subnet['routes']:
        route_addr = netaddr.IPNetwork(route['cidr'])
        new_route = {
            'network': str(route_addr.network),
            'netmask': str(route_addr.netmask),
            'gateway': route['gateway']['address']
        }
        net_info['routes'].append(new_route)

    net_info['services'] = _get_dns_services(subnet)

    return net_info


def _get_default_route(version, subnet):
    """Get a default route for a network

    :param version: IP version as an int, either '4' or '6'
    :param subnet: Neutron subnet
    """
    if subnet.get('gateway') and subnet['gateway'].get('address'):
        gateway = subnet['gateway']['address']
    else:
        return []

    if version == 4:
        return [{
            'network': '0.0.0.0',
            'netmask': '0.0.0.0',
            'gateway': gateway
        }]
    elif version == 6:
        return [{
            'network': '::',
            'netmask': '::',
            'gateway': gateway
        }]


def _get_dns_services(subnet):
    """Get the DNS servers for the subnet."""
    services = []
    if not subnet.get('dns'):
        return services
    return [{'type': 'dns', 'address': ip.get('address')}
            for ip in subnet['dns']]


def get_cached_vifs_with_vlan(network_info):
    """Generates a dict from a list of VIFs that has a vlan tag, with
    MAC, VLAN as a key, value.
    """
    if network_info is None:
        return {}
    return {vif['address']: vif['details']['vlan'] for vif in network_info
                            if vif.get('details', {}).get('vlan')}


def get_cached_vifs_with_trusted(network_info):
    """Generates a dict from a list of VIFs that trusted, MAC as key"""
    if network_info is None:
        return {}
    return {vif['address']: strutils.bool_from_string(
        vif['profile'].get('trusted', 'False')) for vif in network_info
            if vif.get('profile')}
