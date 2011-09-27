# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

"""The zones extension."""


from nova import flags
from nova import log as logging
from nova.api.openstack import extensions


LOG = logging.getLogger("nova.api.zones")
FLAGS = flags.FLAGS


class Zones(extensions.ExtensionDescriptor):
    def get_name(self):
        return "Zones"

    def get_alias(self):
        return "os-zones"

    def get_description(self):
        return """Enables zones-related functionality such as adding
child zones, listing child zones, getting the capabilities of the
local zone, and returning build plans to parent zones' schedulers"""

    def get_namespace(self):
        return "http://docs.openstack.org/ext/zones/api/v1.1"

    def get_updated(self):
        return "2011-09-21T00:00:00+00:00"

    def get_resources(self):
        # Nothing yet.
        return []
