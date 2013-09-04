# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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
import time

from oslo.config import cfg

from nova.compute import flavors
from nova.compute import task_states
from nova.image import glance
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova.virt import images
from nova.virt.powervm import command
from nova.virt.powervm import common
from nova.virt.powervm import constants
from nova.virt.powervm import exception

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class PowerVMDiskAdapter(object):
    """PowerVM disk adapter interface
    Provides a contract to implement multiple ways to generate
    and attach volumes to virtual machines using local and/or
    external storage
    """

    def create_volume(self, size):
        """Creates a volume with a minimum size

        :param size: size of the volume in bytes
        :returns: string -- the name of the disk device.
      """
        pass

    def delete_volume(self, volume_info):
        """Removes the disk and its associated vSCSI connection

        :param volume_info: dictionary with volume info including name of
        disk device in /dev/
        """
        pass

    def create_volume_from_image(self, context, instance, image_id):
        """Creates a Volume and copies the specified image to it

        :param context: nova context used to retrieve image from glance
        :param instance: instance to create the volume for
        :param image_id: image_id reference used to locate image in glance
        :returns: dictionary with the name of the created
                  disk device in 'device_name' key
        """
        pass

    def create_image_from_volume(self, device_name, context,
                                 image_id, image_meta, update_task_state):
        """Capture the contents of a volume and upload to glance

        :param device_name: device in /dev/ to capture
        :param context: nova context for operation
        :param image_id: image reference to pre-created image in glance
        :param image_meta: metadata for new image
        :param update_task_state: Function reference that allows for updates
                                  to the instance task state
        """
        pass

    def migrate_volume(self, lv_name, src_host, dest, image_path,
            instance_name=None):
        """Copy a logical volume to file, compress, and transfer

        :param lv_name: volume device name
        :param src_host: source IP or DNS name.
        :param dest: destination IP or DNS name
        :param image_path: path to remote image storage directory
        :param instance_name: name of instance that is being migrated
        :returns: file path on destination of image file that was moved
        """
        pass

    def attach_volume_to_host(self, *args, **kargs):
        """
        Attaches volume to host using info passed in *args and **kargs
        """
        pass

    def detach_volume_from_host(self, *args, **kargs):
        """
        Detaches volume from host using info passed in *args and **kargs
        """
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
        # create a new connection or verify an existing connection
        # and re-establish if the existing connection is dead
        self._connection = common.check_connection(self._connection,
                                                   self.connection_data)

    def create_volume(self, size):
        """Creates a logical volume with a minimum size

        :param size: size of the logical volume in bytes
        :returns: string -- the name of the new logical volume.
        :raises: PowerVMNoSpaceLeftOnVolumeGroup
        """
        return self._create_logical_volume(size)

    def delete_volume(self, volume_info):
        """Removes the Logical Volume and its associated vSCSI connection

        :param volume_info: Dictionary with volume info including name of
        Logical Volume device in /dev/ via device_name key
        """
        disk_name = volume_info["device_name"]
        LOG.debug(_("Removing the logical volume '%s'") % disk_name)
        self._remove_logical_volume(disk_name)

    def create_volume_from_image(self, context, instance, image_id):
        """Creates a Logical Volume and copies the specified image to it

        :param context: nova context used to retrieve image from glance
        :param instance: instance to create the volume for
        :param image_id: image_id reference used to locate image in glance
        :returns: dictionary with the name of the created
                  Logical Volume device in 'device_name' key
        """

        file_name = '.'.join([image_id, 'gz'])
        file_path = os.path.join(CONF.powervm_img_local_path,
                                 file_name)

        if not os.path.isfile(file_path):
            LOG.debug(_("Fetching image '%s' from glance") % image_id)
            images.fetch(context, image_id, file_path,
                        instance['user_id'],
                        instance['project_id'])
        else:
            LOG.debug((_("Using image found at '%s'") % file_path))

        LOG.debug(_("Ensuring image '%s' exists on IVM") % file_path)
        remote_path = CONF.powervm_img_remote_path
        remote_file_name, size = self._copy_image_file(file_path, remote_path)

        # calculate root device size in bytes
        # we respect the minimum root device size in constants
        instance_type = flavors.extract_flavor(instance)
        size_gb = max(instance_type['root_gb'], constants.POWERVM_MIN_ROOT_GB)
        size = size_gb * 1024 * 1024 * 1024

        disk_name = None
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
                if disk_name is not None:
                    try:
                        self.delete_volume(disk_name)
                    except Exception:
                        msg = _('Error while attempting cleanup of failed '
                                'deploy to logical volume.')
                        LOG.exception(msg)

        return {'device_name': disk_name}

    def create_image_from_volume(self, device_name, context,
                                 image_id, image_meta, update_task_state):
        """Capture the contents of a volume and upload to glance

        :param device_name: device in /dev/ to capture
        :param context: nova context for operation
        :param image_id: image reference to pre-created image in glance
        :param image_meta: metadata for new image
        :param update_task_state: Function reference that allows for updates
                                  to the instance task state.
        """
        # Updating instance task state before capturing instance as a file
        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

        # do the disk copy
        dest_file_path = common.aix_path_join(CONF.powervm_img_remote_path,
                                                 image_id)
        self._copy_device_to_file(device_name, dest_file_path)

        # compress and copy the file back to the nova-compute host
        snapshot_file_path = self._copy_image_file_from_host(
                dest_file_path, CONF.powervm_img_local_path,
                compress=True)

        # get glance service
        glance_service, image_id = glance.get_remote_image_service(
                context, image_id)

        # Updating instance task state before uploading image
        # Snapshot will complete but instance state will not change
        # to none in compute manager if expected state is not correct
        update_task_state(task_state=task_states.IMAGE_UPLOADING,
                     expected_state=task_states.IMAGE_PENDING_UPLOAD)

        # upload snapshot file to glance
        with open(snapshot_file_path, 'r') as img_file:
            glance_service.update(context,
                                  image_id,
                                  image_meta,
                                  img_file)
            LOG.debug(_("Snapshot added to glance."))

        # clean up local image file
        try:
            os.remove(snapshot_file_path)
        except OSError:
            LOG.warn(_("Failed to clean up snapshot file %s"),
                     snapshot_file_path)

    def migrate_volume(self, lv_name, src_host, dest, image_path,
            instance_name=None):
        """Copy a logical volume to file, compress, and transfer

        :param lv_name: logical volume device name
        :param dest: destination IP or DNS name
        :param image_path: path to remote image storage directory
        :param instance_name: name of instance that is being migrated
        :returns: file path on destination of image file that was moved
        """
        if instance_name:
            file_name = ''.join([instance_name, '_rsz'])
        else:
            file_name = ''.join([lv_name, '_rsz'])
        file_path = os.path.join(image_path, file_name)
        self._copy_device_to_file(lv_name, file_path)
        cmds = 'gzip %s' % file_path
        self.run_vios_command_as_root(cmds)
        file_path = file_path + '.gz'
        # If destination is not same host
        # transfer file to destination VIOS system
        if (src_host != dest):
            with common.vios_to_vios_auth(self.connection_data.host,
                                          dest,
                                          self.connection_data) as key_name:
                cmd = ' '.join(['scp -o "StrictHostKeyChecking no"',
                                ('-i %s' % key_name),
                                file_path,
                                '%s@%s:%s' % (self.connection_data.username,
                                              dest,
                                              image_path)
                                ])
                # do the remote copy
                self.run_vios_command(cmd)

            # cleanup local file only if transferring to remote system
            # otherwise keep the file to boot from locally and clean up later
            cleanup_cmd = 'rm %s' % file_path
            self.run_vios_command_as_root(cleanup_cmd)

        return file_path

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

    def _copy_device_to_file(self, device_name, file_path):
        """Copy a device to a file using dd

        :param device_name: device name to copy from
        :param file_path: output file path
        """
        cmd = 'dd if=/dev/%s of=%s bs=1024k' % (device_name, file_path)
        self.run_vios_command_as_root(cmd)

    def _md5sum_remote_file(self, remote_path):
        # AIX6/VIOS cannot md5sum files with sizes greater than ~2GB
        cmd = ("perl -MDigest::MD5 -e 'my $file = \"%s\"; open(FILE, $file); "
               "binmode(FILE); "
               "print Digest::MD5->new->addfile(*FILE)->hexdigest, "
               "\" $file\n\";'" % remote_path)

        output = self.run_vios_command_as_root(cmd)
        return output[0]

    def _checksum_local_file(self, source_path):
        """Calculate local file checksum.

        :param source_path: source file path
        :returns: string -- the md5sum of local file
        """
        with open(source_path, 'r') as img_file:
            hasher = hashlib.md5()
            block_size = 0x10000
            buf = img_file.read(block_size)
            while len(buf) > 0:
                hasher.update(buf)
                buf = img_file.read(block_size)
                # this can take awhile so yield so other threads get some time
                time.sleep(0)
            source_cksum = hasher.hexdigest()
        return source_cksum

    def _copy_image_file(self, source_path, remote_path, decompress=False):
        """Copy file to VIOS, decompress it, and return its new size and name.

        :param source_path: source file path
        :param remote_path remote file path
        :param decompress: if True, decompressess the file after copying;
                           if False (default), just copies the file
        """
        # Calculate source image checksum
        source_cksum = self._checksum_local_file(source_path)

        comp_path = os.path.join(remote_path, os.path.basename(source_path))
        if comp_path.endswith(".gz"):
            uncomp_path = os.path.splitext(comp_path)[0]
        else:
            uncomp_path = comp_path
        if not decompress:
            final_path = comp_path
        else:
            final_path = uncomp_path

        # Check whether the image is already on IVM
        output = self.run_vios_command("ls %s" % final_path,
                                       check_exit_code=False)

        # If the image does not exist already
        if not output:
            try:
                # Copy file to IVM
                common.ftp_put_command(self.connection_data, source_path,
                                       remote_path)
            except exception.PowerVMFTPTransferFailed:
                with excutils.save_and_reraise_exception():
                    cmd = "/usr/bin/rm -f %s" % final_path
                    self.run_vios_command_as_root(cmd)

            # Verify image file checksums match
            output = self._md5sum_remote_file(final_path)
            if not output:
                LOG.error(_("Unable to get checksum"))
                # Cleanup inconsistent remote file
                cmd = "/usr/bin/rm -f %s" % final_path
                self.run_vios_command_as_root(cmd)

                raise exception.PowerVMFileTransferFailed(file_path=final_path)
            if source_cksum != output.split(' ')[0]:
                LOG.error(_("Image checksums do not match"))
                # Cleanup inconsistent remote file
                cmd = "/usr/bin/rm -f %s" % final_path
                self.run_vios_command_as_root(cmd)

                raise exception.PowerVMFileTransferFailed(file_path=final_path)

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
        if output:
            size = int(output[0])
        else:
            LOG.error(_("Uncompressed image file not found"))
            raise exception.PowerVMFileTransferFailed()
        if (size % 512 != 0):
            size = (int(size / 512) + 1) * 512

        return final_path, size

    def _copy_image_file_from_host(self, remote_source_path, local_dest_dir,
                                   compress=False):
        """
        Copy a file from IVM to the nova-compute host,
        and return the location of the copy

        :param remote_source_path remote source file path
        :param local_dest_dir local destination directory
        :param compress: if True, compress the file before transfer;
                         if False (default), copy the file as is
        """

        temp_str = common.aix_path_join(local_dest_dir,
                                        os.path.basename(remote_source_path))
        local_file_path = temp_str + '.gz'

        if compress:
            copy_from_path = remote_source_path + '.gz'
        else:
            copy_from_path = remote_source_path

        if compress:
            # Gzip the file
            cmd = "/usr/bin/gzip %s" % remote_source_path
            self.run_vios_command_as_root(cmd)

            # Cleanup uncompressed remote file
            cmd = "/usr/bin/rm -f %s" % remote_source_path
            self.run_vios_command_as_root(cmd)

        # Get file checksum
        output = self._md5sum_remote_file(copy_from_path)
        if not output:
            LOG.error(_("Unable to get checksum"))
            msg_args = {'file_path': copy_from_path}
            raise exception.PowerVMFileTransferFailed(**msg_args)
        else:
            source_chksum = output.split(' ')[0]

        # Copy file to host
        common.ftp_get_command(self.connection_data,
                               copy_from_path,
                               local_file_path)

        # Calculate copied image checksum
        dest_chksum = self._checksum_local_file(local_file_path)

        # do comparison
        if source_chksum and dest_chksum != source_chksum:
            LOG.error(_("Image checksums do not match"))
            raise exception.PowerVMFileTransferFailed(
                                      file_path=local_file_path)

        # Cleanup transferred remote file
        cmd = "/usr/bin/rm -f %s" % copy_from_path
        output = self.run_vios_command_as_root(cmd)

        return local_file_path

    def run_vios_command(self, cmd, check_exit_code=True):
        """Run a remote command using an active ssh connection.

        :param command: String with the command to run.
        """
        self._set_connection()
        stdout, stderr = processutils.ssh_execute(
            self._connection, cmd, check_exit_code=check_exit_code)

        error_text = stderr.strip()
        if error_text:
            LOG.warn(_("Found error stream for command \"%(cmd)s\": "
                        "%(error_text)s"),
                      {'cmd': cmd, 'error_text': error_text})

        return stdout.strip().splitlines()

    def run_vios_command_as_root(self, command, check_exit_code=True):
        """Run a remote command as root using an active ssh connection.

        :param command: List of commands.
        """
        self._set_connection()
        stdout, stderr = common.ssh_command_as_root(
            self._connection, command, check_exit_code=check_exit_code)

        error_text = stderr.read()
        if error_text:
            LOG.warn(_("Found error stream for command \"%(command)s\":"
                        " %(error_text)s"),
                      {'command': command, 'error_text': error_text})

        return stdout.read().splitlines()
