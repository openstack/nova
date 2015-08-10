# Copyright 2012 OpenStack Foundation
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

"""Config Drive extension."""

from nova.api.openstack.compute.legacy_v2 import servers
from nova.api.openstack import extensions
from nova.api.openstack import wsgi

authorize = extensions.soft_extension_authorizer('compute', 'config_drive')


class Controller(servers.Controller):

    def _add_config_drive(self, req, servers):
        for server in servers:
            db_server = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show'/'detail' methods.
            server['config_drive'] = db_server['config_drive']

    def _show(self, req, resp_obj):
        if 'server' in resp_obj.obj:
            server = resp_obj.obj['server']
            self._add_config_drive(req, [server])

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            self._show(req, resp_obj)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if 'servers' in resp_obj.obj and authorize(context):
            servers = resp_obj.obj['servers']
            self._add_config_drive(req, servers)


class Config_drive(extensions.ExtensionDescriptor):
    """Config Drive Extension."""

    name = "ConfigDrive"
    alias = "os-config-drive"
    namespace = "http://docs.openstack.org/compute/ext/config_drive/api/v1.1"
    updated = "2012-07-16T00:00:00Z"

    def get_controller_extensions(self):
        controller = Controller(self.ext_mgr)
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
