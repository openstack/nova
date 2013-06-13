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

from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class VFS(object):

    @staticmethod
    def instance_for_image(imgfile, imgfmt, partition):
        LOG.debug(_("Instance for image imgfile=%(imgfile)s "
                    "imgfmt=%(imgfmt)s partition=%(partition)s"),
                  {'imgfile': imgfile, 'imgfmt': imgfmt,
                   'partition': partition})
        hasGuestfs = False
        try:
            LOG.debug(_("Trying to import guestfs"))
            importutils.import_module("guestfs")
            hasGuestfs = True
        except Exception:
            pass

        if hasGuestfs:
            LOG.debug(_("Using primary VFSGuestFS"))
            return importutils.import_object(
                "nova.virt.disk.vfs.guestfs.VFSGuestFS",
                imgfile, imgfmt, partition)
        else:
            LOG.debug(_("Falling back to VFSLocalFS"))
            return importutils.import_object(
                "nova.virt.disk.vfs.localfs.VFSLocalFS",
                imgfile, imgfmt, partition)

    """
    The VFS class defines an interface for manipulating files within
    a virtual disk image filesystem. This allows file injection code
    to avoid the assumption that the virtual disk image can be mounted
    in the host filesystem.

    All paths provided to the APIs in this class should be relative
    to the root of the virtual disk image filesystem. Subclasses
    will translate paths as required by their implementation.
    """
    def __init__(self, imgfile, imgfmt, partition):
        self.imgfile = imgfile
        self.imgfmt = imgfmt
        self.partition = partition

    """
    Perform any one-time setup tasks to make the virtual
    filesystem available to future API calls
    """
    def setup(self):
        pass

    """
    Release all resources initialized in the setup method
    """
    def teardown(self):
        pass

    """
    Create a directory @path, including all intermedia
    path components if they do not already exist
    """
    def make_path(self, path):
        pass

    """
    Append @content to the end of the file identified
    by @path, creating the file if it does not already
    exist
    """
    def append_file(self, path, content):
        pass

    """
    Replace the entire contents of the file identified
    by @path, with @content, creating the file if it does
    not already exist
    """
    def replace_file(self, path, content):
        pass

    """
    Return the entire contents of the file identified
    by @path
    """
    def read_file(self, path):
        pass

    """
    Return a True if the file identified by @path
    exists
    """
    def has_file(self, path):
        pass

    """
    Set the permissions on the file identified by
    @path to @mode. The file must exist prior to
    this call.
    """
    def set_permissions(self, path, mode):
        pass

    """
    Set the ownership on the file identified by
    @path to the username @user and groupname @group.
    Either of @user or @group may be None, in which case
    the current ownership will be left unchanged. The
    ownership must be passed in string form, allowing
    subclasses to translate to uid/gid form as required.
    The file must exist prior to this call.
    """
    def set_ownership(self, path, user, group):
        pass
