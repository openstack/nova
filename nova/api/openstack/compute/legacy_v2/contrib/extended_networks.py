# Copyright 2014 Nebula, Inc.
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

from nova.api.openstack import extensions


class Extended_networks(extensions.ExtensionDescriptor):
    """Adds additional fields to networks."""

    name = "ExtendedNetworks"
    alias = "os-extended-networks"
    namespace = ("http://docs.openstack.org/compute/ext/extended_networks"
                 "/api/v2")
    updated = "2014-05-09T00:00:00Z"
