# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from eventlet import tpool
import guestfs

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.disk.vfs import api as vfs


LOG = logging.getLogger(__name__)

guestfs = None


class VFSGuestFS(vfs.VFS):

    """
    This class implements a VFS module that uses the libguestfs APIs
    to access the disk image. The disk image is never mapped into
    the host filesystem, thus avoiding any potential for symlink
    attacks from the guest filesystem.
    """
    def __init__(self, imgfile, imgfmt='raw', partition=None):
        super(VFSGuestFS, self).__init__(imgfile, imgfmt, partition)

        global guestfs
        if guestfs is None:
            guestfs = __import__('guestfs')

        self.handle = None

    def setup_os(self):
        if self.partition == -1:
            self.setup_os_inspect()
        else:
            self.setup_os_static()

    def setup_os_static(self):
        LOG.debug(_("Mount guest OS image %(imgfile)s partition %(part)s"),
                  {'imgfile': self.imgfile, 'part': str(self.partition)})

        if self.partition:
            self.handle.mount_options("", "/dev/sda%d" % self.partition, "/")
        else:
            self.handle.mount_options("", "/dev/sda", "/")

    def setup_os_inspect(self):
        LOG.debug(_("Inspecting guest OS image %s"), self.imgfile)
        roots = self.handle.inspect_os()

        if len(roots) == 0:
            raise exception.NovaException(_("No operating system found in %s")
                                          % self.imgfile)

        if len(roots) != 1:
            LOG.debug(_("Multi-boot OS %(roots)s") % {'roots': str(roots)})
            raise exception.NovaException(
                _("Multi-boot operating system found in %s") %
                self.imgfile)

        self.setup_os_root(roots[0])

    def setup_os_root(self, root):
        LOG.debug(_("Inspecting guest OS root filesystem %s"), root)
        mounts = self.handle.inspect_get_mountpoints(root)

        if len(mounts) == 0:
            raise exception.NovaException(
                _("No mount points found in %(root)s of %(imgfile)s") %
                {'root': root, 'imgfile': self.imgfile})

        # the root directory must be mounted first
        mounts.sort(key=lambda mount: mount[0])

        root_mounted = False
        for mount in mounts:
            LOG.debug(_("Mounting %(dev)s at %(dir)s") %
                      {'dev': mount[1], 'dir': mount[0]})
            try:
                self.handle.mount_options("", mount[1], mount[0])
                root_mounted = True
            except RuntimeError as e:
                msg = _("Error mounting %(device)s to %(dir)s in image"
                        " %(imgfile)s with libguestfs (%(e)s)") % \
                      {'imgfile': self.imgfile, 'device': mount[1],
                       'dir': mount[0], 'e': e}
                if root_mounted:
                    LOG.debug(msg)
                else:
                    raise exception.NovaException(msg)

    def setup(self):
        LOG.debug(_("Setting up appliance for %(imgfile)s %(imgfmt)s") %
                  {'imgfile': self.imgfile, 'imgfmt': self.imgfmt})
        self.handle = tpool.Proxy(guestfs.GuestFS())

        try:
            self.handle.add_drive_opts(self.imgfile, format=self.imgfmt)
            self.handle.launch()

            self.setup_os()

            self.handle.aug_init("/", 0)
        except RuntimeError as e:
            # dereference object and implicitly close()
            self.handle = None
            raise exception.NovaException(
                _("Error mounting %(imgfile)s with libguestfs (%(e)s)") %
                {'imgfile': self.imgfile, 'e': e})
        except Exception:
            self.handle = None
            raise

    def teardown(self):
        LOG.debug(_("Tearing down appliance"))

        try:
            try:
                self.handle.aug_close()
            except RuntimeError as e:
                LOG.warn(_("Failed to close augeas %s"), e)

            try:
                self.handle.shutdown()
            except AttributeError:
                # Older libguestfs versions haven't an explicit shutdown
                pass
            except RuntimeError as e:
                LOG.warn(_("Failed to shutdown appliance %s"), e)

            try:
                self.handle.close()
            except AttributeError:
                # Older libguestfs versions haven't an explicit close
                pass
            except RuntimeError as e:
                LOG.warn(_("Failed to close guest handle %s"), e)
        finally:
            # dereference object and implicitly close()
            self.handle = None

    @staticmethod
    def _canonicalize_path(path):
        if path[0] != '/':
            return '/' + path
        return path

    def make_path(self, path):
        LOG.debug(_("Make directory path=%s"), path)
        path = self._canonicalize_path(path)
        self.handle.mkdir_p(path)

    def append_file(self, path, content):
        LOG.debug(_("Append file path=%s"), path)
        path = self._canonicalize_path(path)
        self.handle.write_append(path, content)

    def replace_file(self, path, content):
        LOG.debug(_("Replace file path=%s"), path)
        path = self._canonicalize_path(path)
        self.handle.write(path, content)

    def read_file(self, path):
        LOG.debug(_("Read file path=%s"), path)
        path = self._canonicalize_path(path)
        return self.handle.read_file(path)

    def has_file(self, path):
        LOG.debug(_("Has file path=%s"), path)
        path = self._canonicalize_path(path)
        try:
            self.handle.stat(path)
            return True
        except RuntimeError:
            return False

    def set_permissions(self, path, mode):
        LOG.debug(_("Set permissions path=%(path)s mode=%(mode)s"),
                  {'path': path, 'mode': mode})
        path = self._canonicalize_path(path)
        self.handle.chmod(mode, path)

    def set_ownership(self, path, user, group):
        LOG.debug(_("Set ownership path=%(path)s "
                    "user=%(user)s group=%(group)s"),
                  {'path': path, 'user': user, 'group': group})
        path = self._canonicalize_path(path)
        uid = -1
        gid = -1

        if user is not None:
            uid = int(self.handle.aug_get(
                    "/files/etc/passwd/" + user + "/uid"))
        if group is not None:
            gid = int(self.handle.aug_get(
                    "/files/etc/group/" + group + "/gid"))

        LOG.debug(_("chown uid=%(uid)d gid=%(gid)s"),
                  {'uid': uid, 'gid': gid})
        self.handle.chown(uid, gid, path)
