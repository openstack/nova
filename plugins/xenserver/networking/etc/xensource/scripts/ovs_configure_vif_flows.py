#!/usr/bin/env python
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

"""
This script is used to configure openvswitch flows on XenServer hosts.
"""

import os
import sys

# This is written to Python 2.4, since that is what is available on XenServer
import netaddr
import simplejson as json

import novalib  # noqa


OVS_OFCTL = '/usr/bin/ovs-ofctl'


class OvsFlow(object):
    def __init__(self, bridge, params):
        self.bridge = bridge
        self.params = params

    def add(self, rule):
        novalib.execute(OVS_OFCTL, 'add-flow', self.bridge, rule % self.params)

    def clear_flows(self, ofport):
        novalib.execute(OVS_OFCTL, 'del-flows',
                                        self.bridge, "in_port=%s" % ofport)


def main(command, vif_raw, net_type):
    if command not in ('online', 'offline'):
        return

    vif_name, dom_id, vif_index = vif_raw.split('-')
    vif = "%s%s.%s" % (vif_name, dom_id, vif_index)

    bridge = novalib.execute_get_output('/usr/bin/ovs-vsctl',
                                                    'iface-to-br', vif)

    xsls = novalib.execute_get_output('/usr/bin/xenstore-ls',
                              '/local/domain/%s/vm-data/networking' % dom_id)
    macs = [line.split("=")[0].strip() for line in xsls.splitlines()]

    for mac in macs:
        xsread = novalib.execute_get_output('/usr/bin/xenstore-read',
                                    '/local/domain/%s/vm-data/networking/%s' %
                                    (dom_id, mac))
        data = json.loads(xsread)
        if data["label"] == "public":
            this_vif = "vif%s.0" % dom_id
            phys_dev = "eth0"
        else:
            this_vif = "vif%s.1" % dom_id
            phys_dev = "eth1"

        if vif == this_vif:
            vif_ofport = novalib.execute_get_output('/usr/bin/ovs-vsctl',
                                    'get', 'Interface', vif, 'ofport')
            phys_ofport = novalib.execute_get_output('/usr/bin/ovs-vsctl',
                                    'get', 'Interface', phys_dev, 'ofport')

            params = dict(VIF_NAME=vif,
                          MAC=data['mac'],
                          OF_PORT=vif_ofport,
                          PHYS_PORT=phys_ofport)

            ovs = OvsFlow(bridge, params)

            if command == 'offline':
                # I haven't found a way to clear only IPv4 or IPv6 rules.
                ovs.clear_flows(vif_ofport)

            if command == 'online':
                if net_type in ('ipv4', 'all') and 'ips' in data:
                    for ip4 in data['ips']:
                        ovs.params.update({'IPV4_ADDR': ip4['ip']})
                        apply_ovs_ipv4_flows(ovs, bridge, params)
                if net_type in ('ipv6', 'all') and 'ip6s' in data:
                    for ip6 in data['ip6s']:
                        mac_eui64 = netaddr.EUI(data['mac']).eui64()
                        link_local = str(mac_eui64.ipv6_link_local())
                        ovs.params.update({'IPV6_LINK_LOCAL_ADDR': link_local})
                        ovs.params.update({'IPV6_GLOBAL_ADDR': ip6['ip']})
                        apply_ovs_ipv6_flows(ovs, bridge, params)


