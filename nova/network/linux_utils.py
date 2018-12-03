# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Utility methods for linux networking."""

from oslo_concurrency import processutils
from oslo_log import log as logging

from nova.pci import utils as pci_utils
import nova.privsep.linux_net
from nova import utils


LOG = logging.getLogger(__name__)


def create_tap_dev(dev, mac_address=None, multiqueue=False):
    if not nova.privsep.linux_net.device_exists(dev):
        try:
            # First, try with 'ip'
            cmd = ('ip', 'tuntap', 'add', dev, 'mode', 'tap')
            if multiqueue:
                cmd = cmd + ('multi_queue', )
            utils.execute(*cmd, run_as_root=True, check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            if multiqueue:
                LOG.warning(
                    'Failed to create a tap device with ip tuntap. '
                    'tunctl does not support creation of multi-queue '
                    'enabled devices, skipping fallback.')
                raise

            # Second option: tunctl
            utils.execute('tunctl', '-b', '-t', dev, run_as_root=True)
        if mac_address:
            nova.privsep.linux_net.set_device_macaddr(dev, mac_address)
        nova.privsep.linux_net.set_device_enabled(dev)


def set_vf_interface_vlan(pci_addr, mac_addr, vlan=0):
    pf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr,
                                                    pf_interface=True)
    vf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr)
    vf_num = pci_utils.get_vf_num_by_pci_address(pci_addr)

    # Set the VF's mac address and vlan
    utils.execute('ip', 'link', 'set', pf_ifname,
                  'vf', vf_num,
                  'mac', mac_addr,
                  'vlan', vlan,
                  run_as_root=True,
                  check_exit_code=[0, 2, 254])
    # Bring up/down the VF's interface
    # TODO(edand): The mac is assigned as a workaround for the following issue
    #              https://bugzilla.redhat.com/show_bug.cgi?id=1372944
    #              once resolved it will be removed
    port_state = 'up' if vlan > 0 else 'down'
    nova.privsep.linux_net.set_device_macaddr(vf_ifname, mac_addr,
                                              port_state=port_state)
