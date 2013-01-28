# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Cloudbase Solutions Srl
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

import sys

if sys.platform == 'win32':
    import wmi

from nova.virt.hyperv import vmutils
from xml.etree import ElementTree


class VHDUtils(object):

    def __init__(self):
        self._vmutils = vmutils.VMUtils()
        if sys.platform == 'win32':
            self._conn = wmi.WMI(moniker='//./root/virtualization')

    def create_differencing_vhd(self, path, parent_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (job_path, ret_val) = image_man_svc.CreateDifferencingVirtualHardDisk(
            Path=path, ParentPath=parent_path)
        self._vmutils.check_ret_val(ret_val, job_path)

    def reconnect_parent_vhd(self, child_vhd_path, parent_vhd_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (job_path, ret_val) = image_man_svc.ReconnectParentVirtualHardDisk(
            ChildPath=child_vhd_path,
            ParentPath=parent_vhd_path,
            Force=True)
        self._vmutils.check_ret_val(ret_val, job_path)

    def merge_vhd(self, src_vhd_path, dest_vhd_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (job_path, ret_val) = image_man_svc.MergeVirtualHardDisk(
            SourcePath=src_vhd_path,
            DestinationPath=dest_vhd_path)
        self._vmutils.check_ret_val(ret_val, job_path)

    def get_vhd_parent_path(self, vhd_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (vhd_info,
         job_path,
         ret_val) = image_man_svc.GetVirtualHardDiskInfo(vhd_path)
        self._vmutils.check_ret_val(ret_val, job_path)

        base_disk_path = None
        et = ElementTree.fromstring(vhd_info)
        for item in et.findall("PROPERTY"):
            if item.attrib["NAME"] == "ParentPath":
                base_disk_path = item.find("VALUE").text
                break
        return base_disk_path
