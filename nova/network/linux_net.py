# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Implements vlans, bridges, and iptables rules using linux utilities."""

import calendar
import inspect
import netaddr
import os

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


LOG = logging.getLogger("nova.linux_net")


def _bin_file(script):
    """Return the absolute path to scipt in the bin directory."""
    return os.path.abspath(os.path.join(__file__, '../../../bin', script))


FLAGS = flags.FLAGS
flags.DEFINE_string('dhcpbridge_flagfile',
                    '/etc/nova/nova-dhcpbridge.conf',
                    'location of flagfile for dhcpbridge')
flags.DEFINE_string('networks_path', '$state_path/networks',
                    'Location to keep network config files')
flags.DEFINE_string('public_interface', 'eth0',
                    'Interface for public IP addresses')
flags.DEFINE_string('dhcpbridge', _bin_file('nova-dhcpbridge'),
                        'location of nova-dhcpbridge')
flags.DEFINE_string('routing_source_ip', '$my_ip',
                    'Public IP of network host')
flags.DEFINE_string('input_chain', 'INPUT',
                    'chain to add nova_input to')
flags.DEFINE_integer('dhcp_lease_time', 120,
                     'Lifetime of a DHCP lease')
flags.DEFINE_string('dns_server', None,
                    'if set, uses specific dns server for dnsmasq')
flags.DEFINE_string('dmz_cidr', '10.128.0.0/24',
                    'dmz range that should be accepted')
flags.DEFINE_string('dnsmasq_config_file', "",
                    'Override the default dnsmasq settings with this file')
flags.DEFINE_string('linuxnet_interface_driver',
                    'nova.network.linux_net.LinuxBridgeInterfaceDriver',
                    'Driver used to create ethernet devices.')
flags.DEFINE_string('linuxnet_ovs_integration_bridge',
                    'br-int', 'Name of Open vSwitch bridge used with linuxnet')
flags.DEFINE_bool('send_arp_for_ha', False,
                  'send gratuitous ARPs for HA setup')
flags.DEFINE_bool('use_single_default_gateway',
                   False, 'Use single default gateway. Only first nic of vm'
                          ' will get default gateway from dhcp server')
binary_name = os.path.basename(inspect.stack()[-1][1])


class IptablesRule(object):
    """An iptables rule.

    You shouldn't need to use this class directly, it's only used by
    IptablesManager.

    """

    def __init__(self, chain, rule, wrap=True, top=False):
        self.chain = chain
        self.rule = rule
        self.wrap = wrap
        self.top = top

    def __eq__(self, other):
        return ((self.chain == other.chain) and
                (self.rule == other.rule) and
                (self.top == other.top) and
                (self.wrap == other.wrap))

    def __ne__(self, other):
        return not self == other

    def __str__(self):
        if self.wrap:
            chain = '%s-%s' % (binary_name, self.chain)
        else:
            chain = self.chain
        return '-A %s %s' % (chain, self.rule)


class IptablesTable(object):
    """An iptables table."""

    def __init__(self):
        self.rules = []
        self.chains = set()
        self.unwrapped_chains = set()

    def add_chain(self, name, wrap=True):
        """Adds a named chain to the table.

        The chain name is wrapped to be unique for the component creating
        it, so different components of Nova can safely create identically
        named chains without interfering with one another.

        At the moment, its wrapped name is <binary name>-<chain name>,
        so if nova-compute creates a chain named 'OUTPUT', it'll actually
        end up named 'nova-compute-OUTPUT'.

        """
        if wrap:
            self.chains.add(name)
        else:
            self.unwrapped_chains.add(name)

    def remove_chain(self, name, wrap=True):
        """Remove named chain.

        This removal "cascades". All rule in the chain are removed, as are
        all rules in other chains that jump to it.

        If the chain is not found, this is merely logged.

        """
        if wrap:
            chain_set = self.chains
        else:
            chain_set = self.unwrapped_chains

        if name not in chain_set:
            LOG.debug(_('Attempted to remove chain %s which does not exist'),
                      name)
            return

        chain_set.remove(name)
        self.rules = filter(lambda r: r.chain != name, self.rules)

        if wrap:
            jump_snippet = '-j %s-%s' % (binary_name, name)
        else:
            jump_snippet = '-j %s' % (name,)

        self.rules = filter(lambda r: jump_snippet not in r.rule, self.rules)

    def add_rule(self, chain, rule, wrap=True, top=False):
        """Add a rule to the table.

        This is just like what you'd feed to iptables, just without
        the '-A <chain name>' bit at the start.

        However, if you need to jump to one of your wrapped chains,
        prepend its name with a '$' which will ensure the wrapping
        is applied correctly.

        """
        if wrap and chain not in self.chains:
            raise ValueError(_('Unknown chain: %r') % chain)

        if '$' in rule:
            rule = ' '.join(map(self._wrap_target_chain, rule.split(' ')))

        self.rules.append(IptablesRule(chain, rule, wrap, top))

    def _wrap_target_chain(self, s):
        if s.startswith('$'):
            return '%s-%s' % (binary_name, s[1:])
        return s

    def remove_rule(self, chain, rule, wrap=True, top=False):
        """Remove a rule from a chain.

        Note: The rule must be exactly identical to the one that was added.
        You cannot switch arguments around like you can with the iptables
        CLI tool.

        """
        try:
            self.rules.remove(IptablesRule(chain, rule, wrap, top))
        except ValueError:
            LOG.debug(_('Tried to remove rule that was not there:'
                        ' %(chain)r %(rule)r %(wrap)r %(top)r'),
                      {'chain': chain, 'rule': rule,
                       'top': top, 'wrap': wrap})

    def empty_chain(self, chain, wrap=True):
        """Remove all rules from a chain."""
        chained_rules = [rule for rule in self.rules
                              if rule.chain == chain and rule.wrap == wrap]
        for rule in chained_rules:
            self.rules.remove(rule)


