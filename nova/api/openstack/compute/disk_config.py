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

from oslo_utils import strutils
from webob import exc

from nova.api.openstack.compute.schemas import disk_config
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.i18n import _

ALIAS = 'os-disk-config'
API_DISK_CONFIG = "OS-DCF:diskConfig"
INTERNAL_DISK_CONFIG = "auto_disk_config"
authorize = extensions.os_compute_soft_authorizer(ALIAS)


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


class DiskConfig(extensions.V21APIExtensionBase):
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

    def _extend_server(self, server_dict, create_kwargs):
        """Extends server create/update/rebuild/resize.

        This extends the server create/update/rebuild/resize
        operations to add disk_config into the mix. Because all these
        methods act similarly a common method is used.

        """
        if API_DISK_CONFIG in server_dict:
            api_value = server_dict[API_DISK_CONFIG]
            internal_value = disk_config_from_api(api_value)
            create_kwargs[INTERNAL_DISK_CONFIG] = internal_value

    # Extend server for the 4 extended points
    def server_create(self, server_dict, create_kwargs, body_deprecated):
        self._extend_server(server_dict, create_kwargs)

    def server_update(self, server_dict, update_kwargs):
        self._extend_server(server_dict, update_kwargs)

    def server_rebuild(self, server_dict, rebuild_kwargs):
        self._extend_server(server_dict, rebuild_kwargs)

    def server_resize(self, server_dict, resize_kwargs):
        self._extend_server(server_dict, resize_kwargs)

    # Extend schema for the 4 extended points
    def get_server_create_schema(self, version):
        return disk_config.server_create

    def get_server_update_schema(self, version):
        return disk_config.server_create

    def get_server_rebuild_schema(self, version):
        return disk_config.server_create

    def get_server_resize_schema(self, version):
        return disk_config.server_create
