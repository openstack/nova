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

from oslo_serialization import jsonutils

from nova.virt import firewall


class Dom0IptablesFirewallDriver(firewall.IptablesFirewallDriver):
    """Dom0IptablesFirewallDriver class

    This class provides an implementation for nova.virt.Firewall
    using iptables. This class is meant to be used with the xenapi
    backend and uses xenapi plugin to enforce iptables rules in dom0.
    """
    def _plugin_execute(self, *cmd, **kwargs):
        # Prepare arguments for plugin call
        args = {}
        args.update(map(lambda x: (x, str(kwargs[x])), kwargs))
        args['cmd_args'] = jsonutils.dumps(cmd)
        ret = self._session.call_plugin('xenhost', 'iptables_config', args)
        json_ret = jsonutils.loads(ret)
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