class IptablesManager(object):
    """Wrapper for iptables.

    See IptablesTable for some usage docs

    A number of chains are set up to begin with.

    First, nova-filter-top. It's added at the top of FORWARD and OUTPUT. Its
    name is not wrapped, so it's shared between the various nova workers. It's
    intended for rules that need to live at the top of the FORWARD and OUTPUT
    chains. It's in both the ipv4 and ipv6 set of tables.

    For ipv4 and ipv6, the builtin INPUT, OUTPUT, and FORWARD filter chains are
    wrapped, meaning that the "real" INPUT chain has a rule that jumps to the
    wrapped INPUT chain, etc. Additionally, there's a wrapped chain named
    "local" which is jumped to from nova-filter-top.

    For ipv4, the builtin PREROUTING, OUTPUT, and POSTROUTING nat chains are
    wrapped in the same was as the builtin filter chains. Additionally, there's
    a snat chain that is applied after the POSTROUTING chain.

    """

    def __init__(self, execute=None):
        if not execute:
            self.execute = _execute
        else:
            self.execute = execute

        self.ipv4 = {'filter': IptablesTable(),
                     'nat': IptablesTable()}
        self.ipv6 = {'filter': IptablesTable()}

        # Add a nova-filter-top chain. It's intended to be shared
        # among the various nova components. It sits at the very top
        # of FORWARD and OUTPUT.
        for tables in [self.ipv4, self.ipv6]:
            tables['filter'].add_chain('nova-filter-top', wrap=False)
            tables['filter'].add_rule('FORWARD', '-j nova-filter-top',
                                      wrap=False, top=True)
            tables['filter'].add_rule('OUTPUT', '-j nova-filter-top',
                                      wrap=False, top=True)

            tables['filter'].add_chain('local')
            tables['filter'].add_rule('nova-filter-top', '-j $local',
                                      wrap=False)

        # Wrap the builtin chains
        builtin_chains = {4: {'filter': ['INPUT', 'OUTPUT', 'FORWARD'],
                              'nat': ['PREROUTING', 'OUTPUT', 'POSTROUTING']},
                          6: {'filter': ['INPUT', 'OUTPUT', 'FORWARD']}}

        for ip_version in builtin_chains:
            if ip_version == 4:
                tables = self.ipv4
            elif ip_version == 6:
                tables = self.ipv6

            for table, chains in builtin_chains[ip_version].iteritems():
                for chain in chains:
                    tables[table].add_chain(chain)
                    tables[table].add_rule(chain, '-j $%s' % (chain,),
                                           wrap=False)

        # Add a nova-postrouting-bottom chain. It's intended to be shared
        # among the various nova components. We set it as the last chain
        # of POSTROUTING chain.
        self.ipv4['nat'].add_chain('nova-postrouting-bottom', wrap=False)
        self.ipv4['nat'].add_rule('POSTROUTING', '-j nova-postrouting-bottom',
                                  wrap=False)

        # We add a snat chain to the shared nova-postrouting-bottom chain
        # so that it's applied last.
        self.ipv4['nat'].add_chain('snat')
        self.ipv4['nat'].add_rule('nova-postrouting-bottom', '-j $snat',
                                  wrap=False)

        # And then we add a floating-snat chain and jump to first thing in
        # the snat chain.
        self.ipv4['nat'].add_chain('floating-snat')
        self.ipv4['nat'].add_rule('snat', '-j $floating-snat')

    @utils.synchronized('iptables', external=True)
    def apply(self):
        """Apply the current in-memory set of iptables rules.

        This will blow away any rules left over from previous runs of the
        same component of Nova, and replace them with our current set of
        rules. This happens atomically, thanks to iptables-restore.

        """
        s = [('iptables', self.ipv4)]
        if FLAGS.use_ipv6:
            s += [('ip6tables', self.ipv6)]

        for cmd, tables in s:
            for table in tables:
                current_table, _ = self.execute('%s-save' % (cmd,),
                                                '-t', '%s' % (table,),
                                                run_as_root=True,
                                                attempts=5)
                current_lines = current_table.split('\n')
                new_filter = self._modify_rules(current_lines,
                                                tables[table])
                self.execute('%s-restore' % (cmd,), run_as_root=True,
                             process_input='\n'.join(new_filter),
                             attempts=5)

    def _modify_rules(self, current_lines, table, binary=None):
        unwrapped_chains = table.unwrapped_chains
        chains = table.chains
        rules = table.rules

        # Remove any trace of our rules
        new_filter = filter(lambda line: binary_name not in line,
                            current_lines)

        seen_chains = False
        rules_index = 0
        for rules_index, rule in enumerate(new_filter):
            if not seen_chains:
                if rule.startswith(':'):
                    seen_chains = True
            else:
                if not rule.startswith(':'):
                    break

        our_rules = []
        for rule in rules:
            rule_str = str(rule)
            if rule.top:
                # rule.top == True means we want this rule to be at the top.
                # Further down, we weed out duplicates from the bottom of the
                # list, so here we remove the dupes ahead of time.
                new_filter = filter(lambda s: s.strip() != rule_str.strip(),
                                    new_filter)
            our_rules += [rule_str]

        new_filter[rules_index:rules_index] = our_rules

        new_filter[rules_index:rules_index] = [':%s - [0:0]' % \
                                               (name,) \
                                               for name in unwrapped_chains]
        new_filter[rules_index:rules_index] = [':%s-%s - [0:0]' % \
                                               (binary_name, name,) \
                                               for name in chains]

        seen_lines = set()

        def _weed_out_duplicates(line):
            line = line.strip()
            if line in seen_lines:
                return False
            else:
                seen_lines.add(line)
                return True

        # We filter duplicates, letting the *last* occurrence take
        # precendence.
        new_filter.reverse()
        new_filter = filter(_weed_out_duplicates, new_filter)
        new_filter.reverse()
        return new_filter


