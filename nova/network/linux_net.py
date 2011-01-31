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

import os

from nova import db
from nova import flags
from nova import log as logging
from nova import utils


LOG = logging.getLogger("nova.linux_net")


def _bin_file(script):
    """Return the absolute path to scipt in the bin directory"""
    return os.path.abspath(os.path.join(__file__, "../../../bin", script))


FLAGS = flags.FLAGS
flags.DEFINE_string('dhcpbridge_flagfile',
                    '/etc/nova/nova-dhcpbridge.conf',
                    'location of flagfile for dhcpbridge')

flags.DEFINE_string('networks_path', '$state_path/networks',
                    'Location to keep network config files')
flags.DEFINE_string('public_interface', 'vlan1',
                    'Interface for public IP addresses')
flags.DEFINE_string('vlan_interface', 'eth0',
                    'network device for vlans')
flags.DEFINE_string('dhcpbridge', _bin_file('nova-dhcpbridge'),
                        'location of nova-dhcpbridge')
flags.DEFINE_string('routing_source_ip', '$my_ip',
                    'Public IP of network host')
flags.DEFINE_bool('use_nova_chains', False,
                  'use the nova_ routing chains instead of default')

flags.DEFINE_string('dns_server', None,
                    'if set, uses specific dns server for dnsmasq')
flags.DEFINE_string('dmz_cidr', '10.128.0.0/24',
                    'dmz range that should be accepted')


def metadata_forward():
    """Create forwarding rule for metadata"""
    _confirm_rule("PREROUTING", "-t nat -s 0.0.0.0/0 "
             "-d 169.254.169.254/32 -p tcp -m tcp --dport 80 -j DNAT "
             "--to-destination %s:%s" % (FLAGS.ec2_dmz_host, FLAGS.ec2_port))


