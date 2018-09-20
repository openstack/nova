# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
#
# Copyright 2011, Piston Cloud Computing, Inc.
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
"""
Utility methods to resize, repartition, and modify disk images.

Includes injection of SSH PGP keys into authorized_keys file.

"""

import os
import random
import tempfile

if os.name != 'nt':
    import crypt

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import units

import nova.conf
from nova import exception
from nova.i18n import _
from nova import utils
from nova.virt.disk.mount import api as mount
from nova.virt.disk.vfs import api as vfs
from nova.virt.image import model as imgmodel
from nova.virt import images


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

_MKFS_COMMAND = {}
_DEFAULT_MKFS_COMMAND = None

FS_FORMAT_EXT2 = "ext2"
FS_FORMAT_EXT3 = "ext3"
FS_FORMAT_EXT4 = "ext4"
FS_FORMAT_XFS = "xfs"
FS_FORMAT_NTFS = "ntfs"
FS_FORMAT_VFAT = "vfat"

SUPPORTED_FS_TO_EXTEND = (
    FS_FORMAT_EXT2,
    FS_FORMAT_EXT3,
    FS_FORMAT_EXT4)

_DEFAULT_FILE_SYSTEM = FS_FORMAT_VFAT
_DEFAULT_FS_BY_OSTYPE = {'linux': FS_FORMAT_EXT4,
                         'windows': FS_FORMAT_NTFS}

for s in CONF.virt_mkfs:
    # NOTE(yamahata): mkfs command may includes '=' for its options.
    #                 So item.partition('=') doesn't work here
    os_type, mkfs_command = s.split('=', 1)
    if os_type:
        _MKFS_COMMAND[os_type] = mkfs_command
    if os_type == 'default':
        _DEFAULT_MKFS_COMMAND = mkfs_command


def get_fs_type_for_os_type(os_type):
    return os_type if _MKFS_COMMAND.get(os_type) else 'default'


def get_file_extension_for_os_type(os_type, specified_fs=None):
    mkfs_command = _MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND)
    if mkfs_command:
        extension = mkfs_command
    else:
        if not specified_fs:
            specified_fs = CONF.default_ephemeral_format
            if not specified_fs:
                specified_fs = _DEFAULT_FS_BY_OSTYPE.get(os_type,
                                                         _DEFAULT_FILE_SYSTEM)
        extension = specified_fs
    return utils.get_hash_str(extension)[:7]


def mkfs(os_type, fs_label, target, run_as_root=True, specified_fs=None):
    """Format a file or block device using
       a user provided command for each os type.
       If user has not provided any configuration,
       format type will be used according to a
       default_ephemeral_format configuration
       or a system defaults.
    """

    mkfs_command = (_MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND) or
                    '') % {'fs_label': fs_label, 'target': target}
    if mkfs_command:
        utils.execute(*mkfs_command.split(), run_as_root=run_as_root)
    else:
        if not specified_fs:
            specified_fs = CONF.default_ephemeral_format
            if not specified_fs:
                specified_fs = _DEFAULT_FS_BY_OSTYPE.get(os_type,
                                                         _DEFAULT_FILE_SYSTEM)

        utils.mkfs(specified_fs, target, fs_label, run_as_root=run_as_root)


def resize2fs(image, check_exit_code=False, run_as_root=False):
    try:
        utils.execute('e2fsck',
                      '-fp',
                      image,
                      check_exit_code=[0, 1, 2],
                      run_as_root=run_as_root)
    except processutils.ProcessExecutionError as exc:
        LOG.debug("Checking the file system with e2fsck has failed, "
                  "the resize will be aborted. (%s)", exc)
    else:
        utils.execute('resize2fs',
                      image,
                      check_exit_code=check_exit_code,
                      run_as_root=run_as_root)


def get_disk_info(path):
    """Get QEMU info of a disk image

    :param path: Path to the disk image
    :returns: oslo_utils.imageutils.QemuImgInfo object for the image.
    """
    return images.qemu_img_info(path)


def get_disk_size(path):
    """Get the (virtual) size of a disk image

    :param path: Path to the disk image
    :returns: Size (in bytes) of the given disk image as it would be seen
              by a virtual machine.
    """
    return images.qemu_img_info(path).virtual_size


def get_allocated_disk_size(path):
    """Get the allocated size of a disk image

    :param path: Path to the disk image
    :returns: Size (in bytes) of the given disk image as allocated on the
              filesystem
    """
    return images.qemu_img_info(path).disk_size


