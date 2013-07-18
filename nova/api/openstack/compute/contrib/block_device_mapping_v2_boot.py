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


class Block_device_mapping_v2_boot(extensions.ExtensionDescriptor):
    """Allow boot with the new BDM data format."""

    name = "BlockDeviceMappingV2Boot"
    alias = "os-block-device-mapping-v2-boot"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "block_device_mapping_v2_boot/api/v2")
    updated = "2013-07-08T00:00:00+00:00"
