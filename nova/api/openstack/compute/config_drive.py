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

from nova.api.openstack.compute.schemas import config_drive as \
                                                  schema_config_drive
from nova.api.openstack import extensions
from nova.api.openstack import wsgi

ALIAS = "os-config-drive"
ATTRIBUTE_NAME = "config_drive"
authorize = extensions.os_compute_soft_authorizer(ALIAS)


class ConfigDriveController(wsgi.Controller):

    def _add_config_drive(self, req, servers):
        for server in servers:
            db_server = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show'/'detail' methods.
            server[ATTRIBUTE_NAME] = db_server['config_drive']

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


class ConfigDrive(extensions.V21APIExtensionBase):
    """Config Drive Extension."""

    name = "ConfigDrive"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = ConfigDriveController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []

    # NOTE(gmann): This function is not supposed to use 'body_deprecated_param'
    # parameter as this is placed to handle scheduler_hint extension for V2.1.
    def server_create(self, server_dict, create_kwargs, body_deprecated_param):
        create_kwargs['config_drive'] = server_dict.get(ATTRIBUTE_NAME)

    def get_server_create_schema(self, version):
        return schema_config_drive.server_create
