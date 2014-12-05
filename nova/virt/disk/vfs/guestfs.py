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
from oslo.config import cfg
from oslo.utils import importutils
import six

from nova import exception
from nova.i18n import _
from nova.i18n import _LW
from nova.openstack.common import log as logging
from nova.virt.disk.vfs import api as vfs


LOG = logging.getLogger(__name__)

guestfs = None
forceTCG = False

guestfs_opts = [
    cfg.BoolOpt('debug',
                default=False,
                help='Enable guestfs debug')
]

CONF = cfg.CONF
CONF.register_opts(guestfs_opts, group='guestfs')


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
    def __init__(self, imgfile, imgfmt='raw', partition=None):
        super(VFSGuestFS, self).__init__(imgfile, imgfmt, partition)

        global guestfs
        if guestfs is None:
            try:
                guestfs = importutils.import_module('guestfs')
            except Exception as e:
                raise exception.NovaException(
                    _("libguestfs is not installed (%s)") % e)

        self.handle = None

    def inspect_capabilities(self):
        """Determines whether guestfs is well configured."""
        try:
            g = guestfs.GuestFS()
            g.add_drive("/dev/null")  # sic
            g.launch()
        except Exception as e:
            raise exception.NovaException(
                _("libguestfs installed but not usable (%s)") % e)

        return self

    def configure_debug(self):
        """Configures guestfs to be verbose."""
        if not self.handle:
            LOG.warning(_LW("Please consider to execute setup before trying "
                            "to configure debug log message."))
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
        LOG.debug("Mount guest OS image %(imgfile)s partition %(part)s",
                  {'imgfile': self.imgfile, 'part': str(self.partition)})

        if self.partition:
            self.handle.mount_options("", "/dev/sda%d" % self.partition, "/")
        else:
            self.handle.mount_options("", "/dev/sda", "/")

    def setup_os_inspect(self):
        LOG.debug("Inspecting guest OS image %s", self.imgfile)
        roots = self.handle.inspect_os()

        if len(roots) == 0:
            raise exception.NovaException(_("No operating system found in %s")
                                          % self.imgfile)

        if len(roots) != 1:
            LOG.debug("Multi-boot OS %(roots)s", {'roots': str(roots)})
            raise exception.NovaException(
                _("Multi-boot operating system found in %s") %
                self.imgfile)

        self.setup_os_root(roots[0])

    def setup_os_root(self, root):
        LOG.debug("Inspecting guest OS root filesystem %s", root)
        mounts = self.handle.inspect_get_mountpoints(root)

        if len(mounts) == 0:
            raise exception.NovaException(
                _("No mount points found in %(root)s of %(imgfile)s") %
                {'root': root, 'imgfile': self.imgfile})

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
                        " %(imgfile)s with libguestfs (%(e)s)") % \
                      {'imgfile': self.imgfile, 'device': mount[1],
                       'dir': mount[0], 'e': e}
                if root_mounted:
                    LOG.debug(msg)
                else:
                    raise exception.NovaException(msg)

    def setup(self):
        LOG.debug("Setting up appliance for %(imgfile)s %(imgfmt)s",
                  {'imgfile': self.imgfile, 'imgfmt': self.imgfmt})
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
                self.handle.set_backend_settings("force_tcg")
        except AttributeError as ex:
            # set_backend_settings method doesn't exist in older
            # libguestfs versions, so nothing we can do but ignore
            LOG.warning(_LW("Unable to force TCG mode, "
                            "libguestfs too old? %s"), ex)
            pass

        try:
            self.handle.add_drive_opts(self.imgfile, format=self.imgfmt)
            self.handle.launch()

            self.setup_os()

            self.handle.aug_init("/", 0)
        except RuntimeError as e:
            # explicitly teardown instead of implicit close()
            # to prevent orphaned VMs in cases when an implicit
            # close() is not enough
            self.teardown()
            raise exception.NovaException(
                _("Error mounting %(imgfile)s with libguestfs (%(e)s)") %
                {'imgfile': self.imgfile, 'e': e})
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
                self.handle.aug_close()
            except RuntimeError as e:
                LOG.warning(_LW("Failed to close augeas %s"), e)

            try:
                self.handle.shutdown()
            except AttributeError:
                # Older libguestfs versions haven't an explicit shutdown
                pass
            except RuntimeError as e:
                LOG.warning(_LW("Failed to shutdown appliance %s"), e)

            try:
                self.handle.close()
            except AttributeError:
                # Older libguestfs versions haven't an explicit close
                pass
            except RuntimeError as e:
                LOG.warning(_LW("Failed to close guest handle %s"), e)
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

        if user is not None:
            uid = int(self.handle.aug_get(
                    "/files/etc/passwd/" + user + "/uid"))
        if group is not None:
            gid = int(self.handle.aug_get(
                    "/files/etc/group/" + group + "/gid"))

        LOG.debug("chown uid=%(uid)d gid=%(gid)s",
                  {'uid': uid, 'gid': gid})
        self.handle.chown(uid, gid, path)
