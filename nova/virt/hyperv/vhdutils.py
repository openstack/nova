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

import struct
import sys

if sys.platform == 'win32':
    import wmi

from nova.openstack.common.gettextutils import _
from nova.virt.hyperv import constants
from nova.virt.hyperv import vmutils
from xml.etree import ElementTree


VHD_HEADER_SIZE_FIX = 512
VHD_BAT_ENTRY_SIZE = 4
VHD_DYNAMIC_DISK_HEADER_SIZE = 1024
VHD_HEADER_SIZE_DYNAMIC = 512
VHD_FOOTER_SIZE_DYNAMIC = 512
VHD_BLK_SIZE_OFFSET = 544


class VHDUtils(object):

    def __init__(self):
        self._vmutils = vmutils.VMUtils()
        if sys.platform == 'win32':
            self._conn = wmi.WMI(moniker='//./root/virtualization')

    def validate_vhd(self, vhd_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (job_path, ret_val) = image_man_svc.ValidateVirtualHardDisk(
            Path=vhd_path)
        self._vmutils.check_ret_val(ret_val, job_path)

    def create_dynamic_vhd(self, path, max_internal_size, format):
        if format != constants.DISK_FORMAT_VHD:
            raise vmutils.HyperVException(_("Unsupported disk format: %s") %
                                          format)

        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (job_path, ret_val) = image_man_svc.CreateDynamicVirtualHardDisk(
            Path=path, MaxInternalSize=max_internal_size)
        self._vmutils.check_ret_val(ret_val, job_path)

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

    def resize_vhd(self, vhd_path, new_max_size, is_file_max_size=True):
        if is_file_max_size:
            new_internal_max_size = self.get_internal_vhd_size_by_file_size(
                                            vhd_path, new_max_size)
        else:
            new_internal_max_size = new_max_size

        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (job_path, ret_val) = image_man_svc.ExpandVirtualHardDisk(
            Path=vhd_path, MaxInternalSize=new_internal_max_size)
        self._vmutils.check_ret_val(ret_val, job_path)

    def get_internal_vhd_size_by_file_size(self, vhd_path, new_vhd_file_size):
        """Fixed VHD size = Data Block size + 512 bytes
           Dynamic_VHD_size = Dynamic Disk Header
                             + Copy of hard disk footer
                             + Hard Disk Footer
                             + Data Block
                             + BAT
           Dynamic Disk header fields
                Copy of hard disk footer (512 bytes)
                Dynamic Disk Header (1024 bytes)
                BAT (Block Allocation table)
                Data Block 1
                Data Block 2
                Data Block n
                Hard Disk Footer (512 bytes)
           Default block size is 2M
           BAT entry size is 4byte
        """
        base_vhd_info = self.get_vhd_info(vhd_path)
        vhd_type = base_vhd_info['Type']

        if vhd_type == constants.VHD_TYPE_FIXED:
            vhd_header_size = VHD_HEADER_SIZE_FIX
            return new_vhd_file_size - vhd_header_size
        elif vhd_type == constants.VHD_TYPE_DYNAMIC:
            bs = self._get_vhd_dynamic_blk_size(vhd_path)
            bes = VHD_BAT_ENTRY_SIZE
            ddhs = VHD_DYNAMIC_DISK_HEADER_SIZE
            hs = VHD_HEADER_SIZE_DYNAMIC
            fs = VHD_FOOTER_SIZE_DYNAMIC

            max_internal_size = (new_vhd_file_size -
                                 (hs + ddhs + fs)) * bs / (bes + bs)
            return max_internal_size
        else:
            raise vmutils.HyperVException(_("The %(vhd_type)s type VHD "
                                            "is not supported") %
                                            {"vhd_type": vhd_type})

    def _get_vhd_dynamic_blk_size(self, vhd_path):
        blk_size_offset = VHD_BLK_SIZE_OFFSET
        try:
            with open(vhd_path, "rb") as f:
                f.seek(blk_size_offset)
                version = f.read(4)
        except IOError:
            raise vmutils.HyperVException(_("Unable to obtain block size from"
                                            " VHD %(vhd_path)s") %
                                            {"vhd_path": vhd_path})
        return struct.unpack('>i', version)[0]

    def get_vhd_parent_path(self, vhd_path):
        return self.get_vhd_info(vhd_path).get("ParentPath")

    def get_vhd_info(self, vhd_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (vhd_info,
         job_path,
         ret_val) = image_man_svc.GetVirtualHardDiskInfo(vhd_path)
        self._vmutils.check_ret_val(ret_val, job_path)

        vhd_info_dict = {}

        et = ElementTree.fromstring(vhd_info)
        for item in et.findall("PROPERTY"):
            name = item.attrib["NAME"]
            value_text = item.find("VALUE").text
            if name == "ParentPath":
                vhd_info_dict[name] = value_text
            elif name in ["FileSize", "MaxInternalSize"]:
                vhd_info_dict[name] = long(value_text)
            elif name in ["InSavedState", "InUse"]:
                vhd_info_dict[name] = bool(value_text)
            elif name == "Type":
                vhd_info_dict[name] = int(value_text)

        return vhd_info_dict

    def get_vhd_format(self, path):
        with open(path, 'rb') as f:
            signature = f.read(8)
        if signature == 'vhdxfile':
            return constants.DISK_FORMAT_VHDX
        elif signature == 'conectix':
            return constants.DISK_FORMAT_VHD
        else:
            raise vmutils.HyperVException(_('Unsupported virtual disk format'))

    def get_best_supported_vhd_format(self):
        return constants.DISK_FORMAT_VHD
