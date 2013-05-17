# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import netaddr

from oslo.config import cfg

from nova.network import model

CONF = cfg.CONF
CONF.import_opt('use_ipv6', 'nova.netconf')
CONF.import_opt('injected_network_template', 'nova.virt.disk.api')

Template = None


def _late_load_cheetah():
    global Template
    if Template is None:
        t = __import__('Cheetah.Template', globals(), locals(),
                       ['Template'], -1)
        Template = t.Template


def get_net_and_mask(cidr):
    net = netaddr.IPNetwork(cidr)
    return str(net.ip), str(net.netmask)


def get_net_and_prefixlen(cidr):
    net = netaddr.IPNetwork(cidr)
    return str(net.ip), str(net._prefixlen)


def get_ip_version(cidr):
    net = netaddr.IPNetwork(cidr)
    return int(net.version)


def get_non_legacy_network_template(network_info, use_ipv6=CONF.use_ipv6,
                                    template=CONF.injected_network_template):
    """A new version of get_injected_network_template that does not rely on
       legacy network info.

    Returns a rendered network template for the given network_info.  When
    libvirt's dependency on using legacy network info for network config
    injection goes away, this function can replace
    get_injected_network_template entirely.

    :param network_info:
        :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
    :param use_ipv6: If False, do not return IPv6 template information
        even if an IPv6 subnet is present in network_info.
    :param template: Path to the interfaces template file.
    """
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
        subnet_v4 = [i for i in network['subnets'] if i['version'] == 4][0]
        subnet_v6 = [i for i in network['subnets'] if i['version'] == 6]
        if subnet_v6:
            subnet_v6 = subnet_v6[0]

        ifc_num += 1

        if (not network.get_meta('injected') or not subnet_v4['ips'] or
                subnet_v4.get_meta('dhcp_server') is not None):
            continue

        ip = subnet_v4['ips'][0]
        address = ip['address']
        netmask = model.get_netmask(ip, subnet_v4)
        gateway = ''
        if subnet_v4['gateway']:
            gateway = subnet_v4['gateway']['address']
        broadcast = str(subnet_v4.as_netaddr().broadcast)
        dns = ' '.join([i['address'] for i in subnet_v4['dns']])
        # NOTE(bnemec): I don't think this code would handle a pure IPv6
        # environment properly, but I don't have such an environment in
        # which to test/fix that.
        address_v6 = None
        gateway_v6 = None
        netmask_v6 = None
        have_ipv6 = (use_ipv6 and subnet_v6)
        if have_ipv6:
            if subnet_v6['ips']:
                ipv6_is_available = True
                ip_v6 = subnet_v6['ips'][0]
                address_v6 = ip_v6['address']
                netmask_v6 = model.get_netmask(ip_v6, subnet_v6)
                gateway_v6 = ''
                if subnet_v6['gateway']:
                    gateway_v6 = subnet_v6['gateway']['address']

        net_info = {'name': 'eth%d' % ifc_num,
                    'address': address,
                    'netmask': netmask,
                    'gateway': gateway,
                    'broadcast': broadcast,
                    'dns': dns,
                    'address_v6': address_v6,
                    'gateway_v6': gateway_v6,
                    'netmask_v6': netmask_v6,
                   }
        nets.append(net_info)

    if not nets:
        return

    return build_template(template, nets, ipv6_is_available)


def get_injected_network_template(network_info, use_ipv6=CONF.use_ipv6,
                                  template=CONF.injected_network_template):
    """
    return a rendered network template for the given network_info

    :param network_info:
       :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
    :param use_ipv6: If False, do not return IPv6 template information
        even if an IPv6 subnet is present in network_info.
    :param template: Path to the interfaces template file.
    """

    if not (network_info and template):
        return

    # If we're passed new network_info, make use of it instead of forcing
    # it to the legacy format required below.
    if isinstance(network_info, model.NetworkInfo):
        return get_non_legacy_network_template(network_info,
                                               use_ipv6,
                                               template)

    nets = []
    ifc_num = -1
    have_injected_networks = False

    for (network_ref, mapping) in network_info:
        ifc_num += 1

        if not network_ref['injected']:
            continue

        have_injected_networks = True
        address = mapping['ips'][0]['ip']
        netmask = mapping['ips'][0]['netmask']
        address_v6 = None
        gateway_v6 = None
        netmask_v6 = None
        ipv6_is_available = use_ipv6 and 'ip6s' in mapping
        if ipv6_is_available:
            address_v6 = mapping['ip6s'][0]['ip']
            netmask_v6 = mapping['ip6s'][0]['netmask']
            gateway_v6 = mapping['gateway_v6']
        net_info = {'name': 'eth%d' % ifc_num,
               'address': address,
               'netmask': netmask,
               'gateway': mapping['gateway'],
               'broadcast': mapping['broadcast'],
               'dns': ' '.join(mapping['dns']),
               'address_v6': address_v6,
               'gateway_v6': gateway_v6,
               'netmask_v6': netmask_v6}
        nets.append(net_info)

    if have_injected_networks is False:
        return

    return build_template(template, nets, ipv6_is_available)


def build_template(template, nets, ipv6_is_available):
    _late_load_cheetah()

    ifc_template = open(template).read()
    return str(Template(ifc_template,
                        searchList=[{'interfaces': nets,
                                     'use_ipv6': ipv6_is_available}]))
