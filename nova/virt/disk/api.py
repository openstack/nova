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

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.disk import guestfs
from nova.virt.disk import loop
from nova.virt.disk import nbd
from nova.virt import images


LOG = logging.getLogger(__name__)

disk_opts = [
    cfg.StrOpt('injected_network_template',
               default='$pybasedir/nova/virt/interfaces.template',
               help='Template file for injected network'),
    cfg.ListOpt('img_handlers',
                default=['loop', 'nbd', 'guestfs'],
                help='Order of methods used to mount disk images'),

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
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(disk_opts)

_MKFS_COMMAND = {}
_DEFAULT_MKFS_COMMAND = None


for s in FLAGS.virt_mkfs:
    # NOTE(yamahata): mkfs command may includes '=' for its options.
    #                 So item.partition('=') doesn't work here
    os_type, mkfs_command = s.split('=', 1)
    if os_type:
        _MKFS_COMMAND[os_type] = mkfs_command
    if os_type == 'default':
        _DEFAULT_MKFS_COMMAND = mkfs_command


def mkfs(os_type, fs_label, target):
    mkfs_command = (_MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND) or
                    '') % locals()
    if mkfs_command:
        utils.execute(*mkfs_command.split())


def resize2fs(image, check_exit_code=False):
    utils.execute('e2fsck', '-fp', image, check_exit_code=check_exit_code)
    utils.execute('resize2fs', image, check_exit_code=check_exit_code)


def get_disk_size(path):
    """Get the (virtual) size of a disk image

    :param path: Path to the disk image
    :returns: Size (in bytes) of the given disk image as it would be seen
              by a virtual machine.
    """
    size = images.qemu_img_info(path)['virtual size']
    size = size.split('(')[1].split()[0]
    return int(size)


def extend(image, size):
    """Increase image to size"""
    virt_size = get_disk_size(image)
    if virt_size >= size:
        return
    utils.execute('qemu-img', 'resize', image, size)
    # NOTE(vish): attempts to resize filesystem
    resize2fs(image)


def can_resize_fs(image, size, use_cow=False):
    """Check whether we can resize contained file system."""

    # Check that we're increasing the size
    virt_size = get_disk_size(image)
    if virt_size >= size:
        return False

    # Check the image is unpartitioned
    if use_cow:
        # Try to mount an unpartitioned qcow2 image
        try:
            inject_data(image, use_cow=True)
        except exception.NovaException:
            return False
    else:
        # For raw, we can directly inspect the file system
        try:
            utils.execute('e2label', image)
        except exception.ProcessExecutionError:
            return False

    return True


def bind(src, target, instance_name):
    """Bind device to a filesytem"""
    if src:
        utils.execute('touch', target, run_as_root=True)
        utils.execute('mount', '-o', 'bind', src, target,
                run_as_root=True)
        s = os.stat(src)
        cgroup_info = "b %s:%s rwm\n" % (os.major(s.st_rdev),
                                         os.minor(s.st_rdev))
        cgroups_path = ("/sys/fs/cgroup/devices/libvirt/lxc/"
                        "%s/devices.allow" % instance_name)
        utils.execute('tee', cgroups_path,
                      process_input=cgroup_info, run_as_root=True)


def unbind(target):
    if target:
        utils.execute('umount', target, run_as_root=True)


