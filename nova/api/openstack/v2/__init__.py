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

from nova.api.openstack.v2 import accounts
from nova.api.openstack.v2 import consoles
from nova.api.openstack.v2 import flavors
from nova.api.openstack.v2 import images
from nova.api.openstack.v2 import image_metadata
from nova.api.openstack.v2 import ips
from nova.api.openstack.v2 import limits
from nova.api.openstack.v2 import servers
from nova.api.openstack.v2 import server_metadata
from nova.api.openstack.v2 import users
from nova.api.openstack.v2 import versions
from nova.api.openstack.v2 import zones
from nova.api.openstack import wsgi
from nova import flags
from nova import log as logging
from nova import wsgi as base_wsgi


LOG = logging.getLogger('nova.api.openstack.v2')
FLAGS = flags.FLAGS
flags.DEFINE_bool('allow_admin_api',
    False,
    'When True, this API service will accept admin operations.')
flags.DEFINE_bool('allow_instance_snapshots',
    True,
    'When True, this API service will permit instance snapshot operations.')


class FaultWrapper(base_wsgi.Middleware):
    """Calls down the middleware stack, making exceptions into faults."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        try:
            return req.get_response(self.application)
        except Exception as ex:
            LOG.exception(_("Caught error: %s"), unicode(ex))
            exc = webob.exc.HTTPInternalServerError()
            return wsgi.Fault(exc)


class APIMapper(routes.Mapper):
    def routematch(self, url=None, environ=None):
        if url is "":
            result = self._match("", environ)
            return result[0], result[1]
        return routes.Mapper.routematch(self, url, environ)


class ProjectMapper(APIMapper):

    def resource(self, member_name, collection_name, **kwargs):
        if not ('parent_resource' in kwargs):
            kwargs['path_prefix'] = '{project_id}/'
        else:
            parent_resource = kwargs['parent_resource']
            p_collection = parent_resource['collection_name']
            p_member = parent_resource['member_name']
            kwargs['path_prefix'] = '{project_id}/%s/:%s_id' % (p_collection,
                                                               p_member)
        routes.Mapper.resource(self, member_name,
                                     collection_name,
                                     **kwargs)


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
        self.server_members = {}
        mapper = ProjectMapper()
        self._setup_routes(mapper)
        super(APIRouter, self).__init__(mapper)

    def _setup_routes(self, mapper):
        server_members = self.server_members
        server_members['action'] = 'POST'
        if FLAGS.allow_admin_api:
            LOG.debug(_("Including admin operations in API."))

            server_members['diagnostics'] = 'GET'
            server_members['actions'] = 'GET'

            mapper.resource("user", "users",
                        controller=users.create_resource(),
                        collection={'detail': 'GET'})

            mapper.resource("account", "accounts",
                            controller=accounts.create_resource(),
                            collection={'detail': 'GET'})

            mapper.resource("zone", "zones",
                        controller=zones.create_resource(),
                        collection={'detail': 'GET',
                                    'info': 'GET',
                                    'select': 'POST'})

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
                        member=self.server_members)

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
