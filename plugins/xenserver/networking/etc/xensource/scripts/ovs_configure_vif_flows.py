#!/usr/bin/env python
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

"""
This script is used to configure openvswitch flows on XenServer hosts.
"""

import os
import subprocess
import sys

# This is written to Python 2.4, since that is what is available on XenServer
import simplejson as json


# FIXME(dubs) this needs to be able to be passed in, check xen vif script
XEN_BRIDGE = 'xenbr1'
OVS_OFCTL = '/usr/bin/ovs-ofctl'


def execute(*command, return_stdout=False):
    devnull = open(os.devnull, 'w')
    command = map(str, command)
    proc = subprocess.Popen(command, close_fds=True,
                            stdout=subprocess.PIPE, stderr=devnull)
    devnull.close()
    if return_stdout:
        return proc.stdout.read()
    else:
        return None


class OvsFlow():
    def __init__(self, command, params, bridge=None):
        self.command = command
        self.params = params
        self.bridge = bridge or XEN_BRIDGE

    def add(self, rule):
        execute(OVS_OFCTL, 'add-flow', self.bridge, rule)

    def delete(self, rule):
        execute(OVS_OFCTL, 'del-flow', self.bridge, rule)

    def apply(self, rule):
        self.delete(rule % self.params)
        if self.command == 'online':
            self.add(rule % self.params)


def main(dom_id, command, net_type, only_this_vif=None):
    xsls = execute('/usr/bin/xenstore-ls',
                   '/local/domain/%s/vm-data/networking' % dom_id,
                   return_stdout=True)
    macs = [line.split("=")[0].strip() for line in xsls.splitlines()]

    for mac in macs:
        xsread = execute('/usr/bin/xenstore-read',
                         '/local/domain/%s/vm-data/networking/%s' %
                         (dom_id, mac), True)
        data = json.loads(xsread)
        if data["label"] == "public":
            vif = "vif%s.0" % dom_id
        else:
            vif = "vif%s.1" % dom_id

        if (only_this_vif is None) or (vif == only_this_vif):
            vif_ofport = execute('/usr/bin/ovs-vsctl', 'get', 'Interface',
                                 vif, 'ofport', return_stdout=True)

            params = dict(VIF_NAME=vif,
                          VIF_MAC=data['mac'],
                          VIF_OFPORT=vif_ofport)
            if net_type in ('ipv4', 'all'):
                for ip4 in data['ips']:
                    params.update({'VIF_IPv4': ip4['ip']})
                    apply_ovs_ipv4_flows(command, params)
            if net_type in ('ipv6', 'all'):
                for ip6 in data['ip6s']:
                    params.update({'VIF_GLOBAL_IPv6': ip6['ip']})
                    # TODO(dubs) calculate v6 link local addr
                    #params.update({'VIF_LOCAL_IPv6': XXX})
                    apply_ovs_ipv6_flows(command, params)


def apply_ovs_ipv4_flows(command, params):
    flow = OvsFlow(command, params)

    # allow valid ARP outbound (both request / reply)
    flow.apply("priority=3,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,arp,"
               "arp_sha=%(VIF_MAC)s,nw_src=%(VIF_IPv4)s,action=normal")

    flow.apply("priority=3,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,arp,"
               "arp_sha=%(VIF_MAC)s,nw_src=0.0.0.0,action=normal")

    # allow valid IPv4 outbound
    flow.apply("priority=3,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,ip,"
               "nw_src=%(VIF_IPv4)s,action=normal")


def apply_ovs_ipv6_flows(command, params):
    flow = OvsFlow(command, params)

    # allow valid IPv6 ND outbound (are both global and local IPs needed?)
    # Neighbor Solicitation
    flow.apply("priority=6,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,icmp6,"
               "ipv6_src=%(VIF_LOCAL_IPv6)s,icmp_type=135,nd_sll=%(VIF_MAC)s,"
               "action=normal")
    flow.apply("priority=6,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,icmp6,"
               "ipv6_src=%(VIF_LOCAL_IPv6)s,icmp_type=135,action=normal")
    flow.apply("priority=6,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,icmp6,"
               "ipv6_src=%(VIF_GLOBAL_IPv6)s,icmp_type=135,nd_sll=%(VIF_MAC)s,"
               "action=normal")
    flow.apply("priority=6,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,icmp6,"
               "ipv6_src=%(VIF_GLOBAL_IPv6)s,icmp_type=135,action=normal")

    # Neighbor Advertisement
    flow.apply("priority=6,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,icmp6,"
               "ipv6_src=%(VIF_LOCAL_IPv6)s,icmp_type=136,"
               "nd_target=%(VIF_LOCAL_IPv6)s,action=normal")
    flow.apply("priority=6,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,icmp6,"
               "ipv6_src=%(VIF_LOCAL_IPv6)s,icmp_type=136,action=normal")
    flow.apply("priority=6,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,icmp6,"
               "ipv6_src=%(VIF_GLOBAL_IPv6)s,icmp_type=136,"
               "nd_target=%(VIF_GLOBAL_IPv6)s,action=normal")
    flow.apply("priority=6,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,icmp6,"
               "ipv6_src=%(VIF_GLOBAL_IPv6)s,icmp_type=136,action=normal")

    # drop all other neighbor discovery (required because we permit all icmp6 below) 
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=135,action=drop")
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=136,action=drop")

    # do not allow sending specifc ICMPv6 types
    # Router Advertisement
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=134,action=drop")
    # Redirect Gateway
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=137,action=drop")
    # Mobile Prefix Solicitation
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=146,action=drop")
    # Mobile Prefix Advertisement
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=147,action=drop")
    # Multicast Router Advertisement
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=151,action=drop")
    # Multicast Router Solicitation
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=152,action=drop")
    # Multicast Router Termination
    flow.apply("priority=5,in_port=%(VIF_OFPORT)s,icmp6,icmp_type=153,action=drop")

    # allow valid IPv6 outbound, by type
    flow.apply("priority=4,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,"
               "ipv6_src=%(VIF_GLOBAL_IPv6)s,icmp6,action=normal")
    flow.apply("priority=4,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,"
               "ipv6_src=%(VIF_LOCAL_IPv6)s,icmp6,action=normal")
    flow.apply("priority=4,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,"
               "ipv6_src=%(VIF_GLOBAL_IPv6)s,tcp6,action=normal")
    flow.apply("priority=4,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,"
               "ipv6_src=%(VIF_LOCAL_IPv6)s,tcp6,action=normal")
    flow.apply("priority=4,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,"
               "ipv6_src=%(VIF_GLOBAL_IPv6)s,udp6,action=normal")
    flow.apply("priority=4,in_port=%(VIF_OFPORT)s,dl_src=%(VIF_MAC)s,"
               "ipv6_src=%(VIF_LOCAL_IPv6)s,udp6,action=normal")
    # all else will be dropped ...


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print "usage: %s dom_id online|offline ipv4|ipv6|all [vif_name]" % \
               os.path.basename(sys.argv[0])
        sys.exit(1)
    else:
        dom_id, command, net_type = sys.argv[1:4]
        vif_name = len(sys.argv) == 5 and sys.argv[4] or None
        main(dom_id, command, net_type, vif_name)