class _DiskImage(object):
    """Provide operations on a disk image file."""

    tmp_prefix = 'openstack-disk-mount-tmp'

    def __init__(self, image, partition=None, use_cow=False, mount_dir=None):
        # These passed to each mounter
        self.image = image
        self.partition = partition
        self.mount_dir = mount_dir

        # Internal
        self._mkdir = False
        self._mounter = None
        self._errors = []

        # As a performance tweak, don't bother trying to
        # directly loopback mount a cow image.
        self.handlers = FLAGS.img_handlers[:]
        if use_cow and 'loop' in self.handlers:
            self.handlers.remove('loop')

        if not self.handlers:
            msg = _('no capable image handler configured')
            raise exception.NovaException(msg)

        if mount_dir:
            # Note the os.path.ismount() shortcut doesn't
            # work with libguestfs due to permissions issues.
            device = self._device_for_path(mount_dir)
            if device:
                self._reset(device)

    @staticmethod
    def _device_for_path(path):
        device = None
        with open("/proc/mounts", 'r') as ifp:
            for line in ifp:
                fields = line.split()
                if fields[1] == os.path.realpath(path):
                    device = fields[0]
                    break
        return device

    def _reset(self, device):
        """Reset internal state for a previously mounted directory."""
        mounter_cls = self._handler_class(device=device)
        mounter = mounter_cls(image=self.image,
                              partition=self.partition,
                              mount_dir=self.mount_dir,
                              device=device)
        self._mounter = mounter

        mount_name = os.path.basename(self.mount_dir or '')
        self._mkdir = mount_name.startswith(self.tmp_prefix)

    @property
    def errors(self):
        """Return the collated errors from all operations."""
        return '\n--\n'.join([''] + self._errors)

    @staticmethod
    def _handler_class(mode=None, device=None):
        """Look up the appropriate class to use based on MODE or DEVICE."""
        for cls in (loop.Mount, nbd.Mount, guestfs.Mount):
            if mode and cls.mode == mode:
                return cls
            elif device and cls.device_id_string in device:
                return cls
        msg = _("no disk image handler for: %s") % mode or device
        raise exception.NovaException(msg)

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

        try:
            for h in self.handlers:
                mounter_cls = self._handler_class(h)
                mounter = mounter_cls(image=self.image,
                                      partition=self.partition,
                                      mount_dir=self.mount_dir)
                if mounter.do_mount():
                    self._mounter = mounter
                    break
                else:
                    LOG.debug(mounter.error)
                    self._errors.append(mounter.error)
        finally:
            if not self._mounter:
                self.umount()  # rmdir

        return bool(self._mounter)

    def umount(self):
        """Unmount a disk image from the file system."""
        try:
            if self._mounter:
                self._mounter.do_umount()
        finally:
            if self._mkdir:
                os.rmdir(self.mount_dir)


# Public module functions

def inject_data(image,
                key=None, net=None, metadata=None, admin_password=None,
                files=None, partition=None, use_cow=False):
    """Injects a ssh key and optionally net data into a disk image.

    it will mount the image as a fully partitioned disk and attempt to inject
    into the specified partition number.

    If partition is not specified it mounts the image as a single partition.

    """
    img = _DiskImage(image=image, partition=partition, use_cow=use_cow)
    if img.mount():
        try:
            inject_data_into_fs(img.mount_dir,
                                key, net, metadata, admin_password, files)
        finally:
            img.umount()
    else:
        raise exception.NovaException(img.errors)


def setup_container(image, container_dir, use_cow=False):
    """Setup the LXC container.

    It will mount the loopback image to the container directory in order
    to create the root filesystem for the container.
    """
    img = _DiskImage(image=image, use_cow=use_cow, mount_dir=container_dir)
    if not img.mount():
        LOG.error(_("Failed to mount container filesystem '%(image)s' "
                    "on '%(target)s': %(errors)s") %
                  {"image": img, "target": container_dir,
                   "errors": img.errors})
        raise exception.NovaException(img.errors)


def destroy_container(container_dir):
    """Destroy the container once it terminates.

    It will umount the container that is mounted,
    and delete any  linked devices.
    """
    try:
        img = _DiskImage(image=None, mount_dir=container_dir)
        img.umount()
    except Exception, exn:
        LOG.exception(_('Failed to unmount container filesystem: %s'), exn)


def inject_data_into_fs(fs, key, net, metadata, admin_password, files):
    """Injects data into a filesystem already mounted by the caller.
    Virt connections can call this directly if they mount their fs
    in a different way to inject_data
    """
    if key:
        _inject_key_into_fs(key, fs)
    if net:
        _inject_net_into_fs(net, fs)
    if metadata:
        _inject_metadata_into_fs(metadata, fs)
    if admin_password:
        _inject_admin_password_into_fs(admin_password, fs)
    if files:
        for (path, contents) in files:
            _inject_file_into_fs(fs, path, contents)


def _join_and_check_path_within_fs(fs, *args):
    '''os.path.join() with safety check for injected file paths.

    Join the supplied path components and make sure that the
    resulting path we are injecting into is within the
    mounted guest fs.  Trying to be clever and specifying a
    path with '..' in it will hit this safeguard.
    '''
    absolute_path, _err = utils.execute('readlink', '-nm',
                                        os.path.join(fs, *args),
                                        run_as_root=True)
    if not absolute_path.startswith(os.path.realpath(fs) + '/'):
        raise exception.Invalid(_('injected file path not valid'))
    return absolute_path


def _inject_file_into_fs(fs, path, contents, append=False):
    absolute_path = _join_and_check_path_within_fs(fs, path.lstrip('/'))

    parent_dir = os.path.dirname(absolute_path)
    utils.execute('mkdir', '-p', parent_dir, run_as_root=True)

    args = []
    if append:
        args.append('-a')
    args.append(absolute_path)

    kwargs = dict(process_input=contents, run_as_root=True)

    utils.execute('tee', *args, **kwargs)


def _inject_metadata_into_fs(metadata, fs):
    metadata = dict([(m['key'], m['value']) for m in metadata])
    _inject_file_into_fs(fs, 'meta.js', jsonutils.dumps(metadata))