def init_host():
    """Basic networking setup goes here"""

    if FLAGS.use_nova_chains:
        _execute("sudo iptables -N nova_input", check_exit_code=False)
        _execute("sudo iptables -D %s -j nova_input" % FLAGS.input_chain,
                 check_exit_code=False)
        _execute("sudo iptables -A %s -j nova_input" % FLAGS.input_chain)

        _execute("sudo iptables -N nova_forward", check_exit_code=False)
        _execute("sudo iptables -D FORWARD -j nova_forward",
                 check_exit_code=False)
        _execute("sudo iptables -A FORWARD -j nova_forward")

        _execute("sudo iptables -N nova_output", check_exit_code=False)
        _execute("sudo iptables -D OUTPUT -j nova_output",
                 check_exit_code=False)
        _execute("sudo iptables -A OUTPUT -j nova_output")

        _execute("sudo iptables -t nat -N nova_prerouting",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -D PREROUTING -j nova_prerouting",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -A PREROUTING -j nova_prerouting")

        _execute("sudo iptables -t nat -N nova_postrouting",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -D POSTROUTING -j nova_postrouting",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -A POSTROUTING -j nova_postrouting")

        _execute("sudo iptables -t nat -N nova_snatting",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -D POSTROUTING -j nova_snatting",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -A POSTROUTING -j nova_snatting")

        _execute("sudo iptables -t nat -N nova_output", check_exit_code=False)
        _execute("sudo iptables -t nat -D OUTPUT -j nova_output",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -A OUTPUT -j nova_output")
    else:
        # NOTE(vish): This makes it easy to ensure snatting rules always
        #             come after the accept rules in the postrouting chain
        _execute("sudo iptables -t nat -N SNATTING",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -D POSTROUTING -j SNATTING",
                 check_exit_code=False)
        _execute("sudo iptables -t nat -A POSTROUTING -j SNATTING")

    # NOTE(devcamcar): Cloud public SNAT entries and the default
    # SNAT rule for outbound traffic.
    _confirm_rule("SNATTING", "-t nat -s %s "
             "-j SNAT --to-source %s"
             % (FLAGS.fixed_range, FLAGS.routing_source_ip), append=True)

    _confirm_rule("POSTROUTING", "-t nat -s %s -d %s -j ACCEPT" %
                  (FLAGS.fixed_range, FLAGS.dmz_cidr))
    _confirm_rule("POSTROUTING", "-t nat -s %(range)s -d %(range)s -j ACCEPT" %
                  {'range': FLAGS.fixed_range})


def bind_floating_ip(floating_ip, check_exit_code=True):
    """Bind ip to public interface"""
    _execute("sudo ip addr add %s dev %s" % (floating_ip,
                                             FLAGS.public_interface),
             check_exit_code=check_exit_code)


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
    _confirm_rule("SNATTING", "-t nat -s %s -j SNAT --to %s"
                           % (fixed_ip, floating_ip))


def remove_floating_forward(floating_ip, fixed_ip):
    """Remove forwarding for floating ip"""
    _remove_rule("PREROUTING", "-t nat -d %s -j DNAT --to %s"
                          % (floating_ip, fixed_ip))
    _remove_rule("SNATTING", "-t nat -s %s -j SNAT --to %s"
                          % (fixed_ip, floating_ip))


def ensure_vlan_bridge(vlan_num, bridge, net_attrs=None):
    """Create a vlan and bridge unless they already exist"""
    interface = ensure_vlan(vlan_num)
    ensure_bridge(bridge, interface, net_attrs)


def ensure_vlan(vlan_num):
    """Create a vlan unless it already exists"""
    interface = "vlan%s" % vlan_num
    if not _device_exists(interface):
        LOG.debug(_("Starting VLAN inteface %s"), interface)
        _execute("sudo vconfig set_name_type VLAN_PLUS_VID_NO_PAD")
        _execute("sudo vconfig add %s %s" % (FLAGS.vlan_interface, vlan_num))
        _execute("sudo ifconfig %s up" % interface)
    return interface


def ensure_bridge(bridge, interface, net_attrs=None):
    """Create a bridge unless it already exists"""
    if not _device_exists(bridge):
        LOG.debug(_("Starting Bridge interface for %s"), interface)
        _execute("sudo brctl addbr %s" % bridge)
        _execute("sudo brctl setfd %s 0" % bridge)
        # _execute("sudo brctl setageing %s 10" % bridge)
        _execute("sudo brctl stp %s off" % bridge)
        if interface:
            _execute("sudo brctl addif %s %s" % (bridge, interface))
        _execute("sudo ifconfig %s up" % bridge)
    if net_attrs:
        # NOTE(vish): use ip addr add so it doesn't overwrite
        #             manual addresses on the bridge.
        suffix = net_attrs['cidr'].rpartition('/')[2]
        _execute("sudo ip addr add %s/%s brd %s dev %s" %
                (net_attrs['gateway'],
                 suffix,
                 net_attrs['broadcast'],
                 bridge))
        if(FLAGS.use_ipv6):
            _execute("sudo ip -f inet6 addr change %s dev %s" %
                     (net_attrs['cidr_v6'], bridge))
    if FLAGS.use_nova_chains:
        (out, err) = _execute("sudo iptables -N nova_forward",
                              check_exit_code=False)
        if err != 'iptables: Chain already exists.\n':
            # NOTE(vish): chain didn't exist link chain
            _execute("sudo iptables -D FORWARD -j nova_forward",
                     check_exit_code=False)
            _execute("sudo iptables -A FORWARD -j nova_forward")

    _confirm_rule("FORWARD", "--in-interface %s -j ACCEPT" % bridge)
    _confirm_rule("FORWARD", "--out-interface %s -j ACCEPT" % bridge)
    _execute("sudo iptables -N nova-local", check_exit_code=False)
    _confirm_rule("FORWARD", "-j nova-local")


def get_dhcp_hosts(context, network_id):
    """Get a string containing a network's hosts config in dnsmasq format"""
    hosts = []
    for fixed_ip_ref in db.network_get_associated_fixed_ips(context,
                                                            network_id):
        hosts.append(_host_dhcp(fixed_ip_ref))
    return '\n'.join(hosts)


# NOTE(ja): Sending a HUP only reloads the hostfile, so any
#           configuration options (like dchp-range, vlan, ...)
#           aren't reloaded.
def update_dhcp(context, network_id):
    """(Re)starts a dnsmasq server for a given network

    if a dnsmasq instance is already running then send a HUP
    signal causing it to reload, otherwise spawn a new instance
    """
    network_ref = db.network_get(context, network_id)

    conffile = _dhcp_file(network_ref['bridge'], 'conf')
    with open(conffile, 'w') as f:
        f.write(get_dhcp_hosts(context, network_id))

    # Make sure dnsmasq can actually read it (it setuid()s to "nobody")
    os.chmod(conffile, 0644)

    pid = _dnsmasq_pid_for(network_ref['bridge'])

    # if dnsmasq is already running, then tell it to reload
    if pid:
        out, _err = _execute('cat /proc/%d/cmdline' % pid,
                             check_exit_code=False)
        if conffile in out:
            try:
                _execute('sudo kill -HUP %d' % pid)
                return
            except Exception as exc:  # pylint: disable-msg=W0703
                LOG.debug(_("Hupping dnsmasq threw %s"), exc)
        else:
            LOG.debug(_("Pid %d is stale, relaunching dnsmasq"), pid)

    # FLAGFILE and DNSMASQ_INTERFACE in env
    env = {'FLAGFILE': FLAGS.dhcpbridge_flagfile,
           'DNSMASQ_INTERFACE': network_ref['bridge']}
    command = _dnsmasq_cmd(network_ref)
    _execute(command, addl_env=env)


def update_ra(context, network_id):
    network_ref = db.network_get(context, network_id)

    conffile = _ra_file(network_ref['bridge'], 'conf')
    with open(conffile, 'w') as f:
        conf_str = """
interface %s
{
   AdvSendAdvert on;
   MinRtrAdvInterval 3;
   MaxRtrAdvInterval 10;
   prefix %s
   {
        AdvOnLink on;
        AdvAutonomous on;
   };
};
""" % (network_ref['bridge'], network_ref['cidr_v6'])
        f.write(conf_str)

    # Make sure radvd can actually read it (it setuid()s to "nobody")
    os.chmod(conffile, 0644)

    pid = _ra_pid_for(network_ref['bridge'])

    # if radvd is already running, then tell it to reload
    if pid:
        out, _err = _execute('cat /proc/%d/cmdline'
                             % pid, check_exit_code=False)
        if conffile in out:
            try:
                _execute('sudo kill %d' % pid)
            except Exception as exc:  # pylint: disable-msg=W0703
                LOG.debug(_("killing radvd threw %s"), exc)
        else:
            LOG.debug(_("Pid %d is stale, relaunching radvd"), pid)
    command = _ra_cmd(network_ref)
    _execute(command)
    db.network_update(context, network_id,
                      {"ra_server":
                       utils.get_my_linklocal(network_ref['bridge'])})


def _host_dhcp(fixed_ip_ref):
    """Return a host string for an address"""
    instance_ref = fixed_ip_ref['instance']
    return "%s,%s.novalocal,%s" % (instance_ref['mac_address'],
                                   instance_ref['hostname'],
                                   fixed_ip_ref['address'])


def _execute(cmd, *args, **kwargs):
    """Wrapper around utils._execute for fake_network"""
    if FLAGS.fake_network:
        LOG.debug("FAKE NET: %s", cmd)
        return "fake", 0
    else:
        return utils.execute(cmd, *args, **kwargs)


def _device_exists(device):
    """Check if ethernet device exists"""
    (_out, err) = _execute("ifconfig %s" % device, check_exit_code=False)
    return not err


def _confirm_rule(chain, cmd, append=False):
    """Delete and re-add iptables rule"""
    if FLAGS.use_nova_chains:
        chain = "nova_%s" % chain.lower()
    if append:
        loc = "-A"
    else:
        loc = "-I"
    _execute("sudo iptables --delete %s %s" % (chain, cmd),
             check_exit_code=False)
    _execute("sudo iptables %s %s %s" % (loc, chain, cmd))


def _remove_rule(chain, cmd):
    """Remove iptables rule"""
    if FLAGS.use_nova_chains:
        chain = "%s" % chain.lower()
    _execute("sudo iptables --delete %s %s" % (chain, cmd))


def _dnsmasq_cmd(net):
    """Builds dnsmasq command"""
    cmd = ['sudo -E dnsmasq',
           ' --strict-order',
           ' --bind-interfaces',
           ' --conf-file=',
           ' --pid-file=%s' % _dhcp_file(net['bridge'], 'pid'),
           ' --listen-address=%s' % net['gateway'],
           ' --except-interface=lo',
           ' --dhcp-range=%s,static,120s' % net['dhcp_start'],
           ' --dhcp-hostsfile=%s' % _dhcp_file(net['bridge'], 'conf'),
           ' --dhcp-script=%s' % FLAGS.dhcpbridge,
           ' --leasefile-ro']
    if FLAGS.dns_server:
        cmd.append(' -h -R --server=%s' % FLAGS.dns_server)
    return ''.join(cmd)


def _ra_cmd(net):
    """Builds radvd command"""
    cmd = ['sudo -E radvd',
#           ' -u nobody',
           ' -C %s' % _ra_file(net['bridge'], 'conf'),
           ' -p %s' % _ra_file(net['bridge'], 'pid')]
    return ''.join(cmd)


def _stop_dnsmasq(network):
    """Stops the dnsmasq instance for a given network"""
    pid = _dnsmasq_pid_for(network)

    if pid:
        try:
            _execute('sudo kill -TERM %d' % pid)
        except Exception as exc:  # pylint: disable-msg=W0703
            LOG.debug(_("Killing dnsmasq threw %s"), exc)


def _dhcp_file(bridge, kind):
    """Return path to a pid, leases or conf file for a bridge"""

    if not os.path.exists(FLAGS.networks_path):
        os.makedirs(FLAGS.networks_path)
    return os.path.abspath("%s/nova-%s.%s" % (FLAGS.networks_path,
                                              bridge,
                                              kind))


def _ra_file(bridge, kind):
    """Return path to a pid or conf file for a bridge"""

    if not os.path.exists(FLAGS.networks_path):
        os.makedirs(FLAGS.networks_path)
    return os.path.abspath("%s/nova-ra-%s.%s" % (FLAGS.networks_path,
                                              bridge,
                                              kind))


def _dnsmasq_pid_for(bridge):
    """Returns the pid for prior dnsmasq instance for a bridge

    Returns None if no pid file exists

    If machine has rebooted pid might be incorrect (caller should check)
    """

    pid_file = _dhcp_file(bridge, 'pid')

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            return int(f.read())


def _ra_pid_for(bridge):
    """Returns the pid for prior radvd instance for a bridge

    Returns None if no pid file exists

    If machine has rebooted pid might be incorrect (caller should check)
    """

    pid_file = _ra_file(bridge, 'pid')

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            return int(f.read())
