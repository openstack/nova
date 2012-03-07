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

import json


from nova import context
from nova import flags
from nova import log as logging
from nova.db import api as db
from nova.virt import netutils
from nova.virt import firewall


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS

# The default Firewall driver must be listed at position 0
drivers = ['nova.virt.firewall.IptablesFirewallDriver',
           'nova.virt.firewall.NoopFirewallDriver',
           'nova.virt.xenapi.firewall.Dom0IptablesFirewallDriver', ]


class Dom0IptablesFirewallDriver(firewall.IptablesFirewallDriver):
    """ Dom0IptablesFirewallDriver class

    This class provides an implementation for nova.virt.Firewall
    using iptables. This class is meant to be used with the xenapi
    backend and uses xenapi plugin to enforce iptables rules in dom0

    """
    def _plugin_execute(self, *cmd, **kwargs):
        # Prepare arguments for plugin call
        args = {}
        args.update(map(lambda x: (x, str(kwargs[x])), kwargs))
        args['cmd_args'] = json.dumps(cmd)
        task = self._session.async_call_plugin(
            'xenhost', 'iptables_config', args)
        ret = self._session.wait_for_task(task)
        json_ret = json.loads(ret)
        return (json_ret['out'], json_ret['err'])

    def __init__(self, xenapi_session=None, **kwargs):
        from nova.network import linux_net
        super(Dom0IptablesFirewallDriver, self).__init__(**kwargs)
        self._session = xenapi_session
        # Create IpTablesManager with executor through plugin
        self.iptables = linux_net.IptablesManager(self._plugin_execute)
        self.iptables.ipv4['filter'].add_chain('sg-fallback')
        self.iptables.ipv4['filter'].add_rule('sg-fallback', '-j DROP')
        self.iptables.ipv6['filter'].add_chain('sg-fallback')
        self.iptables.ipv6['filter'].add_rule('sg-fallback', '-j DROP')

    def _build_tcp_udp_rule(self, rule, version):
        if rule.from_port == rule.to_port:
            return ['--dport', '%s' % (rule.from_port,)]
        else:
            #  No multiport needed for XS!
            return ['--dport', '%s:%s' % (rule.from_port,
                                           rule.to_port)]

    @staticmethod
    def _provider_rules():
        """Generate a list of rules from provider for IP4 & IP6.
        Note: We could not use the common code from virt.firewall because
        XS doesn't accept the '-m multiport' option"""

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
                    args += ['--dport', '%s:%s' % (rule['from_port'],
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
