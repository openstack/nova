# Copyright 2011 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2011 Citrix Systems, Inc.
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

from oslo_log import log as logging
from oslo_utils import importutils

import nova.conf
from nova import context
from nova.network import linux_net
from nova import objects
from nova import utils
from nova.virt import netutils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


def load_driver(default, *args, **kwargs):
    fw_class = importutils.import_class(CONF.firewall_driver or default)
    return fw_class(*args, **kwargs)


class FirewallDriver(object):
    """Firewall Driver base class.

    Defines methods that any driver providing security groups should implement.

    """
    def prepare_instance_filter(self, instance, network_info):
        """Prepare filters for the instance.

        At this point, the instance isn't running yet.
        """
        raise NotImplementedError()

    def filter_defer_apply_on(self):
        """Defer application of IPTables rules."""
        pass

    def filter_defer_apply_off(self):
        """Turn off deferral of IPTables rules and apply the rules now."""
        pass

    def unfilter_instance(self, instance, network_info):
        """Stop filtering instance."""
        raise NotImplementedError()

    def apply_instance_filter(self, instance, network_info):
        """Apply instance filter.

        Once this method returns, the instance should be firewalled
        appropriately. This method should as far as possible be a
        no-op. It's vastly preferred to get everything set up in
        prepare_instance_filter.
        """
        raise NotImplementedError()

    def refresh_security_group_rules(self, security_group_id):
        """Refresh security group rules from data store

        Gets called when a rule has been added to or removed from
        the security group.
        """
        raise NotImplementedError()

    def refresh_instance_security_rules(self, instance):
        """Refresh security group rules from data store

        Gets called when an instance gets added to or removed from
        the security group the instance is a member of or if the
        group gains or loses a rule.
        """
        raise NotImplementedError()

    def setup_basic_filtering(self, instance, network_info):
        """Create rules to block spoofing and allow dhcp.

        This gets called when spawning an instance, before
        :py:meth:`prepare_instance_filter`.

        """
        raise NotImplementedError()

    def instance_filter_exists(self, instance, network_info):
        """Check nova-instance-instance-xxx exists."""
        raise NotImplementedError()


