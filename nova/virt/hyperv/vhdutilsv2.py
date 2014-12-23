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
import struct
import sys

if sys.platform == 'win32':
    import wmi

from xml.etree import ElementTree

from oslo.utils import units

from nova.i18n import _
from nova.virt.hyperv import constants
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import vmutilsv2


VHDX_BAT_ENTRY_SIZE = 8
VHDX_HEADER_OFFSETS = [64 * units.Ki, 128 * units.Ki]
VHDX_HEADER_SECTION_SIZE = units.Mi
VHDX_LOG_LENGTH_OFFSET = 68
VHDX_METADATA_SIZE_OFFSET = 64
VHDX_REGION_TABLE_OFFSET = 192 * units.Ki
VHDX_BS_METADATA_ENTRY_OFFSET = 48


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
        # Although this method can take a size argument in case of VHDX
        # images, avoid it as the underlying Win32 is currently not
        # resizing the disk properly. This can be reconsidered once the
        # Win32 issue is fixed.
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

        et = ElementTree.fromstring(vhd_info_xml)
        item = et.find(".//PROPERTY[@NAME='ParentPath']/VALUE")
        if item:
            item.text = parent_vhd_path
        vhd_info_xml = ElementTree.tostring(et)

        (job_path, ret_val) = image_man_svc.SetVirtualHardDiskSettingData(
            VirtualDiskSettingData=vhd_info_xml)

        self._vmutils.check_ret_val(ret_val, job_path)

    def _get_resize_method(self):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        return image_man_svc.ResizeVirtualHardDisk

    def get_internal_vhd_size_by_file_size(self, vhd_path,
                                           new_vhd_file_size):
        """VHDX Size = Header (1 MB)
                        + Log
                        + Metadata Region
                        + BAT
                        + Payload Blocks
            Chunk size = maximum number of bytes described by a SB block
                       = 2 ** 23 * LogicalSectorSize
        """
        vhd_format = self.get_vhd_format(vhd_path)
        if vhd_format == constants.DISK_FORMAT_VHD:
            return super(VHDUtilsV2,
                         self).get_internal_vhd_size_by_file_size(
                            vhd_path, new_vhd_file_size)
        else:
            vhd_info = self.get_vhd_info(vhd_path)
            vhd_type = vhd_info['Type']
            if vhd_type == self._VHD_TYPE_DIFFERENCING:
                vhd_parent = self.get_vhd_parent_path(vhd_path)
                return self.get_internal_vhd_size_by_file_size(vhd_parent,
                    new_vhd_file_size)
            else:
                try:
                    with open(vhd_path, 'rb') as f:
                        hs = VHDX_HEADER_SECTION_SIZE
                        bes = VHDX_BAT_ENTRY_SIZE

                        lss = vhd_info['LogicalSectorSize']
                        bs = self._get_vhdx_block_size(f)
                        ls = self._get_vhdx_log_size(f)
                        ms = self._get_vhdx_metadata_size_and_offset(f)[0]

                        chunk_ratio = (1 << 23) * lss / bs
                        size = new_vhd_file_size

                        max_internal_size = (bs * chunk_ratio * (size - hs -
                            ls - ms - bes - bes / chunk_ratio) / (bs *
                            chunk_ratio + bes * chunk_ratio + bes))

                        return max_internal_size - (max_internal_size % bs)

                except IOError as ex:
                    raise vmutils.HyperVException(_("Unable to obtain "
                                                    "internal size from VHDX: "
                                                    "%(vhd_path)s. Exception: "
                                                    "%(ex)s") %
                                                    {"vhd_path": vhd_path,
                                                     "ex": ex})

    def _get_vhdx_current_header_offset(self, vhdx_file):
        sequence_numbers = []
        for offset in VHDX_HEADER_OFFSETS:
            vhdx_file.seek(offset + 8)
            sequence_numbers.append(struct.unpack('<Q',
                                    vhdx_file.read(8))[0])
        current_header = sequence_numbers.index(max(sequence_numbers))
        return VHDX_HEADER_OFFSETS[current_header]

    def _get_vhdx_log_size(self, vhdx_file):
        current_header_offset = self._get_vhdx_current_header_offset(vhdx_file)
        offset = current_header_offset + VHDX_LOG_LENGTH_OFFSET
        vhdx_file.seek(offset)
        log_size = struct.unpack('<I', vhdx_file.read(4))[0]
        return log_size

    def _get_vhdx_metadata_size_and_offset(self, vhdx_file):
        offset = VHDX_METADATA_SIZE_OFFSET + VHDX_REGION_TABLE_OFFSET
        vhdx_file.seek(offset)
        metadata_offset = struct.unpack('<Q', vhdx_file.read(8))[0]
        metadata_size = struct.unpack('<I', vhdx_file.read(4))[0]
        return metadata_size, metadata_offset

    def _get_vhdx_block_size(self, vhdx_file):
        metadata_offset = self._get_vhdx_metadata_size_and_offset(vhdx_file)[1]
        offset = metadata_offset + VHDX_BS_METADATA_ENTRY_OFFSET
        vhdx_file.seek(offset)
        file_parameter_offset = struct.unpack('<I', vhdx_file.read(4))[0]

        vhdx_file.seek(file_parameter_offset + metadata_offset)
        block_size = struct.unpack('<I', vhdx_file.read(4))[0]
        return block_size

    def _get_vhd_info_xml(self, image_man_svc, vhd_path):
        (job_path,
         ret_val,
         vhd_info_xml) = image_man_svc.GetVirtualHardDiskSettingData(vhd_path)

        self._vmutils.check_ret_val(ret_val, job_path)

        return vhd_info_xml.encode('utf8', 'xmlcharrefreplace')

    def get_vhd_info(self, vhd_path):
        image_man_svc = self._conn.Msvm_ImageManagementService()[0]
        vhd_info_xml = self._get_vhd_info_xml(image_man_svc, vhd_path)

        vhd_info_dict = {}
        et = ElementTree.fromstring(vhd_info_xml)
        for item in et.findall("PROPERTY"):
            name = item.attrib["NAME"]
            value_item = item.find("VALUE")
            if value_item is None:
                value_text = None
            else:
                value_text = value_item.text

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
