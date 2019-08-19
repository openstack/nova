# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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
import os
import re
import signal
import time

import netaddr
import netifaces
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import importutils
from oslo_utils import timeutils
import six

import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova.pci import utils as pci_utils
import nova.privsep.linux_net
from nova import utils

LOG = logging.getLogger(__name__)


CONF = nova.conf.CONF


# NOTE(vish): Iptables supports chain names of up to 28 characters,  and we
#             add up to 12 characters to binary_name which is used as a prefix,
#             so we limit it to 16 characters.
#             (max_chain_name_length - len('-POSTROUTING') == 16)
def get_binary_name():
    """Grab the name of the binary we're running in."""
    return os.path.basename(inspect.stack()[-1][1])[:16]


binary_name = get_binary_name()


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

    def __repr__(self):
        if self.wrap:
            chain = '%s-%s' % (binary_name, self.chain)
        else:
            chain = self.chain
        # new rules should have a zero [packet: byte] count
        return '[0:0] -A %s %s' % (chain, self.rule)


class IptablesTable(object):
    """An iptables table."""

    def __init__(self):
        self.rules = []
        self.remove_rules = []
        self.chains = set()
        self.unwrapped_chains = set()
        self.remove_chains = set()
        self.dirty = True

    def has_chain(self, name, wrap=True):
        if wrap:
            return name in self.chains
        else:
            return name in self.unwrapped_chains

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
        self.dirty = True

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
            LOG.warning('Attempted to remove chain %s which does not exist',
                        name)
            return
        self.dirty = True

        # non-wrapped chains and rules need to be dealt with specially,
        # so we keep a list of them to be iterated over in apply()
        if not wrap:
            self.remove_chains.add(name)
        chain_set.remove(name)
        if not wrap:
            self.remove_rules += [r for r in self.rules if r.chain == name]
        self.rules = [r for r in self.rules if r.chain != name]

        if wrap:
            jump_snippet = '-j %s-%s' % (binary_name, name)
        else:
            jump_snippet = '-j %s' % (name,)

        if not wrap:
            self.remove_rules += [r for r in self.rules
                                  if jump_snippet in r.rule]
        self.rules = [r for r in self.rules if jump_snippet not in r.rule]

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

        rule_obj = IptablesRule(chain, rule, wrap, top)
        if rule_obj in self.rules:
            LOG.debug("Skipping duplicate iptables rule addition. "
                      "%(rule)r already in %(rules)r",
                      {'rule': rule_obj, 'rules': self.rules})
        else:
            self.rules.append(IptablesRule(chain, rule, wrap, top))
            self.dirty = True

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
            if not wrap:
                self.remove_rules.append(IptablesRule(chain, rule, wrap, top))
            self.dirty = True
        except ValueError:
            LOG.warning('Tried to remove rule that was not there:'
                        ' %(chain)r %(rule)r %(wrap)r %(top)r',
                        {'chain': chain, 'rule': rule,
                         'top': top, 'wrap': wrap})

    def remove_rules_regex(self, regex):
        """Remove all rules matching regex."""
        if isinstance(regex, six.string_types):
            regex = re.compile(regex)
        num_rules = len(self.rules)
        self.rules = [r for r in self.rules if not regex.match(str(r))]
        removed = num_rules - len(self.rules)
        if removed > 0:
            self.dirty = True
        return removed

    def empty_chain(self, chain, wrap=True):
        """Remove all rules from a chain."""
        chained_rules = [rule for rule in self.rules
                              if rule.chain == chain and rule.wrap == wrap]
        if chained_rules:
            self.dirty = True
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

    For ipv4 and ipv6, the built-in INPUT, OUTPUT, and FORWARD filter chains
    are wrapped, meaning that the "real" INPUT chain has a rule that jumps to
    the wrapped INPUT chain, etc. Additionally, there's a wrapped chain named
    "local" which is jumped to from nova-filter-top.

    For ipv4, the built-in PREROUTING, OUTPUT, and POSTROUTING nat chains are
    wrapped in the same was as the built-in filter chains. Additionally,
    there's a snat chain that is applied after the POSTROUTING chain.

    """

    def __init__(self, redirect_privsep_calls_to=None):
        # NOTE(mikal): This is only used by the xenapi hypervisor driver,
        # which wants to intercept our calls to iptables and redirect them
        # to an agent running in dom0.
        # TODO(mikal): We really should make the dom0 agent feel more like
        # privsep. They really are the same thing, just one is from a simpler
        # time in our past.
        self.redirect_privsep = redirect_privsep_calls_to

        self.ipv4 = {'filter': IptablesTable(),
                     'nat': IptablesTable(),
                     'mangle': IptablesTable()}
        self.ipv6 = {'filter': IptablesTable()}

        self.iptables_apply_deferred = False

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

        # Wrap the built-in chains
        builtin_chains = {4: {'filter': ['INPUT', 'OUTPUT', 'FORWARD'],
                              'nat': ['PREROUTING', 'OUTPUT', 'POSTROUTING'],
                              'mangle': ['POSTROUTING']},
                          6: {'filter': ['INPUT', 'OUTPUT', 'FORWARD']}}

        for ip_version in builtin_chains:
            if ip_version == 4:
                tables = self.ipv4
            elif ip_version == 6:
                tables = self.ipv6

            for table, chains in builtin_chains[ip_version].items():
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

        # And then we add a float-snat chain and jump to first thing in
        # the snat chain.
        self.ipv4['nat'].add_chain('float-snat')
        self.ipv4['nat'].add_rule('snat', '-j $float-snat')

    def defer_apply_on(self):
        self.iptables_apply_deferred = True

    def defer_apply_off(self):
        self.iptables_apply_deferred = False
        self.apply()

    def dirty(self):
        for table in six.itervalues(self.ipv4):
            if table.dirty:
                return True
        if CONF.use_ipv6:
            for table in six.itervalues(self.ipv6):
                if table.dirty:
                    return True
        return False

    def apply(self):
        if self.iptables_apply_deferred:
            return
        if self.dirty():
            self._apply()
        else:
            LOG.debug("Skipping apply due to lack of new rules")

    @utils.synchronized('iptables', external=True)
    def _apply(self):
        """Apply the current in-memory set of iptables rules.

        This will blow away any rules left over from previous runs of the
        same component of Nova, and replace them with our current set of
        rules. This happens atomically, thanks to iptables-restore.

        """
        s = [(True, self.ipv4)]
        if CONF.use_ipv6:
            s += [(False, self.ipv6)]

        for is_ipv4, tables in s:
            if not self.redirect_privsep:
                all_tables, _err = nova.privsep.linux_net.iptables_get_rules(
                                       ipv4=is_ipv4)
            else:
                if is_ipv4:
                    cmd = 'iptables-save'
                else:
                    cmd = 'ip6tables-save'
                all_tables, _err = self.redirect_privsep(
                    cmd, '-c', run_as_root=True, attempts=5)

            all_lines = all_tables.split('\n')
            for table_name, table in tables.items():
                start, end = self._find_table(all_lines, table_name)
                all_lines[start:end] = self._modify_rules(
                        all_lines[start:end], table, table_name)
                table.dirty = False

            if not self.redirect_privsep:
                nova.privsep.linux_net.iptables_set_rules(all_lines,
                                                          ipv4=is_ipv4)
            else:
                if is_ipv4:
                    cmd = 'iptables-restore'
                else:
                    cmd = 'ip6tables-restore'
                self.redirect_privsep(
                    cmd, '-c', run_as_root=True,
                    process_input=six.b('\n'.join(all_lines)),
                    attempts=5)

        LOG.debug("IPTablesManager.apply completed with success")

    def _find_table(self, lines, table_name):
        if len(lines) < 3:
            # length only <2 when fake iptables
            return (0, 0)
        try:
            start = lines.index('*%s' % table_name) - 1
        except ValueError:
            # Couldn't find table_name
            return (0, 0)
        end = lines[start:].index('COMMIT') + start + 2
        return (start, end)

    @staticmethod
    def create_rules_from_regexp(criterion, new_filter):
        if not criterion:
            return [], new_filter
        regex = re.compile(criterion)
        temp_filter = [line for line in new_filter if regex.search(line)]
        for rule_str in temp_filter:
            new_filter = [s for s in new_filter
                          if s.strip() != rule_str.strip()]
        return temp_filter, new_filter

    def _modify_rules(self, current_lines, table, table_name):
        unwrapped_chains = table.unwrapped_chains
        chains = sorted(table.chains)
        remove_chains = table.remove_chains
        rules = table.rules
        remove_rules = table.remove_rules

        if not current_lines:
            fake_table = ['#Generated by nova',
                          '*' + table_name, 'COMMIT',
                          '#Completed by nova']
            current_lines = fake_table

        # Remove any trace of our rules
        new_filter = [line for line in current_lines
                      if binary_name not in line]

        top_rules, new_filter = self.create_rules_from_regexp(
            CONF.iptables_top_regex, new_filter)
        bottom_rules, new_filter = self.create_rules_from_regexp(
            CONF.iptables_bottom_regex, new_filter)

        seen_chains = False
        rules_index = 0
        for rules_index, rule in enumerate(new_filter):
            if not seen_chains:
                if rule.startswith(':'):
                    seen_chains = True
            else:
                if not rule.startswith(':'):
                    break

        if not seen_chains:
            rules_index = 2

        our_rules = top_rules
        bot_rules = []
        for rule in rules:
            rule_str = str(rule)
            if rule.top:
                # rule.top == True means we want this rule to be at the top.
                # Further down, we weed out duplicates from the bottom of the
                # list, so here we remove the dupes ahead of time.

                # We don't want to remove an entry if it has non-zero
                # [packet:byte] counts and replace it with [0:0], so let's
                # go look for a duplicate, and over-ride our table rule if
                # found.

                # ignore [packet:byte] counts at beginning of line
                if rule_str.startswith('['):
                    rule_str = rule_str.split(']', 1)[1]
                dup_filter = [s for s in new_filter
                              if rule_str.strip() in s.strip()]

                new_filter = [s for s in new_filter
                              if rule_str.strip() not in s.strip()]
                # if no duplicates, use original rule
                if dup_filter:
                    # grab the last entry, if there is one
                    dup = list(dup_filter)[-1]
                    rule_str = str(dup)
                else:
                    rule_str = str(rule)
                rule_str.strip()

                our_rules += [rule_str]
            else:
                bot_rules += [rule_str]

        our_rules += bot_rules

        new_filter = list(new_filter)
        new_filter[rules_index:rules_index] = our_rules

        new_filter[rules_index:rules_index] = [':%s - [0:0]' % (name,)
                                               for name in unwrapped_chains]
        new_filter[rules_index:rules_index] = [':%s-%s - [0:0]' %
                                               (binary_name, name,)
                                               for name in chains]

        commit_index = new_filter.index('COMMIT')
        new_filter[commit_index:commit_index] = bottom_rules
        seen_lines = set()

        def _weed_out_duplicates(line):
            # ignore [packet:byte] counts at beginning of lines
            if line.startswith('['):
                line = line.split(']', 1)[1]
            line = line.strip()
            if line in seen_lines:
                return False
            else:
                seen_lines.add(line)
                return True

        def _weed_out_removes(line):
            # We need to find exact matches here
            if line.startswith(':'):
                # it's a chain, for example, ":nova-billing - [0:0]"
                # strip off everything except the chain name
                line = line.split(':')[1]
                line = line.split('- [')[0]
                line = line.strip()
                for chain in remove_chains:
                    if chain == line:
                        remove_chains.remove(chain)
                        return False
            elif line.startswith('['):
                # it's a rule
                # ignore [packet:byte] counts at beginning of lines
                line = line.split(']', 1)[1]
                line = line.strip()
                for rule in remove_rules:
                    # ignore [packet:byte] counts at beginning of rules
                    rule_str = str(rule)
                    rule_str = rule_str.split(' ', 1)[1]
                    rule_str = rule_str.strip()
                    if rule_str == line:
                        remove_rules.remove(rule)
                        return False

            # Leave it alone
            return True

        # We filter duplicates, letting the *last* occurrence take
        # precedence.  We also filter out anything in the "remove"
        # lists.
        new_filter = list(new_filter)
        new_filter.reverse()
        new_filter = filter(_weed_out_duplicates, new_filter)
        new_filter = filter(_weed_out_removes, new_filter)
        new_filter = list(new_filter)
        new_filter.reverse()

        # flush lists, just in case we didn't find something
        remove_chains.clear()
        for rule in remove_rules:
            remove_rules.remove(rule)

        return new_filter


# NOTE(jkoelker) This is just a nice little stub point since mocking
#                builtins with mox is a nightmare
def write_to_file(file, data, mode='w'):
    with open(file, mode) as f:
        f.write(data)


def is_pid_cmdline_correct(pid, match):
    """Ensure that the cmdline for a pid seems sane

    Because pids are recycled, blindly killing by pid is something to
    avoid. This provides the ability to include a substring that is
    expected in the cmdline as a safety check.
    """
    try:
        with open('/proc/%d/cmdline' % pid) as f:
            cmdline = f.read()
            return match in cmdline
    except EnvironmentError:
        return False


def metadata_forward():
    """Create forwarding rule for metadata."""
    if CONF.metadata_host != '127.0.0.1':
        iptables_manager.ipv4['nat'].add_rule('PREROUTING',
                                          '-s 0.0.0.0/0 -d 169.254.169.254/32 '
                                          '-p tcp -m tcp --dport 80 -j DNAT '
                                          '--to-destination %s:%s' %
                                          (CONF.metadata_host,
                                           CONF.metadata_port))
    else:
        iptables_manager.ipv4['nat'].add_rule('PREROUTING',
                                          '-s 0.0.0.0/0 -d 169.254.169.254/32 '
                                          '-p tcp -m tcp --dport 80 '
                                          '-j REDIRECT --to-ports %s' %
                                           CONF.metadata_port)
    iptables_manager.apply()


def _iptables_dest(ip):
    if ((netaddr.IPAddress(ip).version == 4 and ip == '127.0.0.1') or
            ip == '::1'):
        return '-m addrtype --dst-type LOCAL'
    else:
        return '-d %s' % ip


def metadata_accept():
    """Create the filter accept rule for metadata."""

    rule = ('-p tcp -m tcp --dport %s %s -j ACCEPT' %
            (CONF.metadata_port, _iptables_dest(CONF.metadata_host)))

    if netaddr.IPAddress(CONF.metadata_host).version == 4:
        iptables_manager.ipv4['filter'].add_rule('INPUT', rule)
    else:
        iptables_manager.ipv6['filter'].add_rule('INPUT', rule)

    iptables_manager.apply()


def add_snat_rule(ip_range, is_external=False):
    if CONF.routing_source_ip:
        if is_external:
            if CONF.force_snat_range:
                snat_range = CONF.force_snat_range
            else:
                snat_range = []
        else:
            snat_range = ['0.0.0.0/0']
        for dest_range in snat_range:
            rule = ('-s %s -d %s -j SNAT --to-source %s'
                    % (ip_range, dest_range, CONF.routing_source_ip))
            if not is_external and CONF.public_interface:
                rule += ' -o %s' % CONF.public_interface
            iptables_manager.ipv4['nat'].add_rule('snat', rule)
        iptables_manager.apply()


def init_host(ip_range, is_external=False):
    """Basic networking setup goes here."""
    # NOTE(devcamcar): Cloud public SNAT entries and the default
    # SNAT rule for outbound traffic.

    add_snat_rule(ip_range, is_external)

    rules = []
    if is_external:
        for snat_range in CONF.force_snat_range:
            rules.append('PREROUTING -p ipv4 --ip-src %s --ip-dst %s '
                         '-j redirect --redirect-target ACCEPT' %
                         (ip_range, snat_range))
    if rules:
        ensure_ebtables_rules(rules, 'nat')

    iptables_manager.ipv4['nat'].add_rule('POSTROUTING',
                                          '-s %s -d %s/32 -j ACCEPT' %
                                          (ip_range, CONF.metadata_host))

    for dmz in CONF.dmz_cidr:
        iptables_manager.ipv4['nat'].add_rule('POSTROUTING',
                                              '-s %s -d %s -j ACCEPT' %
                                              (ip_range, dmz))

    iptables_manager.ipv4['nat'].add_rule('POSTROUTING',
                                          '-s %(range)s -d %(range)s '
                                          '-m conntrack ! --ctstate DNAT '
                                          '-j ACCEPT' %
                                          {'range': ip_range})
    iptables_manager.apply()


def bind_floating_ip(floating_ip, device):
    """Bind IP to public interface."""
    nova.privsep.linux_net.bind_ip(device, floating_ip)
    if CONF.send_arp_for_ha and CONF.send_arp_for_ha_count > 0:
        nova.privsep.linux_net.send_arp_for_ip(
            floating_ip, device, CONF.send_arp_for_ha_count)


def ensure_metadata_ip():
    """Sets up local metadata IP."""
    nova.privsep.linux_net.bind_ip('lo', '169.254.169.254',
                                   scope_is_link=True)


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
    iptables_manager.ipv4['nat'].add_rule('OUTPUT',
                                          '-d %s -p udp '
                                          '--dport %s -j DNAT --to %s:1194' %
                                          (public_ip, port, private_ip))
    iptables_manager.apply()


def ensure_floating_forward(floating_ip, fixed_ip, device, network):
    """Ensure floating IP forwarding rule."""
    # NOTE(vish): Make sure we never have duplicate rules for the same ip
    regex = r'.*\s+%s(/32|\s+|$)' % floating_ip
    num_rules = iptables_manager.ipv4['nat'].remove_rules_regex(regex)
    if num_rules:
        LOG.warning('Removed %(num)d duplicate rules for floating IP '
                    '%(float)s', {'num': num_rules, 'float': floating_ip})
    for chain, rule in floating_forward_rules(floating_ip, fixed_ip, device):
        iptables_manager.ipv4['nat'].add_rule(chain, rule)
    iptables_manager.apply()
    if device != network['bridge']:
        ensure_ebtables_rules(*floating_ebtables_rules(fixed_ip, network))


def remove_floating_forward(floating_ip, fixed_ip, device, network):
    """Remove forwarding for floating IP."""
    for chain, rule in floating_forward_rules(floating_ip, fixed_ip, device):
        iptables_manager.ipv4['nat'].remove_rule(chain, rule)
    iptables_manager.apply()
    if device != network['bridge']:
        remove_ebtables_rules(*floating_ebtables_rules(fixed_ip, network))


def floating_ebtables_rules(fixed_ip, network):
    """Makes sure only in-network traffic is bridged."""
    return (['PREROUTING --logical-in %s -p ipv4 --ip-src %s '
            '! --ip-dst %s -j redirect --redirect-target ACCEPT' %
            (network['bridge'], fixed_ip, network['cidr'])], 'nat')


def floating_forward_rules(floating_ip, fixed_ip, device):
    rules = []
    rule = '-s %s -j SNAT --to %s' % (fixed_ip, floating_ip)
    if device:
        rules.append(('float-snat', rule + ' -d %s' % fixed_ip))
        rules.append(('float-snat', rule + ' -o %s' % device))
    else:
        rules.append(('float-snat', rule))
    rules.append(
            ('PREROUTING', '-d %s -j DNAT --to %s' % (floating_ip, fixed_ip)))
    rules.append(
            ('OUTPUT', '-d %s -j DNAT --to %s' % (floating_ip, fixed_ip)))
    rules.append(('POSTROUTING', '-s %s -m conntrack --ctstate DNAT -j SNAT '
                  '--to-source %s' %
                  (fixed_ip, floating_ip)))
    return rules


@utils.synchronized('lock_gateway', external=True)
def initialize_gateway_device(dev, network_ref):
    if not network_ref:
        return

    nova.privsep.linux_net.enable_ipv4_forwarding()

    # NOTE(vish): The ip for dnsmasq has to be the first address on the
    #             bridge for it to respond to requests properly
    try:
        prefix = network_ref.cidr.prefixlen
    except AttributeError:
        prefix = network_ref['cidr'].rpartition('/')[2]

    full_ip = '%s/%s' % (network_ref['dhcp_server'], prefix)
    new_ip_params = [[full_ip, 'brd', network_ref['broadcast']]]
    old_ip_params = []
    out, err = nova.privsep.linux_net.lookup_ip(dev)
    for line in out.split('\n'):
        fields = line.split()
        if fields and fields[0] == 'inet':
            if fields[-2] in ('secondary', 'dynamic'):
                ip_params = fields[1:-2]
            else:
                ip_params = fields[1:-1]
            old_ip_params.append(ip_params)
            if ip_params[0] != full_ip:
                new_ip_params.append(ip_params)
    if not old_ip_params or old_ip_params[0][0] != full_ip:
        old_routes = []
        result = nova.privsep.linux_net.routes_show(dev)
        if result:
            out, err = result
            for line in out.split('\n'):
                fields = line.split()
                if fields and 'via' in fields:
                    old_routes.append(fields)
                    nova.privsep.linux_net.route_delete(dev, fields[0])
        for ip_params in old_ip_params:
            nova.privsep.linux_net.address_command_deprecated(
                dev, 'del', ip_params)
        for ip_params in new_ip_params:
            nova.privsep.linux_net.address_command_deprecated(
                dev, 'add', ip_params)

        for fields in old_routes:
            # TODO(mikal): this is horrible and should be re-written
            nova.privsep.linux_net.route_add_deprecated(fields)
        if CONF.send_arp_for_ha and CONF.send_arp_for_ha_count > 0:
            nova.privsep.linux_net.send_arp_for_ip(
                network_ref['dhcp_server'], dev,
                CONF.send_arp_for_ha_count)
    if CONF.use_ipv6:
        nova.privsep.linux_net.change_ip(dev, network_ref['cidr_v6'])


def get_dhcp_leases(context, network_ref):
    """Return a network's hosts config in dnsmasq leasefile format."""
    hosts = []
    host = None
    if network_ref['multi_host']:
        host = CONF.host
    for fixedip in objects.FixedIPList.get_by_network(context,
                                                      network_ref,
                                                      host=host):
        # NOTE(cfb): Don't return a lease entry if the IP isn't
        #            already leased
        if fixedip.leased:
            hosts.append(_host_lease(fixedip))

    return '\n'.join(hosts)


