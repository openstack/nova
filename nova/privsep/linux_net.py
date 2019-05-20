# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
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
Linux network specific helpers.
"""


import os

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils

import nova.privsep.linux_net


LOG = logging.getLogger(__name__)


def device_exists(device):
    """Check if ethernet device exists."""
    return os.path.exists('/sys/class/net/%s' % device)


def delete_net_dev(dev):
    """Delete a network device only if it exists."""
    if device_exists(dev):
        try:
            delete_net_dev_escalated(dev)
            LOG.debug("Net device removed: '%s'", dev)
        except processutils.ProcessExecutionError:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed removing net device: '%s'", dev)


@nova.privsep.sys_admin_pctxt.entrypoint
def delete_net_dev_escalated(dev):
    processutils.execute('ip', 'link', 'delete', dev,
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_mtu(dev, mtu):
    if mtu:
        processutils.execute('ip', 'link', 'set', dev, 'mtu',
                             mtu, check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_enabled(dev):
    _set_device_enabled_inner(dev)


def _set_device_enabled_inner(dev):
    processutils.execute('ip', 'link', 'set', dev, 'up',
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_trust(dev, vf_num, trusted):
    _set_device_trust_inner(dev, vf_num, trusted)


def _set_device_trust_inner(dev, vf_num, trusted):
    processutils.execute('ip', 'link', 'set', dev,
                         'vf', vf_num,
                         'trust', bool(trusted) and 'on' or 'off',
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_macaddr(dev, mac_addr, port_state=None):
    _set_device_macaddr_inner(dev, mac_addr, port_state=port_state)


def _set_device_macaddr_inner(dev, mac_addr, port_state=None):
    if port_state:
        processutils.execute('ip', 'link', 'set', dev, 'address', mac_addr,
                             port_state, check_exit_code=[0, 2, 254])
    else:
        processutils.execute('ip', 'link', 'set', dev, 'address', mac_addr,
                             check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_macaddr_and_vlan(dev, vf_num, mac_addr, vlan):
    processutils.execute('ip', 'link', 'set', dev,
                         'vf', vf_num,
                         'mac', mac_addr,
                         'vlan', vlan,
                         run_as_root=True,
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def create_tap_dev(dev, mac_address=None, multiqueue=False):
    if not device_exists(dev):
        try:
            # First, try with 'ip'
            cmd = ('ip', 'tuntap', 'add', dev, 'mode', 'tap')
            if multiqueue:
                cmd = cmd + ('multi_queue', )
            processutils.execute(*cmd, check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            if multiqueue:
                LOG.warning(
                    'Failed to create a tap device with ip tuntap. '
                    'tunctl does not support creation of multi-queue '
                    'enabled devices, skipping fallback.')
                raise

            # Second option: tunctl
            processutils.execute('tunctl', '-b', '-t', dev)

        if mac_address:
            _set_device_macaddr_inner(dev, mac_address)
        _set_device_enabled_inner(dev)


@nova.privsep.sys_admin_pctxt.entrypoint
def add_vlan(bridge_interface, interface, vlan_num):
    processutils.execute('ip', 'link', 'add', 'link', bridge_interface,
                         'name', interface, 'type', 'vlan',
                         'id', vlan_num, check_exit_code=[0, 2, 254])
