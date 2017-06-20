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

from oslo_log import log as logging
from oslo_utils import importutils

from nova import exception

LOG = logging.getLogger(__name__)


class VFS(object):
    """Interface for manipulating disk image.

    The VFS class defines an interface for manipulating files within
    a virtual disk image filesystem. This allows file injection code
    to avoid the assumption that the virtual disk image can be mounted
    in the host filesystem.

    All paths provided to the APIs in this class should be relative
    to the root of the virtual disk image filesystem. Subclasses
    will translate paths as required by their implementation.
    """

    # Class level flag to indicate whether we can consider
    # that guestfs is ready to be used.
    guestfs_ready = False

    @staticmethod
    def instance_for_image(image, partition):
        """Get a VFS instance for the image

        :param image: instance of nova.virt.image.model.Image
        :param partition: the partition number to access
        """

        LOG.debug("Instance for image image=%(image)s "
                  "partition=%(partition)s",
                  {'image': image, 'partition': partition})

        vfs = None
        try:
            LOG.debug("Using primary VFSGuestFS")
            vfs = importutils.import_object(
                "nova.virt.disk.vfs.guestfs.VFSGuestFS",
                image, partition)
            if not VFS.guestfs_ready:
                # Inspect for capabilities and keep
                # track of the result only if succeeded.
                vfs.inspect_capabilities()
                VFS.guestfs_ready = True
            return vfs
        except exception.NovaException:
            if vfs is not None:
                # We are able to load libguestfs but
                # something wrong happens when trying to
                # check for capabilities.
                raise
            else:
                LOG.info("Unable to import guestfs, "
                         "falling back to VFSLocalFS")

        return importutils.import_object(
            "nova.virt.disk.vfs.localfs.VFSLocalFS",
            image, partition)

    def __init__(self, image, partition):
        """Create a new local VFS instance

        :param image: instance of nova.virt.image.model.Image
        :param partition: the partition number to access
        """

        self.image = image
        self.partition = partition

    def setup(self, mount=True):
        """Performs any one-time setup.

        Perform any one-time setup tasks to make the virtual filesystem
        available to future API calls.
        """
        pass

    def teardown(self):
        """Releases all resources initialized in the setup method."""
        pass

    def make_path(self, path):
        """Creates a directory @path.

        Create a directory @path, including all intermedia path components
        if they do not already exist.
        """
        pass

    def append_file(self, path, content):
        """Appends @content to the end of the file.

        Append @content to the end of the file identified by @path, creating
        the file if it does not already exist.
        """
        pass

    def replace_file(self, path, content):
        """Replaces contents of the file.

        Replace the entire contents of the file identified by @path, with
        @content, creating the file if it does not already exist.
        """
        pass

    def read_file(self, path):
        """Returns the entire contents of the file identified by @path."""
        pass

    def has_file(self, path):
        """Returns a True if the file identified by @path exists."""
        pass

    def set_permissions(self, path, mode):
        """Sets the permissions on the file.

        Set the permissions on the file identified by @path to @mode. The file
        must exist prior to this call.
        """
        pass

    def set_ownership(self, path, user, group):
        """Sets the ownership on the file.

        Set the ownership on the file identified by @path to the username
        @user and groupname @group. Either of @user or @group may be None,
        in which case the current ownership will be left unchanged.
        The ownership must be passed in string form, allowing subclasses to
        translate to uid/gid form as required. The file must exist prior to
        this call.
        """
        pass

    def get_image_fs(self):
        """Returns the filesystem type or an empty string.

        Determine the filesystem type whether the disk image is
        partition less.
        """
        pass
