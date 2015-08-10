# Copyright 2013 OpenStack Foundation
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

from nova.api.openstack import extensions


class Baremetal_ext_status(extensions.ExtensionDescriptor):
    """Add extended status in Baremetal Nodes v2 API."""

    name = "BareMetalExtStatus"
    alias = "os-baremetal-ext-status"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "baremetal_ext_status/api/v2")
    updated = "2013-08-27T00:00:00Z"
