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
from oslo.config import cfg

from nova.network import model
from nova import paths

CONF = cfg.CONF

netutils_opts = [
    cfg.StrOpt('injected_network_template',
               default=paths.basedir_def('nova/virt/interfaces.template'),
               help='Template file for injected network'),
]

CONF.register_opts(netutils_opts)
CONF.import_opt('use_ipv6', 'nova.netconf')


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
        return (i for i in network['subnets']
                if i['version'] == version).next()
    except StopIteration:
        pass


def get_injected_network_template(network_info, use_ipv6=None, template=None,
                                  libvirt_virt_type=None):
    """Returns a rendered network template for the given network_info.

    :param network_info:
        :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
    :param use_ipv6: If False, do not return IPv6 template information
        even if an IPv6 subnet is present in network_info.
    :param template: Path to the interfaces template file.
    :param libvirt_virt_type: The Libvirt `virt_type`, will be `None` for
        other hypervisors..
    """
    if use_ipv6 is None:
        use_ipv6 = CONF.use_ipv6

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

        address = None
        netmask = None
        gateway = ''
        broadcast = None
        dns = None
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

        address_v6 = None
        gateway_v6 = ''
        netmask_v6 = None
        dns_v6 = None
        have_ipv6 = (use_ipv6 and subnet_v6)
        if have_ipv6:
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
                    'address': address,
                    'netmask': netmask,
                    'gateway': gateway,
                    'broadcast': broadcast,
                    'dns': dns,
                    'address_v6': address_v6,
                    'gateway_v6': gateway_v6,
                    'netmask_v6': netmask_v6,
                    'dns_v6': dns_v6,
                   }
        nets.append(net_info)

    if not nets:
        return

    tmpl_path, tmpl_file = os.path.split(CONF.injected_network_template)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path),
                             trim_blocks=True)
    template = env.get_template(tmpl_file)
    return template.render({'interfaces': nets,
                            'use_ipv6': ipv6_is_available,
                            'libvirt_virt_type': libvirt_virt_type})
