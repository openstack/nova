#!/usr/bin/env python
# Copyright 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

import novalib  # noqa


def main(command, phys_dev_name):
    ovs_ofctl = lambda *rule: novalib.execute('/usr/bin/ovs-ofctl', *rule)

    bridge_name = novalib.execute_get_output('/usr/bin/ovs-vsctl',
                                             'iface-to-br', phys_dev_name)

    # always clear all flows first
    ovs_ofctl('del-flows', bridge_name)

    if command in ('online', 'reset'):
        pnic_ofport = novalib.execute_get_output('/usr/bin/ovs-vsctl', 'get',
                                         'Interface', phys_dev_name, 'ofport')

        # these flows are lower priority than all VM-specific flows.

        # allow all traffic from the physical NIC, as it is trusted (i.e.,
        # from a filtered vif, or from the physical infrastructure)
        ovs_ofctl('add-flow', bridge_name,
                  "priority=2,in_port=%s,actions=normal" % pnic_ofport)

        # Allow traffic from dom0 if there is a management interface
        # present (its IP address is on the bridge itself)
        bridge_addr = novalib.execute_get_output('/sbin/ip', '-o', '-f',
                                                 'inet', 'addr', 'show',
                                                 bridge_name)
        if bridge_addr != '':
            ovs_ofctl('add-flow', bridge_name,
                      "priority=2,in_port=LOCAL,actions=normal")

        # default drop
        ovs_ofctl('add-flow', bridge_name, 'priority=1,actions=drop')


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ('online', 'offline', 'reset'):
        print(sys.argv)
        script_name = os.path.basename(sys.argv[0])
        print("This script configures base ovs flows.")
        print("usage: %s [online|offline|reset] phys-dev-name" % script_name)
        print("   ex: %s online eth0" % script_name)
        sys.exit(1)
    else:
        command, phys_dev_name = sys.argv[1:3]
        main(command, phys_dev_name)