def apply_ovs_ipv4_flows(ovs, bridge, params):
    # When ARP traffic arrives from a vif, push it to virtual port
    # 9999 for further processing
    ovs.add("priority=4,arp,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "nw_src=%(IPV4_ADDR)s,arp_sha=%(MAC)s,actions=resubmit:9999")
    ovs.add("priority=4,arp,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "nw_src=0.0.0.0,arp_sha=%(MAC)s,actions=resubmit:9999")

    # When IP traffic arrives from a vif, push it to virtual port 9999
    # for further processing
    ovs.add("priority=4,ip,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "nw_src=%(IPV4_ADDR)s,actions=resubmit:9999")

    # Drop IP bcast/mcast
    ovs.add("priority=6,ip,in_port=%(OF_PORT)s,dl_dst=ff:ff:ff:ff:ff:ff,"
            "actions=drop")
    ovs.add("priority=5,ip,in_port=%(OF_PORT)s,nw_dst=224.0.0.0/4,"
            "actions=drop")
    ovs.add("priority=5,ip,in_port=%(OF_PORT)s,nw_dst=240.0.0.0/4,"
            "actions=drop")

    # Pass ARP requests coming from any VMs on the local HV (port
    # 9999) or coming from external sources (PHYS_PORT) to the VM and
    # physical NIC.  We output this to the physical NIC as well, since
    # with instances of shared ip groups, the active host for the
    # destination IP might be elsewhere...
    ovs.add("priority=3,arp,in_port=9999,nw_dst=%(IPV4_ADDR)s,"
            "actions=output:%(OF_PORT)s,output:%(PHYS_PORT)s")

    # Pass ARP traffic originating from external sources the VM with
    # the matching IP address
    ovs.add("priority=3,arp,in_port=%(PHYS_PORT)s,nw_dst=%(IPV4_ADDR)s,"
            "actions=output:%(OF_PORT)s")

    # Pass ARP traffic from one VM (src mac already validated) to
    # another VM on the same HV
    ovs.add("priority=3,arp,in_port=9999,dl_dst=%(MAC)s,"
            "actions=output:%(OF_PORT)s")

    # Pass ARP replies coming from the external environment to the
    # target VM
    ovs.add("priority=3,arp,in_port=%(PHYS_PORT)s,dl_dst=%(MAC)s,"
            "actions=output:%(OF_PORT)s")

    # ALL IP traffic: Pass IP data coming from any VMs on the local HV
    # (port 9999) or coming from external sources (PHYS_PORT) to the
    # VM and physical NIC.  We output this to the physical NIC as
    # well, since with instances of shared ip groups, the active host
    # for the destination IP might be elsewhere...
    ovs.add("priority=3,ip,in_port=9999,dl_dst=%(MAC)s,"
            "nw_dst=%(IPV4_ADDR)s,actions=output:%(OF_PORT)s,"
            "output:%(PHYS_PORT)s")

    # Pass IP traffic from the external environment to the VM
    ovs.add("priority=3,ip,in_port=%(PHYS_PORT)s,dl_dst=%(MAC)s,"
            "nw_dst=%(IPV4_ADDR)s,actions=output:%(OF_PORT)s")

    # Send any local traffic to the physical NIC's OVS port for
    # physical network learning
    ovs.add("priority=2,in_port=9999,actions=output:%(PHYS_PORT)s")


def apply_ovs_ipv6_flows(ovs, bridge, params):
    # allow valid IPv6 ND outbound (are both global and local IPs needed?)
    # Neighbor Solicitation
    ovs.add("priority=6,in_port=%(OF_PORT)s,dl_src=%(MAC)s,icmp6,"
            "ipv6_src=%(IPV6_LINK_LOCAL_ADDR)s,icmp_type=135,nd_sll=%(MAC)s,"
            "actions=normal")
    ovs.add("priority=6,in_port=%(OF_PORT)s,dl_src=%(MAC)s,icmp6,"
            "ipv6_src=%(IPV6_LINK_LOCAL_ADDR)s,icmp_type=135,actions=normal")
    ovs.add("priority=6,in_port=%(OF_PORT)s,dl_src=%(MAC)s,icmp6,"
            "ipv6_src=%(IPV6_GLOBAL_ADDR)s,icmp_type=135,nd_sll=%(MAC)s,"
            "actions=normal")
    ovs.add("priority=6,in_port=%(OF_PORT)s,dl_src=%(MAC)s,icmp6,"
            "ipv6_src=%(IPV6_GLOBAL_ADDR)s,icmp_type=135,actions=normal")

    # Neighbor Advertisement
    ovs.add("priority=6,in_port=%(OF_PORT)s,dl_src=%(MAC)s,icmp6,"
            "ipv6_src=%(IPV6_LINK_LOCAL_ADDR)s,icmp_type=136,"
            "nd_target=%(IPV6_LINK_LOCAL_ADDR)s,actions=normal")
    ovs.add("priority=6,in_port=%(OF_PORT)s,dl_src=%(MAC)s,icmp6,"
            "ipv6_src=%(IPV6_LINK_LOCAL_ADDR)s,icmp_type=136,actions=normal")
    ovs.add("priority=6,in_port=%(OF_PORT)s,dl_src=%(MAC)s,icmp6,"
            "ipv6_src=%(IPV6_GLOBAL_ADDR)s,icmp_type=136,"
            "nd_target=%(IPV6_GLOBAL_ADDR)s,actions=normal")
    ovs.add("priority=6,in_port=%(OF_PORT)s,dl_src=%(MAC)s,icmp6,"
            "ipv6_src=%(IPV6_GLOBAL_ADDR)s,icmp_type=136,actions=normal")

    # drop all other neighbor discovery (req b/c we permit all icmp6 below)
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=135,actions=drop")
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=136,actions=drop")

    # do not allow sending specific ICMPv6 types
    # Router Advertisement
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=134,actions=drop")
    # Redirect Gateway
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=137,actions=drop")
    # Mobile Prefix Solicitation
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=146,actions=drop")
    # Mobile Prefix Advertisement
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=147,actions=drop")
    # Multicast Router Advertisement
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=151,actions=drop")
    # Multicast Router Solicitation
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=152,actions=drop")
    # Multicast Router Termination
    ovs.add("priority=5,in_port=%(OF_PORT)s,icmp6,icmp_type=153,actions=drop")

    # allow valid IPv6 outbound, by type
    ovs.add("priority=4,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "ipv6_src=%(IPV6_GLOBAL_ADDR)s,icmp6,actions=normal")
    ovs.add("priority=4,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "ipv6_src=%(IPV6_LINK_LOCAL_ADDR)s,icmp6,actions=normal")
    ovs.add("priority=4,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "ipv6_src=%(IPV6_GLOBAL_ADDR)s,tcp6,actions=normal")
    ovs.add("priority=4,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "ipv6_src=%(IPV6_LINK_LOCAL_ADDR)s,tcp6,actions=normal")
    ovs.add("priority=4,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "ipv6_src=%(IPV6_GLOBAL_ADDR)s,udp6,actions=normal")
    ovs.add("priority=4,in_port=%(OF_PORT)s,dl_src=%(MAC)s,"
            "ipv6_src=%(IPV6_LINK_LOCAL_ADDR)s,udp6,actions=normal")
    # all else will be dropped ...


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: %s [online|offline] vif-domid-idx [ipv4|ipv6|all] " %
              os.path.basename(sys.argv[0]))
        sys.exit(1)
    else:
        command, vif_raw, net_type = sys.argv[1:4]
        main(command, vif_raw, net_type)
