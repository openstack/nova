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

"""
Utility class for VHD related operations.
Based on the "root/virtualization/v2" namespace available starting with
Hyper-V Server / Windows Server 2012.
"""
import sys

if sys.platform == 'win32':
    import wmi

from nova.openstack.common.gettextutils import _
from nova.virt.hyperv import constants
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import vmutilsv2
from xml.etree import ElementTree


class VHDUtilsV2(vhdutils.VHDUtils):

    _VHD_TYPE_DYNAMIC = 3
    _VHD_TYPE_DIFFERENCING = 4

    _vhd_format_map = {
        constants.DISK_FORMAT_VHD: 2,
        constants.DISK_FORMAT_VHDX: 3,
    }

    def __init__(self):
        self._vmutils = vmutilsv2.VMUtilsV2()
        if sys.platform == 'win32':
            self._conn = wmi.WMI(moniker='//./root/virtualization/v2')

    def create_dynamic_vhd(self, path, max_internal_size, format):
        vhd_format = self._vhd_format_map.get(format)
        if not vhd_format:
            raise vmutils.HyperVException(_("Unsupported disk format: %s") %
                                          format)

        self._create_vhd(self._VHD_TYPE_DYNAMIC, vhd_format, path,
                         max_internal_size=max_internal_size)

    def create_differencing_vhd(self, path, parent_path):
        parent_vhd_info = self.get_vhd_info(parent_path)
        self._create_vhd(self._VHD_TYPE_DIFFERENCING,
                         parent_vhd_info["Format"],
                         path, parent_path=parent_path)

    def _create_vhd(self, vhd_type, format, path, max_internal_size=None,
                    parent_path=None):
        vhd_info = self._conn.Msvm_VirtualHardDiskSettingData.new()

        vhd_info.Type = vhd_type
        vhd_info.Format = format
        vhd_info.Path = path
        vhd_info.ParentPath = parent_path

        if max_internal_size:
            vhd_info.MaxInternalSize = max_internal_size

        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        (job_path, ret_val) = image_man_svc.CreateVirtualHardDisk(
            VirtualDiskSettingData=vhd_info.GetText_(1))
        self._vmutils.check_ret_val(ret_val, job_path)

    def reconnect_parent_vhd(self, child_vhd_path, parent_vhd_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        vhd_info_xml = self._get_vhd_info_xml(image_man_svc, child_vhd_path)

        # Can't use ".//PROPERTY[@NAME='ParentPath']/VALUE" due to
        # compatibility requirements with Python 2.6
        et = ElementTree.fromstring(vhd_info_xml)
        for item in et.findall("PROPERTY"):
            name = item.attrib["NAME"]
            if name == 'ParentPath':
                item.find("VALUE").text = parent_vhd_path
                break
        vhd_info_xml = ElementTree.tostring(et)

        (job_path, ret_val) = image_man_svc.SetVirtualHardDiskSettingData(
            VirtualDiskSettingData=vhd_info_xml)

        self._vmutils.check_ret_val(ret_val, job_path)

    def resize_vhd(self, vhd_path, new_max_size):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (job_path, ret_val) = image_man_svc.ResizeVirtualHardDisk(
            Path=vhd_path, MaxInternalSize=new_max_size)

        self._vmutils.check_ret_val(ret_val, job_path)

    def _get_vhd_info_xml(self, image_man_svc, vhd_path):
        (job_path,
         ret_val,
         vhd_info_xml) = image_man_svc.GetVirtualHardDiskSettingData(vhd_path)

        self._vmutils.check_ret_val(ret_val, job_path)

        return vhd_info_xml

    def get_vhd_info(self, vhd_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        vhd_info_xml = self._get_vhd_info_xml(image_man_svc, vhd_path)

        vhd_info_dict = {}
        et = ElementTree.fromstring(vhd_info_xml)
        for item in et.findall("PROPERTY"):
            name = item.attrib["NAME"]
            value_text = item.find("VALUE").text
            if name in ["Path", "ParentPath"]:
                vhd_info_dict[name] = value_text
            elif name in ["BlockSize", "LogicalSectorSize",
                          "PhysicalSectorSize", "MaxInternalSize"]:
                vhd_info_dict[name] = long(value_text)
            elif name in ["Type", "Format"]:
                vhd_info_dict[name] = int(value_text)

        return vhd_info_dict

    def get_best_supported_vhd_format(self):
        return constants.DISK_FORMAT_VHDX
