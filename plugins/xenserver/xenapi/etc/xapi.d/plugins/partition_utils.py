#!/usr/bin/env python
# Copyright (c) 2012 OpenStack Foundation
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

# NOTE: XenServer still only supports Python 2.4 in it's dom0 userspace
# which means the Nova xenapi plugins must use only Python 2.4 features

import logging
import os
import time

import pluginlib_nova as pluginlib
import utils

pluginlib.configure_logging("disk_utils")
_ = pluginlib._


def wait_for_dev(session, dev_path, max_seconds):
    for i in range(0, max_seconds):
        if os.path.exists(dev_path):
            return dev_path
        time.sleep(1)

    return ""


def make_partition(session, dev, partition_start, partition_end):
    dev_path = utils.make_dev_path(dev)

    if partition_end != "-":
        raise pluginlib.PluginError("Can only create unbounded partitions")

    utils.run_command(['sfdisk', '-uS', dev_path],
                      '%s,;\n' % (partition_start))


def _mkfs(fs, path, label):
    """Format a file or block device

    :param fs: Filesystem type (only 'swap', 'ext3' supported)
    :param path: Path to file or block device to format
    :param label: Volume label to use
    """
    if fs == 'swap':
        args = ['mkswap']
    elif fs == 'ext3':
        args = ['mkfs', '-t', fs]
        # add -F to force no interactive execute on non-block device.
        args.extend(['-F'])
        if label:
            args.extend(['-L', label])
    else:
        raise pluginlib.PluginError("Partition type %s not supported" % fs)
    args.append(path)
    utils.run_command(args)


def mkfs(session, dev, partnum, fs_type, fs_label):
    dev_path = utils.make_dev_path(dev)

    out = utils.run_command(['kpartx', '-avspp', dev_path])
    try:
        logging.info('kpartx output: %s' % out)
        mapperdir = os.path.join('/dev', 'mapper')
        dev_base = os.path.basename(dev)
        partition_path = os.path.join(mapperdir, "%sp%s" % (dev_base, partnum))
        _mkfs(fs_type, partition_path, fs_label)
    finally:
        # Always remove partitions otherwise we can't unplug the VBD
        utils.run_command(['kpartx', '-dvspp', dev_path])

if __name__ == "__main__":
    utils.register_plugin_calls(wait_for_dev,
                                make_partition,
                                mkfs)
