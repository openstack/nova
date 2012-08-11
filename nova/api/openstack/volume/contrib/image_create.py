# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NTT.
# Copyright (c) 2012 OpenStack, LLC.
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

"""The Create Volume from Image extension."""


from nova.api.openstack import extensions


class Image_create(extensions.ExtensionDescriptor):
    """Allow creating a volume from an image in the Create Volume v1 API"""

    name = "CreateVolumeExtension"
    alias = "os-image-create"
    namespace = "http://docs.openstack.org/volume/ext/image-create/api/v1"
    updated = "2012-08-13T00:00:00+00:00"
