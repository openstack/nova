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
This script is used to configure base openvswitch flows for XenServer hosts.
"""

import os
import subprocess
import sys


PNIC_NAME="eth1"
XEN_BRIDGE="xenbr1"

def main(dom_id, command, only_this_vif=None):
    pnic_ofport = execute('/usr/bin/ovs-ofctl', 'get', 'Interface', PNIC_NAME,
                          'ofport', return_stdout=True)
    ovs_ofctl = lambda *rule: execute('/usr/bin/ovs-ofctl', *rule)

    # clear all flows
    ovs_ofctl('del-flows', XEN_BRIDGE)

    # these flows are lower priority than all VM-specific flows.

    # allow all traffic from the physical NIC, as it is trusted (i.e., from a
    # filtered vif, or from the physical infrastructure
    ovs_ofctl('add-flow', XEN_BRIDGE,
              "priority=2,in_port=%s,action=normal" % pnic_ofport)

    # default drop
    ovs_ofctl('add-flow', XEN_BRIDGE, 'priority=1,action=drop')


def execute(*command, return_stdout=False):
    devnull = open(os.devnull, 'w')
    command = map(str, command)
    proc = subprocess.Popen(command, close_fds=True,
                            stdout=subprocess.PIPE, stderr=devnull)
    devnull.close()
    if return_stdout:
        return proc.stdout.read()
    else:
        return None


if __name__ == "__main__":
    if sys.argv:
        print "This script configures base ovs flows."
        print "usage: %s" % os.path.basename(sys.argv[0])
        sys.exit(1)
    else:
        main()
