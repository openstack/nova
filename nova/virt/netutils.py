# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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


def get_injected_network_template(network_info, use_ipv6=CONF.use_ipv6,
                                  template=CONF.injected_network_template):
    """
    return a rendered network template for the given network_info

    :param network_info:
       :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`

    Note: this code actually depends on the legacy network_info, but will
    convert the type itself if necessary.
    """

    if network_info is None:
        return None

    # the code below depends on the legacy 'network_info'
    if hasattr(network_info, 'legacy'):
        network_info = network_info.legacy()

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
        if use_ipv6:
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
        return None

    if not template:
        return None

    _late_load_cheetah()

    ifc_template = open(template).read()
    return str(Template(ifc_template,
                        searchList=[{'interfaces': nets,
                                     'use_ipv6': use_ipv6}]))
