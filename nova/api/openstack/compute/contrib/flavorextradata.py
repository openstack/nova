# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Canonical Ltd.
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

"""
The Flavor extra data extension
Openstack API version 1.1 lists "name", "ram", "disk", "vcpus" as flavor
attributes.  This extension adds to that list:
   rxtx_cap
   rxtx_quota
   swap
"""

from nova.api.openstack import extensions


class Flavorextradata(extensions.ExtensionDescriptor):
    """Provide additional data for flavors"""

    name = "FlavorExtraData"
    alias = "os-flavor-extra-data"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "flavor_extra_data/api/v1.1"
    updated = "2011-09-14T00:00:00+00:00"
