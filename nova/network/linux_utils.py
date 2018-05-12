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

import os

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils

from nova.pci import utils as pci_utils
from nova import utils


LOG = logging.getLogger(__name__)


def device_exists(device):
    """Check if ethernet device exists."""
    return os.path.exists('/sys/class/net/%s' % device)


def delete_net_dev(dev):
    """Delete a network device only if it exists."""
    if device_exists(dev):
        try:
            utils.execute('ip', 'link', 'delete', dev, run_as_root=True,
                          check_exit_code=[0, 2, 254])
            LOG.debug("Net device removed: '%s'", dev)
        except processutils.ProcessExecutionError:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed removing net device: '%s'", dev)


def set_device_mtu(dev, mtu=None):
    """Set the device MTU."""
    if mtu:
        utils.execute('ip', 'link', 'set', dev, 'mtu',
                      mtu, run_as_root=True,
                      check_exit_code=[0, 2, 254])


def create_veth_pair(dev1_name, dev2_name, mtu=None):
    """Create a pair of veth devices with the specified names,
    deleting any previous devices with those names.
    """
    for dev in [dev1_name, dev2_name]:
        delete_net_dev(dev)

    utils.execute('ip', 'link', 'add', dev1_name, 'type', 'veth', 'peer',
                  'name', dev2_name, run_as_root=True)
    for dev in [dev1_name, dev2_name]:
        utils.execute('ip', 'link', 'set', dev, 'up', run_as_root=True)
        utils.execute('ip', 'link', 'set', dev, 'promisc', 'on',
                      run_as_root=True)
        set_device_mtu(dev, mtu)


def create_tap_dev(dev, mac_address=None, multiqueue=False):
    if not device_exists(dev):
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
            utils.execute('ip', 'link', 'set', dev, 'address', mac_address,
                          run_as_root=True, check_exit_code=[0, 2, 254])
        utils.execute('ip', 'link', 'set', dev, 'up', run_as_root=True,
                      check_exit_code=[0, 2, 254])


def set_vf_interface_vlan(pci_addr, mac_addr, vlan=0):
    pf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr,
                                                    pf_interface=True)
    vf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr)
    vf_num = pci_utils.get_vf_num_by_pci_address(pci_addr)

    # Set the VF's mac address and vlan
    exit_code = [0, 2, 254]
    port_state = 'up' if vlan > 0 else 'down'
    utils.execute('ip', 'link', 'set', pf_ifname,
                  'vf', vf_num,
                  'mac', mac_addr,
                  'vlan', vlan,
                  run_as_root=True,
                  check_exit_code=exit_code)
    # Bring up/down the VF's interface
    # TODO(edand): The mac is assigned as a workaround for the following issue
    #              https://bugzilla.redhat.com/show_bug.cgi?id=1372944
    #              once resolved it will be removed
    utils.execute('ip', 'link', 'set', vf_ifname,
                  'address', mac_addr,
                  port_state,
                  run_as_root=True,
                  check_exit_code=exit_code)
