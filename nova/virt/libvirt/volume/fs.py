# Copyright 2015 IBM Corp.
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

import abc
import os

import six

from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume


@six.add_metaclass(abc.ABCMeta)
class LibvirtBaseFileSystemVolumeDriver(
    libvirt_volume.LibvirtBaseVolumeDriver):
    """The base class for file system type volume drivers"""

    def __init__(self, host):
        super(LibvirtBaseFileSystemVolumeDriver,
              self).__init__(host, is_block_dev=False)

    @abc.abstractmethod
    def _get_mount_point_base(self):
        """Return the mount point path prefix.

        This is used to build the device path.

        :returns: The mount point path prefix.
        """
        raise NotImplementedError('_get_mount_point_base')

    def _normalize_export(self, export):
        """Normalize the export (share) if necessary.

        Subclasses should override this method if they have a non-standard
        export value, e.g. if the export is a URL. By default this method just
        returns the export value passed in unchanged.

        :param export: The export (share) value to normalize.
        :returns: The normalized export value.
        """
        return export

    def _get_mount_path(self, connection_info):
        """Returns the mount path prefix using the mount point base and share.

        :param connection_info: dict of the form

        ::

          connection_info = {
              'data': {
                  'export': the file system share,
                  ...
              }
              ...
          }

        :returns: The mount path prefix.
        """
        share = self._normalize_export(connection_info['data']['export'])
        return os.path.join(self._get_mount_point_base(),
                            utils.get_hash_str(share))

    def _get_device_path(self, connection_info):
        """Returns the hashed path to the device.

        :param connection_info: dict of the form

        ::

          connection_info = {
              'data': {
                  'export': the file system share,
                  'name': the name of the device,
                  ...
              }
              ...
          }

        :returns: The full path to the device.
        """
        mount_path = self._get_mount_path(connection_info)
        return os.path.join(mount_path, connection_info['data']['name'])
