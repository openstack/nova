#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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
This script is used to configure iptables, ebtables, and arptables rules on
XenServer hosts.
"""

import os
import subprocess
import sys

# This is written to Python 2.4, since that is what is available on XenServer
import simplejson as json


from novalib import execute, execute_get_output


def main(dom_id, command, only_this_vif=None):
    xsls = execute_get_output('/usr/bin/xenstore-ls',
                              '/local/domain/%s/vm-data/networking' % dom_id)
    macs = [line.split("=")[0].strip() for line in xsls.splitlines()]

    for mac in macs:
        xsread = execute_get_output('/usr/bin/xenstore-read',
                                    '/local/domain/%s/vm-data/networking/%s' %
                                    (dom_id, mac))
        data = json.loads(xsread)
        for ip in data['ips']:
            if data["label"] == "public":
                vif = "vif%s.0" % dom_id
            else:
                vif = "vif%s.1" % dom_id

            if (only_this_vif is None) or (vif == only_this_vif):
                params = dict(IP=ip['ip'], VIF=vif, MAC=data['mac'])
                apply_ebtables_rules(command, params)
                apply_arptables_rules(command, params)
                apply_iptables_rules(command, params)


# A note about adding rules:
#   Whenever we add any rule to iptables, arptables or ebtables we first
#   delete the same rule to ensure the rule only exists once.


def apply_iptables_rules(command, params):
    iptables = lambda *rule: execute('/sbin/iptables', *rule)

    iptables('-D', 'FORWARD', '-m', 'physdev',
             '--physdev-in', params['VIF'],
             '-s', params['IP'],
             '-j', 'ACCEPT')
    if command == 'online':
        iptables('-A', 'FORWARD', '-m', 'physdev',
                 '--physdev-in', params['VIF'],
                 '-s', params['IP'],
                 '-j', 'ACCEPT')


def apply_arptables_rules(command, params):
    arptables = lambda *rule: execute('/sbin/arptables', *rule)

    arptables('-D', 'FORWARD', '--opcode', 'Request',
              '--in-interface', params['VIF'],
              '--source-ip', params['IP'],
              '--source-mac', params['MAC'],
              '-j', 'ACCEPT')
    arptables('-D', 'FORWARD', '--opcode', 'Reply',
              '--in-interface', params['VIF'],
              '--source-ip', params['IP'],
              '--source-mac', params['MAC'],
              '-j', 'ACCEPT')
    if command == 'online':
        arptables('-A', 'FORWARD', '--opcode', 'Request',
                  '--in-interface', params['VIF'],
                  '--source-mac', params['MAC'],
                  '-j', 'ACCEPT')
        arptables('-A', 'FORWARD', '--opcode', 'Reply',
                  '--in-interface', params['VIF'],
                  '--source-ip', params['IP'],
                  '--source-mac', params['MAC'],
                  '-j', 'ACCEPT')


def apply_ebtables_rules(command, params):
    ebtables = lambda *rule: execute("/sbin/ebtables", *rule)

    ebtables('-D', 'FORWARD', '-p', '0806', '-o', params['VIF'],
             '--arp-ip-dst', params['IP'],
             '-j', 'ACCEPT')
    ebtables('-D', 'FORWARD', '-p', '0800', '-o', params['VIF'],
             '--ip-dst', params['IP'],
             '-j', 'ACCEPT')
    if command == 'online':
        ebtables('-A', 'FORWARD', '-p', '0806',
                 '-o', params['VIF'],
                 '--arp-ip-dst', params['IP'],
                 '-j', 'ACCEPT')
        ebtables('-A', 'FORWARD', '-p', '0800',
                 '-o', params['VIF'],
                 '--ip-dst', params['IP'],
                 '-j', 'ACCEPT')

    ebtables('-D', 'FORWARD', '-s', '!', params['MAC'],
             '-i', params['VIF'], '-j', 'DROP')
    if command == 'online':
        ebtables('-I', 'FORWARD', '1', '-s', '!', params['MAC'],
                 '-i', params['VIF'], '-j', 'DROP')


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print "usage: %s dom_id online|offline [vif]" % \
               os.path.basename(sys.argv[0])
        sys.exit(1)
    else:
        dom_id, command = sys.argv[1:3]
        vif = len(sys.argv) == 4 and sys.argv[3] or None
        main(dom_id, command, vif)
