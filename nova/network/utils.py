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
