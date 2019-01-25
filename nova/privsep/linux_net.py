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
    processutils.execute('ip', 'link', 'set', dev, 'up',
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def create_veth_pair(dev1_name, dev2_name, mtu=None):
    """Create a pair of veth devices with the specified names,
    deleting any previous devices with those names.
    """
    _create_veth_pair_inner(dev1_name, dev2_name, mtu=mtu)


def _create_veth_pair_inner(dev1_name, dev2_name, mtu=None):
    for dev in [dev1_name, dev2_name]:
        delete_net_dev(dev)

    processutils.execute('ip', 'link', 'add', dev1_name, 'type', 'veth',
                         'peer', 'name', dev2_name)
    for dev in [dev1_name, dev2_name]:
        processutils.execute('ip', 'link', 'set', dev, 'up')
        processutils.execute('ip', 'link', 'set', dev, 'promisc', 'on')
        _set_device_mtu_inner(dev, mtu)