def get_dhcp_hosts(context, network_ref, fixedips):
    """Get network's hosts config in dhcp-host format."""
    hosts = []
    macs = set()
    for fixedip in fixedips:
        if fixedip.allocated:
            if fixedip.virtual_interface.address not in macs:
                hosts.append(_host_dhcp(fixedip))
                macs.add(fixedip.virtual_interface.address)
    return '\n'.join(hosts)


def get_dns_hosts(context, network_ref):
    """Get network's DNS hosts in hosts format."""
    hosts = []
    for fixedip in objects.FixedIPList.get_by_network(context, network_ref):
        if fixedip.allocated:
            hosts.append(_host_dns(fixedip))
    return '\n'.join(hosts)


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


def _remove_dnsmasq_accept_rules(dev):
    """Remove DHCP and DNS traffic allowed through to dnsmasq."""
    table = iptables_manager.ipv4['filter']
    for port in [67, 53]:
        for proto in ['udp', 'tcp']:
            args = {'dev': dev, 'port': port, 'proto': proto}
            table.remove_rule('INPUT',
                           '-i %(dev)s -p %(proto)s -m %(proto)s '
                           '--dport %(port)s -j ACCEPT' % args)
    iptables_manager.apply()


# NOTE(russellb) Curious why this is needed?  Check out this explanation from
# markmc: https://bugzilla.redhat.com/show_bug.cgi?id=910619#c6
def _add_dhcp_mangle_rule(dev):
    table = iptables_manager.ipv4['mangle']
    table.add_rule('POSTROUTING',
                   '-o %s -p udp -m udp --dport 68 -j CHECKSUM '
                   '--checksum-fill' % dev)
    iptables_manager.apply()


