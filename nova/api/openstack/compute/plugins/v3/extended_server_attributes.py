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

from nova.api.openstack import api_version_request
from nova.api.openstack import extensions
from nova.api.openstack import wsgi


ALIAS = "os-extended-server-attributes"
authorize = extensions.os_compute_soft_authorizer(ALIAS)


class ExtendedServerAttributesController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ExtendedServerAttributesController, self).__init__(*args,
                                                                 **kwargs)
        self.api_version_2_3 = api_version_request.APIVersionRequest('2.3')

    def _extend_server(self, context, server, instance, requested_version):
        key = "OS-EXT-SRV-ATTR:hypervisor_hostname"
        server[key] = instance.node

        properties = ['host', 'name']
        if requested_version >= self.api_version_2_3:
            properties += ['reservation_id', 'launch_index',
                           'hostname', 'kernel_id', 'ramdisk_id',
                           'root_device_name', 'user_data']
        for attr in properties:
            if attr == 'name':
                key = "OS-EXT-SRV-ATTR:instance_%s" % attr
            else:
                key = "OS-EXT-SRV-ATTR:%s" % attr
            server[key] = instance[attr]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(context, server, db_instance,
                                req.api_version_request)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(context, server, db_instance,
                                    req.api_version_request)


class ExtendedServerAttributes(extensions.V3APIExtensionBase):
    """Extended Server Attributes support."""

    name = "ExtendedServerAttributes"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = ExtendedServerAttributesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
