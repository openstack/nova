# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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


from eventlet import tpool

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import utils
from nova.virt.libvirt import netutils


LOG = logging.getLogger("nova.virt.libvirt.firewall")
FLAGS = flags.FLAGS


try:
    import libvirt
except ImportError:
    LOG.warn(_("Libvirt module could not be loaded. NWFilterFirewall will "
               "not work correctly."))


class FirewallDriver(object):
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


class NWFilterFirewall(FirewallDriver):
    """
    This class implements a network filtering mechanism versatile
    enough for EC2 style Security Group filtering by leveraging
    libvirt's nwfilter.

    First, all instances get a filter ("nova-base-filter") applied.
    This filter provides some basic security such as protection against
    MAC spoofing, IP spoofing, and ARP spoofing.

    This filter drops all incoming ipv4 and ipv6 connections.
    Outgoing connections are never blocked.

    Second, every security group maps to a nwfilter filter(*).
    NWFilters can be updated at runtime and changes are applied
    immediately, so changes to security groups can be applied at
    runtime (as mandated by the spec).

    Security group rules are named "nova-secgroup-<id>" where <id>
    is the internal id of the security group. They're applied only on
    hosts that have instances in the security group in question.

    Updates to security groups are done by updating the data model
    (in response to API calls) followed by a request sent to all
    the nodes with instances in the security group to refresh the
    security group.

    Each instance has its own NWFilter, which references the above
    mentioned security group NWFilters. This was done because
    interfaces can only reference one filter while filters can
    reference multiple other filters. This has the added benefit of
    actually being able to add and remove security groups from an
    instance at run time. This functionality is not exposed anywhere,
    though.

    Outstanding questions:

    The name is unique, so would there be any good reason to sync
    the uuid across the nodes (by assigning it from the datamodel)?


    (*) This sentence brought to you by the redundancy department of
        redundancy.

    """

    def __init__(self, get_connection, **kwargs):
        self._libvirt_get_connection = get_connection
        self.static_filters_configured = False
        self.handle_security_groups = False

    def apply_instance_filter(self, instance, network_info):
        """No-op. Everything is done in prepare_instance_filter"""
        pass

    def _get_connection(self):
        return self._libvirt_get_connection()
    _conn = property(_get_connection)

    def nova_dhcp_filter(self):
        """The standard allow-dhcp-server filter is an <ip> one, so it uses
           ebtables to allow traffic through. Without a corresponding rule in
           iptables, it'll get blocked anyway."""

        return '''<filter name='nova-allow-dhcp-server' chain='ipv4'>
                    <uuid>891e4787-e5c0-d59b-cbd6-41bc3c6b36fc</uuid>
                    <rule action='accept' direction='out'
                          priority='100'>
                      <udp srcipaddr='0.0.0.0'
                           dstipaddr='255.255.255.255'
                           srcportstart='68'
                           dstportstart='67'/>
                    </rule>
                    <rule action='accept' direction='in'
                          priority='100'>
                      <udp srcipaddr='$DHCPSERVER'
                           srcportstart='67'
                           dstportstart='68'/>
                    </rule>
                  </filter>'''

    def nova_ra_filter(self):
        return '''<filter name='nova-allow-ra-server' chain='root'>
                            <uuid>d707fa71-4fb5-4b27-9ab7-ba5ca19c8804</uuid>
                              <rule action='accept' direction='inout'
                                    priority='100'>
                                <icmpv6 srcipaddr='$RASERVER'/>
                              </rule>
                            </filter>'''

    def setup_basic_filtering(self, instance, network_info):
        """Set up basic filtering (MAC, IP, and ARP spoofing protection)"""
        logging.info('called setup_basic_filtering in nwfilter')

        if self.handle_security_groups:
            # No point in setting up a filter set that we'll be overriding
            # anyway.
            return

        logging.info('ensuring static filters')
        self._ensure_static_filters()

        if instance['image_ref'] == str(FLAGS.vpn_image_id):
            base_filter = 'nova-vpn'
        else:
            base_filter = 'nova-base'

        for (network, mapping) in network_info:
            nic_id = mapping['mac'].replace(':', '')
            instance_filter_name = self._instance_filter_name(instance, nic_id)
            self._define_filter(self._filter_container(instance_filter_name,
                                                       [base_filter]))

    def _ensure_static_filters(self):
        """Static filters are filters that have no need to be IP aware.

        There is no configuration or tuneability of these filters, so they
        can be set up once and forgotten about.

        """

        if self.static_filters_configured:
            return

        self._define_filter(self._filter_container('nova-base',
                                                   ['no-mac-spoofing',
                                                    'no-ip-spoofing',
                                                    'no-arp-spoofing',
                                                    'allow-dhcp-server']))
        self._define_filter(self._filter_container('nova-vpn',
                                                   ['allow-dhcp-server']))
        self._define_filter(self.nova_base_ipv4_filter)
        self._define_filter(self.nova_base_ipv6_filter)
        self._define_filter(self.nova_dhcp_filter)
        self._define_filter(self.nova_ra_filter)
        if FLAGS.allow_same_net_traffic:
            self._define_filter(self.nova_project_filter)
            if FLAGS.use_ipv6:
                self._define_filter(self.nova_project_filter_v6)

        self.static_filters_configured = True

    def _filter_container(self, name, filters):
        xml = '''<filter name='%s' chain='root'>%s</filter>''' % (
                 name,
                 ''.join(["<filterref filter='%s'/>" % (f,) for f in filters]))
        return xml

    def nova_base_ipv4_filter(self):
        retval = "<filter name='nova-base-ipv4' chain='ipv4'>"
        for protocol in ['tcp', 'udp', 'icmp']:
            for direction, action, priority in [('out', 'accept', 399),
                                                ('in', 'drop', 400)]:
                retval += """<rule action='%s' direction='%s' priority='%d'>
                               <%s />
                             </rule>""" % (action, direction,
                                              priority, protocol)
        retval += '</filter>'
        return retval

    def nova_base_ipv6_filter(self):
        retval = "<filter name='nova-base-ipv6' chain='ipv6'>"
        for protocol in ['tcp-ipv6', 'udp-ipv6', 'icmpv6']:
            for direction, action, priority in [('out', 'accept', 399),
                                                ('in', 'drop', 400)]:
                retval += """<rule action='%s' direction='%s' priority='%d'>
                               <%s />
                             </rule>""" % (action, direction,
                                              priority, protocol)
        retval += '</filter>'
        return retval

    def nova_project_filter(self):
        retval = "<filter name='nova-project' chain='ipv4'>"
        for protocol in ['tcp', 'udp', 'icmp']:
            retval += """<rule action='accept' direction='in' priority='200'>
                           <%s srcipaddr='$PROJNET' srcipmask='$PROJMASK' />
                         </rule>""" % protocol
        retval += '</filter>'
        return retval

    def nova_project_filter_v6(self):
        retval = "<filter name='nova-project-v6' chain='ipv6'>"
        for protocol in ['tcp-ipv6', 'udp-ipv6', 'icmpv6']:
            retval += """<rule action='accept' direction='inout'
                                                   priority='200'>
                           <%s srcipaddr='$PROJNETV6'
                               srcipmask='$PROJMASKV6' />
                         </rule>""" % (protocol)
        retval += '</filter>'
        return retval

    def _define_filter(self, xml):
        if callable(xml):
            xml = xml()
        # execute in a native thread and block current greenthread until done
        tpool.execute(self._conn.nwfilterDefineXML, xml)

    def unfilter_instance(self, instance, network_info):
        """Clear out the nwfilter rules."""
        instance_name = instance.name
        for (network, mapping) in network_info:
            nic_id = mapping['mac'].replace(':', '')
            instance_filter_name = self._instance_filter_name(instance, nic_id)

            try:
                self._conn.nwfilterLookupByName(instance_filter_name).\
                                                    undefine()
            except libvirt.libvirtError:
                LOG.debug(_('The nwfilter(%(instance_filter_name)s) '
                            'for %(instance_name)s is not found.') % locals())

        instance_secgroup_filter_name =\
            '%s-secgroup' % (self._instance_filter_name(instance))

        try:
            self._conn.nwfilterLookupByName(instance_secgroup_filter_name)\
                                            .undefine()
        except libvirt.libvirtError:
            LOG.debug(_('The nwfilter(%(instance_secgroup_filter_name)s) '
                        'for %(instance_name)s is not found.') % locals())

    def prepare_instance_filter(self, instance, network_info):
        """Creates an NWFilter for the given instance.

        In the process, it makes sure the filters for the provider blocks,
        security groups, and base filter are all in place.

        """
        self.refresh_provider_fw_rules()

        ctxt = context.get_admin_context()

        instance_secgroup_filter_name = \
            '%s-secgroup' % (self._instance_filter_name(instance))

        instance_secgroup_filter_children = ['nova-base-ipv4',
                                             'nova-base-ipv6',
                                             'nova-allow-dhcp-server']

        if FLAGS.use_ipv6:
            networks = [network for (network, _m) in network_info if
                        network['gateway_v6']]

            if networks:
                instance_secgroup_filter_children.\
                    append('nova-allow-ra-server')

        for security_group in \
                db.security_group_get_by_instance(ctxt, instance['id']):

            self.refresh_security_group_rules(security_group['id'])

            instance_secgroup_filter_children.append('nova-secgroup-%s' %
                                                    security_group['id'])

            self._define_filter(
                    self._filter_container(instance_secgroup_filter_name,
                                           instance_secgroup_filter_children))

        network_filters = self.\
            _create_network_filters(instance, network_info,
                                    instance_secgroup_filter_name)

        for (name, children) in network_filters:
            self._define_filters(name, children)

    def _create_network_filters(self, instance, network_info,
                               instance_secgroup_filter_name):
        if instance['image_ref'] == str(FLAGS.vpn_image_id):
            base_filter = 'nova-vpn'
        else:
            base_filter = 'nova-base'

        result = []
        for (_n, mapping) in network_info:
            nic_id = mapping['mac'].replace(':', '')
            instance_filter_name = self._instance_filter_name(instance, nic_id)
            instance_filter_children = [base_filter, 'nova-provider-rules',
                                        instance_secgroup_filter_name]

            if FLAGS.allow_same_net_traffic:
                instance_filter_children.append('nova-project')
                if FLAGS.use_ipv6:
                    instance_filter_children.append('nova-project-v6')

            result.append((instance_filter_name, instance_filter_children))

        return result

    def _define_filters(self, filter_name, filter_children):
        self._define_filter(self._filter_container(filter_name,
                                                   filter_children))

    def refresh_security_group_rules(self, security_group_id):
        return self._define_filter(
                   self.security_group_to_nwfilter_xml(security_group_id))

    def refresh_provider_fw_rules(self):
        """Update rules for all instances.

        This is part of the FirewallDriver API and is called when the
        provider firewall rules change in the database.  In the
        `prepare_instance_filter` we add a reference to the
        'nova-provider-rules' filter for each instance's firewall, and
        by changing that filter we update them all.

        """
        xml = self.provider_fw_to_nwfilter_xml()
        return self._define_filter(xml)

    def security_group_to_nwfilter_xml(self, security_group_id):
        security_group = db.security_group_get(context.get_admin_context(),
                                               security_group_id)
        rule_xml = ""
        v6protocol = {'tcp': 'tcp-ipv6', 'udp': 'udp-ipv6', 'icmp': 'icmpv6'}
        for rule in security_group.rules:
            rule_xml += "<rule action='accept' direction='in' priority='300'>"
            if rule.cidr:
                version = netutils.get_ip_version(rule.cidr)
                if(FLAGS.use_ipv6 and version == 6):
                    net, prefixlen = netutils.get_net_and_prefixlen(rule.cidr)
                    rule_xml += "<%s srcipaddr='%s' srcipmask='%s' " % \
                                (v6protocol[rule.protocol], net, prefixlen)
                else:
                    net, mask = netutils.get_net_and_mask(rule.cidr)
                    rule_xml += "<%s srcipaddr='%s' srcipmask='%s' " % \
                                (rule.protocol, net, mask)
                if rule.protocol in ['tcp', 'udp']:
                    rule_xml += "dstportstart='%s' dstportend='%s' " % \
                                (rule.from_port, rule.to_port)
                elif rule.protocol == 'icmp':
                    LOG.info('rule.protocol: %r, rule.from_port: %r, '
                             'rule.to_port: %r', rule.protocol,
                             rule.from_port, rule.to_port)
                    if rule.from_port != -1:
                        rule_xml += "type='%s' " % rule.from_port
                    if rule.to_port != -1:
                        rule_xml += "code='%s' " % rule.to_port

                rule_xml += '/>\n'
            rule_xml += "</rule>\n"
        xml = "<filter name='nova-secgroup-%s' " % security_group_id
        if(FLAGS.use_ipv6):
            xml += "chain='root'>%s</filter>" % rule_xml
        else:
            xml += "chain='ipv4'>%s</filter>" % rule_xml
        return xml

    def provider_fw_to_nwfilter_xml(self):
        """Compose a filter of drop rules from specified cidrs."""
        rule_xml = ""
        v6protocol = {'tcp': 'tcp-ipv6', 'udp': 'udp-ipv6', 'icmp': 'icmpv6'}
        rules = db.provider_fw_rule_get_all(context.get_admin_context())
        for rule in rules:
            rule_xml += "<rule action='block' direction='in' priority='150'>"
            version = netutils.get_ip_version(rule.cidr)
            if(FLAGS.use_ipv6 and version == 6):
                net, prefixlen = netutils.get_net_and_prefixlen(rule.cidr)
                rule_xml += "<%s srcipaddr='%s' srcipmask='%s' " % \
                            (v6protocol[rule.protocol], net, prefixlen)
            else:
                net, mask = netutils.get_net_and_mask(rule.cidr)
                rule_xml += "<%s srcipaddr='%s' srcipmask='%s' " % \
                            (rule.protocol, net, mask)
            if rule.protocol in ['tcp', 'udp']:
                rule_xml += "dstportstart='%s' dstportend='%s' " % \
                            (rule.from_port, rule.to_port)
            elif rule.protocol == 'icmp':
                LOG.info('rule.protocol: %r, rule.from_port: %r, '
                         'rule.to_port: %r', rule.protocol,
                         rule.from_port, rule.to_port)
                if rule.from_port != -1:
                    rule_xml += "type='%s' " % rule.from_port
                if rule.to_port != -1:
                    rule_xml += "code='%s' " % rule.to_port

                rule_xml += '/>\n'
            rule_xml += "</rule>\n"
        xml = "<filter name='nova-provider-rules' "
        if(FLAGS.use_ipv6):
            xml += "chain='root'>%s</filter>" % rule_xml
        else:
            xml += "chain='ipv4'>%s</filter>" % rule_xml
        return xml

    def _instance_filter_name(self, instance, nic_id=None):
        if not nic_id:
            return 'nova-instance-%s' % (instance['name'])
        return 'nova-instance-%s-%s' % (instance['name'], nic_id)

    def instance_filter_exists(self, instance, network_info):
        """Check nova-instance-instance-xxx exists"""
        for (network, mapping) in network_info:
            nic_id = mapping['mac'].replace(':', '')
            instance_filter_name = self._instance_filter_name(instance, nic_id)
            try:
                self._conn.nwfilterLookupByName(instance_filter_name)
            except libvirt.libvirtError:
                name = instance.name
                LOG.debug(_('The nwfilter(%(instance_filter_name)s) for'
                            '%(name)s is not found.') % locals())
                return False
        return True


