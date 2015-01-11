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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.i18n import _

ALIAS = 'OS-DCF'
XMLNS_DCF = "http://docs.openstack.org/compute/ext/disk_config/api/v1.1"
API_DISK_CONFIG = "%s:diskConfig" % ALIAS
INTERNAL_DISK_CONFIG = "auto_disk_config"
authorize = extensions.soft_extension_authorizer('compute', 'disk_config')


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

    def _set_disk_config(self, dict_):
        if API_DISK_CONFIG in dict_:
            api_value = dict_[API_DISK_CONFIG]
            internal_value = disk_config_from_api(api_value)
            dict_[INTERNAL_DISK_CONFIG] = internal_value

    @wsgi.extends
    def create(self, req, body):
        context = req.environ['nova.context']
        if authorize(context):
            if 'server' in body:
                self._set_disk_config(body['server'])
            resp_obj = (yield)
            self._show(req, resp_obj)

    @wsgi.extends
    def update(self, req, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            if 'server' in body:
                self._set_disk_config(body['server'])
            resp_obj = (yield)
            self._show(req, resp_obj)

    @wsgi.extends(action='rebuild')
    def _action_rebuild(self, req, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._set_disk_config(body['rebuild'])
            resp_obj = (yield)
            self._show(req, resp_obj)

    @wsgi.extends(action='resize')
    def _action_resize(self, req, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._set_disk_config(body['resize'])
            yield


class Disk_config(extensions.ExtensionDescriptor):
    """Disk Management Extension."""

    name = "DiskConfig"
    alias = ALIAS
    namespace = XMLNS_DCF
    updated = "2011-09-27T00:00:00Z"

    def get_controller_extensions(self):
        servers_extension = extensions.ControllerExtension(
                self, 'servers', ServerDiskConfigController())

        images_extension = extensions.ControllerExtension(
                self, 'images', ImageDiskConfigController())

        return [servers_extension, images_extension]
