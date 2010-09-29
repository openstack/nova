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
import os
import signal

# TODO(ja): does the definition of network_path belong here?

from nova import db
from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('dhcpbridge_flagfile',
                    '/etc/nova/nova-dhcpbridge.conf',
                    'location of flagfile for dhcpbridge')

flags.DEFINE_string('networks_path', utils.abspath('../networks'),
                    'Location to keep network config files')
flags.DEFINE_string('public_interface', 'vlan1',
                    'Interface for public IP addresses')
flags.DEFINE_string('bridge_dev', 'eth0',
                    'network device for bridges')
flags.DEFINE_string('routing_source_ip', '127.0.0.1',
                    'Public IP of network host')
flags.DEFINE_bool('use_nova_chains', False,
                  'use the nova_ routing chains instead of default')

DEFAULT_PORTS = [("tcp", 80), ("tcp", 22), ("udp", 1194), ("tcp", 443)]

def init_host():
    """Basic networking setup goes here"""
    # NOTE(devcamcar): Cloud public DNAT entries, CloudPipe port
    # forwarding entries and a default DNAT entry.
    _confirm_rule("PREROUTING", "-t nat -s 0.0.0.0/0 "
             "-d 169.254.169.254/32 -p tcp -m tcp --dport 80 -j DNAT "
             "--to-destination %s:%s" % (FLAGS.cc_host, FLAGS.cc_port))

    # NOTE(devcamcar): Cloud public SNAT entries and the default
    # SNAT rule for outbound traffic.
    _confirm_rule("POSTROUTING", "-t nat -s %s "
             "-j SNAT --to-source %s"
             % (FLAGS.private_range, FLAGS.routing_source_ip))

    _confirm_rule("POSTROUTING", "-t nat -s %s -j MASQUERADE" %
                  FLAGS.private_range)
    _confirm_rule("POSTROUTING", "-t nat -s %(range)s -d %(range)s -j ACCEPT" %
                  {'range': FLAGS.private_range})

def bind_floating_ip(floating_ip):
    """Bind ip to public interface"""
    _execute("sudo ip addr add %s dev %s" % (floating_ip,
                                             FLAGS.public_interface))


def unbind_floating_ip(floating_ip):
    """Unbind a public ip from public interface"""
    _execute("sudo ip addr del %s dev %s" % (floating_ip,
                                             FLAGS.public_interface))


def ensure_vlan_forward(public_ip, port, private_ip):
    """Sets up forwarding rules for vlan"""
    _confirm_rule("FORWARD", "-d %s -p udp --dport 1194 -j ACCEPT" %
                  private_ip)
    _confirm_rule("PREROUTING",
                  "-t nat -d %s -p udp --dport %s -j DNAT --to %s:1194"
            % (public_ip, port, private_ip))


def ensure_floating_forward(floating_ip, fixed_ip):
    """Ensure floating ip forwarding rule"""
    _confirm_rule("PREROUTING", "-t nat -d %s -j DNAT --to %s"
                           % (floating_ip, fixed_ip))
    _confirm_rule("POSTROUTING", "-t nat -s %s -j SNAT --to %s"
                           % (fixed_ip, floating_ip))
    # TODO(joshua): Get these from the secgroup datastore entries
    _confirm_rule("FORWARD", "-d %s -p icmp -j ACCEPT"
                           % (fixed_ip))
    for (protocol, port) in DEFAULT_PORTS:
        _confirm_rule("FORWARD","-d %s -p %s --dport %s -j ACCEPT"
            % (fixed_ip, protocol, port))


def remove_floating_forward(floating_ip, fixed_ip):
    """Remove forwarding for floating ip"""
    _remove_rule("PREROUTING", "-t nat -d %s -j DNAT --to %s"
                          % (floating_ip, fixed_ip))
    _remove_rule("POSTROUTING", "-t nat -s %s -j SNAT --to %s"
                          % (fixed_ip, floating_ip))
    _remove_rule("FORWARD", "-d %s -p icmp -j ACCEPT"
                          % (fixed_ip))
    for (protocol, port) in DEFAULT_PORTS:
        _remove_rule("FORWARD", "-d %s -p %s --dport %s -j ACCEPT"
                              % (fixed_ip, protocol, port))


def ensure_vlan_bridge(vlan_num, bridge, net_attrs=None):
    """Create a vlan and bridge unless they already exist"""
    interface = ensure_vlan(vlan_num)
    ensure_bridge(bridge, interface, net_attrs)


def ensure_vlan(vlan_num):
    """Create a vlan unless it already exists"""
    interface = "vlan%s" % vlan_num
    if not _device_exists(interface):
        logging.debug("Starting VLAN inteface %s", interface)
        _execute("sudo vconfig set_name_type VLAN_PLUS_VID_NO_PAD")
        _execute("sudo vconfig add %s %s" % (FLAGS.bridge_dev, vlan_num))
        _execute("sudo ifconfig %s up" % interface)
    return interface