def _setup_selinux_for_keys(fs):
    """Get selinux guests to ensure correct context on injected keys."""

    se_cfg = _join_and_check_path_within_fs(fs, 'etc', 'selinux')
    se_cfg, _err = utils.trycmd('readlink', '-e', se_cfg, run_as_root=True)
    if not se_cfg:
        return

    rclocal = _join_and_check_path_within_fs(fs, 'etc', 'rc.local')

    # Support systemd based systems
    rc_d = _join_and_check_path_within_fs(fs, 'etc', 'rc.d')
    rclocal_e, _err = utils.trycmd('readlink', '-e', rclocal, run_as_root=True)
    rc_d_e, _err = utils.trycmd('readlink', '-e', rc_d, run_as_root=True)
    if not rclocal_e and rc_d_e:
        rclocal = os.path.join(rc_d, 'rc.local')

    # Note some systems end rc.local with "exit 0"
    # and so to append there you'd need something like:
    #  utils.execute('sed', '-i', '${/^exit 0$/d}' rclocal, run_as_root=True)
    restorecon = [
        '\n',
        '# Added by Nova to ensure injected ssh keys have the right context\n',
        'restorecon -RF /root/.ssh/ 2>/dev/null || :\n',
    ]

    if not fs.has_file(rclocal):
        restorecon.insert(0, '#!/bin/sh')

    rclocal_rel = os.path.relpath(rclocal, fs)
    _inject_file_into_fs(fs, rclocal_rel, ''.join(restorecon), append=True)
    utils.execute('chmod', 'a+x', rclocal, run_as_root=True)


def _inject_key_into_fs(key, fs):
    """Add the given public ssh key to root's authorized_keys.

    key is an ssh key string.
    fs is the path to the base of the filesystem into which to inject the key.
    """
    sshdir = _join_and_check_path_within_fs(fs, 'root', '.ssh')
    utils.execute('mkdir', '-p', sshdir, run_as_root=True)
    utils.execute('chown', 'root', sshdir, run_as_root=True)
    utils.execute('chmod', '700', sshdir, run_as_root=True)

    keyfile = os.path.join('root', '.ssh', 'authorized_keys')

    key_data = ''.join([
        '\n',
        '# The following ssh key was injected by Nova',
        '\n',
        key.strip(),
        '\n',
    ])

    _inject_file_into_fs(fs, keyfile, key_data, append=True)

    _setup_selinux_for_keys(fs)


def _inject_net_into_fs(net, fs):
    """Inject /etc/network/interfaces into the filesystem rooted at fs.

    net is the contents of /etc/network/interfaces.
    """
    netdir = _join_and_check_path_within_fs(fs, 'etc', 'network')
    utils.execute('mkdir', '-p', netdir, run_as_root=True)
    utils.execute('chown', 'root:root', netdir, run_as_root=True)
    utils.execute('chmod', 755, netdir, run_as_root=True)

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

    admin_user = 'root'

    fd, tmp_passwd = tempfile.mkstemp()
    os.close(fd)
    fd, tmp_shadow = tempfile.mkstemp()
    os.close(fd)

    passwd_path = _join_and_check_path_within_fs(fs, 'etc', 'passwd')
    shadow_path = _join_and_check_path_within_fs(fs, 'etc', 'shadow')

    utils.execute('cp', passwd_path, tmp_passwd, run_as_root=True)
    utils.execute('cp', shadow_path, tmp_shadow, run_as_root=True)
    _set_passwd(admin_user, admin_passwd, tmp_passwd, tmp_shadow)
    utils.execute('cp', tmp_passwd, passwd_path, run_as_root=True)
    os.unlink(tmp_passwd)
    utils.execute('cp', tmp_shadow, shadow_path, run_as_root=True)
    os.unlink(tmp_shadow)


def _set_passwd(username, admin_passwd, passwd_file, shadow_file):
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

    salt_set = ('abcdefghijklmnopqrstuvwxyz'
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                '0123456789./')
    # encryption algo - id pairs for crypt()
    algos = {'SHA-512': '$6$', 'SHA-256': '$5$', 'MD5': '$1$', 'DES': ''}

    salt = 16 * ' '
    salt = ''.join([random.choice(salt_set) for c in salt])

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

    try:
        p_file = open(passwd_file, 'rb')
        s_file = open(shadow_file, 'rb')

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
        s_file.close()
        if not found:
            msg = _('User %(username)s not found in shadow file.')
            raise exception.NovaException(msg % username)
        s_file = open(shadow_file, 'wb')
        for entry in new_shadow:
            s_file.write(entry)
    finally:
        p_file.close()
        s_file.close()
