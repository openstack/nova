#!/usr/bin/env python

# Copyright (c) 2012 OpenStack Foundation
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

"""Handle the uploading and downloading of images via Glance."""

import os
import shutil

import utils

import pluginlib_nova


pluginlib_nova.configure_logging('workarounds')


def _copy_vdis(sr_path, staging_path, vdi_uuids):
    seq_num = 0
    for vdi_uuid in vdi_uuids:
        src = os.path.join(sr_path, "%s.vhd" % vdi_uuid)
        dst = os.path.join(staging_path, "%d.vhd" % seq_num)
        shutil.copyfile(src, dst)
        seq_num += 1


def safe_copy_vdis(session, sr_path, vdi_uuids, uuid_stack):
    staging_path = utils.make_staging_area(sr_path)
    try:
        _copy_vdis(sr_path, staging_path, vdi_uuids)
        return utils.import_vhds(sr_path, staging_path, uuid_stack)
    finally:
        utils.cleanup_staging_area(staging_path)


if __name__ == '__main__':
    utils.register_plugin_calls(safe_copy_vdis)
