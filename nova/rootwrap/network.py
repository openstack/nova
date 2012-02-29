# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Openstack, LLC.
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


from nova.rootwrap import filters

filterlist = [
    # nova/network/linux_net.py: 'ip', 'addr', 'add', str(floating_ip)+'/32'i..
    # nova/network/linux_net.py: 'ip', 'addr', 'del', str(floating_ip)+'/32'..
    # nova/network/linux_net.py: 'ip', 'addr', 'add', '169.254.169.254/32',..
    # nova/network/linux_net.py: 'ip', 'addr', 'show', 'dev', dev, 'scope',..
    # nova/network/linux_net.py: 'ip', 'addr', 'del/add', ip_params, dev)
    # nova/network/linux_net.py: 'ip', 'addr', 'del', params, fields[-1]
    # nova/network/linux_net.py: 'ip', 'addr', 'add', params, bridge
    # nova/network/linux_net.py: 'ip', '-f', 'inet6', 'addr', 'change', ..
    # nova/network/linux_net.py: 'ip', 'link', 'set', 'dev', dev, 'promisc',..
    # nova/network/linux_net.py: 'ip', 'link', 'add', 'link', bridge_if ...
    # nova/network/linux_net.py: 'ip', 'link', 'set', interface, "address",..
    # nova/network/linux_net.py: 'ip', 'link', 'set', interface, 'up'
    # nova/network/linux_net.py: 'ip', 'link', 'set', bridge, 'up'
    # nova/network/linux_net.py: 'ip', 'addr', 'show', 'dev', interface, ..
    # nova/network/linux_net.py: 'ip', 'link', 'set', dev, "address", ..
    # nova/network/linux_net.py: 'ip', 'link', 'set', dev, 'up'
    filters.CommandFilter("/sbin/ip", "root"),

    # nova/network/linux_net.py: 'ip[6]tables-save' % (cmd,), '-t', ...
    filters.CommandFilter("/sbin/iptables-save", "root"),
    filters.CommandFilter("/sbin/ip6tables-save", "root"),

    # nova/network/linux_net.py: 'ip[6]tables-restore' % (cmd,)
    filters.CommandFilter("/sbin/iptables-restore", "root"),
    filters.CommandFilter("/sbin/ip6tables-restore", "root"),

    # nova/network/linux_net.py: 'arping', '-U', floating_ip, '-A', '-I', ...
    # nova/network/linux_net.py: 'arping', '-U', network_ref['dhcp_server'],..
    filters.CommandFilter("/usr/bin/arping", "root"),

    # nova/network/linux_net.py: 'route', '-n'
    # nova/network/linux_net.py: 'route', 'del', 'default', 'gw'
    # nova/network/linux_net.py: 'route', 'add', 'default', 'gw'
    # nova/network/linux_net.py: 'route', '-n'
    # nova/network/linux_net.py: 'route', 'del', 'default', 'gw', old_gw, ..
    # nova/network/linux_net.py: 'route', 'add', 'default', 'gw', old_gateway
    filters.CommandFilter("/sbin/route", "root"),

    # nova/network/linux_net.py: 'dhcp_release', dev, address, mac_address
    filters.CommandFilter("/usr/bin/dhcp_release", "root"),

    # nova/network/linux_net.py: 'kill', '-9', pid
    # nova/network/linux_net.py: 'kill', '-HUP', pid
    filters.KillFilter("/bin/kill", "root",
                       ['-9', '-HUP'], ['/usr/sbin/dnsmasq']),

    # nova/network/linux_net.py: 'kill', pid
    filters.KillFilter("/bin/kill", "root", [''], ['/usr/sbin/radvd']),

    # nova/network/linux_net.py: dnsmasq call
    filters.DnsmasqFilter("/usr/sbin/dnsmasq", "root"),

    # nova/network/linux_net.py: 'radvd', '-C', '%s' % _ra_file(dev, 'conf'),..
    filters.CommandFilter("/usr/sbin/radvd", "root"),

    # nova/network/linux_net.py: 'brctl', 'addbr', bridge
    # nova/network/linux_net.py: 'brctl', 'setfd', bridge, 0
    # nova/network/linux_net.py: 'brctl', 'stp', bridge, 'off'
    # nova/network/linux_net.py: 'brctl', 'addif', bridge, interface
    filters.CommandFilter("/sbin/brctl", "root"),
    filters.CommandFilter("/usr/sbin/brctl", "root"),

    # nova/network/linux_net.py: 'ovs-vsctl', ....
    filters.CommandFilter("/usr/bin/ovs-vsctl", "root"),

    # nova/network/linux_net.py: 'ovs-ofctl', ....
    filters.CommandFilter("/usr/bin/ovs-ofctl", "root"),
    ]
