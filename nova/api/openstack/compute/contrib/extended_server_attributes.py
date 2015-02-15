#   Copyright 2012 OpenStack Foundation
#
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

"""The Extended Server Attributes API extension."""

from nova.api.openstack import extensions
from nova.api.openstack import wsgi

authorize = extensions.soft_extension_authorizer('compute',
                                                 'extended_server_attributes')


class ExtendedServerAttributesController(wsgi.Controller):
    def _extend_server(self, context, server, instance):
        key = "%s:hypervisor_hostname" % Extended_server_attributes.alias
        server[key] = instance.node

        for attr in ['host', 'name']:
            if attr == 'name':
                key = "%s:instance_%s" % (Extended_server_attributes.alias,
                                          attr)
            else:
                key = "%s:%s" % (Extended_server_attributes.alias, attr)
            server[key] = instance[attr]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(context, server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(context, server, db_instance)


class Extended_server_attributes(extensions.ExtensionDescriptor):
    """Extended Server Attributes support."""

    name = "ExtendedServerAttributes"
    alias = "OS-EXT-SRV-ATTR"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "extended_status/api/v1.1")
    updated = "2011-11-03T00:00:00Z"

    def get_controller_extensions(self):
        controller = ExtendedServerAttributesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