def _remove_dhcp_mangle_rule(dev):
    table = iptables_manager.ipv4['mangle']
    table.remove_rule('POSTROUTING',
                      '-o %s -p udp -m udp --dport 68 -j CHECKSUM '
                      '--checksum-fill' % dev)
    iptables_manager.apply()


def get_dhcp_opts(context, network_ref, fixedips):
    """Get network's hosts config in dhcp-opts format."""
    gateway = network_ref['gateway']
    # NOTE(vish): if we are in multi-host mode and we are not sharing
    #             addresses, then we actually need to hand out the
    #             dhcp server address as the gateway.
    if network_ref['multi_host'] and not (network_ref['share_address'] or
                                          CONF.share_dhcp_address):
        gateway = network_ref['dhcp_server']
    hosts = []
    if CONF.use_single_default_gateway:
        for fixedip in fixedips:
            if fixedip.allocated:
                vif_id = fixedip.virtual_interface_id
                if fixedip.default_route:
                    hosts.append(_host_dhcp_opts(vif_id, gateway))
                else:
                    hosts.append(_host_dhcp_opts(vif_id))
    else:
        hosts.append(_host_dhcp_opts(None, gateway))
    return '\n'.join(hosts)


def release_dhcp(dev, address, mac_address):
    if nova.privsep.linux_net.device_exists(dev):
        try:
            nova.privsep.linux_net.dhcp_release(dev, address, mac_address)
        except processutils.ProcessExecutionError:
            raise exception.NetworkDhcpReleaseFailed(address=address,
                                                     mac_address=mac_address)