def metadata_forward():
    """Create forwarding rule for metadata."""
    iptables_manager.ipv4['nat'].add_rule('PREROUTING',
                                          '-s 0.0.0.0/0 -d 169.254.169.254/32 '
                                          '-p tcp -m tcp --dport 80 -j DNAT '
                                          '--to-destination %s:%s' % \
                                          (FLAGS.ec2_dmz_host, FLAGS.ec2_port))
    iptables_manager.apply()


def init_host():
    """Basic networking setup goes here."""
    # NOTE(devcamcar): Cloud public SNAT entries and the default
    # SNAT rule for outbound traffic.
    iptables_manager.ipv4['nat'].add_rule('snat',
                                          '-s %s -j SNAT --to-source %s' % \
                                           (FLAGS.fixed_range,
                                            FLAGS.routing_source_ip))

    iptables_manager.ipv4['nat'].add_rule('POSTROUTING',
                                          '-s %s -d %s -j ACCEPT' % \
                                          (FLAGS.fixed_range, FLAGS.dmz_cidr))

    iptables_manager.ipv4['nat'].add_rule('POSTROUTING',
                                          '-s %(range)s -d %(range)s '
                                          '-j ACCEPT' % \
                                          {'range': FLAGS.fixed_range})
    iptables_manager.apply()


def bind_floating_ip(floating_ip, check_exit_code=True):
    """Bind ip to public interface."""
    _execute('ip', 'addr', 'add', floating_ip,
             'dev', FLAGS.public_interface,
             run_as_root=True, check_exit_code=check_exit_code)
    if FLAGS.send_arp_for_ha:
        _execute('arping', '-U', floating_ip,
                 '-A', '-I', FLAGS.public_interface,
                 '-c', 1, run_as_root=True, check_exit_code=False)


