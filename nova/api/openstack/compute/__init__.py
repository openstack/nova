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
WSGI middleware for OpenStack Compute API.
"""

import nova.api.openstack
from nova.api.openstack.compute import consoles
from nova.api.openstack.compute import extensions
from nova.api.openstack.compute import flavors
from nova.api.openstack.compute import images
from nova.api.openstack.compute import image_metadata
from nova.api.openstack.compute import ips
from nova.api.openstack.compute import limits
from nova.api.openstack.compute import servers
from nova.api.openstack.compute import server_metadata
from nova.api.openstack.compute import versions
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg


LOG = logging.getLogger('nova.api.openstack.compute')

allow_instance_snapshots_opt = \
    cfg.BoolOpt('allow_instance_snapshots',
                default=True,
                help='Permit instance snapshot operations.')

FLAGS = flags.FLAGS
FLAGS.register_opt(allow_instance_snapshots_opt)


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

        self.resources['consoles'] = consoles.create_resource()
        mapper.resource("console", "consoles",
                    controller=self.resources['consoles'],
                    parent_resource=dict(member_name='server',
                    collection_name='servers'))

        self.resources['servers'] = servers.create_resource()
        mapper.resource("server", "servers",
                        controller=self.resources['servers'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})

        self.resources['ips'] = ips.create_resource()
        mapper.resource("ip", "ips", controller=self.resources['ips'],
                        parent_resource=dict(member_name='server',
                                             collection_name='servers'))

        self.resources['images'] = images.create_resource()
        mapper.resource("image", "images",
                        controller=self.resources['images'],
                        collection={'detail': 'GET'})

        self.resources['limits'] = limits.create_resource()
        mapper.resource("limit", "limits",
                        controller=self.resources['limits'])

        self.resources['flavors'] = flavors.create_resource()
        mapper.resource("flavor", "flavors",
                        controller=self.resources['flavors'],
                        collection={'detail': 'GET'})

        self.resources['image_metadata'] = image_metadata.create_resource()
        image_metadata_controller = self.resources['image_metadata']

        mapper.resource("image_meta", "metadata",
                        controller=image_metadata_controller,
                        parent_resource=dict(member_name='image',
                        collection_name='images'))

        mapper.connect("metadata", "/{project_id}/images/{image_id}/metadata",
                       controller=image_metadata_controller,
                       action='update_all',
                       conditions={"method": ['PUT']})

        self.resources['server_metadata'] = server_metadata.create_resource()
        server_metadata_controller = self.resources['server_metadata']

        mapper.resource("server_meta", "metadata",
                        controller=server_metadata_controller,
                        parent_resource=dict(member_name='server',
                        collection_name='servers'))

        mapper.connect("metadata",
                       "/{project_id}/servers/{server_id}/metadata",
                       controller=server_metadata_controller,
                       action='update_all',
                       conditions={"method": ['PUT']})
