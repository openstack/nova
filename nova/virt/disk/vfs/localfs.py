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
import tempfile

from oslo.utils import excutils

from nova import exception
from nova.i18n import _
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.disk.mount import loop
from nova.virt.disk.mount import nbd
from nova.virt.disk.vfs import api as vfs

LOG = logging.getLogger(__name__)


class VFSLocalFS(vfs.VFS):

    """os.path.join() with safety check for injected file paths.

    Join the supplied path components and make sure that the
    resulting path we are injecting into is within the
    mounted guest fs.  Trying to be clever and specifying a
    path with '..' in it will hit this safeguard.
    """
    def _canonical_path(self, path):
        canonpath, _err = utils.execute(
            'readlink', '-nm',
            os.path.join(self.imgdir, path.lstrip("/")),
            run_as_root=True)
        if not canonpath.startswith(os.path.realpath(self.imgdir) + '/'):
            raise exception.Invalid(_('File path %s not valid') % path)
        return canonpath

    """
    This class implements a VFS module that is mapped to a virtual
    root directory present on the host filesystem. This implementation
    uses the nova.virt.disk.mount.Mount API to make virtual disk
    images visible in the host filesystem. If the disk format is
    raw, it will use the loopback mount impl, otherwise it will
    use the qemu-nbd impl.
    """
    def __init__(self, imgfile, imgfmt="raw", partition=None, imgdir=None):
        super(VFSLocalFS, self).__init__(imgfile, imgfmt, partition)

        self.imgdir = imgdir
        self.mount = None

    def setup(self):
        self.imgdir = tempfile.mkdtemp(prefix="openstack-vfs-localfs")
        try:
            if self.imgfmt == "raw":
                LOG.debug("Using LoopMount")
                mount = loop.LoopMount(self.imgfile,
                                       self.imgdir,
                                       self.partition)
            else:
                LOG.debug("Using NbdMount")
                mount = nbd.NbdMount(self.imgfile,
                                     self.imgdir,
                                     self.partition)
            if not mount.do_mount():
                raise exception.NovaException(mount.error)
            self.mount = mount
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.debug("Failed to mount image %(ex)s)", {'ex': e})
                self.teardown()

    def teardown(self):
        try:
            if self.mount:
                self.mount.do_teardown()
        except Exception as e:
            LOG.debug("Failed to unmount %(imgdir)s: %(ex)s",
                      {'imgdir': self.imgdir, 'ex': e})
        try:
            if self.imgdir:
                os.rmdir(self.imgdir)
        except Exception as e:
            LOG.debug("Failed to remove %(imgdir)s: %(ex)s",
                      {'imgdir': self.imgdir, 'ex': e})
        self.imgdir = None
        self.mount = None

    def make_path(self, path):
        LOG.debug("Make directory path=%s", path)
        canonpath = self._canonical_path(path)
        utils.execute('mkdir', '-p', canonpath, run_as_root=True)

    def append_file(self, path, content):
        LOG.debug("Append file path=%s", path)
        canonpath = self._canonical_path(path)

        args = ["-a", canonpath]
        kwargs = dict(process_input=content, run_as_root=True)

        utils.execute('tee', *args, **kwargs)

    def replace_file(self, path, content):
        LOG.debug("Replace file path=%s", path)
        canonpath = self._canonical_path(path)

        args = [canonpath]
        kwargs = dict(process_input=content, run_as_root=True)

        utils.execute('tee', *args, **kwargs)

    def read_file(self, path):
        LOG.debug("Read file path=%s", path)
        canonpath = self._canonical_path(path)

        return utils.read_file_as_root(canonpath)

    def has_file(self, path):
        LOG.debug("Has file path=%s", path)
        canonpath = self._canonical_path(path)
        exists, _err = utils.trycmd('readlink', '-e',
                                    canonpath,
                                    run_as_root=True)
        return exists

    def set_permissions(self, path, mode):
        LOG.debug("Set permissions path=%(path)s mode=%(mode)o",
                  {'path': path, 'mode': mode})
        canonpath = self._canonical_path(path)
        utils.execute('chmod', "%o" % mode, canonpath, run_as_root=True)

    def set_ownership(self, path, user, group):
        LOG.debug("Set permissions path=%(path)s "
                  "user=%(user)s group=%(group)s",
                  {'path': path, 'user': user, 'group': group})
        canonpath = self._canonical_path(path)
        owner = None
        cmd = "chown"
        if group is not None and user is not None:
            owner = user + ":" + group
        elif user is not None:
            owner = user
        elif group is not None:
            owner = group
            cmd = "chgrp"

        if owner is not None:
            utils.execute(cmd, owner, canonpath, run_as_root=True)
