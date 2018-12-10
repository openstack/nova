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


@nova.privsep.sys_admin_pctxt.entrypoint
def add_bridge(interface):
    """Add a bridge.

    :param interface: the name of the bridge
    """
    processutils.execute('brctl', 'addbr', interface)


@nova.privsep.sys_admin_pctxt.entrypoint
def delete_bridge(interface):
    """Delete a bridge.

    :param interface: the name of the bridge
    """
    processutils.execute('brctl', 'delbr', interface)


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
    _delete_net_dev_inner(dev)


def _delete_net_dev_inner(dev):
    processutils.execute('ip', 'link', 'delete', dev,
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_mtu(dev, mtu):
    _set_device_mtu_inner(dev, mtu)


def _set_device_mtu_inner(dev, mtu):
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
def set_device_disabled(dev):
    processutils.execute('ip', 'link', 'set', dev, 'down')


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
def bind_ip(device, ip, scope_is_link=False):
    if not scope_is_link:
        processutils.execute('ip', 'addr', 'add', str(ip) + '/32',
                             'dev', device, check_exit_code=[0, 2, 254])
    else:
        processutils.execute('ip', 'addr', 'add', str(ip) + '/32',
                             'scope', 'link', 'dev', device,
                             check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def unbind_ip(device, ip):
    processutils.execute('ip', 'addr', 'del', str(ip) + '/32',
                         'dev', device, check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def dhcp_release(dev, address, mac_address):
    processutils.execute('dhcp_release', dev, address, mac_address)


def routes_show(dev):
    # Format of output is:
    #     192.168.1.0/24  proto kernel  scope link  src 192.168.1.6
    return processutils.execute('ip', 'route', 'show', 'dev', dev)


# TODO(mikal): this is horrid. The calling code takes arguments from a route
# list and just regurgitates them into new routes. This isn't good enough,
# but is outside the scope of the privsep transition. Mark it as bonkers and
# hope we clean it up later.
@nova.privsep.sys_admin_pctxt.entrypoint
def route_add_horrid(routes):
    processutils.execute('ip', 'route', 'add', *routes)


@nova.privsep.sys_admin_pctxt.entrypoint
def route_delete(dev, route):
    processutils.execute('ip', 'route', 'del', route, 'dev', dev)


# TODO(mikal): this is horrid. The calling code takes arguments from a route
# list and just regurgitates them into new routes. This isn't good enough,
# but is outside the scope of the privsep transition. Mark it as bonkers and
# hope we clean it up later.
@nova.privsep.sys_admin_pctxt.entrypoint
def route_delete_horrid(dev, routes):
    processutils.execute('ip', 'route', 'del', *routes)


@nova.privsep.sys_admin_pctxt.entrypoint
def create_tap_dev(dev, mac_address=None, multiqueue=False):
    _create_tap_dev_inner(dev, mac_address=mac_address,
                          multiqueue=multiqueue)


def _create_tap_dev_inner(dev, mac_address=None, multiqueue=False):
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