class IptablesFirewallDriver(FirewallDriver):
    def __init__(self, execute=None, **kwargs):
        from nova.network import linux_net
        self.iptables = linux_net.iptables_manager
        self.instances = {}
        self.network_infos = {}
        self.nwfilter = NWFilterFirewall(kwargs['get_connection'])
        self.basicly_filtered = False

        self.iptables.ipv4['filter'].add_chain('sg-fallback')
        self.iptables.ipv4['filter'].add_rule('sg-fallback', '-j DROP')
        self.iptables.ipv6['filter'].add_chain('sg-fallback')
        self.iptables.ipv6['filter'].add_rule('sg-fallback', '-j DROP')

    def setup_basic_filtering(self, instance, network_info):
        """Set up provider rules and basic NWFilter."""
        self.nwfilter.setup_basic_filtering(instance, network_info)
        if not self.basicly_filtered:
            LOG.debug(_('iptables firewall: Setup Basic Filtering'))
            self.refresh_provider_fw_rules()
            self.basicly_filtered = True

    def apply_instance_filter(self, instance, network_info):
        """No-op. Everything is done in prepare_instance_filter"""
        pass

    def unfilter_instance(self, instance, network_info):
        if self.instances.pop(instance['id'], None):
            # NOTE(vish): use the passed info instead of the stored info
            self.network_infos.pop(instance['id'])
            self.remove_filters_for_instance(instance)
            self.iptables.apply()
            self.nwfilter.unfilter_instance(instance, network_info)
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

    def instance_rules(self, instance, network_info):
        ctxt = context.get_admin_context()

        ipv4_rules = []
        ipv6_rules = []

        # Always drop invalid packets
        ipv4_rules += ['-m state --state ' 'INVALID -j DROP']
        ipv6_rules += ['-m state --state ' 'INVALID -j DROP']

        # Allow established connections
        ipv4_rules += ['-m state --state ESTABLISHED,RELATED -j ACCEPT']
        ipv6_rules += ['-m state --state ESTABLISHED,RELATED -j ACCEPT']

        # Pass through provider-wide drops
        ipv4_rules += ['-j $provider']
        ipv6_rules += ['-j $provider']

        dhcp_servers = [info['dhcp_server'] for (_n, info) in network_info]

        for dhcp_server in dhcp_servers:
            ipv4_rules.append('-s %s -p udp --sport 67 --dport 68 '
                              '-j ACCEPT' % (dhcp_server,))

        #Allow project network traffic
        if FLAGS.allow_same_net_traffic:
            cidrs = [network['cidr'] for (network, _m) in network_info]
            for cidr in cidrs:
                ipv4_rules.append('-s %s -j ACCEPT' % (cidr,))

        # We wrap these in FLAGS.use_ipv6 because they might cause
        # a DB lookup. The other ones are just list operations, so
        # they're not worth the clutter.
        if FLAGS.use_ipv6:
            # Allow RA responses
            gateways_v6 = [mapping['gateway6'] for (_n, mapping) in
                           network_info]
            for gateway_v6 in gateways_v6:
                ipv6_rules.append(
                        '-s %s/128 -p icmpv6 -j ACCEPT' % (gateway_v6,))

            #Allow project network traffic
            if FLAGS.allow_same_net_traffic:
                cidrv6s = [network['cidr_v6'] for (network, _m) in
                           network_info]

                for cidrv6 in cidrv6s:
                    ipv6_rules.append('-s %s -j ACCEPT' % (cidrv6,))

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
                    if rule.from_port == rule.to_port:
                        args += ['--dport', '%s' % (rule.from_port,)]
                    else:
                        args += ['-m', 'multiport',
                                 '--dports', '%s:%s' % (rule.from_port,
                                                        rule.to_port)]
                elif protocol == 'icmp':
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
                            args += ['-m', 'icmp', '--icmp-type',
                                     icmp_type_arg]
                        elif version == 6:
                            args += ['-m', 'icmp6', '--icmpv6-type',
                                     icmp_type_arg]

                if rule.cidr:
                    LOG.info('Using cidr %r', rule.cidr)
                    args += ['-s', rule.cidr]
                    fw_rules += [' '.join(args)]
                else:
                    if rule['grantee_group']:
                        for instance in rule['grantee_group']['instances']:
                            LOG.info('instance: %r', instance)
                            ips = db.instance_get_fixed_addresses(ctxt,
                                                                instance['id'])
                            LOG.info('ips: %r', ips)
                            for ip in ips:
                                subrule = args + ['-s %s' % ip]
                                fw_rules += [' '.join(subrule)]

                LOG.info('Using fw_rules: %r', fw_rules)
        ipv4_rules += ['-j $sg-fallback']
        ipv6_rules += ['-j $sg-fallback']

        return ipv4_rules, ipv6_rules

    def instance_filter_exists(self, instance, network_info):
        """Check nova-instance-instance-xxx exists"""
        return self.nwfilter.instance_filter_exists(instance, network_info)

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

    def refresh_provider_fw_rules(self):
        """See class:FirewallDriver: docs."""
        self._do_refresh_provider_fw_rules()
        self.iptables.apply()

    @utils.synchronized('iptables', external=True)
    def _do_refresh_provider_fw_rules(self):
        """Internal, synchronized version of refresh_provider_fw_rules."""
        self._purge_provider_fw_rules()
        self._build_provider_fw_rules()

    def _purge_provider_fw_rules(self):
        """Remove all rules from the provider chains."""
        self.iptables.ipv4['filter'].empty_chain('provider')
        if FLAGS.use_ipv6:
            self.iptables.ipv6['filter'].empty_chain('provider')

    def _build_provider_fw_rules(self):
        """Create all rules for the provider IP DROPs."""
        self.iptables.ipv4['filter'].add_chain('provider')
        if FLAGS.use_ipv6:
            self.iptables.ipv6['filter'].add_chain('provider')
        ipv4_rules, ipv6_rules = self._provider_rules()
        for rule in ipv4_rules:
            self.iptables.ipv4['filter'].add_rule('provider', rule)

        if FLAGS.use_ipv6:
            for rule in ipv6_rules:
                self.iptables.ipv6['filter'].add_rule('provider', rule)

    def _provider_rules(self):
        """Generate a list of rules from provider for IP4 & IP6."""
        ctxt = context.get_admin_context()
        ipv4_rules = []
        ipv6_rules = []
        rules = db.provider_fw_rule_get_all(ctxt)
        for rule in rules:
            LOG.debug(_('Adding provider rule: %s'), rule['cidr'])
            version = netutils.get_ip_version(rule['cidr'])
            if version == 4:
                fw_rules = ipv4_rules
            else:
                fw_rules = ipv6_rules

            protocol = rule['protocol']
            if version == 6 and protocol == 'icmp':
                protocol = 'icmpv6'

            args = ['-p', protocol, '-s', rule['cidr']]

            if protocol in ['udp', 'tcp']:
                if rule['from_port'] == rule['to_port']:
                    args += ['--dport', '%s' % (rule['from_port'],)]
                else:
                    args += ['-m', 'multiport',
                             '--dports', '%s:%s' % (rule['from_port'],
                                                    rule['to_port'])]
            elif protocol == 'icmp':
                icmp_type = rule['from_port']
                icmp_code = rule['to_port']

                if icmp_type == -1:
                    icmp_type_arg = None
                else:
                    icmp_type_arg = '%s' % icmp_type
                    if not icmp_code == -1:
                        icmp_type_arg += '/%s' % icmp_code

                if icmp_type_arg:
                    if version == 4:
                        args += ['-m', 'icmp', '--icmp-type',
                                 icmp_type_arg]
                    elif version == 6:
                        args += ['-m', 'icmp6', '--icmpv6-type',
                                 icmp_type_arg]
            args += ['-j DROP']
            fw_rules += [' '.join(args)]
        return ipv4_rules, ipv6_rules

    def _security_group_chain_name(self, security_group_id):
        return 'nova-sg-%s' % (security_group_id,)

    def _instance_chain_name(self, instance):
        return 'inst-%s' % (instance['id'],)
