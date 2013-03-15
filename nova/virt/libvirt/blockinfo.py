# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2012-2013 Red Hat, Inc.
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
Handling of block device information and mapping.

This module contains helper methods for intepreting the block
device information and determining the suitable mapping to
guest devices and libvirt XML.

Throughout these methods there are a number of standard
variables / types used

 * 'mapping': a dict contains the storage device mapping.

   For the default disk types it will contain the following
   keys & values:

      'disk' -> disk_info
      'disk.rescue' -> disk_info
      'disk.local' -> disk_info
      'disk.swap' -> disk_info
      'disk.config' -> disk_info

   If any of the default disks are overriden by the block
   device info mappings, the hash value will be None

   For any ephemeral device there will also be a dict entry

      'disk.eph$NUM' -> disk_info

   For any volume device there will also be a dict entry:

       $path -> disk_info

   Finally a special key will refer to the root device:

      'root' -> disk_info


 * 'disk_info': a tuple specifying disk configuration

   It contains the following 3 fields

      (disk bus, disk dev, device type)

 * 'disk_bus': the guest bus type ('ide', 'virtio', 'scsi', etc)

 * 'disk_dev': the device name 'vda', 'hdc', 'sdf', 'xvde' etc

 * 'device_type': type of device eg 'disk', 'cdrom', 'floppy'

