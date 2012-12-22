# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM
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

import hashlib
import os
import re

from nova import utils

from nova.openstack.common import cfg
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova.virt import images
from nova.virt.powervm import command
from nova.virt.powervm import common
from nova.virt.powervm import constants
from nova.virt.powervm import exception

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class PowerVMDiskAdapter(object):
    pass


class PowerVMLocalVolumeAdapter(PowerVMDiskAdapter):
    """Default block device providor for PowerVM

    This disk adapter uses logical volumes on the hosting VIOS
    to provide backing block devices for instances/LPARs
    """

    def __init__(self, connection):
        super(PowerVMLocalVolumeAdapter, self).__init__()

        self.command = command.IVMCommand()

        self._connection = None
        self.connection_data = connection

    def _set_connection(self):
        if self._connection is None:
            self._connection = common.ssh_connect(self.connection_data)

    def create_volume(self, size):
        """Creates a logical volume with a minimum size

        :param size: size of the logical volume in bytes
        :returns: string -- the name of the new logical volume.
        :raises: PowerVMNoSpaceLeftOnVolumeGroup
        """
        return self._create_logical_volume(size)

    def delete_volume(self, disk_name):
        """Removes the Logical Volume and its associated vSCSI connection

        :param disk_name: name of Logical Volume device in /dev/
        """
        LOG.debug(_("Removing the logical volume '%s'") % disk_name)
        self._remove_logical_volume(disk_name)

    def create_volume_from_image(self, context, instance, image_id):
        """Creates a Logical Volume and copies the specified image to it

        :param context: nova context used to retrieve image from glance
        :param instance: instance to create the volume for
        :image_id: image_id reference used to locate image in glance
        :returns: dictionary with the name of the created
                  Logical Volume device in 'device_name' key
        """

        file_name = '.'.join([image_id, 'gz'])
        file_path = os.path.join(CONF.powervm_img_local_path,
                                 file_name)

        if not os.path.isfile(file_path):
            LOG.debug(_("Fetching image '%s' from glance") % image_id)
            images.fetch_to_raw(context, image_id, file_path,
                                instance['user_id'],
                                project_id=instance['project_id'])
        else:
            LOG.debug((_("Using image found at '%s'") % file_path))

        LOG.debug(_("Ensuring image '%s' exists on IVM") % file_path)
        remote_path = CONF.powervm_img_remote_path
        remote_file_name, size = self._copy_image_file(file_path, remote_path)

        # calculate root device size in bytes
        # we respect the minimum root device size in constants
        size_gb = max(instance['instance_type']['root_gb'],
                      constants.POWERVM_MIN_ROOT_GB)
        size = size_gb * 1024 * 1024 * 1024

        try:
            LOG.debug(_("Creating logical volume of size %s bytes") % size)
            disk_name = self._create_logical_volume(size)

            LOG.debug(_("Copying image to the device '%s'") % disk_name)
            self._copy_file_to_device(remote_file_name, disk_name)
        except Exception:
            LOG.error(_("Error while creating logical volume from image. "
                        "Will attempt cleanup."))
            # attempt cleanup of logical volume before re-raising exception
            with excutils.save_and_reraise_exception():
                try:
                    self.delete_volume(disk_name)
                except Exception:
                    msg = _('Error while attempting cleanup of failed '
                            'deploy to logical volume.')
                    LOG.exception(msg)

        return {'device_name': disk_name}

    def create_image_from_volume(self):
        raise NotImplementedError()

    def migrate_volume(self):
        raise NotImplementedError()

    def attach_volume_to_host(self, *args, **kargs):
        pass

    def detach_volume_from_host(self, *args, **kargs):
        pass

    def _create_logical_volume(self, size):
        """Creates a logical volume with a minimum size.

        :param size: size of the logical volume in bytes
        :returns: string -- the name of the new logical volume.
        :raises: PowerVMNoSpaceLeftOnVolumeGroup
        """
        vgs = self.run_vios_command(self.command.lsvg())
        cmd = self.command.lsvg('%s -field vgname freepps -fmt :' %
                                ' '.join(vgs))
        output = self.run_vios_command(cmd)
        found_vg = None

        # If it's not a multiple of 1MB we get the next
        # multiple and use it as the megabyte_size.
        megabyte = 1024 * 1024
        if (size % megabyte) != 0:
            megabyte_size = int(size / megabyte) + 1
        else:
            megabyte_size = size / megabyte

        # Search for a volume group with enough free space for
        # the new logical volume.
        for vg in output:
            # Returned output example: 'rootvg:396 (25344 megabytes)'
            match = re.search(r'^(\w+):\d+\s\((\d+).+$', vg)
            if match is None:
                continue
            vg_name, avail_size = match.groups()
            if megabyte_size <= int(avail_size):
                found_vg = vg_name
                break

        if not found_vg:
            LOG.error(_('Could not create logical volume. '
                        'No space left on any volume group.'))
            raise exception.PowerVMNoSpaceLeftOnVolumeGroup()

        cmd = self.command.mklv('%s %sB' % (found_vg, size / 512))
        lv_name = self.run_vios_command(cmd)[0]
        return lv_name

    def _remove_logical_volume(self, lv_name):
        """Removes the lv and the connection between its associated vscsi.

        :param lv_name: a logical volume name
        """
        cmd = self.command.rmvdev('-vdev %s -rmlv' % lv_name)
        self.run_vios_command(cmd)

    def _copy_file_to_device(self, source_path, device, decompress=True):
        """Copy file to device.

        :param source_path: path to input source file
        :param device: output device name
        :param decompress: if True (default) the file will be decompressed
                           on the fly while being copied to the drive
        """
        if decompress:
            cmd = ('gunzip -c %s | dd of=/dev/%s bs=1024k' %
                   (source_path, device))
        else:
            cmd = 'dd if=%s of=/dev/%s bs=1024k' % (source_path, device)
        self.run_vios_command_as_root(cmd)

    def _copy_image_file(self, source_path, remote_path, decompress=False):
        """Copy file to VIOS, decompress it, and return its new size and name.

        :param source_path: source file path
        :param remote_path remote file path
        :param decompress: if True, decompressess the file after copying;
                           if False (default), just copies the file
        """
        # Calculate source image checksum
        hasher = hashlib.md5()
        block_size = 0x10000
        img_file = file(source_path, 'r')
        buf = img_file.read(block_size)
        while len(buf) > 0:
            hasher.update(buf)
            buf = img_file.read(block_size)
        source_cksum = hasher.hexdigest()

        comp_path = os.path.join(remote_path, os.path.basename(source_path))
        uncomp_path = comp_path.rstrip(".gz")
        if not decompress:
            final_path = comp_path
        else:
            final_path = "%s.%s" % (uncomp_path, source_cksum)

        # Check whether the image is already on IVM
        output = self.run_vios_command("ls %s" % final_path,
                                       check_exit_code=False)

        # If the image does not exist already
        if not len(output):
            # Copy file to IVM
            common.ftp_put_command(self.connection_data, source_path,
                                   remote_path)

            # Verify image file checksums match
            cmd = ("/usr/bin/csum -h MD5 %s |"
                   "/usr/bin/awk '{print $1}'" % comp_path)
            output = self.run_vios_command_as_root(cmd)
            if not len(output):
                LOG.error(_("Unable to get checksum"))
                raise exception.PowerVMFileTransferFailed()
            if source_cksum != output[0]:
                LOG.error(_("Image checksums do not match"))
                raise exception.PowerVMFileTransferFailed()

            if decompress:
                # Unzip the image
                cmd = "/usr/bin/gunzip %s" % comp_path
                output = self.run_vios_command_as_root(cmd)

                # Remove existing image file
                cmd = "/usr/bin/rm -f %s.*" % uncomp_path
                output = self.run_vios_command_as_root(cmd)

                # Rename unzipped image
                cmd = "/usr/bin/mv %s %s" % (uncomp_path, final_path)
                output = self.run_vios_command_as_root(cmd)

                # Remove compressed image file
                cmd = "/usr/bin/rm -f %s" % comp_path
                output = self.run_vios_command_as_root(cmd)

        else:
            LOG.debug(_("Image found on host at '%s'") % final_path)

        # Calculate file size in multiples of 512 bytes
        output = self.run_vios_command("ls -o %s|awk '{print $4}'" %
                                  final_path, check_exit_code=False)
        if len(output):
            size = int(output[0])
        else:
            LOG.error(_("Uncompressed image file not found"))
            raise exception.PowerVMFileTransferFailed()
        if (size % 512 != 0):
            size = (int(size / 512) + 1) * 512

        return final_path, size

    def run_vios_command(self, cmd, check_exit_code=True):
        """Run a remote command using an active ssh connection.

        :param command: String with the command to run.
        """
        self._set_connection()
        stdout, stderr = utils.ssh_execute(self._connection, cmd,
                                           check_exit_code=check_exit_code)
        return stdout.strip().splitlines()

    def run_vios_command_as_root(self, command, check_exit_code=True):
        """Run a remote command as root using an active ssh connection.

        :param command: List of commands.
        """
        self._set_connection()
        stdout, stderr = common.ssh_command_as_root(
            self._connection, command, check_exit_code=check_exit_code)
        return stdout.read().splitlines()
