# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
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

"""Compute-related Utilities and helpers."""

import netaddr

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import network
from nova.network import model as network_model
from nova.notifier import api as notifier_api
from nova import utils


FLAGS = flags.FLAGS


def notify_usage_exists(instance_ref, current_period=False):
    """ Generates 'exists' notification for an instance for usage auditing
        purposes.

        Generates usage for last completed period, unless 'current_period'
        is True."""
    admin_context = context.get_admin_context()
    begin, end = utils.current_audit_period()
    bw = {}
    if current_period:
        audit_start = end
        audit_end = utils.utcnow()
    else:
        audit_start = begin
        audit_end = end

    if (instance_ref.get('info_cache') and
        instance_ref['info_cache'].get('network_info')):

        cached_info = instance_ref['info_cache']['network_info']
        nw_info = network_model.NetworkInfo.hydrate(cached_info)
    else:
        nw_info = network.API().get_instance_nw_info(admin_context,
                                                         instance_ref)

    for b in db.bw_usage_get_by_instance(admin_context,
                                         instance_ref['id'],
                                         audit_start):
        label = 'net-name-not-found-%s' % b['mac']
        for vif in nw_info:
            if vif['address'] == b['mac']:
                label = vif['network']['label']
                break

        bw[label] = dict(bw_in=b.bw_in, bw_out=b.bw_out)
    usage_info = utils.usage_from_instance(instance_ref,
                          audit_period_beginning=str(audit_start),
                          audit_period_ending=str(audit_end),
                          bandwidth=bw)
    notifier_api.notify('compute.%s' % FLAGS.host,
                        'compute.instance.exists',
                        notifier_api.INFO,
                        usage_info)


def legacy_network_info(network_model):
    """
    Return the legacy network_info representation of the network_model
    """
    def get_ip(ip):
        if not ip:
            return None
        return ip['address']

    def fixed_ip_dict(ip, subnet):
        if ip['version'] == 4:
            netmask = str(subnet.as_netaddr().netmask)
        else:
            netmask = subnet.as_netaddr()._prefixlen

        return {'ip': ip['address'],
                'enabled': '1',
                'netmask': netmask,
                'gateway': get_ip(subnet['gateway'])}

    def get_meta(model, key, default=None):
        if 'meta' in model and key in model['meta']:
            return model['meta'][key]
        return default

    def convert_routes(routes):
        routes_list = []
        for route in routes:
            r = {'route': str(netaddr.IPNetwork(route['cidr']).network),
                 'netmask': str(netaddr.IPNetwork(route['cidr']).netmask),
                 'gateway': get_ip(route['gateway'])}
            routes_list.append(r)
        return routes_list

    network_info = []
    for vif in network_model:
        if not vif['network'] or not vif['network']['subnets']:
            continue
        network = vif['network']

        # NOTE(jkoelker) The legacy format only supports one subnet per
        #                network, so we only use the 1st one of each type
        # NOTE(tr3buchet): o.O
        v4_subnets = []
        v6_subnets = []
        for subnet in vif['network']['subnets']:
            if subnet['version'] == 4:
                v4_subnets.append(subnet)
            else:
                v6_subnets.append(subnet)

        subnet_v4 = None
        subnet_v6 = None

        if v4_subnets:
            subnet_v4 = v4_subnets[0]

        if v6_subnets:
            subnet_v6 = v6_subnets[0]

        if not subnet_v4:
            raise exception.NovaException(
                    message=_('v4 subnets are required for legacy nw_info'))

        routes = convert_routes(subnet_v4['routes'])

        should_create_bridge = get_meta(network, 'should_create_bridge',
                                        False)
        should_create_vlan = get_meta(network, 'should_create_vlan', False)
        gateway = get_ip(subnet_v4['gateway'])
        dhcp_server = get_meta(subnet_v4, 'dhcp_server', gateway)
        network_dict = dict(bridge=network['bridge'],
                            id=network['id'],
                            cidr=subnet_v4['cidr'],
                            cidr_v6=subnet_v6['cidr'] if subnet_v6 else None,
                            vlan=get_meta(network, 'vlan'),
                            injected=get_meta(network, 'injected', False),
                            multi_host=get_meta(network, 'multi_host',
                                                False),
                            bridge_interface=get_meta(network,
                                                      'bridge_interface'))
        # NOTE(tr3buchet): the 'ips' bit here is tricky, we support a single
        #                  subnet but we want all the IPs to be there
        #                  so we use the v4_subnets[0] and its IPs are first
        #                  so that eth0 will be from subnet_v4, the rest of the
        #                  IPs will be aliased eth0:1 etc and the gateways from
        #                  their subnets will not be used
        info_dict = dict(label=network['label'],
                         broadcast=str(subnet_v4.as_netaddr().broadcast),
                         mac=vif['address'],
                         vif_uuid=vif['id'],
                         rxtx_cap=get_meta(network, 'rxtx_cap', 0),
                         dns=[get_ip(ip) for ip in subnet['dns']],
                         ips=[fixed_ip_dict(ip, subnet)
                              for subnet in v4_subnets
                              for ip in subnet['ips']],
                         should_create_bridge=should_create_bridge,
                         should_create_vlan=should_create_vlan,
                         dhcp_server=dhcp_server)
        if routes:
            info_dict['routes'] = routes

        if gateway:
            info_dict['gateway'] = gateway

        if v6_subnets:
            if subnet_v6['gateway']:
                info_dict['gateway_v6'] = get_ip(subnet_v6['gateway'])
            info_dict['ip6s'] = [fixed_ip_dict(ip, subnet_v6)
                                 for ip in subnet_v6['ips']]

        network_info.append((network_dict, info_dict))
    return network_info
