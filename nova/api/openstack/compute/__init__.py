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
WSGI middleware for OpenStack API controllers.
"""

import routes
import webob.dec
import webob.exc

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
from nova.api.openstack import wsgi
from nova import flags
from nova import log as logging
from nova import wsgi as base_wsgi


LOG = logging.getLogger('nova.api.openstack.compute')
FLAGS = flags.FLAGS
flags.DEFINE_bool('allow_admin_api',
    False,
    'When True, this API service will accept admin operations.')
flags.DEFINE_bool('allow_instance_snapshots',
    True,
    'When True, this API service will permit instance snapshot operations.')


class APIRouter(base_wsgi.Router):
    """
    Routes requests on the OpenStack API to the appropriate controller
    and method.
    """

    @classmethod
    def factory(cls, global_config, **local_config):
        """Simple paste factory, :class:`nova.wsgi.Router` doesn't have one"""
        return cls()

    def __init__(self, ext_mgr=None):
        if ext_mgr is None:
            ext_mgr = extensions.ExtensionManager()

        mapper = nova.api.openstack.ProjectMapper()
        self._setup_routes(mapper)
        self._setup_ext_routes(mapper, ext_mgr)
        super(APIRouter, self).__init__(mapper)

    def _setup_ext_routes(self, mapper, ext_mgr):
        for resource in ext_mgr.get_resources():
            LOG.debug(_('Extended resource: %s'),
                      resource.collection)

            kargs = dict(
                controller=wsgi.Resource(
                    resource.controller, resource.deserializer,
                    resource.serializer),
                collection=resource.collection_actions,
                member=resource.member_actions)

            if resource.parent:
                kargs['parent_resource'] = resource.parent

            mapper.resource(resource.collection, resource.collection, **kargs)

    def _setup_routes(self, mapper):
        mapper.connect("versions", "/",
                    controller=versions.create_resource(),
                    action='show')

        mapper.redirect("", "/")

        mapper.resource("console", "consoles",
                    controller=consoles.create_resource(),
                    parent_resource=dict(member_name='server',
                    collection_name='servers'))

        mapper.resource("server", "servers",
                        controller=servers.create_resource(),
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})

        mapper.resource("ip", "ips", controller=ips.create_resource(),
                        parent_resource=dict(member_name='server',
                                             collection_name='servers'))

        mapper.resource("image", "images",
                        controller=images.create_resource(),
                        collection={'detail': 'GET'})

        mapper.resource("limit", "limits",
                        controller=limits.create_resource())

        mapper.resource("flavor", "flavors",
                        controller=flavors.create_resource(),
                        collection={'detail': 'GET'})

        image_metadata_controller = image_metadata.create_resource()

        mapper.resource("image_meta", "metadata",
                        controller=image_metadata_controller,
                        parent_resource=dict(member_name='image',
                        collection_name='images'))

        mapper.connect("metadata", "/{project_id}/images/{image_id}/metadata",
                       controller=image_metadata_controller,
                       action='update_all',
                       conditions={"method": ['PUT']})

        server_metadata_controller = server_metadata.create_resource()

        mapper.resource("server_meta", "metadata",
                        controller=server_metadata_controller,
                        parent_resource=dict(member_name='server',
                        collection_name='servers'))

        mapper.connect("metadata",
                       "/{project_id}/servers/{server_id}/metadata",
                       controller=server_metadata_controller,
                       action='update_all',
                       conditions={"method": ['PUT']})
