# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 VMware, Inc.
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
Helper methods for operations related to the management of volumes,
and storage repositories
"""

import re
import string

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)


class StorageError(Exception):
    """To raise errors related to Volume commands."""

    def __init__(self, message=None):
        super(StorageError, self).__init__(message)


def get_host_iqn(session, cluster=None):
    """
    Return the host iSCSI IQN.
    """
    host_mor = vm_util.get_host_ref(session, cluster)
    hbas_ret = session._call_method(vim_util, "get_dynamic_property",
                                    host_mor, "HostSystem",
                                    "config.storageDevice.hostBusAdapter")

    # Meaning there are no host bus adapters on the host
    if hbas_ret is None:
        return
    host_hbas = hbas_ret.HostHostBusAdapter
    if not host_hbas:
        return
    for hba in host_hbas:
        if hba.__class__.__name__ == 'HostInternetScsiHba':
            return hba.iScsiName


def find_st(session, data, cluster=None):
    """
    Return the iSCSI Target given a volume info.
    """
    target_portal = data['target_portal']
    target_iqn = data['target_iqn']
    host_mor = vm_util.get_host_ref(session, cluster)

    lst_properties = ["config.storageDevice.hostBusAdapter",
                      "config.storageDevice.scsiTopology",
                      "config.storageDevice.scsiLun"]
    props = session._call_method(vim_util, "get_object_properties",
                       None, host_mor, "HostSystem",
                       lst_properties)
    result = (None, None)
    hbas_ret = None
    scsi_topology = None
    scsi_lun_ret = None
    for elem in props:
        for prop in elem.propSet:
            if prop.name == "config.storageDevice.hostBusAdapter":
                hbas_ret = prop.val
            elif prop.name == "config.storageDevice.scsiTopology":
                scsi_topology = prop.val
            elif prop.name == "config.storageDevice.scsiLun":
                scsi_lun_ret = prop.val

    # Meaning there are no host bus adapters on the host
    if hbas_ret is None:
        return result
    host_hbas = hbas_ret.HostHostBusAdapter
    if not host_hbas:
        return result
    for hba in host_hbas:
        if hba.__class__.__name__ == 'HostInternetScsiHba':
            hba_key = hba.key
            break
    else:
        return result

    if scsi_topology is None:
        return result
    host_adapters = scsi_topology.adapter
    if not host_adapters:
        return result
    scsi_lun_key = None
    for adapter in host_adapters:
        if adapter.adapter == hba_key:
            if not getattr(adapter, 'target', None):
                return result
            for target in adapter.target:
                if (getattr(target.transport, 'address', None) and
                    target.transport.address[0] == target_portal and
                        target.transport.iScsiName == target_iqn):
                    if not target.lun:
                        return result
                    for lun in target.lun:
                        if 'host.ScsiDisk' in lun.scsiLun:
                            scsi_lun_key = lun.scsiLun
                            break
                    break
            break

    if scsi_lun_key is None:
        return result

    if scsi_lun_ret is None:
        return result
    host_scsi_luns = scsi_lun_ret.ScsiLun
    if not host_scsi_luns:
        return result
    for scsi_lun in host_scsi_luns:
        if scsi_lun.key == scsi_lun_key:
            return (scsi_lun.deviceName, scsi_lun.uuid)

    return result


def rescan_iscsi_hba(session, cluster=None):
    """
    Rescan the iSCSI HBA to discover iSCSI targets.
    """
    host_mor = vm_util.get_host_ref(session, cluster)
    storage_system_mor = session._call_method(vim_util, "get_dynamic_property",
                                              host_mor, "HostSystem",
                                              "configManager.storageSystem")
    hbas_ret = session._call_method(vim_util,
                                    "get_dynamic_property",
                                    storage_system_mor,
                                    "HostStorageSystem",
                                    "storageDeviceInfo.hostBusAdapter")
    # Meaning there are no host bus adapters on the host
    if hbas_ret is None:
        return
    host_hbas = hbas_ret.HostHostBusAdapter
    if not host_hbas:
        return
    for hba in host_hbas:
        if hba.__class__.__name__ == 'HostInternetScsiHba':
            hba_device = hba.device
            break
    else:
        return

    LOG.debug(_("Rescanning HBA %s") % hba_device)
    session._call_method(session._get_vim(), "RescanHba", storage_system_mor,
                         hbaDevice=hba_device)
    LOG.debug(_("Rescanned HBA %s ") % hba_device)


def mountpoint_to_number(mountpoint):
    """Translate a mountpoint like /dev/sdc into a numeric."""
    if mountpoint.startswith('/dev/'):
        mountpoint = mountpoint[5:]
    if re.match('^[hsv]d[a-p]$', mountpoint):
        return (ord(mountpoint[2:3]) - ord('a'))
    elif re.match('^[0-9]+$', mountpoint):
        return string.atoi(mountpoint, 10)
    else:
        LOG.warn(_("Mountpoint cannot be translated: %s") % mountpoint)
        return -1