class IptablesFirewallDriver(FirewallDriver):
    """Driver which enforces security groups through iptables rules."""

    def __init__(self, **kwargs):
        self.iptables = linux_net.iptables_manager
        self.instance_info = {}

        # Flags for DHCP request rule
        self.dhcp_create = False
        self.dhcp_created = False

        self.iptables.ipv4['filter'].add_chain('sg-fallback')
        self.iptables.ipv4['filter'].add_rule('sg-fallback', '-j DROP')
        self.iptables.ipv6['filter'].add_chain('sg-fallback')
        self.iptables.ipv6['filter'].add_rule('sg-fallback', '-j DROP')

    def setup_basic_filtering(self, instance, network_info):
        pass

    def apply_instance_filter(self, instance, network_info):
        """No-op. Everything is done in prepare_instance_filter."""
        pass

    def filter_defer_apply_on(self):
        self.iptables.defer_apply_on()

    def filter_defer_apply_off(self):
        self.iptables.defer_apply_off()

    def unfilter_instance(self, instance, network_info):
        if self.instance_info.pop(instance.id, None):
            self.remove_filters_for_instance(instance)
            self.iptables.apply()
        else:
            LOG.info('Attempted to unfilter instance which is not filtered',
                     instance=instance)

    def prepare_instance_filter(self, instance, network_info):
        self.instance_info[instance.id] = (instance, network_info)
        ipv4_rules, ipv6_rules = self.instance_rules(instance, network_info)
        self.add_filters_for_instance(instance, network_info, ipv4_rules,
                                      ipv6_rules)
        LOG.debug('Filters added to instance: %s', instance.id,
                  instance=instance)
        # Ensure that DHCP request rule is updated if necessary
        if (self.dhcp_create and not self.dhcp_created):
            self.iptables.ipv4['filter'].add_rule(
                    'INPUT',
                    '-s 0.0.0.0/32 -d 255.255.255.255/32 '
                    '-p udp -m udp --sport 68 --dport 67 -j ACCEPT')
            self.iptables.ipv4['filter'].add_rule(
                    'FORWARD',
                    '-s 0.0.0.0/32 -d 255.255.255.255/32 '
                    '-p udp -m udp --sport 68 --dport 67 -j ACCEPT')
            self.dhcp_created = True
        self.iptables.apply()

    def _create_filter(self, ips, chain_name):
        return ['-d %s -j $%s' % (ip, chain_name) for ip in ips]

    def _get_subnets(self, network_info, version):
        subnets = []
        for vif in network_info:
            if 'network' in vif and 'subnets' in vif['network']:
                for subnet in vif['network']['subnets']:
                    if subnet['version'] == version:
                        subnets.append(subnet)
        return subnets

    def _filters_for_instance(self, chain_name, network_info):
        """Creates a rule corresponding to each ip that defines a
           jump to the corresponding instance - chain for all the traffic
           destined to that ip.
        """
        v4_subnets = self._get_subnets(network_info, 4)
        v6_subnets = self._get_subnets(network_info, 6)
        ips_v4 = [ip['address'] for subnet in v4_subnets
                                for ip in subnet['ips']]
        ipv4_rules = self._create_filter(ips_v4, chain_name)

        ipv6_rules = ips_v6 = []
        if CONF.use_ipv6:
            if v6_subnets:
                ips_v6 = [ip['address'] for subnet in v6_subnets
                                        for ip in subnet['ips']]
            ipv6_rules = self._create_filter(ips_v6, chain_name)

        return ipv4_rules, ipv6_rules

    def _add_filters(self, chain_name, ipv4_rules, ipv6_rules):
        for rule in ipv4_rules:
            self.iptables.ipv4['filter'].add_rule(chain_name, rule)

        if CONF.use_ipv6:
            for rule in ipv6_rules:
                self.iptables.ipv6['filter'].add_rule(chain_name, rule)

    def add_filters_for_instance(self, instance, network_info, inst_ipv4_rules,
                                 inst_ipv6_rules):
        chain_name = self._instance_chain_name(instance)
        if CONF.use_ipv6:
            self.iptables.ipv6['filter'].add_chain(chain_name)
        self.iptables.ipv4['filter'].add_chain(chain_name)
        ipv4_rules, ipv6_rules = self._filters_for_instance(chain_name,
                                                            network_info)
        self._add_filters('local', ipv4_rules, ipv6_rules)
        self._add_filters(chain_name, inst_ipv4_rules, inst_ipv6_rules)

    def remove_filters_for_instance(self, instance):
        chain_name = self._instance_chain_name(instance)

        self.iptables.ipv4['filter'].remove_chain(chain_name)
        if CONF.use_ipv6:
            self.iptables.ipv6['filter'].remove_chain(chain_name)

    def _instance_chain_name(self, instance):
        return 'inst-%s' % (instance.id,)

    def _do_basic_rules(self, ipv4_rules, ipv6_rules, network_info):
        # Always drop invalid packets
        ipv4_rules += ['-m state --state ' 'INVALID -j DROP']
        ipv6_rules += ['-m state --state ' 'INVALID -j DROP']

        # Allow established connections
        ipv4_rules += ['-m state --state ESTABLISHED,RELATED -j ACCEPT']
        ipv6_rules += ['-m state --state ESTABLISHED,RELATED -j ACCEPT']

    def _do_dhcp_rules(self, ipv4_rules, network_info):
        v4_subnets = self._get_subnets(network_info, 4)
        dhcp_servers = [subnet.get_meta('dhcp_server')
            for subnet in v4_subnets if subnet.get_meta('dhcp_server')]

        for dhcp_server in dhcp_servers:
            if dhcp_server:
                ipv4_rules.append('-s %s -p udp --sport 67 --dport 68 '
                                  '-j ACCEPT' % (dhcp_server,))
                self.dhcp_create = True

    def _do_project_network_rules(self, ipv4_rules, ipv6_rules, network_info):
        v4_subnets = self._get_subnets(network_info, 4)
        v6_subnets = self._get_subnets(network_info, 6)
        cidrs = [subnet['cidr'] for subnet in v4_subnets]
        for cidr in cidrs:
            ipv4_rules.append('-s %s -j ACCEPT' % (cidr,))
        if CONF.use_ipv6:
            cidrv6s = [subnet['cidr'] for subnet in v6_subnets]
            for cidrv6 in cidrv6s:
                ipv6_rules.append('-s %s -j ACCEPT' % (cidrv6,))

    def _do_ra_rules(self, ipv6_rules, network_info):
        v6_subnets = self._get_subnets(network_info, 6)
        gateways_v6 = [subnet['gateway']['address'] for subnet in v6_subnets]

        for gateway_v6 in gateways_v6:
            ipv6_rules.append(
                    '-s %s/128 -p icmpv6 -j ACCEPT' % (gateway_v6,))

    def _build_icmp_rule(self, rule, version):
        icmp_type = rule.from_port
        icmp_code = rule.to_port

        if icmp_type == -1:
            icmp_type_arg = None
        else:
            icmp_type_arg = '%s' % icmp_type
            if not icmp_code == -1:
                icmp_type_arg += '/%s' % icmp_code

        if icmp_type_arg:
            if version == 4:
                return ['-m', 'icmp', '--icmp-type', icmp_type_arg]
            elif version == 6:
                return ['-m', 'icmp6', '--icmpv6-type', icmp_type_arg]
        # return empty list if icmp_type == -1
        return []

    def _build_tcp_udp_rule(self, rule, version):
        if rule.from_port == rule.to_port:
            return ['--dport', '%s' % (rule.from_port,)]
        else:
            return ['-m', 'multiport',
                    '--dports', '%s:%s' % (rule.from_port,
                                           rule.to_port)]

    def instance_rules(self, instance, network_info):
        ctxt = context.get_admin_context()
        if isinstance(instance, dict):
            # NOTE(danms): allow old-world instance objects from
            # unconverted callers; all we need is instance.uuid below
            instance = objects.Instance._from_db_object(
                ctxt, objects.Instance(), instance, [])

        ipv4_rules = []
        ipv6_rules = []

        # Initialize with basic rules
        self._do_basic_rules(ipv4_rules, ipv6_rules, network_info)
        # Set up rules to allow traffic to/from DHCP server
        self._do_dhcp_rules(ipv4_rules, network_info)

        # Allow project network traffic
        if CONF.allow_same_net_traffic:
            self._do_project_network_rules(ipv4_rules, ipv6_rules,
                                           network_info)
        # We wrap these in CONF.use_ipv6 because they might cause
        # a DB lookup. The other ones are just list operations, so
        # they're not worth the clutter.
        if CONF.use_ipv6:
            # Allow RA responses
            self._do_ra_rules(ipv6_rules, network_info)

        # then, security group chains and rules
        rules = objects.SecurityGroupRuleList.get_by_instance(ctxt, instance)

        for rule in rules:
            if not rule.cidr:
                version = 4
            else:
                version = netutils.get_ip_version(rule.cidr)

            if version == 4:
                fw_rules = ipv4_rules
            else:
                fw_rules = ipv6_rules

            protocol = rule.protocol

            if protocol:
                protocol = rule.protocol.lower()

            if version == 6 and protocol == 'icmp':
                protocol = 'icmpv6'

            args = ['-j ACCEPT']
            if protocol:
                args += ['-p', protocol]

            if protocol in ['udp', 'tcp']:
                args += self._build_tcp_udp_rule(rule, version)
            elif protocol == 'icmp':
                args += self._build_icmp_rule(rule, version)
            if rule.cidr:
                args += ['-s', str(rule.cidr)]
                fw_rules += [' '.join(args)]
            else:
                if rule.grantee_group:
                    insts = objects.InstanceList.get_by_security_group(
                            ctxt, rule.grantee_group)
                    for inst in insts:
                        if inst.info_cache.deleted:
                            LOG.debug('ignoring deleted cache')
                            continue
                        nw_info = inst.get_network_info()

                        ips = [ip['address'] for ip in nw_info.fixed_ips()
                               if ip['version'] == version]

                        LOG.debug('ips: %r', ips, instance=inst)
                        for ip in ips:
                            subrule = args + ['-s %s' % ip]
                            fw_rules += [' '.join(subrule)]

        ipv4_rules += ['-j $sg-fallback']
        ipv6_rules += ['-j $sg-fallback']
        LOG.debug('Security Group Rules %s translated to ipv4: %r, ipv6: %r',
                  list(rules), ipv4_rules, ipv6_rules,
                  instance=instance)
        return ipv4_rules, ipv6_rules

    def instance_filter_exists(self, instance, network_info):
        pass

    def refresh_security_group_rules(self, security_group):
        self.do_refresh_security_group_rules(security_group)
        self.iptables.apply()

    def refresh_instance_security_rules(self, instance):
        self.do_refresh_instance_rules(instance)
        self.iptables.apply()

    @utils.synchronized('iptables', external=True)
    def _inner_do_refresh_rules(self, instance, network_info, ipv4_rules,
                                ipv6_rules):
        chain_name = self._instance_chain_name(instance)
        if not self.iptables.ipv4['filter'].has_chain(chain_name):
            LOG.info('instance chain %s disappeared during refresh, skipping',
                     chain_name, instance=instance)
            return
        self.remove_filters_for_instance(instance)
        self.add_filters_for_instance(instance, network_info, ipv4_rules,
                                      ipv6_rules)

    def do_refresh_security_group_rules(self, security_group):
        id_list = self.instance_info.keys()
        for instance_id in id_list:
            try:
                instance, network_info = self.instance_info[instance_id]
            except KeyError:
                # NOTE(danms): instance cache must have been modified,
                # ignore this deleted instance and move on
                continue
            ipv4_rules, ipv6_rules = self.instance_rules(instance,
                                                         network_info)
            self._inner_do_refresh_rules(instance, network_info, ipv4_rules,
                                         ipv6_rules)

    def do_refresh_instance_rules(self, instance):
        _instance, network_info = self.instance_info[instance.id]
        ipv4_rules, ipv6_rules = self.instance_rules(instance, network_info)
        self._inner_do_refresh_rules(instance, network_info, ipv4_rules,
                                     ipv6_rules)


class NoopFirewallDriver(object):
    """Firewall driver which just provides No-op methods."""
    def __init__(self, *args, **kwargs):
        pass

    def _noop(self, *args, **kwargs):
        pass

    def __getattr__(self, key):
        return self._noop

    def instance_filter_exists(self, instance, network_info):
        return True
