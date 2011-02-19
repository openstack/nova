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

import inspect
import os

from eventlet import semaphore

from nova import db
from nova import exception
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
flags.DEFINE_string('dhcp_domain',
                    'novalocal',
                    'domain to use for building the hostnames')

flags.DEFINE_string('networks_path', '$state_path/networks',
                    'Location to keep network config files')
flags.DEFINE_string('public_interface', 'eth0',
                    'Interface for public IP addresses')
flags.DEFINE_string('vlan_interface', 'eth0',
                    'network device for vlans')
flags.DEFINE_string('dhcpbridge', _bin_file('nova-dhcpbridge'),
                        'location of nova-dhcpbridge')
flags.DEFINE_string('routing_source_ip', '$my_ip',
                    'Public IP of network host')
flags.DEFINE_bool('use_nova_chains', False,
                  'use the nova_ routing chains instead of default')
flags.DEFINE_string('input_chain', 'INPUT',
                    'chain to add nova_input to')

flags.DEFINE_string('dns_server', None,
                    'if set, uses specific dns server for dnsmasq')
flags.DEFINE_string('dmz_cidr', '10.128.0.0/24',
                    'dmz range that should be accepted')


binary_name = os.path.basename(inspect.stack()[-1][1])


class IptablesRule(object):
    def __init__(self, chain, rule, wrap=True):
        self.chain = chain
        self.rule = rule
        self.wrap = wrap

    def __eq__(self, other):
        return ((self.chain == other.chain) and
                (self.rule == other.rule) and
                (self.wrap == other.wrap))

    def __ne__(self, other):
        return ((self.chain != other.chain) or
                (self.rule != other.rule) or
                (self.wrap != other.wrap))

    def __str__(self):
        if self.wrap:
            chain = '%s-%s' % (binary_name, self.chain)
        else:
            chain = self.chain
        return '-A %s %s' % (chain, self.rule)


class IptablesTable(object):
    def __init__(self):
        self.rules = []
        self.chains = set()

    def add_chain(self, name):
        self.chains.add(name)

    def remove_chain(self, name):
        self.chains.remove(name)
        self.rules = filter(lambda r: r.chain != name, self.rules)

    def add_rule(self, chain, rule, wrap=True):
        if wrap and chain not in self.chains:
            raise ValueError(_("Unknown chain: %r") % chain)

        if '$' in rule:
            rule = ' '.join(map(self._wrap_target_chain, rule.split(' ')))

        self.rules.append(IptablesRule(chain, rule, wrap))

    def _wrap_target_chain(self, s):
        if s.startswith('$'):
            return '%s-%s' % (binary_name, s[1:])
        return s

    def remove_rule(self, chain, rule):
        self.rules.remove(IptablesRule(chain, rule))

class IptablesManager(object):
    def __init__(self, execute=None):
        if not execute:
            if FLAGS.fake_network:
                self.execute = lambda *args, **kwargs: ('', '')
            else:
                self.execute = utils.execute
        else:
            self.execute = execute

        self.ipv4 = { 'filter': IptablesTable(),
                      'nat': IptablesTable() }
        self.ipv6 = { 'filter': IptablesTable() }

        self.ipv4['nat'].add_chain('SNATTING')
        self.ipv4['nat'].add_rule('POSTROUTING',
                                  '-j %s-SNATTING' % (binary_name,),
                                  wrap=False)

        self.ipv4['filter'].add_chain('local')
        self.ipv4['filter'].add_rule('FORWARD',
                                    '-j %s-local' % (binary_name,),
                                    wrap=False)

        self.ipv4['filter'].add_rule('OUTPUT',
                                    '-j %s-local' % (binary_name,),
                                    wrap=False)

        # Wrap the builtin chains
        builtin_chains = {'filter': ['INPUT', 'OUTPUT', 'FORWARD'],
                          'nat': ['PREROUTING', 'OUTPUT', 'POSTROUTING']}

        for table, chains in builtin_chains.iteritems():
            for chain in chains:
                self.ipv4[table].add_chain(chain)
                self.ipv4[table].add_rule(chain,
                                          '-j %s-%s' % (binary_name, chain),
                                          wrap=False)
        self.semaphore = semaphore.Semaphore()


    def apply(self):
        with self.semaphore:
            s = [('iptables', self.ipv4)]
            if FLAGS.use_ipv6:
                s += [('ip6tables', self.ipv6)]

            for cmd, tables in s:
                for table in tables:
                    current_table, _ = self.execute('sudo %s-save -t %s' %
                                                    (cmd, table), attempts=5)
                    current_lines = current_table.split('\n')
                    new_filter = self.modify_rules(current_lines, tables[table])
                    self.execute('sudo %s-restore' % (cmd,),
                                 process_input='\n'.join(new_filter),
                                 attempts=5)

    def modify_rules(self, current_lines, table, binary=None):

        chains = table.chains
        rules = table.rules

        # Remove any trace of our rules
        new_filter = filter(lambda l: binary_name not in l, current_lines)

        seen_chains = False
        for rules_index in range(len(new_filter)):
            if not seen_chains:
                if new_filter[rules_index].startswith(':'):
                    seen_chains = True
            elif seen_chains == 1:
                if not new_filter[rules_index].startswith(':'):
                    break

        new_filter[rules_index:rules_index] = [str(rule) for rule in rules]
        new_filter[rules_index:rules_index] = [':%s-%s - [0:0]' % \
                                               (binary_name, name,) \
                                               for name in chains]

        return new_filter


