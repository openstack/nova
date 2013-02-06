# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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

"""Deprecated file, kept for back-compat only. To be removed in Hxxxx."""

from nova.openstack.common import log as logging
from nova.virt.libvirt import volume

LOG = logging.getLogger(__name__)


class NfsVolumeDriver(volume.LibvirtNFSVolumeDriver):
    """Deprecated driver for NFS, renamed to LibvirtNFSVolumeDriver
       and moved into the main volume.py module. Kept for backwards
       compatibility in the Grizzly cycle to give users opportunity
       to configure before its removal in the Hxxxx cycle."""

    def __init__(self, *args, **kwargs):
        super(NfsVolumeDriver,
              self).__init__(*args, **kwargs)
        LOG.deprecated(
            _("The nova.virt.libvirt.volume_nfs.NfsVolumeDriver "
              "class is deprecated and will be removed in the "
              "Hxxxx release. Please update nova.conf so that "
              "the 'libvirt_volume_drivers' parameter refers to "
              "nova.virt.libvirt.volume.LibvirtNFSVolumeDriver."))