def unbind_floating_ip(floating_ip):
    """Unbind a public ip from public interface."""
    _execute('ip', 'addr', 'del', floating_ip,
             'dev', FLAGS.public_interface, run_as_root=True)


def ensure_metadata_ip():
    """Sets up local metadata ip."""
    _execute('ip', 'addr', 'add', '169.254.169.254/32',
             'scope', 'link', 'dev', 'lo',
             run_as_root=True, check_exit_code=False)


def ensure_vpn_forward(public_ip, port, private_ip):
    """Sets up forwarding rules for vlan."""
    iptables_manager.ipv4['filter'].add_rule('FORWARD',
                                             '-d %s -p udp '
                                             '--dport 1194 '
                                             '-j ACCEPT' % private_ip)
    iptables_manager.ipv4['nat'].add_rule('PREROUTING',
                                          '-d %s -p udp '
                                          '--dport %s -j DNAT --to %s:1194' %
                                          (public_ip, port, private_ip))
    iptables_manager.ipv4['nat'].add_rule("OUTPUT",
                                          "-d %s -p udp "
                                          "--dport %s -j DNAT --to %s:1194" %
                                          (public_ip, port, private_ip))
    iptables_manager.apply()


def ensure_floating_forward(floating_ip, fixed_ip):
    """Ensure floating ip forwarding rule."""
    for chain, rule in floating_forward_rules(floating_ip, fixed_ip):
        iptables_manager.ipv4['nat'].add_rule(chain, rule)
    iptables_manager.apply()


def remove_floating_forward(floating_ip, fixed_ip):
    """Remove forwarding for floating ip."""
    for chain, rule in floating_forward_rules(floating_ip, fixed_ip):
        iptables_manager.ipv4['nat'].remove_rule(chain, rule)
    iptables_manager.apply()


def floating_forward_rules(floating_ip, fixed_ip):
    return [('PREROUTING', '-d %s -j DNAT --to %s' % (floating_ip, fixed_ip)),
            ('OUTPUT', '-d %s -j DNAT --to %s' % (floating_ip, fixed_ip)),
            ('floating-snat',
             '-s %s -j SNAT --to %s' % (fixed_ip, floating_ip))]


def initialize_gateway_device(dev, network_ref):
    if not network_ref:
        return

    # NOTE(vish): The ip for dnsmasq has to be the first address on the
    #             bridge for it to respond to reqests properly
    full_ip = '%s/%s' % (network_ref['dhcp_server'],
                         network_ref['cidr'].rpartition('/')[2])
    new_ip_params = [[full_ip, 'brd', network_ref['broadcast']]]
    old_ip_params = []
    out, err = _execute('ip', 'addr', 'show', 'dev', dev,
                        'scope', 'global', run_as_root=True)
    for line in out.split('\n'):
        fields = line.split()
        if fields and fields[0] == 'inet':
            ip_params = fields[1:-1]
            old_ip_params.append(ip_params)
            if ip_params[0] != full_ip:
                new_ip_params.append(ip_params)
    if not old_ip_params or old_ip_params[0][0] != full_ip:
        gateway = None
        out, err = _execute('route', '-n', run_as_root=True)
        for line in out.split('\n'):
            fields = line.split()
            if fields and fields[0] == '0.0.0.0' and \
                            fields[-1] == dev:
                gateway = fields[1]
                _execute('route', 'del', 'default', 'gw', gateway,
                         'dev', dev, check_exit_code=False,
                         run_as_root=True)
        for ip_params in old_ip_params:
            _execute(*_ip_bridge_cmd('del', ip_params, dev),
                        run_as_root=True)
        for ip_params in new_ip_params:
            _execute(*_ip_bridge_cmd('add', ip_params, dev),
                        run_as_root=True)
        if gateway:
            _execute('route', 'add', 'default', 'gw', gateway,
                        run_as_root=True)
        if FLAGS.send_arp_for_ha:
            _execute('arping', '-U', network_ref['dhcp_server'],
                      '-A', '-I', dev,
                      '-c', 1, run_as_root=True, check_exit_code=False)
    if(FLAGS.use_ipv6):
        _execute('ip', '-f', 'inet6', 'addr',
                     'change', network_ref['cidr_v6'],
                     'dev', dev, run_as_root=True)
    # NOTE(vish): If the public interface is the same as the
    #             bridge, then the bridge has to be in promiscuous
    #             to forward packets properly.
    if(FLAGS.public_interface == dev):
        _execute('ip', 'link', 'set',
                     'dev', dev, 'promisc', 'on', run_as_root=True)


