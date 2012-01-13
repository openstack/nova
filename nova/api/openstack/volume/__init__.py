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

import routes
import webob.dec
import webob.exc

import nova.api.openstack
from nova.api.openstack.volume import extensions
from nova.api.openstack.volume import snapshots
from nova.api.openstack.volume import types
from nova.api.openstack.volume import volumes
from nova.api.openstack.volume import versions
from nova.api.openstack import wsgi
from nova import flags
from nova import log as logging
from nova import wsgi as base_wsgi


LOG = logging.getLogger('nova.api.openstack.volume')
FLAGS = flags.FLAGS


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
        serializer = wsgi.ResponseSerializer(
            {'application/xml': wsgi.XMLDictSerializer()})
        for resource in ext_mgr.get_resources():
            LOG.debug(_('Extended resource: %s'),
                      resource.collection)
            if resource.serializer is None:
                resource.serializer = serializer

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

        mapper.resource("volume", "volumes",
                        controller=volumes.create_resource(),
                        collection={'detail': 'GET'})

        mapper.resource("type", "types",
                        controller=types.create_resource())

        mapper.resource("snapshot", "snapshots",
                        controller=snapshots.create_resource())
