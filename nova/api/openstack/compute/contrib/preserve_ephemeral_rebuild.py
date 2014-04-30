#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from nova.api.openstack import extensions


class Preserve_ephemeral_rebuild(extensions.ExtensionDescriptor):
    """Allow preservation of the ephemeral partition on rebuild."""

    name = "PreserveEphemeralOnRebuild"
    alias = "os-preserve-ephemeral-rebuild"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "preserve_ephemeral_rebuild/api/v2")
    updated = "2013-12-17T00:00:00Z"
