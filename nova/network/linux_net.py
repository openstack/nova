# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Implements vlans, bridges, and iptables rules using linux utilities.
"""

import logging
import signal
import os

# todo(ja): does the definition of network_path belong here?

from nova import flags
from nova import utils

FLAGS = flags.FLAGS

flags.DEFINE_string('dhcpbridge_flagfile',
                    '/etc/nova/nova-dhcpbridge.conf',
                    'location of flagfile for dhcpbridge')


def execute(cmd, addl_env=None):
    """Wrapper around utils.execute for fake_network"""
    if FLAGS.fake_network:
        logging.debug("FAKE NET: %s", cmd)
        return "fake", 0
    else:
        return utils.execute(cmd, addl_env=addl_env)


def runthis(desc, cmd):
    """Wrapper around utils.runthis for fake_network"""
    if FLAGS.fake_network:
        return execute(cmd)
    else:
        return utils.runthis(desc, cmd)


def device_exists(device):
    """Check if ethernet device exists"""
    (_out, err) = execute("ifconfig %s" % device)
    return not err


def confirm_rule(cmd):
    """Delete and re-add iptables rule"""
    execute("sudo iptables --delete %s" % (cmd))
    execute("sudo iptables -I %s" % (cmd))


def remove_rule(cmd):
    """Remove iptables rule"""
    execute("sudo iptables --delete %s" % (cmd))


def bind_public_ip(public_ip, interface):
    """Bind ip to an interface"""
    runthis("Binding IP to interface: %s",
            "sudo ip addr add %s dev %s" % (public_ip, interface))


def unbind_public_ip(public_ip, interface):
    """Unbind a public ip from an interface"""
    runthis("Binding IP to interface: %s",
            "sudo ip addr del %s dev %s" % (public_ip, interface))


def vlan_create(net):
    """Create a vlan on on a bridge device unless vlan already exists"""
    if not device_exists("vlan%s" % net['vlan']):
        logging.debug("Starting VLAN inteface for %s network", (net['vlan']))
        execute("sudo vconfig set_name_type VLAN_PLUS_VID_NO_PAD")
        execute("sudo vconfig add %s %s" % (FLAGS.bridge_dev, net['vlan']))
        execute("sudo ifconfig vlan%s up" % (net['vlan']))


def bridge_create(net):
    """Create a bridge on a vlan unless it already exists"""
    if not device_exists(net['bridge_name']):
        logging.debug("Starting Bridge inteface for %s network", (net['vlan']))
        execute("sudo brctl addbr %s" % (net['bridge_name']))
        execute("sudo brctl setfd %s 0" % (net.bridge_name))
        # execute("sudo brctl setageing %s 10" % (net.bridge_name))
        execute("sudo brctl stp %s off" % (net['bridge_name']))
        execute("sudo brctl addif %s vlan%s" % (net['bridge_name'],
                                                net['vlan']))
        if net.bridge_gets_ip:
            execute("sudo ifconfig %s %s broadcast %s netmask %s up" % \
                (net['bridge_name'], net.gateway, net.broadcast, net.netmask))
            confirm_rule("FORWARD --in-interface %s -j ACCEPT" %
                         (net['bridge_name']))
        else:
            execute("sudo ifconfig %s up" % net['bridge_name'])


def _dnsmasq_cmd(net):
    """Builds dnsmasq command"""
    cmd = ['sudo -E dnsmasq',
        ' --strict-order',
        ' --bind-interfaces',
        ' --conf-file=',
        ' --pid-file=%s' % dhcp_file(net['vlan'], 'pid'),
        ' --listen-address=%s' % net.dhcp_listen_address,
        ' --except-interface=lo',
        ' --dhcp-range=%s,static,120s' % net.dhcp_range_start,
        ' --dhcp-hostsfile=%s' % dhcp_file(net['vlan'], 'conf'),
        ' --dhcp-script=%s' % bin_file('nova-dhcpbridge'),
        ' --leasefile-ro']
    return ''.join(cmd)


def host_dhcp(address):
    """Return a host string for an address object"""
    return "%s,%s.novalocal,%s" % (address['mac'],
                                   address['hostname'],
                                   address.address)


# TODO(ja): if the system has restarted or pid numbers have wrapped
#           then you cannot be certain that the pid refers to the
#           dnsmasq.  As well, sending a HUP only reloads the hostfile,
#           so any configuration options (like dchp-range, vlan, ...)
#           aren't reloaded
def start_dnsmasq(network):
    """(Re)starts a dnsmasq server for a given network

    if a dnsmasq instance is already running then send a HUP
    signal causing it to reload, otherwise spawn a new instance
    """
    with open(dhcp_file(network['vlan'], 'conf'), 'w') as f:
        for address in network.assigned_objs:
            f.write("%s\n" % host_dhcp(address))

    pid = dnsmasq_pid_for(network)

    # if dnsmasq is already running, then tell it to reload
    if pid:
        # TODO(ja): use "/proc/%d/cmdline" % (pid) to determine if pid refers
        #           correct dnsmasq process
        try:
            os.kill(pid, signal.SIGHUP)
            return
        except Exception as exc:  # pylint: disable=W0703
            logging.debug("Hupping dnsmasq threw %s", exc)

    # FLAGFILE and DNSMASQ_INTERFACE in env
    env = {'FLAGFILE': FLAGS.dhcpbridge_flagfile,
           'DNSMASQ_INTERFACE': network['bridge_name']}
    execute(_dnsmasq_cmd(network), addl_env=env)


def stop_dnsmasq(network):
    """Stops the dnsmasq instance for a given network"""
    pid = dnsmasq_pid_for(network)

    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as exc:  # pylint: disable=W0703
            logging.debug("Killing dnsmasq threw %s", exc)


def dhcp_file(vlan, kind):
    """Return path to a pid, leases or conf file for a vlan"""

    return os.path.abspath("%s/nova-%s.%s" % (FLAGS.networks_path, vlan, kind))


def bin_file(script):
    """Return the absolute path to scipt in the bin directory"""
    return os.path.abspath(os.path.join(__file__, "../../../bin", script))


def dnsmasq_pid_for(network):
    """Returns he pid for prior dnsmasq instance for a vlan

    Returns None if no pid file exists

    If machine has rebooted pid might be incorrect (caller should check)
    """

    pid_file = dhcp_file(network['vlan'], 'pid')

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            return int(f.read())
