# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova import paths
from nova import utils
from nova.virt.disk.mount import api as mount
from nova.virt.disk.vfs import api as vfs
from nova.virt import images


LOG = logging.getLogger(__name__)

disk_opts = [
    cfg.StrOpt('injected_network_template',
               default=paths.basedir_def('nova/virt/interfaces.template'),
               help='Template file for injected network'),

    # NOTE(yamahata): ListOpt won't work because the command may include a
    #                 comma. For example:
    #
    #                 mkfs.ext3 -O dir_index,extent -E stride=8,stripe-width=16
    #                           --label %(fs_label)s %(target)s
    #
    #                 list arguments are comma separated and there is no way to
    #                 escape such commas.
    #
    cfg.MultiStrOpt('virt_mkfs',
                    default=[
                      'default=mkfs.ext3 -L %(fs_label)s -F %(target)s',
                      'linux=mkfs.ext3 -L %(fs_label)s -F %(target)s',
                      'windows=mkfs.ntfs'
                      ' --force --fast --label %(fs_label)s %(target)s',
                      # NOTE(yamahata): vfat case
                      #'windows=mkfs.vfat -n %(fs_label)s %(target)s',
                      ],
                    help='mkfs commands for ephemeral device. '
                         'The format is <os_type>=<mkfs command>'),

    cfg.BoolOpt('resize_fs_using_block_device',
                default=False,
                help='Attempt to resize the filesystem by accessing the '
                     'image over a block device. This is done by the host '
                     'and may not be necessary if the image contains a recent '
                     'version of cloud-init. Possible mechanisms require '
                     'the nbd driver (for qcow and raw), or loop (for raw).'),
    ]

CONF = cfg.CONF
CONF.register_opts(disk_opts)

_MKFS_COMMAND = {}
_DEFAULT_MKFS_COMMAND = None


for s in CONF.virt_mkfs:
    # NOTE(yamahata): mkfs command may includes '=' for its options.
    #                 So item.partition('=') doesn't work here
    os_type, mkfs_command = s.split('=', 1)
    if os_type:
        _MKFS_COMMAND[os_type] = mkfs_command
    if os_type == 'default':
        _DEFAULT_MKFS_COMMAND = mkfs_command


def mkfs(os_type, fs_label, target):
    mkfs_command = (_MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND) or
                    '') % {'fs_label': fs_label, 'target': target}
    if mkfs_command:
        utils.execute(*mkfs_command.split(), run_as_root=True)


def resize2fs(image, check_exit_code=False, run_as_root=False):
    utils.execute('e2fsck', '-fp', image,
                  check_exit_code=check_exit_code,
                  run_as_root=run_as_root)
    utils.execute('resize2fs', image,
                  check_exit_code=check_exit_code,
                  run_as_root=run_as_root)


def get_disk_size(path):
    """Get the (virtual) size of a disk image

    :param path: Path to the disk image
    :returns: Size (in bytes) of the given disk image as it would be seen
              by a virtual machine.
    """
    return images.qemu_img_info(path).virtual_size


def extend(image, size, use_cow=False):
    """Increase image to size."""
    if not can_resize_image(image, size):
        return

    utils.execute('qemu-img', 'resize', image, size)

    # if we can't access the filesystem, we can't do anything more
    if not is_image_partitionless(image, use_cow):
        return

    # NOTE(vish): attempts to resize filesystem
    if use_cow:
        if CONF.resize_fs_using_block_device:
            # in case of non-raw disks we can't just resize the image, but
            # rather the mounted device instead
            mounter = mount.Mount.instance_for_format(image, None, None,
                                                      'qcow2')
            if mounter.get_dev():
                resize2fs(mounter.device, run_as_root=True)
                mounter.unget_dev()
    else:
        resize2fs(image)


def can_resize_image(image, size):
    """Check whether we can resize the container image file."""
    LOG.debug(_('Checking if we can resize image %(image)s. '
                'size=%(size)s'), {'image': image, 'size': size})

    # Check that we're increasing the size
    virt_size = get_disk_size(image)
    if virt_size >= size:
        LOG.debug(_('Cannot resize image %s to a smaller size.'),
                  image)
        return False
    return True


def is_image_partitionless(image, use_cow=False):
    """Check whether we can resize contained file system."""
    LOG.debug(_('Checking if we can resize filesystem inside %(image)s. '
                'CoW=%(use_cow)s'), {'image': image, 'use_cow': use_cow})

    # Check the image is unpartitioned
    if use_cow:
        try:
            fs = vfs.VFS.instance_for_image(image, 'qcow2', None)
            fs.setup()
            fs.teardown()
        except exception.NovaException as e:
            LOG.debug(_('Unable to mount image %(image)s with '
                        'error %(error)s. Cannot resize.'),
                      {'image': image,
                       'error': e})
            return False
    else:
        # For raw, we can directly inspect the file system
        try:
            utils.execute('e2label', image)
        except processutils.ProcessExecutionError as e:
            LOG.debug(_('Unable to determine label for image %(image)s with '
                        'error %(error)s. Cannot resize.'),
                      {'image': image,
                       'error': e})
            return False

    return True


