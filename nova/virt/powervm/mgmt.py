# Copyright 2015, 2018 IBM Corp.
#
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

"""Utilities related to the PowerVM management partition.

The management partition is a special LPAR that runs the PowerVM REST API
service.  It itself appears through the REST API as a LogicalPartition of type
aixlinux, but with the is_mgmt_partition property set to True.
The PowerVM Nova Compute service runs on the management partition.
"""
import glob
import os
from os import path

from oslo_concurrency import lockutils
from oslo_log import log as logging
from pypowervm.tasks import partition as pvm_par
import retrying

from nova import exception
import nova.privsep.path


LOG = logging.getLogger(__name__)

_MP_UUID = None


@lockutils.synchronized("mgmt_lpar_uuid")
def mgmt_uuid(adapter):
    """Returns the management partitions UUID."""
    global _MP_UUID
    if not _MP_UUID:
        _MP_UUID = pvm_par.get_this_partition(adapter).uuid
    return _MP_UUID


def discover_vscsi_disk(mapping, scan_timeout=300):
    """Bring a mapped device into the management partition and find its name.

    Based on a VSCSIMapping, scan the appropriate virtual SCSI host bus,
    causing the operating system to discover the mapped device. Find and
    return the path of the newly-discovered device based on its UDID in the
    mapping.

    Note: scanning the bus will cause the operating system to discover *all*
    devices on that bus. However, this method will only return the path for
    the specific device from the input mapping, based on its UDID.

    :param mapping: The pypowervm.wrappers.virtual_io_server.VSCSIMapping
                    representing the mapping of the desired disk to the
                    management partition.
    :param scan_timeout: The maximum number of seconds after scanning to wait
                         for the specified device to appear.
    :return: The udev-generated ("/dev/sdX") name of the discovered disk.
    :raise NoDiskDiscoveryException: If the disk did not appear after the
                                     specified timeout.
    :raise UniqueDiskDiscoveryException: If more than one disk appears with the
                                         expected UDID.
    """
    # Calculate the Linux slot number from the client adapter slot number.
    lslot = 0x30000000 | mapping.client_adapter.lpar_slot_num
    # We'll match the device ID based on the UDID, which is actually the last
    # 32 chars of the field we get from PowerVM.
    udid = mapping.backing_storage.udid[-32:]

    LOG.debug("Trying to discover VSCSI disk with UDID %(udid)s on slot "
              "%(slot)x.", {'udid': udid, 'slot': lslot})

    # Find the special file to scan the bus, and scan it.
    # This glob should yield exactly one result, but use the loop just in case.
    for scanpath in glob.glob(
            '/sys/bus/vio/devices/%x/host*/scsi_host/host*/scan' % lslot):
        # Writing '- - -' to this sysfs file triggers bus rescan
        nova.privsep.path.writefile(scanpath, 'a', '- - -')

    # Now see if our device showed up. If so, we can reliably match it based
    # on its Linux ID, which ends with the disk's UDID.
    dpathpat = '/dev/disk/by-id/*%s' % udid

    # The bus scan is asynchronous.  Need to poll, waiting for the device to
    # spring into existence. Stop when glob finds at least one device, or
    # after the specified timeout.  Sleep 1/4 second between polls.
    @retrying.retry(retry_on_result=lambda result: not result, wait_fixed=250,
                    stop_max_delay=scan_timeout * 1000)
    def _poll_for_dev(globpat):
        return glob.glob(globpat)
    try:
        disks = _poll_for_dev(dpathpat)
    except retrying.RetryError as re:
        raise exception.NoDiskDiscoveryException(
            bus=lslot, udid=udid, polls=re.last_attempt.attempt_number,
            timeout=scan_timeout)
    # If we get here, _poll_for_dev returned a nonempty list. If not exactly
    # one entry, this is an error.
    if len(disks) != 1:
        raise exception.UniqueDiskDiscoveryException(path_pattern=dpathpat,
                                                     count=len(disks))

    # The by-id path is a symlink. Resolve to the /dev/sdX path
    dpath = path.realpath(disks[0])
    LOG.debug("Discovered VSCSI disk with UDID %(udid)s on slot %(slot)x at "
              "path %(devname)s.",
              {'udid': udid, 'slot': lslot, 'devname': dpath})
    return dpath


def remove_block_dev(devpath, scan_timeout=10):
    """Remove a block device from the management partition.

    This method causes the operating system of the management partition to
    delete the device special files associated with the specified block device.

    :param devpath: Any path to the block special file associated with the
                    device to be removed.
    :param scan_timeout: The maximum number of seconds after scanning to wait
                         for the specified device to disappear.
    :raise InvalidDevicePath: If the specified device or its 'delete' special
                              file cannot be found.
    :raise DeviceDeletionException: If the deletion was attempted, but the
                                    device special file is still present
                                    afterward.
    """
    # Resolve symlinks, if any, to get to the /dev/sdX path
    devpath = path.realpath(devpath)
    try:
        os.stat(devpath)
    except OSError:
        raise exception.InvalidDevicePath(path=devpath)
    devname = devpath.rsplit('/', 1)[-1]
    delpath = '/sys/block/%s/device/delete' % devname
    try:
        os.stat(delpath)
    except OSError:
        raise exception.InvalidDevicePath(path=delpath)
    LOG.debug("Deleting block device %(devpath)s from the management "
              "partition via special file %(delpath)s.",
              {'devpath': devpath, 'delpath': delpath})
    # Writing '1' to this sysfs file deletes the block device and rescans.
    nova.privsep.path.writefile(delpath, 'a', '1')

    # The bus scan is asynchronous. Need to poll, waiting for the device to
    # disappear. Stop when stat raises OSError (dev file not found) - which is
    # success - or after the specified timeout (which is failure). Sleep 1/4
    # second between polls.
    @retrying.retry(retry_on_result=lambda result: result, wait_fixed=250,
                    stop_max_delay=scan_timeout * 1000)
    def _poll_for_del(statpath):
        try:
            os.stat(statpath)
            return True
        except OSError:
            # Device special file is absent, as expected
            return False
    try:
        _poll_for_del(devpath)
    except retrying.RetryError as re:
        # stat just kept returning (dev file continued to exist).
        raise exception.DeviceDeletionException(
            devpath=devpath, polls=re.last_attempt.attempt_number,
            timeout=scan_timeout)
    # Else stat raised - the device disappeared - all done.
