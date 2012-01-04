# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import utils
from nova.virt import netutils

LOG = logging.getLogger("nova.virt.firewall")
FLAGS = flags.FLAGS
flags.DEFINE_bool('allow_same_net_traffic',
                  True,
                  'Whether to allow network traffic from same network')


class FirewallDriver(object):
    """ Firewall Driver base class.

        Defines methos that any driver providing security groups
        and provider fireall functionality should implement.
    """
    def prepare_instance_filter(self, instance, network_info):
        """Prepare filters for the instance.
        At this point, the instance isn't running yet."""
        raise NotImplementedError()

    def unfilter_instance(self, instance, network_info):
        """Stop filtering instance"""
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
        the security group."""
        raise NotImplementedError()

    def refresh_security_group_members(self, security_group_id):
        """Refresh security group members from data store

        Gets called when an instance gets added to or removed from
        the security group."""
        raise NotImplementedError()

    def refresh_provider_fw_rules(self):
        """Refresh common rules for all hosts/instances from data store.

        Gets called when a rule has been added to or removed from
        the list of rules (via admin api).

        """
        raise NotImplementedError()

    def setup_basic_filtering(self, instance, network_info):
        """Create rules to block spoofing and allow dhcp.

        This gets called when spawning an instance, before
        :method:`prepare_instance_filter`.

        """
        raise NotImplementedError()

    def instance_filter_exists(self, instance, network_info):
        """Check nova-instance-instance-xxx exists"""
        raise NotImplementedError()


class IptablesFirewallDriver(FirewallDriver):
    """ Driver which enforces security groups through iptables rules. """

    def __init__(self, **kwargs):
        from nova.network import linux_net
        self.iptables = linux_net.iptables_manager
        self.instances = {}
        self.network_infos = {}
        self.basicly_filtered = False

        self.iptables.ipv4['filter'].add_chain('sg-fallback')
        self.iptables.ipv4['filter'].add_rule('sg-fallback', '-j DROP')
        self.iptables.ipv6['filter'].add_chain('sg-fallback')
        self.iptables.ipv6['filter'].add_rule('sg-fallback', '-j DROP')

    def setup_basic_filtering(self, instance, network_info):
        pass

    def apply_instance_filter(self, instance, network_info):
        """No-op. Everything is done in prepare_instance_filter"""
        pass

    def unfilter_instance(self, instance, network_info):
        if self.instances.pop(instance['id'], None):
            # NOTE(vish): use the passed info instead of the stored info
            self.network_infos.pop(instance['id'])
            self.remove_filters_for_instance(instance)
            self.iptables.apply()
        else:
            LOG.info(_('Attempted to unfilter instance %s which is not '
                     'filtered'), instance['id'])

    def prepare_instance_filter(self, instance, network_info):
        self.instances[instance['id']] = instance
        self.network_infos[instance['id']] = network_info
        self.add_filters_for_instance(instance)
        self.iptables.apply()

    def _create_filter(self, ips, chain_name):
        return ['-d %s -j $%s' % (ip, chain_name) for ip in ips]

    def _filters_for_instance(self, chain_name, network_info):
        ips_v4 = [ip['ip'] for (_n, mapping) in network_info
                 for ip in mapping['ips']]
        ipv4_rules = self._create_filter(ips_v4, chain_name)

        ipv6_rules = []
        if FLAGS.use_ipv6:
            ips_v6 = [ip['ip'] for (_n, mapping) in network_info
                     for ip in mapping['ip6s']]
            ipv6_rules = self._create_filter(ips_v6, chain_name)

        return ipv4_rules, ipv6_rules

    def _add_filters(self, chain_name, ipv4_rules, ipv6_rules):
        for rule in ipv4_rules:
            self.iptables.ipv4['filter'].add_rule(chain_name, rule)

        if FLAGS.use_ipv6:
            for rule in ipv6_rules:
                self.iptables.ipv6['filter'].add_rule(chain_name, rule)

    def add_filters_for_instance(self, instance):
        network_info = self.network_infos[instance['id']]
        chain_name = self._instance_chain_name(instance)
        if FLAGS.use_ipv6:
            self.iptables.ipv6['filter'].add_chain(chain_name)
        self.iptables.ipv4['filter'].add_chain(chain_name)
        ipv4_rules, ipv6_rules = self._filters_for_instance(chain_name,
                                                            network_info)
        self._add_filters('local', ipv4_rules, ipv6_rules)
        ipv4_rules, ipv6_rules = self.instance_rules(instance, network_info)
        self._add_filters(chain_name, ipv4_rules, ipv6_rules)

    def remove_filters_for_instance(self, instance):
        chain_name = self._instance_chain_name(instance)

        self.iptables.ipv4['filter'].remove_chain(chain_name)
        if FLAGS.use_ipv6:
            self.iptables.ipv6['filter'].remove_chain(chain_name)

    @staticmethod
    def _security_group_chain_name(security_group_id):
        return 'nova-sg-%s' % (security_group_id,)

    def _instance_chain_name(self, instance):
        return 'inst-%s' % (instance['id'],)

    def _do_basic_rules(self, ipv4_rules, ipv6_rules, network_info):
        # Always drop invalid packets
        ipv4_rules += ['-m state --state ' 'INVALID -j DROP']
        ipv6_rules += ['-m state --state ' 'INVALID -j DROP']

        # Allow established connections
        ipv4_rules += ['-m state --state ESTABLISHED,RELATED -j ACCEPT']
        ipv6_rules += ['-m state --state ESTABLISHED,RELATED -j ACCEPT']

    def _do_dhcp_rules(self, ipv4_rules, network_info):
        dhcp_servers = [info['dhcp_server'] for (_n, info) in network_info]

        for dhcp_server in dhcp_servers:
            ipv4_rules.append('-s %s -p udp --sport 67 --dport 68 '
                              '-j ACCEPT' % (dhcp_server,))

    def _do_project_network_rules(self, ipv4_rules, ipv6_rules, network_info):
        cidrs = [network['cidr'] for (network, _i) in network_info]
        for cidr in cidrs:
            ipv4_rules.append('-s %s -j ACCEPT' % (cidr,))
        if FLAGS.use_ipv6:
            cidrv6s = [network['cidr_v6'] for (network, _i) in
                       network_info]

            for cidrv6 in cidrv6s:
                ipv6_rules.append('-s %s -j ACCEPT' % (cidrv6,))

    def _do_ra_rules(self, ipv6_rules, network_info):
        gateways_v6 = [mapping['gateway_v6'] for (_n, mapping) in
                       network_info]
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

        ipv4_rules = []
        ipv6_rules = []

        # Initialize with basic rules
        self._do_basic_rules(ipv4_rules, ipv6_rules, network_info)
        # Set up rules to allow traffic to/from DHCP server
        self._do_dhcp_rules(ipv4_rules, network_info)

        #Allow project network traffic
        if FLAGS.allow_same_net_traffic:
            self._do_project_network_rules(ipv4_rules, ipv6_rules,
                                           network_info)
        # We wrap these in FLAGS.use_ipv6 because they might cause
        # a DB lookup. The other ones are just list operations, so
        # they're not worth the clutter.
        if FLAGS.use_ipv6:
            # Allow RA responses
            self._do_ra_rules(ipv6_rules, network_info)

        security_groups = db.security_group_get_by_instance(ctxt,
                                                            instance['id'])

        # then, security group chains and rules
        for security_group in security_groups:
            rules = db.security_group_rule_get_by_security_group(ctxt,
                                                          security_group['id'])

            for rule in rules:
                LOG.debug(_('Adding security group rule: %r'), rule)

                if not rule.cidr:
                    version = 4
                else:
                    version = netutils.get_ip_version(rule.cidr)

                if version == 4:
                    fw_rules = ipv4_rules
                else:
                    fw_rules = ipv6_rules

                protocol = rule.protocol
                if version == 6 and rule.protocol == 'icmp':
                    protocol = 'icmpv6'

                args = ['-j ACCEPT']
                if protocol:
                    args += ['-p', protocol]

                if protocol in ['udp', 'tcp']:
                    args += self._build_tcp_udp_rule(rule, version)
                elif protocol == 'icmp':
                    args += self._build_icmp_rule(rule, version)
                if rule.cidr:
                    LOG.info('Using cidr %r', rule.cidr)
                    args += ['-s', rule.cidr]
                    fw_rules += [' '.join(args)]
                else:
                    if rule['grantee_group']:
                        # FIXME(jkoelker) This needs to be ported up into
                        #                 the compute manager which already
                        #                 has access to a nw_api handle,
                        #                 and should be the only one making
                        #                 making rpc calls.
                        import nova.network
                        nw_api = nova.network.API()
                        for instance in rule['grantee_group']['instances']:
                            LOG.info('instance: %r', instance)
                            ips = []
                            nw_info = nw_api.get_instance_nw_info(ctxt,
                                                                  instance)
                            for net in nw_info:
                                ips.extend(net[1]['ips'])

                            LOG.info('ips: %r', ips)
                            for ip in ips:
                                subrule = args + ['-s %s' % ip['ip']]
                                fw_rules += [' '.join(subrule)]

                LOG.info('Using fw_rules: %r', fw_rules)
        ipv4_rules += ['-j $sg-fallback']
        ipv6_rules += ['-j $sg-fallback']

        return ipv4_rules, ipv6_rules

    def instance_filter_exists(self, instance, network_info):
        pass

    def refresh_security_group_members(self, security_group):
        self.do_refresh_security_group_rules(security_group)
        self.iptables.apply()

    def refresh_security_group_rules(self, security_group):
        self.do_refresh_security_group_rules(security_group)
        self.iptables.apply()

    @utils.synchronized('iptables', external=True)
    def do_refresh_security_group_rules(self, security_group):
        for instance in self.instances.values():
            self.remove_filters_for_instance(instance)
            self.add_filters_for_instance(instance)
