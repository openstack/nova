# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
#    under the License

"""Disk Config extension."""

from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import db
from nova import utils

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
        msg = _("%s must be either 'MANUAL' or 'AUTO'." % API_DISK_CONFIG)
        raise exc.HTTPBadRequest(explanation=msg)


class ImageDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('image')
        root.set('{%s}diskConfig' % XMLNS_DCF, API_DISK_CONFIG)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ImagesDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('images')
        elem = xmlutil.SubTemplateElement(root, 'image', selector='images')
        elem.set('{%s}diskConfig' % XMLNS_DCF, API_DISK_CONFIG)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ImageDiskConfigController(wsgi.Controller):
    def _add_disk_config(self, context, images):
        for image in images:
            metadata = image['metadata']
            if INTERNAL_DISK_CONFIG in metadata:
                raw_value = metadata[INTERNAL_DISK_CONFIG]
                value = utils.bool_from_str(raw_value)
                image[API_DISK_CONFIG] = disk_config_to_api(value)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if 'image' in resp_obj.obj and authorize(context):
            resp_obj.attach(xml=ImageDiskConfigTemplate())
            image = resp_obj.obj['image']
            self._add_disk_config(context, [image])

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if 'images' in resp_obj.obj and authorize(context):
            resp_obj.attach(xml=ImagesDiskConfigTemplate())
            images = resp_obj.obj['images']
            self._add_disk_config(context, images)


class ServerDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        root.set('{%s}diskConfig' % XMLNS_DCF, API_DISK_CONFIG)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ServersDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        elem.set('{%s}diskConfig' % XMLNS_DCF, API_DISK_CONFIG)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ServerDiskConfigController(wsgi.Controller):
    def _add_disk_config(self, context, servers):
        # Filter out any servers that already have the key set
        # (most likely from a remote zone)
        servers = [s for s in servers if API_DISK_CONFIG not in s]
        if not servers:
            return

        # Get DB information for servers
        uuids = [server['id'] for server in servers]
        db_servers = db.instance_get_all_by_filters(context,
                                                    {'uuid': uuids})
        db_servers_by_uuid = dict((s['uuid'], s) for s in db_servers)

        for server in servers:
            db_server = db_servers_by_uuid.get(server['id'])
            if db_server:
                value = db_server[INTERNAL_DISK_CONFIG]
                server[API_DISK_CONFIG] = disk_config_to_api(value)

    def _show(self, context, resp_obj):
        if 'server' in resp_obj.obj:
            resp_obj.attach(xml=ServerDiskConfigTemplate())
            server = resp_obj.obj['server']
            self._add_disk_config(context, [server])

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            self._show(context, resp_obj)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if 'servers' in resp_obj.obj and authorize(context):
            resp_obj.attach(xml=ServersDiskConfigTemplate())
            servers = resp_obj.obj['servers']
            self._add_disk_config(context, servers)

    def _set_disk_config(self, dict_):
        if API_DISK_CONFIG in dict_:
            api_value = dict_[API_DISK_CONFIG]
            internal_value = disk_config_from_api(api_value)
            dict_[INTERNAL_DISK_CONFIG] = internal_value

    @wsgi.extends
    def create(self, req, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._set_disk_config(body['server'])
            resp_obj = (yield)
            self._show(context, resp_obj)

    @wsgi.extends
    def update(self, req, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._set_disk_config(body['server'])
            resp_obj = (yield)
            self._show(context, resp_obj)

    @wsgi.extends(action='rebuild')
    def _action_rebuild(self, req, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._set_disk_config(body['rebuild'])
            resp_obj = (yield)
            self._show(context, resp_obj)

    @wsgi.extends(action='resize')
    def _action_resize(self, req, id, body):
        context = req.environ['nova.context']
        if authorize(context):
            self._set_disk_config(body['resize'])
            yield


class Disk_config(extensions.ExtensionDescriptor):
    """Disk Management Extension"""

    name = "DiskConfig"
    alias = ALIAS
    namespace = XMLNS_DCF
    updated = "2011-09-27:00:00+00:00"

    def get_controller_extensions(self):
        servers_extension = extensions.ControllerExtension(
                self, 'servers', ServerDiskConfigController())

        images_extension = extensions.ControllerExtension(
                self, 'images', ImageDiskConfigController())

        return [servers_extension, images_extension]