def update_dhcp(context, dev, network_ref):
    conffile = _dhcp_file(dev, 'conf')
    host = None
    if network_ref['multi_host']:
        host = CONF.host
    fixedips = objects.FixedIPList.get_by_network(context,
                                                  network_ref,
                                                  host=host)
    write_to_file(conffile, get_dhcp_hosts(context, network_ref, fixedips))
    restart_dhcp(context, dev, network_ref, fixedips)


def update_dns(context, dev, network_ref):
    hostsfile = _dhcp_file(dev, 'hosts')
    host = None
    if network_ref['multi_host']:
        host = CONF.host
    fixedips = objects.FixedIPList.get_by_network(context,
                                                  network_ref,
                                                  host=host)
    write_to_file(hostsfile, get_dns_hosts(context, network_ref))
    restart_dhcp(context, dev, network_ref, fixedips)


def kill_dhcp(dev):
    pid = _dnsmasq_pid_for(dev)
    if pid:
        # Check that the process exists and looks like a dnsmasq process
        conffile = _dhcp_file(dev, 'conf')
        if is_pid_cmdline_correct(pid, conffile.split('/')[-1]):
            nova.privsep.utils.kill(pid, signal.SIGKILL)
        else:
            LOG.debug('Pid %d is stale, skip killing dnsmasq', pid)
    _remove_dnsmasq_accept_rules(dev)
    _remove_dhcp_mangle_rule(dev)


