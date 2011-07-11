#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
This script is used to configure base openvswitch flows for XenServer hosts.
"""

import os
import sys


from novalib import execute, execute_get_output


def main(command, phys_dev_name, bridge_name):
    ovs_ofctl = lambda *rule: execute('/usr/bin/ovs-ofctl', *rule)

    # always clear all flows first
    ovs_ofctl('del-flows', bridge_name)

    if command in ('online', 'reset'):
        pnic_ofport = execute_get_output('/usr/bin/ovs-vsctl', 'get',
                                         'Interface', phys_dev_name, 'ofport')

        # these flows are lower priority than all VM-specific flows.

        # allow all traffic from the physical NIC, as it is trusted (i.e.,
        # from a filtered vif, or from the physical infrastructure)
        ovs_ofctl('add-flow', bridge_name,
                  "priority=2,in_port=%s,actions=normal" % pnic_ofport)

        # default drop
        ovs_ofctl('add-flow', bridge_name, 'priority=1,actions=drop')


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ('online', 'offline', 'reset'):
        print sys.argv
        script_name = os.path.basename(sys.argv[0])
        print "This script configures base ovs flows."
        print "usage: %s [online|offline|reset] phys-dev-name bridge-name" \
                % script_name
        print "   ex: %s online eth0 xenbr0" % script_name
        sys.exit(1)
    else:
        command, phys_dev_name, bridge_name = sys.argv[1:4]
        main(command, phys_dev_name, bridge_name)
