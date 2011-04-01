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
import subprocess
import sys


from novalib import execute, execute_get_output


def main(phys_dev_name, bridge_name):
    pnic_ofport = execute_get_output('/usr/bin/ovs-vsctl', 'get', 'Interface',
                                     phys_dev_name, 'ofport')
    ovs_ofctl = lambda *rule: execute('/usr/bin/ovs-ofctl', *rule)

    # clear all flows
    ovs_ofctl('del-flows', bridge_name)

    # these flows are lower priority than all VM-specific flows.

    # allow all traffic from the physical NIC, as it is trusted (i.e., from a
    # filtered vif, or from the physical infrastructure
    ovs_ofctl('add-flow', bridge_name,
              "priority=2,in_port=%s,action=normal" % pnic_ofport)

    # default drop
    ovs_ofctl('add-flow', bridge_name, 'priority=1,action=drop')


if __name__ == "__main__":
    if len(sys.argv) != 3:
        script_name = os.path.basename(sys.argv[0])
        print "This script configures base ovs flows."
        print "usage: %s phys-dev-name bridge-name" % script_name
        print "   ex: %s eth0 xenbr0" % script_name
        sys.exit(1)
    else:
        phys_dev_name, bridge_name = sys.argv[1:3]
        main(phys_dev_name, bridge_name)