def get_dhcp_leases(context, network_ref):
    """Return a network's hosts config in dnsmasq leasefile format."""
    hosts = []
    for fixed_ref in db.network_get_associated_fixed_ips(context,
                                                         network_ref['id']):
        host = fixed_ref['instance']['host']
        if network_ref['multi_host'] and FLAGS.host != host:
            continue
        hosts.append(_host_lease(fixed_ref))
    return '\n'.join(hosts)


def get_dhcp_hosts(context, network_ref):
    """Get network's hosts config in dhcp-host format."""
    hosts = []
    for fixed_ref in db.network_get_associated_fixed_ips(context,
                                                         network_ref['id']):
        host = fixed_ref['instance']['host']
        if network_ref['multi_host'] and FLAGS.host != host:
            continue
        hosts.append(_host_dhcp(fixed_ref))
    return '\n'.join(hosts)


def get_dhcp_opts(context, network_ref):
    """Get network's hosts config in dhcp-opts format."""
    hosts = []
    ips_ref = db.network_get_associated_fixed_ips(context, network_ref['id'])

    if ips_ref:
        #set of instance ids
        instance_set = set([fixed_ip_ref['instance_id']
                            for fixed_ip_ref in ips_ref])
        default_gw_network_node = {}
        for instance_id in instance_set:
            vifs = db.virtual_interface_get_by_instance(context, instance_id)
            if vifs:
                #offer a default gateway to the first virtual interface
                default_gw_network_node[instance_id] = vifs[0]['network_id']

        for fixed_ip_ref in ips_ref:
            instance_id = fixed_ip_ref['instance_id']
            if instance_id in default_gw_network_node:
                target_network_id = default_gw_network_node[instance_id]
                # we don't want default gateway for this fixed ip
                if target_network_id != fixed_ip_ref['network_id']:
                    hosts.append(_host_dhcp_opts(fixed_ip_ref))
    return '\n'.join(hosts)


def release_dhcp(dev, address, mac_address):
    utils.execute('dhcp_release', dev, address, mac_address, run_as_root=True)


def _add_dnsmasq_accept_rules(dev):
    """Allow DHCP and DNS traffic through to dnsmasq."""
    table = iptables_manager.ipv4['filter']
    for port in [67, 53]:
        for proto in ['udp', 'tcp']:
            args = {'dev': dev, 'port': port, 'proto': proto}
            table.add_rule('INPUT',
                           '-i %(dev)s -p %(proto)s -m %(proto)s '
                           '--dport %(port)s -j ACCEPT' % args)
    iptables_manager.apply()


# NOTE(ja): Sending a HUP only reloads the hostfile, so any
#           configuration options (like dchp-range, vlan, ...)
#           aren't reloaded.
@utils.synchronized('dnsmasq_start')
def update_dhcp(context, dev, network_ref):
    """(Re)starts a dnsmasq server for a given network.

    If a dnsmasq instance is already running then send a HUP
    signal causing it to reload, otherwise spawn a new instance.

    """
    conffile = _dhcp_file(dev, 'conf')
    with open(conffile, 'w') as f:
        f.write(get_dhcp_hosts(context, network_ref))

    if FLAGS.use_single_default_gateway:
        optsfile = _dhcp_file(dev, 'opts')
        with open(optsfile, 'w') as f:
            f.write(get_dhcp_opts(context, network_ref))
        os.chmod(optsfile, 0644)

    # Make sure dnsmasq can actually read it (it setuid()s to "nobody")
    os.chmod(conffile, 0644)

    pid = _dnsmasq_pid_for(dev)

    # if dnsmasq is already running, then tell it to reload
    if pid:
        out, _err = _execute('cat', '/proc/%d/cmdline' % pid,
                             check_exit_code=False)
        if conffile in out:
            try:
                _execute('kill', '-HUP', pid, run_as_root=True)
                return
            except Exception as exc:  # pylint: disable=W0703
                LOG.debug(_('Hupping dnsmasq threw %s'), exc)
        else:
            LOG.debug(_('Pid %d is stale, relaunching dnsmasq'), pid)

    cmd = ['FLAGFILE=%s' % FLAGS.dhcpbridge_flagfile,
           'NETWORK_ID=%s' % str(network_ref['id']),
           'dnsmasq',
           '--strict-order',
           '--bind-interfaces',
           '--conf-file=%s' % FLAGS.dnsmasq_config_file,
           '--domain=%s' % FLAGS.dhcp_domain,
           '--pid-file=%s' % _dhcp_file(dev, 'pid'),
           '--listen-address=%s' % network_ref['dhcp_server'],
           '--except-interface=lo',
           '--dhcp-range=%s,static,120s' % network_ref['dhcp_start'],
           '--dhcp-lease-max=%s' % len(netaddr.IPNetwork(network_ref['cidr'])),
           '--dhcp-hostsfile=%s' % _dhcp_file(dev, 'conf'),
           '--dhcp-script=%s' % FLAGS.dhcpbridge,
           '--leasefile-ro']
    if FLAGS.dns_server:
        cmd += ['-h', '-R', '--server=%s' % FLAGS.dns_server]

    if FLAGS.use_single_default_gateway:
        cmd += ['--dhcp-optsfile=%s' % _dhcp_file(dev, 'opts')]

    _execute(*cmd, run_as_root=True)

    _add_dnsmasq_accept_rules(dev)