iptables_manager = IptablesManager()


def metadata_forward():
    """Create forwarding rule for metadata"""
    iptables_manager.ipv4['nat'].add_rule("PREROUTING",
                                          "-s 0.0.0.0/0 -d 169.254.169.254/32 "
                                          "-p tcp -m tcp --dport 80 -j DNAT "
                                          "--to-destination %s:%s" % \
                                          (FLAGS.ec2_dmz_host, FLAGS.ec2_port))
    iptables_manager.apply()


def init_host():
    """Basic networking setup goes here"""

    # NOTE(devcamcar): Cloud public SNAT entries and the default
    # SNAT rule for outbound traffic.
    iptables_manager.ipv4['nat'].add_rule("SNATTING",
                                          "-s %s -j SNAT --to-source %s" % \
                                           (FLAGS.fixed_range,
                                            FLAGS.routing_source_ip))

    iptables_manager.ipv4['nat'].add_rule("POSTROUTING",
                                          "-s %s -j SNAT --to-source %s" % \
                                           (FLAGS.fixed_range,
                                            FLAGS.routing_source_ip))

    iptables_manager.ipv4['nat'].add_rule("POSTROUTING",
                                          "-s %s -d %s -j ACCEPT" % \
                                          (FLAGS.fixed_range, FLAGS.dmz_cidr))

    iptables_manager.ipv4['nat'].add_rule("POSTROUTING",
                                          "-s %(range)s -d %(range)s "
                                          "-j ACCEPT" % \
                                          {'range': FLAGS.fixed_range})
    iptables_manager.apply()


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
    iptables_manager.ipv4['filter'].add_rule("FORWARD",
                                             "-d %s -p udp "
                                             "--dport 1194 "
                                             "-j ACCEPT" % private_ip)
    iptables_manager.ipv4['nat'].add_rule("PREROUTING",
                                          "-d %s -p udp "
                                          "--dport %s -j DNAT --to %s:1194" %
                                          (public_ip, port, private_ip))
    iptables_manager.apply()


def ensure_floating_forward(floating_ip, fixed_ip):
    """Ensure floating ip forwarding rule"""
    for chain, rule in floating_forward_rules(floating_ip, fixed_ip):
        iptables_manager.ipv4['nat'].add_rule(chain, rule)
    iptables_manager.apply()

def remove_floating_forward(floating_ip, fixed_ip):
    """Remove forwarding for floating ip"""
    for chain, rule in floating_forward_rules(floating_ip, fixed_ip):
        iptables_manager.ipv4['nat'].remove_rule(chain, rule)
    iptables_manager.apply()

def floating_forward_rules(floating_ip, fixed_ip):
    return [("PREROUTING", "-d %s -j DNAT --to %s" % (floating_ip, fixed_ip)),
            ("OUTPUT", "-d %s -j DNAT --to %s" % (floating_ip, fixed_ip)),
            ("SNATTING", "-d %s -j DNAT --to %s" % (fixed_ip, floating_ip))]

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
        _execute("sudo ip link set %s up" % interface)
    return interface