class _DiskImage(object):
    """Provide operations on a disk image file."""

    tmp_prefix = 'openstack-disk-mount-tmp'

    def __init__(self, image, partition=None, use_cow=False, mount_dir=None):
        # These passed to each mounter
        self.image = image
        self.partition = partition
        self.mount_dir = mount_dir
        self.use_cow = use_cow

        # Internal
        self._mkdir = False
        self._mounter = None
        self._errors = []

        if mount_dir:
            device = self._device_for_path(mount_dir)
            if device:
                self._reset(device)

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

        imgfmt = "raw"
        if self.use_cow:
            imgfmt = "qcow2"

        mounter = mount.Mount.instance_for_format(self.image,
                                                  self.mount_dir,
                                                  self.partition,
                                                  imgfmt)
        if mounter.do_mount():
            self._mounter = mounter
        else:
            LOG.debug(mounter.error)
            self._errors.append(mounter.error)

        return bool(self._mounter)

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
                files=None, partition=None, use_cow=False, mandatory=()):
    """Inject the specified items into a disk image.

    If an item name is not specified in the MANDATORY iterable, then a warning
    is logged on failure to inject that item, rather than raising an exception.

    it will mount the image as a fully partitioned disk and attempt to inject
    into the specified partition number.

    If PARTITION is not specified the image is mounted as a single partition.

    Returns True if all requested operations completed without issue.
    Raises an exception if a mandatory item can't be injected.
    """
    LOG.debug(_("Inject data image=%(image)s key=%(key)s net=%(net)s "
                "metadata=%(metadata)s admin_password=<SANITIZED> "
                "files=%(files)s partition=%(partition)s use_cow=%(use_cow)s"),
              {'image': image, 'key': key, 'net': net, 'metadata': metadata,
               'files': files, 'partition': partition, 'use_cow': use_cow})
    fmt = "raw"
    if use_cow:
        fmt = "qcow2"
    try:
        # Note(mrda): Test if the image exists first to short circuit errors
        os.stat(image)
        fs = vfs.VFS.instance_for_image(image, fmt, partition)
        fs.setup()
    except Exception as e:
        # If a mandatory item is passed to this function,
        # then reraise the exception to indicate the error.
        for inject in mandatory:
            inject_val = locals()[inject]
            if inject_val:
                raise
        LOG.warn(_('Ignoring error injecting data into image '
                   '(%(e)s)'), {'e': e})
        return False

    try:
        return inject_data_into_fs(fs, key, net, metadata,
                                   admin_password, files, mandatory)
    finally:
        fs.teardown()


def setup_container(image, container_dir, use_cow=False):
    """Setup the LXC container.

    It will mount the loopback image to the container directory in order
    to create the root filesystem for the container.
    """
    img = _DiskImage(image=image, use_cow=use_cow, mount_dir=container_dir)
    if not img.mount():
        LOG.error(_("Failed to mount container filesystem '%(image)s' "
                    "on '%(target)s': %(errors)s"),
                  {"image": img, "target": container_dir,
                   "errors": img.errors})
        raise exception.NovaException(img.errors)


def teardown_container(container_dir):
    """Teardown the container rootfs mounting once it is spawned.

    It will umount the container that is mounted,
    and delete any linked devices.
    """
    try:
        img = _DiskImage(image=None, mount_dir=container_dir)
        img.teardown()
    except Exception as exn:
        LOG.exception(_('Failed to teardown ntainer filesystem: %s'), exn)


def clean_lxc_namespace(container_dir):
    """Clean up the container namespace rootfs mounting one spawned.

    It will umount the mounted names that are mounted
    but leave the linked devices alone.
    """
    try:
        img = _DiskImage(image=None, mount_dir=container_dir)
        img.umount()
    except Exception as exn:
        LOG.exception(_('Failed to umount container filesystem: %s'), exn)


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
    status = True
    for inject in ('key', 'net', 'metadata', 'admin_password', 'files'):
        inject_val = locals()[inject]
        inject_func = globals()['_inject_%s_into_fs' % inject]
        if inject_val:
            try:
                inject_func(inject_val, fs)
            except Exception as e:
                if inject in mandatory:
                    raise
                LOG.warn(_('Ignoring error injecting %(inject)s into image '
                           '(%(e)s)'), {'e': e, 'inject': inject})
                status = False
    return status


def _inject_files_into_fs(files, fs):
    for (path, contents) in files:
        _inject_file_into_fs(fs, path, contents)


def _inject_file_into_fs(fs, path, contents, append=False):
    LOG.debug(_("Inject file fs=%(fs)s path=%(path)s append=%(append)s"),
              {'fs': fs, 'path': path, 'append': append})
    if append:
        fs.append_file(path, contents)
    else:
        fs.replace_file(path, contents)


def _inject_metadata_into_fs(metadata, fs):
    LOG.debug(_("Inject metadata fs=%(fs)s metadata=%(metadata)s"),
              {'fs': fs, 'metadata': metadata})
    metadata = dict([(m['key'], m['value']) for m in metadata])
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

    LOG.debug(_("Inject key fs=%(fs)s key=%(key)s"), {'fs': fs, 'key': key})
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

    LOG.debug(_("Inject key fs=%(fs)s net=%(net)s"), {'fs': fs, 'net': net})
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

    LOG.debug(_("Inject admin password fs=%(fs)s "
                "admin_passwd=<SANITIZED>"), {'fs': fs})
    admin_user = 'root'

    fd, tmp_passwd = tempfile.mkstemp()
    os.close(fd)
    fd, tmp_shadow = tempfile.mkstemp()
    os.close(fd)

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
    :param encrypted_passwd: the  encrypted password
    :param passwd_file: path to the passwd file
    :param shadow_file: path to the shadow password file
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
    found = False
    for entry in p_file:
        split_entry = entry.split(':')
        if split_entry[0] == username:
            found = True
            break
    if not found:
        msg = _('User %(username)s not found in password file.')
        raise exception.NovaException(msg % username)

    # update password in the shadow file.It's an error if the
    # the user doesn't exist.
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
