# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
WSGI middleware for OpenStack Volume API.
"""

import nova.api.openstack
from nova.api.openstack.volume import extensions
from nova.api.openstack.volume import snapshots
from nova.api.openstack.volume import types
from nova.api.openstack.volume import volumes
from nova.api.openstack.volume import versions
from nova import log as logging


LOG = logging.getLogger(__name__)


class APIRouter(nova.api.openstack.APIRouter):
    """
    Routes requests on the OpenStack API to the appropriate controller
    and method.
    """
    ExtensionManager = extensions.ExtensionManager

    def _setup_routes(self, mapper):
        self.resources['versions'] = versions.create_resource()
        mapper.connect("versions", "/",
                    controller=self.resources['versions'],
                    action='show')

        mapper.redirect("", "/")

        self.resources['volumes'] = volumes.create_resource()
        mapper.resource("volume", "volumes",
                        controller=self.resources['volumes'],
                        collection={'detail': 'GET'})

        self.resources['types'] = types.create_resource()
        mapper.resource("type", "types",
                        controller=self.resources['types'])

        self.resources['snapshots'] = snapshots.create_resource()
        mapper.resource("snapshot", "snapshots",
                        controller=self.resources['snapshots'])