@utils.synchronized('radvd_start')
def update_ra(context, dev, network_ref):
    conffile = _ra_file(dev, 'conf')
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
""" % (dev, network_ref['cidr_v6'])
        f.write(conf_str)

    # Make sure radvd can actually read it (it setuid()s to "nobody")
    os.chmod(conffile, 0644)

    pid = _ra_pid_for(dev)

    # if radvd is already running, then tell it to reload
    if pid:
        out, _err = _execute('cat', '/proc/%d/cmdline'
                             % pid, check_exit_code=False)
        if conffile in out:
            try:
                _execute('kill', pid, run_as_root=True)
            except Exception as exc:  # pylint: disable=W0703
                LOG.debug(_('killing radvd threw %s'), exc)
        else:
            LOG.debug(_('Pid %d is stale, relaunching radvd'), pid)

    cmd = ['radvd',
           '-C', '%s' % _ra_file(dev, 'conf'),
           '-p', '%s' % _ra_file(dev, 'pid')]

    _execute(*cmd, run_as_root=True)


def _host_lease(fixed_ip_ref):
    """Return a host string for an address in leasefile format."""
    instance_ref = fixed_ip_ref['instance']
    if instance_ref['updated_at']:
        timestamp = instance_ref['updated_at']
    else:
        timestamp = instance_ref['created_at']

    seconds_since_epoch = calendar.timegm(timestamp.utctimetuple())

    return '%d %s %s %s *' % (seconds_since_epoch + FLAGS.dhcp_lease_time,
                              fixed_ip_ref['virtual_interface']['address'],
                              fixed_ip_ref['address'],
                              instance_ref['hostname'] or '*')


def _host_dhcp_network(fixed_ip_ref):
    instance_ref = fixed_ip_ref['instance']
    return 'NW-i%08d-%s' % (instance_ref['id'],
                            fixed_ip_ref['network_id'])


def _host_dhcp(fixed_ip_ref):
    """Return a host string for an address in dhcp-host format."""
    instance_ref = fixed_ip_ref['instance']
    vif = fixed_ip_ref['virtual_interface']
    if FLAGS.use_single_default_gateway:
        return '%s,%s.%s,%s,%s' % (vif['address'],
                               instance_ref['hostname'],
                               FLAGS.dhcp_domain,
                               fixed_ip_ref['address'],
                               "net:" + _host_dhcp_network(fixed_ip_ref))
    else:
        return '%s,%s.%s,%s' % (vif['address'],
                               instance_ref['hostname'],
                               FLAGS.dhcp_domain,
                               fixed_ip_ref['address'])


def _host_dhcp_opts(fixed_ip_ref):
    """Return a host string for an address in dhcp-host format."""
    return '%s,%s' % (_host_dhcp_network(fixed_ip_ref), 3)


def _execute(*cmd, **kwargs):
    """Wrapper around utils._execute for fake_network."""
    if FLAGS.fake_network:
        LOG.debug('FAKE NET: %s', ' '.join(map(str, cmd)))
        return 'fake', 0
    else:
        return utils.execute(*cmd, **kwargs)


def _device_exists(device):
    """Check if ethernet device exists."""
    (_out, err) = _execute('ip', 'link', 'show', 'dev', device,
                           check_exit_code=False)
    return not err


def _stop_dnsmasq(dev):
    """Stops the dnsmasq instance for a given network."""
    pid = _dnsmasq_pid_for(dev)

    if pid:
        try:
            _execute('kill', '-TERM', pid, run_as_root=True)
        except Exception as exc:  # pylint: disable=W0703
            LOG.debug(_('Killing dnsmasq threw %s'), exc)


def _dhcp_file(dev, kind):
    """Return path to a pid, leases or conf file for a bridge/device."""
    if not os.path.exists(FLAGS.networks_path):
        os.makedirs(FLAGS.networks_path)
    return os.path.abspath('%s/nova-%s.%s' % (FLAGS.networks_path,
                                              dev,
                                              kind))


def _ra_file(dev, kind):
    """Return path to a pid or conf file for a bridge/device."""

    if not os.path.exists(FLAGS.networks_path):
        os.makedirs(FLAGS.networks_path)
    return os.path.abspath('%s/nova-ra-%s.%s' % (FLAGS.networks_path,
                                              dev,
                                              kind))


def _dnsmasq_pid_for(dev):
    """Returns the pid for prior dnsmasq instance for a bridge/device.

    Returns None if no pid file exists.

    If machine has rebooted pid might be incorrect (caller should check).

    """
    pid_file = _dhcp_file(dev, 'pid')

    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                return int(f.read())
        except (ValueError, IOError):
            return None


def _ra_pid_for(dev):
    """Returns the pid for prior radvd instance for a bridge/device.

    Returns None if no pid file exists.

    If machine has rebooted pid might be incorrect (caller should check).

    """
    pid_file = _ra_file(dev, 'pid')

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            return int(f.read())


def _ip_bridge_cmd(action, params, device):
    """Build commands to add/del ips to bridges/devices."""
    cmd = ['ip', 'addr', action]
    cmd.extend(params)
    cmd.extend(['dev', device])
    return cmd


# Similar to compute virt layers, the Linux network node
# code uses a flexible driver model to support different ways
# of creating ethernet interfaces and attaching them to the network.
# In the case of a network host, these interfaces
# act as gateway/dhcp/vpn/etc. endpoints not VM interfaces.


def plug(network, mac_address):
    return interface_driver.plug(network, mac_address)


def unplug(network):
    return interface_driver.unplug(network)


def get_dev(network):
    return interface_driver.get_dev(network)


class LinuxNetInterfaceDriver(object):
    """Abstract class that defines generic network host API"""
    """ for for all Linux interface drivers."""

    def plug(self, network, mac_address):
        """Create Linux device, return device name"""
        raise NotImplementedError()

    def unplug(self, network):
        """Destory Linux device, return device name"""
        raise NotImplementedError()

    def get_dev(self, network):
        """Get device name"""
        raise NotImplementedError()


# plugs interfaces using Linux Bridge
class LinuxBridgeInterfaceDriver(LinuxNetInterfaceDriver):

    def plug(self, network, mac_address):
        if network.get('vlan', None) is not None:
            LinuxBridgeInterfaceDriver.ensure_vlan_bridge(
                           network['vlan'],
                           network['bridge'],
                           network['bridge_interface'],
                           network,
                           mac_address)
        else:
            LinuxBridgeInterfaceDriver.ensure_bridge(
                          network['bridge'],
                          network['bridge_interface'],
                          network)

        return network['bridge']

    def unplug(self, network):
        return self.get_dev(network)

    def get_dev(self, network):
        return network['bridge']

    @classmethod
    def ensure_vlan_bridge(_self, vlan_num, bridge, bridge_interface,
                                            net_attrs=None, mac_address=None):
        """Create a vlan and bridge unless they already exist."""
        interface = LinuxBridgeInterfaceDriver.ensure_vlan(vlan_num,
                                               bridge_interface, mac_address)
        LinuxBridgeInterfaceDriver.ensure_bridge(bridge, interface, net_attrs)
        return interface

    @classmethod
    @utils.synchronized('ensure_vlan', external=True)
    def ensure_vlan(_self, vlan_num, bridge_interface, mac_address=None):
        """Create a vlan unless it already exists."""
        interface = 'vlan%s' % vlan_num
        if not _device_exists(interface):
            LOG.debug(_('Starting VLAN inteface %s'), interface)
            _execute('vconfig', 'set_name_type',
                     'VLAN_PLUS_VID_NO_PAD', run_as_root=True)
            _execute('vconfig', 'add', bridge_interface,
                        vlan_num, run_as_root=True)
            # (danwent) the bridge will inherit this address, so we want to
            # make sure it is the value set from the NetworkManager
            if mac_address:
                _execute('ip', 'link', 'set', interface, "address",
                            mac_address, run_as_root=True)
            _execute('ip', 'link', 'set', interface, 'up', run_as_root=True)
        return interface

    @classmethod
    @utils.synchronized('ensure_bridge', external=True)
    def ensure_bridge(_self, bridge, interface, net_attrs=None):
        """Create a bridge unless it already exists.

        :param interface: the interface to create the bridge on.
        :param net_attrs: dictionary with  attributes used to create bridge.

        If net_attrs is set, it will add the net_attrs['gateway'] to the bridge
        using net_attrs['broadcast'] and net_attrs['cidr'].  It will also add
        the ip_v6 address specified in net_attrs['cidr_v6'] if use_ipv6 is set.

        The code will attempt to move any ips that already exist on the
        interface onto the bridge and reset the default gateway if necessary.

        """
        if not _device_exists(bridge):
            LOG.debug(_('Starting Bridge interface for %s'), interface)
            _execute('brctl', 'addbr', bridge, run_as_root=True)
            _execute('brctl', 'setfd', bridge, 0, run_as_root=True)
            # _execute('brctl setageing %s 10' % bridge, run_as_root=True)
            _execute('brctl', 'stp', bridge, 'off', run_as_root=True)
            # (danwent) bridge device MAC address can't be set directly.
            # instead it inherits the MAC address of the first device on the
            # bridge, which will either be the vlan interface, or a
            # physical NIC.
            _execute('ip', 'link', 'set', bridge, 'up', run_as_root=True)

        if interface:
            out, err = _execute('brctl', 'addif', bridge, interface,
                            check_exit_code=False, run_as_root=True)

            # NOTE(vish): This will break if there is already an ip on the
            #             interface, so we move any ips to the bridge
            gateway = None
            out, err = _execute('route', '-n', run_as_root=True)
            for line in out.split('\n'):
                fields = line.split()
                if fields and fields[0] == '0.0.0.0' and \
                                fields[-1] == interface:
                    gateway = fields[1]
                    _execute('route', 'del', 'default', 'gw', gateway,
                             'dev', interface, check_exit_code=False,
                             run_as_root=True)
            out, err = _execute('ip', 'addr', 'show', 'dev', interface,
                                'scope', 'global', run_as_root=True)
            for line in out.split('\n'):
                fields = line.split()
                if fields and fields[0] == 'inet':
                    params = fields[1:-1]
                    _execute(*_ip_bridge_cmd('del', params, fields[-1]),
                                run_as_root=True)
                    _execute(*_ip_bridge_cmd('add', params, bridge),
                                run_as_root=True)
            if gateway:
                _execute('route', 'add', 'default', 'gw', gateway,
                            run_as_root=True)

            if (err and err != "device %s is already a member of a bridge;"
                     "can't enslave it to bridge %s.\n" % (interface, bridge)):
                raise exception.Error('Failed to add interface: %s' % err)

        iptables_manager.ipv4['filter'].add_rule('FORWARD',
                                             '--in-interface %s -j ACCEPT' % \
                                             bridge)
        iptables_manager.ipv4['filter'].add_rule('FORWARD',
                                             '--out-interface %s -j ACCEPT' % \
                                             bridge)


# plugs interfaces using Open vSwitch
class LinuxOVSInterfaceDriver(LinuxNetInterfaceDriver):

    def plug(self, network, mac_address):
        dev = "gw-" + str(network['id'])
        if not _device_exists(dev):
            bridge = FLAGS.linuxnet_ovs_integration_bridge
            _execute('ovs-vsctl',
                        '--', '--may-exist', 'add-port', bridge, dev,
                        '--', 'set', 'Interface', dev, "type=internal",
                        '--', 'set', 'Interface', dev,
                                "external-ids:iface-id=nova-%s" % dev,
                        '--', 'set', 'Interface', dev,
                                "external-ids:iface-status=active",
                        '--', 'set', 'Interface', dev,
                                "external-ids:attached-mac=%s" % mac_address,
                        run_as_root=True)
            _execute('ip', 'link', 'set', dev, "address", mac_address,
                        run_as_root=True)
            _execute('ip', 'link', 'set', dev, 'up', run_as_root=True)

        return dev

    def unplug(self, network):
        return self.get_dev(network)

    def get_dev(self, network):
        dev = "gw-" + str(network['id'])
        return dev

iptables_manager = IptablesManager()
interface_driver = utils.import_object(FLAGS.linuxnet_interface_driver)
