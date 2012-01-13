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
        self.resources = {}
        self._setup_routes(mapper)
        self._setup_ext_routes(mapper, ext_mgr)
        self._setup_extensions(ext_mgr)
        super(APIRouter, self).__init__(mapper)

    def _setup_ext_routes(self, mapper, ext_mgr):
        serializer = wsgi.ResponseSerializer(
            {'application/xml': wsgi.XMLDictSerializer()})
        for resource in ext_mgr.get_resources():
            LOG.debug(_('Extended resource: %s'),
                      resource.collection)

            wsgi_resource = wsgi.Resource(
                resource.controller, resource.deserializer,
                resource.serializer)
            self.resources[resource.collection] = wsgi_resource
            kargs = dict(
                controller=wsgi_resource,
                collection=resource.collection_actions,
                member=resource.member_actions)

            if resource.parent:
                kargs['parent_resource'] = resource.parent

            mapper.resource(resource.collection, resource.collection, **kargs)

    def _setup_extensions(self, ext_mgr):
        for extension in ext_mgr.get_controller_extensions():
            ext_name = extension.extension.name
            collection = extension.collection
            controller = extension.controller

            if collection not in self.resources:
                LOG.warning(_('Extension %(ext_name)s: Cannot extend '
                              'resource %(collection)s: No such resource') %
                            locals())
                continue

            LOG.debug(_('Extension %(ext_name)s extending resource: '
                        '%(collection)s') % locals())

            resource = self.resources[collection]
            resource.register_actions(controller)
            resource.register_extensions(controller)

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