# NOTE(ja): Sending a HUP only reloads the hostfile, so any
#           configuration options (like dchp-range, vlan, ...)
#           aren't reloaded.
@utils.synchronized('dnsmasq_start')
def restart_dhcp(context, dev, network_ref, fixedips):
    """(Re)starts a dnsmasq server for a given network.

    If a dnsmasq instance is already running then send a HUP
    signal causing it to reload, otherwise spawn a new instance.

    """
    conffile = _dhcp_file(dev, 'conf')

    optsfile = _dhcp_file(dev, 'opts')
    write_to_file(optsfile, get_dhcp_opts(context, network_ref, fixedips))
    os.chmod(optsfile, 0o644)

    _add_dhcp_mangle_rule(dev)

    # Make sure dnsmasq can actually read it (it setuid()s to "nobody")
    os.chmod(conffile, 0o644)

    pid = _dnsmasq_pid_for(dev)

    # if dnsmasq is already running, then tell it to reload
    if pid:
        if is_pid_cmdline_correct(pid, conffile.split('/')[-1]):
            try:
                nova.privsep.utils.kill(pid, signal.SIGHUP)
                _add_dnsmasq_accept_rules(dev)
                return
            except Exception as exc:
                LOG.error('kill -HUP dnsmasq threw %s', exc)
        else:
            LOG.debug('Pid %d is stale, relaunching dnsmasq', pid)

    dns_servers = CONF.dns_server
    if CONF.use_network_dns_servers:
        if network_ref.get('dns1'):
            dns_servers.append(network_ref.get('dns1'))
        if network_ref.get('dns2'):
            dns_servers.append(network_ref.get('dns2'))

    hosts_path = None
    if network_ref['multi_host']:
        hosts_path = _dhcp_file(dev, 'hosts')

    nova.privsep.linux_net.restart_dnsmasq(
        jsonutils.dumps(CONF.dhcpbridge_flagfile),
        network_ref,
        CONF.dnsmasq_config_file,
        _dhcp_file(dev, 'pid'),
        _dhcp_file(dev, 'opts'),
        CONF.dhcp_lease_time,
        len(netaddr.IPNetwork(network_ref['cidr'])),
        _dhcp_file(dev, 'conf'),
        CONF.dhcpbridge,
        CONF.api.dhcp_domain,
        dns_servers,
        hosts_path)

    _add_dnsmasq_accept_rules(dev)


@utils.synchronized('radvd_start')
def update_ra(context, dev, network_ref):
    conffile = _ra_file(dev, 'conf')
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
    write_to_file(conffile, conf_str)

    # Make sure radvd can actually read it (it setuid()s to "nobody")
    os.chmod(conffile, 0o644)

    pid = _ra_pid_for(dev)

    # if radvd is already running, then tell it to reload
    if pid:
        if is_pid_cmdline_correct(pid, conffile):
            try:
                nova.privsep.utils.kill(pid, signal.SIGTERM)
            except Exception as exc:
                LOG.error('killing radvd threw %s', exc)
        else:
            LOG.debug('Pid %d is stale, relaunching radvd', pid)

    nova.privsep.linux_net.start_ra(_ra_file(dev, 'conf'),
                                    _ra_file(dev, 'pid'))


def _host_lease(fixedip):
    """Return a host string for an address in leasefile format."""
    timestamp = timeutils.utcnow()
    seconds_since_epoch = calendar.timegm(timestamp.utctimetuple())
    return '%d %s %s %s *' % (seconds_since_epoch + CONF.dhcp_lease_time,
                              fixedip.virtual_interface.address,
                              fixedip.address,
                              fixedip.instance.hostname or '*')


def _host_dhcp_network(vif_id):
    return 'NW-%s' % vif_id


def _host_dhcp(fixedip):
    """Return a host string for an address in dhcp-host format."""
    # NOTE(cfb): dnsmasq on linux only supports 64 characters in the hostname
    #            field (LP #1238910). Since the . counts as a character we need
    #            to truncate the hostname to only 63 characters.
    hostname = fixedip.instance.hostname
    if len(hostname) > 63:
        LOG.warning('hostname %s too long, truncating.', hostname)
        hostname = fixedip.instance.hostname[:2] + '-' +\
                   fixedip.instance.hostname[-60:]
    if CONF.use_single_default_gateway:
        net = _host_dhcp_network(fixedip.virtual_interface_id)
        return '%s,%s.%s,%s,net:%s' % (fixedip.virtual_interface.address,
                               hostname,
                               CONF.api.dhcp_domain,
                               fixedip.address,
                               net)
    else:
        return '%s,%s.%s,%s' % (fixedip.virtual_interface.address,
                               hostname,
                               CONF.api.dhcp_domain,
                               fixedip.address)