"""

from oslo.config import cfg

from nova import block_device
from nova.compute import instance_types
from nova import exception
from nova.openstack.common import log as logging
from nova.virt import configdrive
from nova.virt import driver


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


def has_disk_dev(mapping, disk_dev):
    """Determine if a disk device name has already been used.

       Looks at all the keys in mapping to see if any
       corresponding disk_info tuple has a device name
       matching disk_dev

       Returns True if the disk_dev is in use."""

    for disk in mapping:
        info = mapping[disk]
        if info['dev'] == disk_dev:
            return True
    return False


def get_dev_prefix_for_disk_bus(disk_bus):
    """Determine the dev prefix for a disk bus.

       Determine the dev prefix to be combined
       with a disk number to fix a disk_dev.
       eg 'hd' for 'ide' bus can be used to
       form a disk dev 'hda'

       Returns the dev prefix or raises an
       exception if the disk bus is unknown."""

    if CONF.libvirt_disk_prefix:
        return CONF.libvirt_disk_prefix
    if disk_bus == "ide":
        return "hd"
    elif disk_bus == "virtio":
        return "vd"
    elif disk_bus == "xen":
        # Two possible mappings for Xen, xvda or sda
        # which are interchangable, so we pick sda
        return "sd"
    elif disk_bus == "scsi":
        return "sd"
    elif disk_bus == "usb":
        return "sd"
    elif disk_bus == "uml":
        return "ubd"
    elif disk_bus == "lxc":
        return None
    else:
        raise exception.NovaException(
            _("Unable to determine disk prefix for %s") %
            disk_bus)


def get_dev_count_for_disk_bus(disk_bus):
    """Determine the number disks supported.

       Determine how many disks can be supported in
       a single VM for a particular disk bus.

       Returns the number of disks supported."""

    if disk_bus == "ide":
        return 4
    else:
        return 26


def find_disk_dev_for_disk_bus(mapping, bus, last_device=False):
    """Identify a free disk dev name for a bus.

       Determines the possible disk dev names for
       the bus, and then checks them in order until
       it identifies one that is not yet used in the
       disk mapping. If 'last_device' is set, it will
       only consider the last available disk dev name.

       Returns the chosen disk_dev name, or raises an
       exception if none is available.
    """

    dev_prefix = get_dev_prefix_for_disk_bus(bus)
    if dev_prefix is None:
        return None

    max_dev = get_dev_count_for_disk_bus(bus)
    if last_device:
        devs = [max_dev - 1]
    else:
        devs = range(max_dev)

    for idx in devs:
        disk_dev = dev_prefix + chr(ord('a') + idx)
        if not has_disk_dev(mapping, disk_dev):
            return disk_dev

    raise exception.NovaException(
        _("No free disk device names for prefix '%s'"),
        dev_prefix)


def is_disk_bus_valid_for_virt(virt_type, disk_bus):
        valid_bus = {
            'qemu': ['virtio', 'scsi', 'ide', 'usb'],
            'kvm': ['virtio', 'scsi', 'ide', 'usb'],
            'xen': ['xen', 'ide'],
            'uml': ['uml'],
            'lxc': ['lxc'],
            }

        if virt_type not in valid_bus:
            raise exception.UnsupportedVirtType(virt=virt_type)

        return disk_bus in valid_bus[virt_type]


def get_disk_bus_for_device_type(virt_type,
                                 image_meta=None,
                                 device_type="disk"):
    """Determine the best disk bus to use for a device type.

       Considering the currently configured virtualization
       type, return the optimal disk_bus to use for a given
       device type. For example, for a disk on KVM it will
       return 'virtio', while for a CDROM it will return 'ide'

       Returns the disk_bus, or returns None if the device
       type is not supported for this virtualization"""

    # Prefer a disk bus set against the image first of all
    if image_meta:
        key = "hw_" + device_type + "_bus"
        disk_bus = image_meta.get('properties', {}).get(key)
        if disk_bus is not None:
            if not is_disk_bus_valid_for_virt(virt_type, disk_bus):
                raise exception.UnsupportedHardware(model=disk_bus,
                                                    virt=virt_type)
            return disk_bus

    # Otherwise pick a hypervisor default disk bus
    if virt_type == "uml":
        if device_type == "disk":
            return "uml"
    elif virt_type == "lxc":
        return "lxc"
    elif virt_type == "xen":
        if device_type == "cdrom":
            return "ide"
        elif device_type == "disk":
            return "xen"
    elif virt_type in ("qemu", "kvm"):
        if device_type == "cdrom":
            return "ide"
        elif device_type == "disk":
            return "virtio"

    return None


def get_disk_bus_for_disk_dev(virt_type, disk_dev):
    """Determine the disk bus for a disk dev.

       Given a disk devi like 'hda', 'sdf', 'xvdb', etc
       guess what the most appropriate disk bus is for
       the currently configured virtualization technology

       Returns the disk bus, or raises an Exception if
       the disk dev prefix is unknown."""

    if disk_dev[:2] == 'hd':
        return "ide"
    elif disk_dev[:2] == 'sd':
        # Reverse mapping 'sd' is not reliable
        # there are many possible mappings. So
        # this picks the most likely mappings
        if virt_type == "xen":
            return "xen"
        else:
            return "scsi"
    elif disk_dev[:2] == 'vd':
        return "virtio"
    elif disk_dev[:3] == 'xvd':
        return "xen"
    elif disk_dev[:3] == 'ubd':
        return "uml"
    else:
        raise exception.NovaException(
            _("Unable to determine disk bus for '%s'") %
            disk_dev[:1])


def get_next_disk_info(mapping, disk_bus,
                       device_type='disk',
                       last_device=False):
    """Determine the disk info for the next device on disk_bus.

       Considering the disks already listed in the disk mapping,
       determine the next available disk dev that can be assigned
       for the disk bus.

       Returns the disk_info for the next available disk."""

    disk_dev = find_disk_dev_for_disk_bus(mapping,
                                          disk_bus,
                                          last_device)
    return {'bus': disk_bus,
            'dev': disk_dev,
            'type': device_type}


def get_eph_disk(ephemeral):
    return 'disk.eph' + str(ephemeral['num'])


def get_disk_mapping(virt_type, instance,
                     disk_bus, cdrom_bus,
                     block_device_info=None,
                     image_meta=None, rescue=False):
    """Determine how to map default disks to the virtual machine.

       This is about figuring out whether the default 'disk',
       'disk.local', 'disk.swap' and 'disk.config' images have
       been overriden by the block device mapping.

       Returns the guest disk mapping for the devices."""

    inst_type = instance_types.extract_instance_type(instance)

    mapping = {}

    if virt_type == "lxc":
        # NOTE(zul): This information is not used by the libvirt driver
        # however we need to populate mapping so the image can be
        # created when the instance is started. This can
        # be removed when we convert LXC to use block devices.
        root_disk_bus = disk_bus
        root_device_type = 'disk'

        root_info = get_next_disk_info(mapping,
                                       root_disk_bus,
                                       root_device_type)
        mapping['root'] = root_info
        mapping['disk'] = root_info

        return mapping

    if rescue:
        rescue_info = get_next_disk_info(mapping,
                                         disk_bus)
        mapping['disk.rescue'] = rescue_info
        mapping['root'] = rescue_info

        os_info = get_next_disk_info(mapping,
                                     disk_bus)
        mapping['disk'] = os_info

        return mapping

    if image_meta and image_meta.get('disk_format') == 'iso':
        root_disk_bus = cdrom_bus
        root_device_type = 'cdrom'
    else:
        root_disk_bus = disk_bus
        root_device_type = 'disk'

    root_device_name = driver.block_device_info_get_root(block_device_info)
    if root_device_name is not None:
        root_device = block_device.strip_dev(root_device_name)
        root_info = {'bus': get_disk_bus_for_disk_dev(virt_type,
                                                      root_device),
                     'dev': root_device,
                     'type': root_device_type}
    else:
        root_info = get_next_disk_info(mapping,
                                       root_disk_bus,
                                       root_device_type)
    mapping['root'] = root_info
    if not block_device.volume_in_mapping(root_info['dev'],
                                          block_device_info):
        mapping['disk'] = root_info

    eph_info = get_next_disk_info(mapping,
                                  disk_bus)
    ephemeral_device = False
    if not (block_device.volume_in_mapping(eph_info['dev'],
                                           block_device_info) or
            0 in [eph['num'] for eph in
                  driver.block_device_info_get_ephemerals(
                block_device_info)]):
        if instance['ephemeral_gb'] > 0:
            ephemeral_device = True

    if ephemeral_device:
        mapping['disk.local'] = eph_info

    for eph in driver.block_device_info_get_ephemerals(
        block_device_info):
        disk_dev = block_device.strip_dev(eph['device_name'])
        disk_bus = get_disk_bus_for_disk_dev(virt_type, disk_dev)

        mapping[get_eph_disk(eph)] = {'bus': disk_bus,
                                      'dev': disk_dev,
                                      'type': 'disk'}

    swap = driver.block_device_info_get_swap(block_device_info)
    if driver.swap_is_usable(swap):
        disk_dev = block_device.strip_dev(swap['device_name'])
        disk_bus = get_disk_bus_for_disk_dev(virt_type, disk_dev)

        mapping['disk.swap'] = {'bus': disk_bus,
                                'dev': disk_dev,
                                'type': 'disk'}
    elif inst_type['swap'] > 0:
        swap_info = get_next_disk_info(mapping,
                                       disk_bus)
        if not block_device.volume_in_mapping(swap_info['dev'],
                                              block_device_info):
            mapping['disk.swap'] = swap_info

    block_device_mapping = driver.block_device_info_get_mapping(
        block_device_info)

    for vol in block_device_mapping:
        disk_dev = vol['mount_device'].rpartition("/")[2]
        disk_bus = get_disk_bus_for_disk_dev(virt_type, disk_dev)

        mapping[vol['mount_device']] = {'bus': disk_bus,
                                        'dev': disk_dev,
                                        'type': 'disk'}

    if configdrive.enabled_for(instance):
        config_info = get_next_disk_info(mapping,
                                         disk_bus,
                                         last_device=True)
        mapping['disk.config'] = config_info

    return mapping


def get_disk_info(virt_type, instance, block_device_info=None,
                  image_meta=None, rescue=False):
    """Determine guest disk mapping info.

       This is a wrapper around get_disk_mapping, which
       also returns the chosen disk_bus and cdrom_bus.
       The returned data is in a dict

            - disk_bus: the bus for harddisks
            - cdrom_bus: the bus for CDROMs
            - mapping: the disk mapping

       Returns the disk mapping disk."""

    disk_bus = get_disk_bus_for_device_type(virt_type, image_meta, "disk")
    cdrom_bus = get_disk_bus_for_device_type(virt_type, image_meta, "cdrom")
    mapping = get_disk_mapping(virt_type, instance,
                               disk_bus, cdrom_bus,
                               block_device_info,
                               image_meta, rescue)

    return {'disk_bus': disk_bus,
            'cdrom_bus': cdrom_bus,
            'mapping': mapping}
