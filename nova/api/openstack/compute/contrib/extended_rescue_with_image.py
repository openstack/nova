# Copyright 2014 OpenStack Foundation
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

from nova.api.openstack import extensions as exts


class Extended_rescue_with_image(exts.ExtensionDescriptor):
    """Allow the user to specify the image to use for rescue."""

    name = "ExtendedRescueWithImage"
    alias = "os-extended-rescue-with-image"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "extended_rescue_with_image/api/v2")
    updated = "2014-01-04T00:00:00Z"