def ensure_bridge(bridge, interface, net_attrs=None):
    """Create a bridge unless it already exists"""
    if not _device_exists(bridge):
        logging.debug("Starting Bridge inteface for %s", interface)
        _execute("sudo brctl addbr %s" % bridge)
        _execute("sudo brctl setfd %s 0" % bridge)
        # _execute("sudo brctl setageing %s 10" % bridge)
        _execute("sudo brctl stp %s off" % bridge)
        _execute("sudo brctl addif %s %s" % (bridge, interface))
        if net_attrs:
            _execute("sudo ifconfig %s %s broadcast %s netmask %s up" % \
                    (bridge,
                     net_attrs['gateway'],
                     net_attrs['broadcast'],
                     net_attrs['netmask']))
        else:
            _execute("sudo ifconfig %s up" % bridge)
        _confirm_rule("FORWARD", "--in-interface %s -j ACCEPT" % bridge)
        _confirm_rule("FORWARD", "--out-interface %s -j ACCEPT" % bridge)


def get_dhcp_hosts(context, network_id):
    """Get a string containing a network's hosts config in dnsmasq format"""
    hosts = []
    for fixed_ip in db.network_get_associated_fixed_ips(context, network_id):
        hosts.append(_host_dhcp(fixed_ip['str_id']))
    return '\n'.join(hosts)


# TODO(ja): if the system has restarted or pid numbers have wrapped
#           then you cannot be certain that the pid refers to the
#           dnsmasq.  As well, sending a HUP only reloads the hostfile,
#           so any configuration options (like dchp-range, vlan, ...)
#           aren't reloaded
def update_dhcp(context, network_id):
    """(Re)starts a dnsmasq server for a given network

    if a dnsmasq instance is already running then send a HUP
    signal causing it to reload, otherwise spawn a new instance
    """
    network_ref = db.network_get(context, network_id)
    with open(_dhcp_file(network_ref['vlan'], 'conf'), 'w') as f:
        f.write(get_dhcp_hosts(context, network_id))

    pid = _dnsmasq_pid_for(network_ref['vlan'])

    # if dnsmasq is already running, then tell it to reload
    if pid:
        # TODO(ja): use "/proc/%d/cmdline" % (pid) to determine if pid refers
        #           correct dnsmasq process
        try:
            os.kill(pid, signal.SIGHUP)
            return
        except Exception as exc:  # pylint: disable-msg=W0703
            logging.debug("Hupping dnsmasq threw %s", exc)

    # FLAGFILE and DNSMASQ_INTERFACE in env
    env = {'FLAGFILE': FLAGS.dhcpbridge_flagfile,
           'DNSMASQ_INTERFACE': network_ref['bridge']}
    command = _dnsmasq_cmd(network_ref)
    _execute(command, addl_env=env)


def _host_dhcp(address):
    """Return a host string for an address"""
    instance_ref = db.fixed_ip_get_instance(None, address)
    return "%s,%s.novalocal,%s" % (instance_ref['mac_address'],
                                   instance_ref['hostname'],
                                   address)


def _execute(cmd, *args, **kwargs):
    """Wrapper around utils._execute for fake_network"""
    if FLAGS.fake_network:
        logging.debug("FAKE NET: %s", cmd)
        return "fake", 0
    else:
        return utils.execute(cmd, *args, **kwargs)


def _device_exists(device):
    """Check if ethernet device exists"""
    (_out, err) = _execute("ifconfig %s" % device, check_exit_code=False)
    return not err


def _confirm_rule(chain, cmd):
    """Delete and re-add iptables rule"""
    if FLAGS.use_nova_chains:
        chain = "nova_%s" % chain.lower()
    _execute("sudo iptables --delete %s %s" % (chain, cmd), check_exit_code=False)
    _execute("sudo iptables -I %s %s" % (chain, cmd))


def _remove_rule(chain, cmd):
    """Remove iptables rule"""
    if FLAGS.use_nova_chains:
        chain = "%S" % chain.lower()
    _execute("sudo iptables --delete %s %s" % (chain, cmd))


def _dnsmasq_cmd(net):
    """Builds dnsmasq command"""
    cmd = ['sudo -E dnsmasq',
           ' --strict-order',
           ' --bind-interfaces',
           ' --conf-file=',
           ' --pid-file=%s' % _dhcp_file(net['vlan'], 'pid'),
           ' --listen-address=%s' % net['gateway'],
           ' --except-interface=lo',
           ' --dhcp-range=%s,static,120s' % net['dhcp_start'],
           ' --dhcp-hostsfile=%s' % _dhcp_file(net['vlan'], 'conf'),
           ' --dhcp-script=%s' % _bin_file('nova-dhcpbridge'),
           ' --leasefile-ro']
    return ''.join(cmd)


def _stop_dnsmasq(network):
    """Stops the dnsmasq instance for a given network"""
    pid = _dnsmasq_pid_for(network)

    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as exc:  # pylint: disable-msg=W0703
            logging.debug("Killing dnsmasq threw %s", exc)


def _dhcp_file(vlan, kind):
    """Return path to a pid, leases or conf file for a vlan"""

    return os.path.abspath("%s/nova-%s.%s" % (FLAGS.networks_path, vlan, kind))


def _bin_file(script):
    """Return the absolute path to scipt in the bin directory"""
    return os.path.abspath(os.path.join(__file__, "../../../bin", script))


def _dnsmasq_pid_for(vlan):
    """Returns he pid for prior dnsmasq instance for a vlan

    Returns None if no pid file exists

    If machine has rebooted pid might be incorrect (caller should check)
    """

    pid_file = _dhcp_file(vlan, 'pid')

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            return int(f.read())