def ensure_bridge(bridge, interface, net_attrs=None):
    """Create a bridge unless it already exists.

    :param interface: the interface to create the bridge on.
    :param net_attrs: dictionary with  attributes used to create the bridge.

    If net_attrs is set, it will add the net_attrs['gateway'] to the bridge
    using net_attrs['broadcast'] and net_attrs['cidr'].  It will also add
    the ip_v6 address specified in net_attrs['cidr_v6'] if use_ipv6 is set.

    The code will attempt to move any ips that already exist on the interface
    onto the bridge and reset the default gateway if necessary.
    """
    if not _device_exists(bridge):
        LOG.debug(_("Starting Bridge interface for %s"), interface)
        _execute("sudo brctl addbr %s" % bridge)
        _execute("sudo brctl setfd %s 0" % bridge)
        # _execute("sudo brctl setageing %s 10" % bridge)
        _execute("sudo brctl stp %s off" % bridge)
        _execute("sudo ip link set %s up" % bridge)
    if net_attrs:
        # NOTE(vish): The ip for dnsmasq has to be the first address on the
        #             bridge for it to respond to reqests properly
        suffix = net_attrs['cidr'].rpartition('/')[2]
        out, err = _execute("sudo ip addr add %s/%s brd %s dev %s" %
                            (net_attrs['gateway'],
                             suffix,
                             net_attrs['broadcast'],
                             bridge),
                            check_exit_code=False)
        if err and err != "RTNETLINK answers: File exists\n":
            raise exception.Error("Failed to add ip: %s" % err)
        if(FLAGS.use_ipv6):
            _execute("sudo ip -f inet6 addr change %s dev %s" %
                     (net_attrs['cidr_v6'], bridge))
        # NOTE(vish): If the public interface is the same as the
        #             bridge, then the bridge has to be in promiscuous
        #             to forward packets properly.
        if(FLAGS.public_interface == bridge):
            _execute("sudo ip link set dev %s promisc on" % bridge)
    if interface:
        # NOTE(vish): This will break if there is already an ip on the
        #             interface, so we move any ips to the bridge
        gateway = None
        out, err = _execute("sudo route -n")
        for line in out.split("\n"):
            fields = line.split()
            if fields and fields[0] == "0.0.0.0" and fields[-1] == interface:
                gateway = fields[1]
        out, err = _execute("sudo ip addr show dev %s scope global" %
                            interface)
        for line in out.split("\n"):
            fields = line.split()
            if fields and fields[0] == "inet":
                params = ' '.join(fields[1:-1])
                _execute("sudo ip addr del %s dev %s" % (params, fields[-1]))
                _execute("sudo ip addr add %s dev %s" % (params, bridge))
        if gateway:
            _execute("sudo route add 0.0.0.0 gw %s" % gateway)
        out, err = _execute("sudo brctl addif %s %s" %
                            (bridge, interface),
                            check_exit_code=False)

        if (err and err != "device %s is already a member of a bridge; can't "
                           "enslave it to bridge %s.\n" % (interface, bridge)):
            raise exception.Error("Failed to add interface: %s" % err)

    iptables_manager.ipv4['filter'].add_rule("FORWARD",
                                             "--in-interface %s -j ACCEPT" % \
                                             bridge)
    iptables_manager.ipv4['filter'].add_rule("FORWARD",
                                             "--out-interface %s -j ACCEPT" % \
                                             bridge)


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
    return "%s,%s.%s,%s" % (instance_ref['mac_address'],
                                   instance_ref['hostname'],
                                   FLAGS.dhcp_domain,
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
    (_out, err) = _execute("ip link show dev %s" % device,
                           check_exit_code=False)
    return not err


def _dnsmasq_cmd(net):
    """Builds dnsmasq command"""
    cmd = ['sudo -E dnsmasq',
           ' --strict-order',
           ' --bind-interfaces',
           ' --conf-file=',
           ' --domain=%s' % FLAGS.dhcp_domain,
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
