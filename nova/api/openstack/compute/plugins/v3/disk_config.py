# Copyright 2011 OpenStack Foundation
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

"""Disk Config extension."""

from oslo.utils import strutils
from webob import exc

from nova.api.openstack.compute.schemas.v3 import disk_config
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.i18n import _

ALIAS = 'os-disk-config'
API_DISK_CONFIG = "OS-DCF:diskConfig"
INTERNAL_DISK_CONFIG = "auto_disk_config"
authorize = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)


def disk_config_to_api(value):
    return 'AUTO' if value else 'MANUAL'


def disk_config_from_api(value):
    if value == 'AUTO':
        return True
    elif value == 'MANUAL':
        return False
    else:
        msg = _("%s must be either 'MANUAL' or 'AUTO'.") % API_DISK_CONFIG
        raise exc.HTTPBadRequest(explanation=msg)


class ImageDiskConfigController(wsgi.Controller):
    def _add_disk_config(self, context, images):
        for image in images:
            metadata = image['metadata']
            if INTERNAL_DISK_CONFIG in metadata:
                raw_value = metadata[INTERNAL_DISK_CONFIG]
                value = strutils.bool_from_string(raw_value)
                image[API_DISK_CONFIG] = disk_config_to_api(value)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if 'image' in resp_obj.obj and authorize(context):
            image = resp_obj.obj['image']
            self._add_disk_config(context, [image])

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if 'images' in resp_obj.obj and authorize(context):
            images = resp_obj.obj['images']
            self._add_disk_config(context, images)


class ServerDiskConfigController(wsgi.Controller):
    def _add_disk_config(self, req, servers):
        for server in servers:
            db_server = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show'/'detail' methods.
            value = db_server.get(INTERNAL_DISK_CONFIG)
            server[API_DISK_CONFIG] = disk_config_to_api(value)

    def _show(self, req, resp_obj):
        if 'server' in resp_obj.obj:
            server = resp_obj.obj['server']
            self._add_disk_config(req, [server])

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
            self._add_disk_config(req, servers)

    @wsgi.extends
    def create(self, req, resp_obj, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._show(req, resp_obj)

    @wsgi.extends
    def update(self, req, resp_obj, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._show(req, resp_obj)

    @wsgi.extends(action='rebuild')
    def _action_rebuild(self, req, resp_obj, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._show(req, resp_obj)


class DiskConfig(extensions.V3APIExtensionBase):
    """Disk Management Extension."""

    name = "DiskConfig"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        servers_extension = extensions.ControllerExtension(
                self, 'servers', ServerDiskConfigController())

        images_extension = extensions.ControllerExtension(
                self, 'images', ImageDiskConfigController())

        return [servers_extension, images_extension]

    def get_resources(self):
        return []

    # NOTE(gmann): This function is not supposed to use 'body_deprecated_param'
    # parameter as this is placed to handle scheduler_hint extension for V2.1.
    # making 'body_deprecated_param' as optional to avoid changes for
    # server_update & server_rebuild
    def server_create(self, server_dict, create_kwargs,
                      body_deprecated_param=None):
        if API_DISK_CONFIG in server_dict:
            api_value = server_dict[API_DISK_CONFIG]
            internal_value = disk_config_from_api(api_value)
            create_kwargs[INTERNAL_DISK_CONFIG] = internal_value

    server_update = server_create
    server_rebuild = server_create
    server_resize = server_create

    def get_server_create_schema(self):
        return disk_config.server_create

    get_server_update_schema = get_server_create_schema
    get_server_rebuild_schema = get_server_create_schema
    get_server_resize_schema = get_server_create_schema