def _host_dns(fixedip):
    return '%s\t%s.%s' % (fixedip.address,
                          fixedip.instance.hostname,
                          CONF.api.dhcp_domain)


def _host_dhcp_opts(vif_id=None, gateway=None):
    """Return an empty gateway option."""
    values = []
    if vif_id is not None:
        values.append(_host_dhcp_network(vif_id))
    # NOTE(vish): 3 is the dhcp option for gateway.
    values.append('3')
    if gateway:
        values.append('%s' % gateway)
    return ','.join(values)


def _dhcp_file(dev, kind):
    """Return path to a pid, leases, hosts or conf file for a bridge/device."""
    fileutils.ensure_tree(CONF.networks_path)
    return os.path.abspath('%s/nova-%s.%s' % (CONF.networks_path,
                                              dev,
                                              kind))


def _ra_file(dev, kind):
    """Return path to a pid or conf file for a bridge/device."""
    fileutils.ensure_tree(CONF.networks_path)
    return os.path.abspath('%s/nova-ra-%s.%s' % (CONF.networks_path,
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


def delete_bridge_dev(dev):
    """Delete a network bridge."""
    if nova.privsep.linux_net.device_exists(dev):
        try:
            nova.privsep.linux_net.set_device_disabled(dev)
            nova.privsep.linux_net.delete_bridge(dev)
        except processutils.ProcessExecutionError:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed removing bridge device: '%s'", dev)


# Similar to compute virt layers, the Linux network node
# code uses a flexible driver model to support different ways
# of creating ethernet interfaces and attaching them to the network.
# In the case of a network host, these interfaces
# act as gateway/dhcp/vpn/etc. endpoints not VM interfaces.
interface_driver = None


def _get_interface_driver():
    global interface_driver
    if not interface_driver:
        interface_driver = importutils.import_object(
                CONF.linuxnet_interface_driver)
    return interface_driver


def plug(network, mac_address, gateway=True):
    return _get_interface_driver().plug(network, mac_address, gateway)


def unplug(network):
    return _get_interface_driver().unplug(network)


def get_dev(network):
    return _get_interface_driver().get_dev(network)


class LinuxNetInterfaceDriver(object):
    """Abstract class that defines generic network host API
    for all Linux interface drivers.
    """

    def plug(self, network, mac_address):
        """Create Linux device, return device name."""
        raise NotImplementedError()

    def unplug(self, network):
        """Destroy Linux device, return device name."""
        raise NotImplementedError()

    def get_dev(self, network):
        """Get device name."""
        raise NotImplementedError()


# plugs interfaces using Linux Bridge
class LinuxBridgeInterfaceDriver(LinuxNetInterfaceDriver):

    def plug(self, network, mac_address, gateway=True):
        vlan = network.get('vlan')
        if vlan is not None:
            iface = CONF.vlan_interface or network['bridge_interface']
            LinuxBridgeInterfaceDriver.ensure_vlan_bridge(
                           vlan,
                           network['bridge'],
                           iface,
                           network,
                           mac_address,
                           network.get('mtu'))
            iface = 'vlan%s' % vlan
        else:
            iface = CONF.flat_interface or network['bridge_interface']
            LinuxBridgeInterfaceDriver.ensure_bridge(
                          network['bridge'],
                          iface,
                          network, gateway)

        if network['share_address'] or CONF.share_dhcp_address:
            isolate_dhcp_address(iface, network['dhcp_server'])
        # NOTE(vish): applying here so we don't get a lock conflict
        iptables_manager.apply()
        return network['bridge']

    def unplug(self, network, gateway=True):
        vlan = network.get('vlan')
        if vlan is not None:
            iface = 'vlan%s' % vlan
            LinuxBridgeInterfaceDriver.remove_vlan_bridge(vlan,
                                                          network['bridge'])
        else:
            iface = CONF.flat_interface or network['bridge_interface']
            LinuxBridgeInterfaceDriver.remove_bridge(network['bridge'],
                                                     gateway)

        if network['share_address'] or CONF.share_dhcp_address:
            remove_isolate_dhcp_address(iface, network['dhcp_server'])

        iptables_manager.apply()
        return self.get_dev(network)

    def get_dev(self, network):
        return network['bridge']

    @staticmethod
    def ensure_vlan_bridge(vlan_num, bridge, bridge_interface,
                           net_attrs=None, mac_address=None,
                           mtu=None):
        """Create a vlan and bridge unless they already exist."""
        interface = LinuxBridgeInterfaceDriver.ensure_vlan(vlan_num,
                                               bridge_interface, mac_address,
                                               mtu)
        LinuxBridgeInterfaceDriver.ensure_bridge(bridge, interface, net_attrs)
        return interface

    @staticmethod
    def remove_vlan_bridge(vlan_num, bridge):
        """Delete a bridge and vlan."""
        LinuxBridgeInterfaceDriver.remove_bridge(bridge)
        LinuxBridgeInterfaceDriver.remove_vlan(vlan_num)

    @staticmethod
    @utils.synchronized('lock_vlan', external=True)
    def ensure_vlan(vlan_num, bridge_interface, mac_address=None, mtu=None,
                    interface=None):
        """Create a vlan unless it already exists."""
        if interface is None:
            interface = 'vlan%s' % vlan_num
        if not nova.privsep.linux_net.device_exists(interface):
            LOG.debug('Starting VLAN interface %s', interface)
            nova.privsep.linux_net.add_vlan(bridge_interface, interface,
                                            vlan_num)
            # (danwent) the bridge will inherit this address, so we want to
            # make sure it is the value set from the NetworkManager
            if mac_address:
                nova.privsep.linux_net.set_device_macaddr(
                    interface, mac_address)
            nova.privsep.linux_net.set_device_enabled(interface)
        # NOTE(vish): set mtu every time to ensure that changes to mtu get
        #             propagated
        nova.privsep.linux_net.set_device_mtu(interface, mtu)
        return interface

    @staticmethod
    @utils.synchronized('lock_vlan', external=True)
    def remove_vlan(vlan_num):
        """Delete a vlan."""
        vlan_interface = 'vlan%s' % vlan_num
        nova.privsep.linux_net.delete_net_dev(vlan_interface)

    @staticmethod
    @utils.synchronized('lock_bridge', external=True)
    def ensure_bridge(bridge, interface, net_attrs=None, gateway=True,
                      filtering=True):
        """Create a bridge unless it already exists.

        :param interface: the interface to create the bridge on.
        :param net_attrs: dictionary with  attributes used to create bridge.
        :param gateway: whether or not the bridge is a gateway.
        :param filtering: whether or not to create filters on the bridge.

        If net_attrs is set, it will add the net_attrs['gateway'] to the bridge
        using net_attrs['broadcast'] and net_attrs['cidr'].  It will also add
        the ip_v6 address specified in net_attrs['cidr_v6'] if use_ipv6 is set.

        The code will attempt to move any IPs that already exist on the
        interface onto the bridge and reset the default gateway if necessary.

        """
        if not nova.privsep.linux_net.device_exists(bridge):
            LOG.debug('Starting Bridge %s', bridge)
            out, err = nova.privsep.linux_net.add_bridge(bridge)
            if (err and err != "device %s already exists; can't create "
                               "bridge with the same name\n" % (bridge)):
                msg = _('Failed to add bridge: %s') % err
                raise exception.NovaException(msg)

            nova.privsep.linux_net.bridge_setfd(bridge)
            nova.privsep.linux_net.bridge_disable_stp(bridge)
            nova.privsep.linux_net.set_device_enabled(bridge)

        if interface:
            LOG.debug('Adding interface %(interface)s to bridge %(bridge)s',
                      {'interface': interface, 'bridge': bridge})
            out, err = nova.privsep.linux_net.bridge_add_interface(
                           bridge, interface)
            if (err and err != "device %s is already a member of a bridge; "
                     "can't enslave it to bridge %s.\n" % (interface, bridge)):
                msg = _('Failed to add interface: %s') % err
                raise exception.NovaException(msg)

            # NOTE(apmelton): Linux bridge's default behavior is to use the
            # lowest mac of all plugged interfaces. This isn't a problem when
            # it is first created and the only interface is the bridged
            # interface. But, as instance interfaces are plugged, there is a
            # chance for the mac to change. So, set it here so that it won't
            # change in the future.
            if not CONF.fake_network:
                interface_addrs = netifaces.ifaddresses(interface)
                interface_mac = interface_addrs[netifaces.AF_LINK][0]['addr']
                nova.privsep.linux_net.set_device_macaddr(
                    bridge, interface_mac)

            nova.privsep.linux_net.set_device_enabled(interface)

            # NOTE(vish): This will break if there is already an ip on the
            #             interface, so we move any ips to the bridge
            # NOTE(danms): We also need to copy routes to the bridge so as
            #              not to break existing connectivity on the interface
            old_routes = []
            out, err = nova.privsep.linux_net.routes_show(interface)
            for line in out.split('\n'):
                fields = line.split()
                if fields and 'via' in fields:
                    old_routes.append(fields)
                    nova.privsep.linux_net.route_delete_deprecated(fields)
            out, err = nova.privsep.linux_net.lookup_ip(interface)
            for line in out.split('\n'):
                fields = line.split()
                if fields and fields[0] == 'inet':
                    if fields[-2] in ('secondary', 'dynamic', ):
                        params = fields[1:-2]
                    else:
                        params = fields[1:-1]
                    nova.privsep.linux_net.address_command_deprecated(
                        fields[-1], 'del', params)
                    nova.privsep.linux_net.address_command_deprecated(
                        bridge, 'add', params)
            for fields in old_routes:
                nova.privsep.linux_net.route_add_deprecated(fields)

        if filtering:
            # Don't forward traffic unless we were told to be a gateway
            ipv4_filter = iptables_manager.ipv4['filter']
            if gateway:
                for rule in get_gateway_rules(bridge):
                    ipv4_filter.add_rule(*rule)
            else:
                ipv4_filter.add_rule('FORWARD',
                                     ('--in-interface %s -j %s'
                                      % (bridge, CONF.iptables_drop_action)))
                ipv4_filter.add_rule('FORWARD',
                                     ('--out-interface %s -j %s'
                                      % (bridge, CONF.iptables_drop_action)))

    @staticmethod
    @utils.synchronized('lock_bridge', external=True)
    def remove_bridge(bridge, gateway=True, filtering=True):
        """Delete a bridge."""
        if not nova.privsep.linux_net.device_exists(bridge):
            return
        else:
            if filtering:
                ipv4_filter = iptables_manager.ipv4['filter']
                if gateway:
                    for rule in get_gateway_rules(bridge):
                        ipv4_filter.remove_rule(*rule)
                else:
                    drop_actions = ['DROP']
                    if CONF.iptables_drop_action != 'DROP':
                        drop_actions.append(CONF.iptables_drop_action)

                    for drop_action in drop_actions:
                        ipv4_filter.remove_rule('FORWARD',
                                                ('--in-interface %s -j %s'
                                                 % (bridge, drop_action)))
                        ipv4_filter.remove_rule('FORWARD',
                                                ('--out-interface %s -j %s'
                                                 % (bridge, drop_action)))
            delete_bridge_dev(bridge)


# NOTE(cfb): Fix for LP #1316621, #1501366.
#            We call ebtables with --concurrent which causes ebtables to
#            use a lock file to deal with concurrent calls. Since we can't
#            be sure the libvirt also uses --concurrent we retry in a loop
#            to be sure.
#
#            ebtables doesn't implement a timeout and doesn't gracefully
#            handle cleaning up a lock file if someone sends a SIGKILL to
#            ebtables while its holding a lock. As a result we want to add
#            a timeout to the ebtables calls but we first need to teach
#            oslo_concurrency how to do that.
def _exec_ebtables(table, rule, insert_rule=True, check_exit_code=True):
    # List of error strings to re-try.
    retry_strings = (
        'Multiple ebtables programs',
    )

    # We always try at least once
    attempts = CONF.ebtables_exec_attempts
    count = 1
    while count <= attempts:
        # Updated our counters if needed
        sleep = CONF.ebtables_retry_interval * count
        count += 1
        # NOTE(cfb): ebtables reports all errors with a return code of 255.
        #            As such we can't know if we hit a locking error, or some
        #            other error (like a rule doesn't exist) so we have to
        #            to parse stderr.
        try:
            nova.privsep.linux_net.modify_ebtables(table, rule,
                                                   insert_rule=insert_rule)
        except processutils.ProcessExecutionError as exc:
            # See if we can retry the error.
            if any(error in exc.stderr for error in retry_strings):
                if count > attempts and check_exit_code:
                    LOG.warning('Rule edit for %s failed. Not Retrying.',
                                table)
                    raise
                else:
                    # We need to sleep a bit before retrying
                    LOG.warning('Rule edit for %(table)s failed. '
                                'Sleeping %(time)s seconds before retry.',
                                {'table': table, 'time': sleep})
                    time.sleep(sleep)
            else:
                # Not eligible for retry
                if check_exit_code:
                    LOG.warning('Rule edit for %s failed and not eligible '
                                'for retry.',
                                table)
                    raise
                else:
                    return
        else:
            # Success
            return


@utils.synchronized('ebtables', external=True)
def ensure_ebtables_rules(rules, table='filter'):
    for rule in rules:
        _exec_ebtables(table, rule.split(), insert_rule=False,
                       check_exit_code=False)
        _exec_ebtables(table, rule.split())


@utils.synchronized('ebtables', external=True)
def remove_ebtables_rules(rules, table='filter'):
    for rule in rules:
        _exec_ebtables(table, rule.split(), insert_rule=False,
                       check_exit_code=False)


def isolate_dhcp_address(interface, address):
    # block arp traffic to address across the interface
    rules = []
    rules.append('INPUT -p ARP -i %s --arp-ip-dst %s -j DROP'
                 % (interface, address))
    rules.append('OUTPUT -p ARP -o %s --arp-ip-src %s -j DROP'
                 % (interface, address))
    rules.append('FORWARD -p IPv4 -i %s --ip-protocol udp '
                 '--ip-destination-port 67:68 -j DROP'
                 % interface)
    rules.append('FORWARD -p IPv4 -o %s --ip-protocol udp '
                 '--ip-destination-port 67:68 -j DROP'
                 % interface)
    # NOTE(vish): the above is not possible with iptables/arptables
    ensure_ebtables_rules(rules)


def remove_isolate_dhcp_address(interface, address):
    # block arp traffic to address across the interface
    rules = []
    rules.append('INPUT -p ARP -i %s --arp-ip-dst %s -j DROP'
                 % (interface, address))
    rules.append('OUTPUT -p ARP -o %s --arp-ip-src %s -j DROP'
                 % (interface, address))
    rules.append('FORWARD -p IPv4 -i %s --ip-protocol udp '
                 '--ip-destination-port 67:68 -j DROP'
                 % interface)
    rules.append('FORWARD -p IPv4 -o %s --ip-protocol udp '
                 '--ip-destination-port 67:68 -j DROP'
                 % interface)
    remove_ebtables_rules(rules)
    # NOTE(vish): the above is not possible with iptables/arptables


def get_gateway_rules(bridge):
    interfaces = CONF.forward_bridge_interface
    if 'all' in interfaces:
        return [('FORWARD', '-i %s -j ACCEPT' % bridge),
                ('FORWARD', '-o %s -j ACCEPT' % bridge)]
    rules = []
    for iface in CONF.forward_bridge_interface:
        if iface:
            rules.append(('FORWARD', '-i %s -o %s -j ACCEPT' % (bridge,
                                                                iface)))
            rules.append(('FORWARD', '-i %s -o %s -j ACCEPT' % (iface,
                                                                bridge)))
    rules.append(('FORWARD', '-i %s -o %s -j ACCEPT' % (bridge, bridge)))
    rules.append(('FORWARD', '-i %s -j %s' % (bridge,
                                              CONF.iptables_drop_action)))
    rules.append(('FORWARD', '-o %s -j %s' % (bridge,
                                              CONF.iptables_drop_action)))
    return rules


# plugs interfaces using Open vSwitch
class LinuxOVSInterfaceDriver(LinuxNetInterfaceDriver):

    def plug(self, network, mac_address, gateway=True):
        dev = self.get_dev(network)
        if not nova.privsep.linux_net.device_exists(dev):
            bridge = CONF.linuxnet_ovs_integration_bridge

            nova.privsep.linux_net.ovs_plug(CONF.ovs_vsctl_timeout,
                                            bridge, dev, mac_address)
            nova.privsep.linux_net.set_device_macaddr(
                dev, mac_address)
            nova.privsep.linux_net.set_device_mtu(dev, network.get('mtu'))
            nova.privsep.linux_net.set_device_enabled(dev)
            if not gateway:
                # If we weren't instructed to act as a gateway then add the
                # appropriate flows to block all non-dhcp traffic.
                nova.privsep.linux_net.ovs_drop_nondhcp(
                    bridge, mac_address)

                # .. and make sure iptbles won't forward it as well.
                iptables_manager.ipv4['filter'].add_rule('FORWARD',
                    '--in-interface %s -j %s' % (bridge,
                                                 CONF.iptables_drop_action))
                iptables_manager.ipv4['filter'].add_rule('FORWARD',
                    '--out-interface %s -j %s' % (bridge,
                                                  CONF.iptables_drop_action))
            else:
                for rule in get_gateway_rules(bridge):
                    iptables_manager.ipv4['filter'].add_rule(*rule)

        return dev

    def unplug(self, network):
        dev = self.get_dev(network)
        bridge = CONF.linuxnet_ovs_integration_bridge

        nova.privsep.linux_net.ovs_unplug(CONF.ovs_vsctl_timeout, bridge, dev)

        return dev

    def get_dev(self, network):
        dev = 'gw-' + str(network['uuid'][0:11])
        return dev


iptables_manager = IptablesManager()


def set_vf_trusted(pci_addr, trusted):
    """Configures the VF to be trusted or not

    :param pci_addr: PCI slot of the device
    :param trusted: Boolean value to indicate whether to
                    enable/disable 'trusted' capability
    """
    pf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr,
                                                    pf_interface=True)
    vf_num = pci_utils.get_vf_num_by_pci_address(pci_addr)
    nova.privsep.linux_net.set_device_trust(
        pf_ifname, vf_num, trusted)
