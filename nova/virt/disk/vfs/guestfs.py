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

import os

from eventlet import tpool
from oslo_log import log as logging
from oslo_utils import importutils
import six

import nova.conf
from nova import exception
from nova.i18n import _
from nova.virt.disk.vfs import api as vfs
from nova.virt.image import model as imgmodel


LOG = logging.getLogger(__name__)

guestfs = None
forceTCG = False

CONF = nova.conf.CONF


def force_tcg(force=True):
    """Prevent libguestfs trying to use KVM acceleration

    It is a good idea to call this if it is known that
    KVM is not desired, even if technically available.
    """

    global forceTCG
    forceTCG = force


class VFSGuestFS(vfs.VFS):

    """This class implements a VFS module that uses the libguestfs APIs
    to access the disk image. The disk image is never mapped into
    the host filesystem, thus avoiding any potential for symlink
    attacks from the guest filesystem.
    """
    def __init__(self, image, partition=None):
        """Create a new local VFS instance

        :param image: instance of nova.virt.image.model.Image
        :param partition: the partition number of access
        """

        super(VFSGuestFS, self).__init__(image, partition)

        global guestfs
        if guestfs is None:
            try:
                guestfs = importutils.import_module('guestfs')
            except Exception as e:
                raise exception.NovaException(
                    _("libguestfs is not installed (%s)") % e)

        self.handle = None
        self.mount = False

    def inspect_capabilities(self):
        """Determines whether guestfs is well configured."""
        try:
            # If guestfs debug is enabled, we can't launch in a thread because
            # the debug logging callback can make eventlet try to switch
            # threads and then the launch hangs, causing eternal sadness.
            if CONF.guestfs.debug:
                LOG.debug('Inspecting guestfs capabilities non-threaded.')
                g = guestfs.GuestFS()
            else:
                g = tpool.Proxy(guestfs.GuestFS())
            g.add_drive("/dev/null")  # sic
            g.launch()
        except Exception as e:
            kernel_file = "/boot/vmlinuz-%s" % os.uname()[2]
            if not os.access(kernel_file, os.R_OK):
                raise exception.LibguestfsCannotReadKernel(
                    _("Please change permissions on %s to 0x644")
                    % kernel_file)
            raise exception.NovaException(
                _("libguestfs installed but not usable (%s)") % e)

        return self

    def configure_debug(self):
        """Configures guestfs to be verbose."""
        if not self.handle:
            LOG.warning("Please consider to execute setup before trying "
                        "to configure debug log message.")
        else:
            def log_callback(ev, eh, buf, array):
                if ev == guestfs.EVENT_APPLIANCE:
                    buf = buf.rstrip()
                LOG.debug("event=%(event)s eh=%(eh)d buf='%(buf)s' "
                          "array=%(array)s", {
                              "event": guestfs.event_to_string(ev),
                              "eh": eh, "buf": buf, "array": array})

            events = (guestfs.EVENT_APPLIANCE | guestfs.EVENT_LIBRARY
                      | guestfs.EVENT_WARNING | guestfs.EVENT_TRACE)

            self.handle.set_trace(True)  # just traces libguestfs API calls
            self.handle.set_verbose(True)
            self.handle.set_event_callback(log_callback, events)

    def setup_os(self):
        if self.partition == -1:
            self.setup_os_inspect()
        else:
            self.setup_os_static()

    def setup_os_static(self):
        LOG.debug("Mount guest OS image %(image)s partition %(part)s",
                  {'image': self.image, 'part': str(self.partition)})

        if self.partition:
            self.handle.mount_options("", "/dev/sda%d" % self.partition, "/")
        else:
            self.handle.mount_options("", "/dev/sda", "/")

    def setup_os_inspect(self):
        LOG.debug("Inspecting guest OS image %s", self.image)
        roots = self.handle.inspect_os()

        if len(roots) == 0:
            raise exception.NovaException(_("No operating system found in %s")
                                          % self.image)

        if len(roots) != 1:
            LOG.debug("Multi-boot OS %(roots)s", {'roots': str(roots)})
            raise exception.NovaException(
                _("Multi-boot operating system found in %s") %
                self.image)

        self.setup_os_root(roots[0])

    def setup_os_root(self, root):
        LOG.debug("Inspecting guest OS root filesystem %s", root)
        mounts = self.handle.inspect_get_mountpoints(root)

        if len(mounts) == 0:
            raise exception.NovaException(
                _("No mount points found in %(root)s of %(image)s") %
                {'root': root, 'image': self.image})

        # the root directory must be mounted first
        mounts.sort(key=lambda mount: mount[0])

        root_mounted = False
        for mount in mounts:
            LOG.debug("Mounting %(dev)s at %(dir)s",
                      {'dev': mount[1], 'dir': mount[0]})
            try:
                self.handle.mount_options("", mount[1], mount[0])
                root_mounted = True
            except RuntimeError as e:
                msg = _("Error mounting %(device)s to %(dir)s in image"
                        " %(image)s with libguestfs (%(e)s)") % \
                      {'image': self.image, 'device': mount[1],
                       'dir': mount[0], 'e': e}
                if root_mounted:
                    LOG.debug(msg)
                else:
                    raise exception.NovaException(msg)

    def setup(self, mount=True):
        LOG.debug("Setting up appliance for %(image)s",
                  {'image': self.image})
        try:
            self.handle = tpool.Proxy(
                guestfs.GuestFS(python_return_dict=False,
                                close_on_exit=False))
        except TypeError as e:
            if ('close_on_exit' in six.text_type(e) or
                'python_return_dict' in six.text_type(e)):
                # NOTE(russellb) In case we're not using a version of
                # libguestfs new enough to support parameters close_on_exit
                # and python_return_dict which were added in libguestfs 1.20.
                self.handle = tpool.Proxy(guestfs.GuestFS())
            else:
                raise

        if CONF.guestfs.debug:
            self.configure_debug()

        try:
            if forceTCG:
                ret = self.handle.set_backend_settings("force_tcg")
                if ret != 0:
                    LOG.warning('Failed to force guestfs TCG mode. '
                                'guestfs_set_backend_settings returned: %s',
                                ret)
        except AttributeError as ex:
            # set_backend_settings method doesn't exist in older
            # libguestfs versions, so nothing we can do but ignore
            LOG.warning("Unable to force TCG mode, "
                        "libguestfs too old? %s", ex)
            pass

        try:
            if isinstance(self.image, imgmodel.LocalImage):
                self.handle.add_drive_opts(self.image.path,
                                           format=self.image.format)
            elif isinstance(self.image, imgmodel.RBDImage):
                self.handle.add_drive_opts("%s/%s" % (self.image.pool,
                                                      self.image.name),
                                           protocol="rbd",
                                           format=imgmodel.FORMAT_RAW,
                                           server=self.image.servers,
                                           username=self.image.user,
                                           secret=self.image.password)
            else:
                raise exception.UnsupportedImageModel(
                    self.image.__class__.__name__)

            self.handle.launch()

            if mount:
                self.setup_os()
                self.handle.aug_init("/", 0)
                self.mount = True
        except RuntimeError as e:
            # explicitly teardown instead of implicit close()
            # to prevent orphaned VMs in cases when an implicit
            # close() is not enough
            self.teardown()
            raise exception.NovaException(
                _("Error mounting %(image)s with libguestfs (%(e)s)") %
                {'image': self.image, 'e': e})
        except Exception:
            # explicitly teardown instead of implicit close()
            # to prevent orphaned VMs in cases when an implicit
            # close() is not enough
            self.teardown()
            raise

    def teardown(self):
        LOG.debug("Tearing down appliance")

        try:
            try:
                if self.mount:
                    self.handle.aug_close()
            except RuntimeError as e:
                LOG.warning("Failed to close augeas %s", e)

            try:
                self.handle.shutdown()
            except AttributeError:
                # Older libguestfs versions haven't an explicit shutdown
                pass
            except RuntimeError as e:
                LOG.warning("Failed to shutdown appliance %s", e)

            try:
                self.handle.close()
            except AttributeError:
                # Older libguestfs versions haven't an explicit close
                pass
            except RuntimeError as e:
                LOG.warning("Failed to close guest handle %s", e)
        finally:
            # dereference object and implicitly close()
            self.handle = None

    @staticmethod
    def _canonicalize_path(path):
        if path[0] != '/':
            return '/' + path
        return path

    def make_path(self, path):
        LOG.debug("Make directory path=%s", path)
        path = self._canonicalize_path(path)
        self.handle.mkdir_p(path)

    def append_file(self, path, content):
        LOG.debug("Append file path=%s", path)
        path = self._canonicalize_path(path)
        self.handle.write_append(path, content)

    def replace_file(self, path, content):
        LOG.debug("Replace file path=%s", path)
        path = self._canonicalize_path(path)
        self.handle.write(path, content)

    def read_file(self, path):
        LOG.debug("Read file path=%s", path)
        path = self._canonicalize_path(path)
        return self.handle.read_file(path)

    def has_file(self, path):
        LOG.debug("Has file path=%s", path)
        path = self._canonicalize_path(path)
        try:
            self.handle.stat(path)
            return True
        except RuntimeError:
            return False

    def set_permissions(self, path, mode):
        LOG.debug("Set permissions path=%(path)s mode=%(mode)s",
                  {'path': path, 'mode': mode})
        path = self._canonicalize_path(path)
        self.handle.chmod(mode, path)

    def set_ownership(self, path, user, group):
        LOG.debug("Set ownership path=%(path)s "
                  "user=%(user)s group=%(group)s",
                  {'path': path, 'user': user, 'group': group})
        path = self._canonicalize_path(path)
        uid = -1
        gid = -1

        def _get_item_id(id_path):
            try:
                return int(self.handle.aug_get("/files/etc/" + id_path))
            except RuntimeError as e:
                msg = _("Error obtaining uid/gid for %(user)s/%(group)s: "
                        " path %(id_path)s not found (%(e)s)") % {
                    'id_path': "/files/etc/" + id_path, 'user': user,
                    'group': group, 'e': e}
                raise exception.NovaException(msg)

        if user is not None:
            uid = _get_item_id('passwd/' + user + '/uid')
        if group is not None:
            gid = _get_item_id('group/' + group + '/gid')
        LOG.debug("chown uid=%(uid)d gid=%(gid)s",
                  {'uid': uid, 'gid': gid})
        self.handle.chown(uid, gid, path)

    def get_image_fs(self):
        return self.handle.vfs_type('/dev/sda')