def extend(image, size):
    """Increase image to size.

    :param image: instance of nova.virt.image.model.Image
    :param size: image size in bytes
    """

    # Currently can only resize FS in local images
    if not isinstance(image, imgmodel.LocalImage):
        return

    if (image.format == imgmodel.FORMAT_PLOOP):
        if not can_resize_image(image.path, size):
            return

        utils.execute('prl_disk_tool', 'resize',
                      '--size', '%dM' % (size // units.Mi),
                      '--resize_partition',
                      '--hdd', image.path, run_as_root=True)
        return

    if not can_resize_image(image.path, size):
        return

    utils.execute('qemu-img', 'resize', image.path, size)

    if (image.format != imgmodel.FORMAT_RAW and
        not CONF.resize_fs_using_block_device):
        return

    # if we can't access the filesystem, we can't do anything more
    if not is_image_extendable(image):
        return

    def safe_resize2fs(dev, run_as_root=False, finally_call=lambda: None):
        try:
            resize2fs(dev, run_as_root=run_as_root, check_exit_code=[0])
        except processutils.ProcessExecutionError as exc:
            LOG.debug("Resizing the file system with resize2fs "
                      "has failed with error: %s", exc)
        finally:
            finally_call()

    # NOTE(vish): attempts to resize filesystem
    if image.format != imgmodel.FORMAT_RAW:
        # in case of non-raw disks we can't just resize the image, but
        # rather the mounted device instead
        mounter = mount.Mount.instance_for_format(
            image, None, None)
        if mounter.get_dev():
            safe_resize2fs(mounter.device,
                           run_as_root=True,
                           finally_call=mounter.unget_dev)
    else:
        safe_resize2fs(image.path)


def can_resize_image(image, size):
    """Check whether we can resize the container image file.
    :param image: path to local image file
    :param size: the image size in bytes
    """
    LOG.debug('Checking if we can resize image %(image)s. '
              'size=%(size)s', {'image': image, 'size': size})

    # Check that we're increasing the size
    virt_size = get_disk_size(image)
    if virt_size >= size:
        LOG.debug('Cannot resize image %s to a smaller size.',
                  image)
        return False
    return True


def is_image_extendable(image):
    """Check whether we can extend the image."""
    LOG.debug('Checking if we can extend filesystem inside %(image)s.',
              {'image': image})

    # For anything except a local raw file we must
    # go via the VFS layer
    if (not isinstance(image, imgmodel.LocalImage) or
        image.format != imgmodel.FORMAT_RAW):
        fs = None
        try:
            fs = vfs.VFS.instance_for_image(image, None)
            fs.setup(mount=False)
            if fs.get_image_fs() in SUPPORTED_FS_TO_EXTEND:
                return True
        except exception.NovaException as e:
            # FIXME(sahid): At this step we probably want to break the
            # process if something wrong happens however our CI
            # provides a bad configuration for libguestfs reported in
            # the bug lp#1413142. When resolved we should remove this
            # except to let the error to be propagated.
            LOG.warning('Unable to mount image %(image)s with '
                        'error %(error)s. Cannot resize.',
                        {'image': image, 'error': e})
        finally:
            if fs is not None:
                fs.teardown()

        return False
    else:
        # For raw, we can directly inspect the file system
        try:
            utils.execute('e2label', image.path)
        except processutils.ProcessExecutionError as e:
            LOG.debug('Unable to determine label for image %(image)s with '
                      'error %(error)s. Cannot resize.',
                      {'image': image,
                       'error': e})
            return False

    return True


class _DiskImage(object):
    """Provide operations on a disk image file."""

    tmp_prefix = 'openstack-disk-mount-tmp'

    def __init__(self, image, partition=None, mount_dir=None):
        """Create a new _DiskImage object instance

        :param image: instance of nova.virt.image.model.Image
        :param partition: the partition number within the image
        :param mount_dir: the directory to mount the image on
        """

        # These passed to each mounter
        self.partition = partition
        self.mount_dir = mount_dir
        self.image = image

        # Internal
        self._mkdir = False
        self._mounter = None
        self._errors = []

        if mount_dir:
            device = self._device_for_path(mount_dir)
            if device:
                self._reset(device)
            else:
                LOG.debug('No device found for path: %s', mount_dir)

    @staticmethod
    def _device_for_path(path):
        device = None
        path = os.path.realpath(path)
        with open("/proc/mounts", 'r') as ifp:
            for line in ifp:
                fields = line.split()
                if fields[1] == path:
                    device = fields[0]
                    break
        return device

    def _reset(self, device):
        """Reset internal state for a previously mounted directory."""
        self._mounter = mount.Mount.instance_for_device(self.image,
                                                        self.mount_dir,
                                                        self.partition,
                                                        device)

        mount_name = os.path.basename(self.mount_dir or '')
        self._mkdir = mount_name.startswith(self.tmp_prefix)

    @property
    def errors(self):
        """Return the collated errors from all operations."""
        return '\n--\n'.join([''] + self._errors)

    def mount(self):
        """Mount a disk image, using the object attributes.

        The first supported means provided by the mount classes is used.

        True, or False is returned and the 'errors' attribute
        contains any diagnostics.
        """
        if self._mounter:
            raise exception.NovaException(_('image already mounted'))

        if not self.mount_dir:
            self.mount_dir = tempfile.mkdtemp(prefix=self.tmp_prefix)
            self._mkdir = True

        mounter = mount.Mount.instance_for_format(self.image,
                                                  self.mount_dir,
                                                  self.partition)

        if mounter.do_mount():
            self._mounter = mounter
            return self._mounter.device
        else:
            LOG.debug(mounter.error)
            self._errors.append(mounter.error)
            return None

    def umount(self):
        """Umount a mount point from the filesystem."""
        if self._mounter:
            self._mounter.do_umount()
            self._mounter = None

    def teardown(self):
        """Remove a disk image from the file system."""
        try:
            if self._mounter:
                self._mounter.do_teardown()
                self._mounter = None
        finally:
            if self._mkdir:
                os.rmdir(self.mount_dir)


# Public module functions

def inject_data(image, key=None, net=None, metadata=None, admin_password=None,
                files=None, partition=None, mandatory=()):
    """Inject the specified items into a disk image.

    :param image: instance of nova.virt.image.model.Image
    :param key: the SSH public key to inject
    :param net: the network configuration to inject
    :param metadata: the user metadata to inject
    :param admin_password: the root password to set
    :param files: the files to copy into the image
    :param partition: the partition number to access
    :param mandatory: the list of parameters which must not fail to inject

    If an item name is not specified in the MANDATORY iterable, then a warning
    is logged on failure to inject that item, rather than raising an exception.

    it will mount the image as a fully partitioned disk and attempt to inject
    into the specified partition number.

    If PARTITION is not specified the image is mounted as a single partition.

    Returns True if all requested operations completed without issue.
    Raises an exception if a mandatory item can't be injected.
    """
    items = {'image': image, 'key': key, 'net': net, 'metadata': metadata,
             'files': files, 'partition': partition}
    LOG.debug("Inject data image=%(image)s key=%(key)s net=%(net)s "
              "metadata=%(metadata)s admin_password=<SANITIZED> "
              "files=%(files)s partition=%(partition)s", items)
    try:
        fs = vfs.VFS.instance_for_image(image, partition)
        fs.setup()
    except Exception as e:
        # If a mandatory item is passed to this function,
        # then reraise the exception to indicate the error.
        for inject in mandatory:
            inject_val = items[inject]
            if inject_val:
                raise
        LOG.warning('Ignoring error injecting data into image %(image)s '
                    '(%(e)s)', {'image': image, 'e': e})
        return False

    try:
        return inject_data_into_fs(fs, key, net, metadata, admin_password,
                                   files, mandatory)
    finally:
        fs.teardown()


def setup_container(image, container_dir):
    """Setup the LXC container.

    :param image: instance of nova.virt.image.model.Image
    :param container_dir: directory to mount the image at

    It will mount the loopback image to the container directory in order
    to create the root filesystem for the container.

    Returns path of image device which is mounted to the container directory.
    """
    img = _DiskImage(image=image, mount_dir=container_dir)
    dev = img.mount()
    if dev is None:
        LOG.error("Failed to mount container filesystem '%(image)s' "
                  "on '%(target)s': %(errors)s",
                  {"image": img, "target": container_dir,
                   "errors": img.errors})
        raise exception.NovaException(img.errors)

    return dev


def teardown_container(container_dir, container_root_device=None):
    """Teardown the container rootfs mounting once it is spawned.

    It will umount the container that is mounted,
    and delete any linked devices.
    """
    try:
        img = _DiskImage(image=None, mount_dir=container_dir)
        img.teardown()

        # Make sure container_root_device is released when teardown container.
        if container_root_device:
            if 'loop' in container_root_device:
                LOG.debug("Release loop device %s", container_root_device)
                utils.execute('losetup', '--detach', container_root_device,
                              run_as_root=True, attempts=3)
            elif 'nbd' in container_root_device:
                LOG.debug('Release nbd device %s', container_root_device)
                utils.execute('qemu-nbd', '-d', container_root_device,
                              run_as_root=True)
            else:
                LOG.debug('No release necessary for block device %s',
                          container_root_device)
    except Exception:
        LOG.exception(_('Failed to teardown container filesystem'))


def clean_lxc_namespace(container_dir):
    """Clean up the container namespace rootfs mounting one spawned.

    It will umount the mounted names that are mounted
    but leave the linked devices alone.
    """
    try:
        img = _DiskImage(image=None, mount_dir=container_dir)
        img.umount()
    except Exception:
        LOG.exception(_('Failed to umount container filesystem'))


def inject_data_into_fs(fs, key, net, metadata, admin_password, files,
                        mandatory=()):
    """Injects data into a filesystem already mounted by the caller.
    Virt connections can call this directly if they mount their fs
    in a different way to inject_data.

    If an item name is not specified in the MANDATORY iterable, then a warning
    is logged on failure to inject that item, rather than raising an exception.

    Returns True if all requested operations completed without issue.
    Raises an exception if a mandatory item can't be injected.
    """
    items = {'key': key, 'net': net, 'metadata': metadata,
             'admin_password': admin_password, 'files': files}
    functions = {
        'key': _inject_key_into_fs,
        'net': _inject_net_into_fs,
        'metadata': _inject_metadata_into_fs,
        'admin_password': _inject_admin_password_into_fs,
        'files': _inject_files_into_fs,
    }
    status = True
    for inject, inject_val in items.items():
        if inject_val:
            try:
                inject_func = functions[inject]
                inject_func(inject_val, fs)
            except Exception as e:
                if inject in mandatory:
                    raise
                LOG.warning('Ignoring error injecting %(inject)s into '
                            'image (%(e)s)', {'inject': inject, 'e': e})
                status = False
    return status


def _inject_files_into_fs(files, fs):
    for (path, contents) in files:
        # NOTE(wangpan): Ensure the parent dir of injecting file exists
        parent_dir = os.path.dirname(path)
        if (len(parent_dir) > 0 and parent_dir != "/"
                and not fs.has_file(parent_dir)):
            fs.make_path(parent_dir)
            fs.set_ownership(parent_dir, "root", "root")
            fs.set_permissions(parent_dir, 0o744)
        _inject_file_into_fs(fs, path, contents)


def _inject_file_into_fs(fs, path, contents, append=False):
    LOG.debug("Inject file fs=%(fs)s path=%(path)s append=%(append)s",
              {'fs': fs, 'path': path, 'append': append})
    if append:
        fs.append_file(path, contents)
    else:
        fs.replace_file(path, contents)


def _inject_metadata_into_fs(metadata, fs):
    LOG.debug("Inject metadata fs=%(fs)s metadata=%(metadata)s",
              {'fs': fs, 'metadata': metadata})
    _inject_file_into_fs(fs, 'meta.js', jsonutils.dumps(metadata))


def _setup_selinux_for_keys(fs, sshdir):
    """Get selinux guests to ensure correct context on injected keys."""

    if not fs.has_file(os.path.join("etc", "selinux")):
        return

    rclocal = os.path.join('etc', 'rc.local')
    rc_d = os.path.join('etc', 'rc.d')

    if not fs.has_file(rclocal) and fs.has_file(rc_d):
        rclocal = os.path.join(rc_d, 'rc.local')

    # Note some systems end rc.local with "exit 0"
    # and so to append there you'd need something like:
    #  utils.execute('sed', '-i', '${/^exit 0$/d}' rclocal, run_as_root=True)
    restorecon = [
        '\n',
        '# Added by Nova to ensure injected ssh keys have the right context\n',
        'restorecon -RF %s 2>/dev/null || :\n' % sshdir,
    ]

    if not fs.has_file(rclocal):
        restorecon.insert(0, '#!/bin/sh')

    _inject_file_into_fs(fs, rclocal, ''.join(restorecon), append=True)
    fs.set_permissions(rclocal, 0o700)


def _inject_key_into_fs(key, fs):
    """Add the given public ssh key to root's authorized_keys.

    key is an ssh key string.
    fs is the path to the base of the filesystem into which to inject the key.
    """

    LOG.debug("Inject key fs=%(fs)s key=%(key)s", {'fs': fs, 'key': key})
    sshdir = os.path.join('root', '.ssh')
    fs.make_path(sshdir)
    fs.set_ownership(sshdir, "root", "root")
    fs.set_permissions(sshdir, 0o700)

    keyfile = os.path.join(sshdir, 'authorized_keys')

    key_data = ''.join([
        '\n',
        '# The following ssh key was injected by Nova',
        '\n',
        key.strip(),
        '\n',
    ])

    _inject_file_into_fs(fs, keyfile, key_data, append=True)
    fs.set_permissions(keyfile, 0o600)

    _setup_selinux_for_keys(fs, sshdir)


def _inject_net_into_fs(net, fs):
    """Inject /etc/network/interfaces into the filesystem rooted at fs.

    net is the contents of /etc/network/interfaces.
    """

    LOG.debug("Inject key fs=%(fs)s net=%(net)s", {'fs': fs, 'net': net})
    netdir = os.path.join('etc', 'network')
    fs.make_path(netdir)
    fs.set_ownership(netdir, "root", "root")
    fs.set_permissions(netdir, 0o744)

    netfile = os.path.join('etc', 'network', 'interfaces')
    _inject_file_into_fs(fs, netfile, net)


def _inject_admin_password_into_fs(admin_passwd, fs):
    """Set the root password to admin_passwd

    admin_password is a root password
    fs is the path to the base of the filesystem into which to inject
    the key.

    This method modifies the instance filesystem directly,
    and does not require a guest agent running in the instance.

    """
    # The approach used here is to copy the password and shadow
    # files from the instance filesystem to local files, make any
    # necessary changes, and then copy them back.

    LOG.debug("Inject admin password fs=%(fs)s "
              "admin_passwd=<SANITIZED>", {'fs': fs})
    admin_user = 'root'

    passwd_path = os.path.join('etc', 'passwd')
    shadow_path = os.path.join('etc', 'shadow')

    passwd_data = fs.read_file(passwd_path)
    shadow_data = fs.read_file(shadow_path)

    new_shadow_data = _set_passwd(admin_user, admin_passwd,
                                  passwd_data, shadow_data)

    fs.replace_file(shadow_path, new_shadow_data)


def _generate_salt():
    salt_set = ('abcdefghijklmnopqrstuvwxyz'
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                '0123456789./')
    salt = 16 * ' '
    return ''.join([random.choice(salt_set) for c in salt])


def _set_passwd(username, admin_passwd, passwd_data, shadow_data):
    """set the password for username to admin_passwd

    The passwd_file is not modified.  The shadow_file is updated.
    if the username is not found in both files, an exception is raised.

    :param username: the username
    :param admin_passwd: the admin password
    :param passwd_data: path to the passwd file
    :param shadow_data: path to the shadow password file
    :returns: nothing
    :raises: exception.NovaException(), IOError()

    """
    if os.name == 'nt':
        raise exception.NovaException(_('Not implemented on Windows'))

    # encryption algo - id pairs for crypt()
    algos = {'SHA-512': '$6$', 'SHA-256': '$5$', 'MD5': '$1$', 'DES': ''}

    salt = _generate_salt()

    # crypt() depends on the underlying libc, and may not support all
    # forms of hash. We try md5 first. If we get only 13 characters back,
    # then the underlying crypt() didn't understand the '$n$salt' magic,
    # so we fall back to DES.
    # md5 is the default because it's widely supported. Although the
    # local crypt() might support stronger SHA, the target instance
    # might not.
    encrypted_passwd = crypt.crypt(admin_passwd, algos['MD5'] + salt)
    if len(encrypted_passwd) == 13:
        encrypted_passwd = crypt.crypt(admin_passwd, algos['DES'] + salt)

    p_file = passwd_data.split("\n")
    s_file = shadow_data.split("\n")

    # username MUST exist in passwd file or it's an error
    for entry in p_file:
        split_entry = entry.split(':')
        if split_entry[0] == username:
            break
    else:
        msg = _('User %(username)s not found in password file.')
        raise exception.NovaException(msg % username)

    # update password in the shadow file. It's an error if the
    # user doesn't exist.
    new_shadow = list()
    found = False
    for entry in s_file:
        split_entry = entry.split(':')
        if split_entry[0] == username:
            split_entry[1] = encrypted_passwd
            found = True
        new_entry = ':'.join(split_entry)
        new_shadow.append(new_entry)

    if not found:
        msg = _('User %(username)s not found in shadow file.')
        raise exception.NovaException(msg % username)

    return "\n".join(new_shadow)
