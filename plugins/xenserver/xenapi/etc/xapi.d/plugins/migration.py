#!/usr/bin/env python

# Copyright 2010 OpenStack Foundation
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

# NOTE: XenServer still only supports Python 2.4 in it's dom0 userspace
# which means the Nova xenapi plugins must use only Python 2.4 features

"""
XenAPI Plugin for transferring data between host nodes
"""
import utils

import pluginlib_nova


pluginlib_nova.configure_logging('migration')
logging = pluginlib_nova.logging


def move_vhds_into_sr(session, instance_uuid, sr_path, uuid_stack):
    """Moves the VHDs from their copied location to the SR."""
    staging_path = "/images/instance%s" % instance_uuid
    imported_vhds = utils.import_vhds(sr_path, staging_path, uuid_stack)
    utils.cleanup_staging_area(staging_path)
    return imported_vhds


def _rsync_vhds(instance_uuid, host, staging_path, user="root"):
    if not staging_path.endswith('/'):
        staging_path += '/'

    dest_path = '/images/instance%s/' % (instance_uuid)

    ip_cmd = ["/sbin/ip", "addr", "show"]
    output = utils.run_command(ip_cmd)
    if ' %s/' % host in output:
        # If copying to localhost, don't use SSH
        rsync_cmd = ["/usr/bin/rsync", "-av", "--progress",
                     staging_path, dest_path]
    else:
        ssh_cmd = 'ssh -o StrictHostKeyChecking=no'
        rsync_cmd = ["/usr/bin/rsync", "-av", "--progress", "-e", ssh_cmd,
                     staging_path, '%s@%s:%s' % (user, host, dest_path)]

    # NOTE(hillad): rsync's progress is carriage returned, requiring
    # universal_newlines for real-time output.

    rsync_proc = utils.make_subprocess(rsync_cmd, stdout=True, stderr=True,
                                       universal_newlines=True)
    while True:
        rsync_progress = rsync_proc.stdout.readline()
        if not rsync_progress:
            break
        logging.debug("[%s] %s" % (instance_uuid, rsync_progress))

    utils.finish_subprocess(rsync_proc, rsync_cmd)


def transfer_vhd(session, instance_uuid, host, vdi_uuid, sr_path, seq_num):
    """Rsyncs a VHD to an adjacent host."""
    staging_path = utils.make_staging_area(sr_path)
    try:
        utils.prepare_staging_area(
                sr_path, staging_path, [vdi_uuid], seq_num=seq_num)
        _rsync_vhds(instance_uuid, host, staging_path)
    finally:
        utils.cleanup_staging_area(staging_path)


if __name__ == '__main__':
    utils.register_plugin_calls(move_vhds_into_sr, transfer_vhd)
