# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.openstack.common.gettextutils import _

ALIAS = 'os-disk-config'
XMLNS_DCF = "http://docs.openstack.org/compute/ext/disk_config/api/v3"
API_DISK_CONFIG = "%s:disk_config" % ALIAS
INTERNAL_DISK_CONFIG = "auto_disk_config"
authorize = extensions.soft_extension_authorizer('compute',
                                                 'v3:' + ALIAS)


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


class ServerDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        root.set('{%s}disk_config' % XMLNS_DCF, API_DISK_CONFIG)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ServersDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        elem.set('{%s}disk_config' % XMLNS_DCF, API_DISK_CONFIG)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


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
            resp_obj.attach(xml=ServerDiskConfigTemplate())
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
            resp_obj.attach(xml=ServersDiskConfigTemplate())
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


class DiskConfig(extensions.V3APIExtensionBase):
    """Disk Management Extension."""

    name = "DiskConfig"
    alias = ALIAS
    namespace = XMLNS_DCF
    version = 1

    def get_controller_extensions(self):
        servers_extension = extensions.ControllerExtension(
            self, 'servers', ServerDiskConfigController())

        return [servers_extension]

    def get_resources(self):
        return []

    def server_create(self, server_dict, create_kwargs):
        create_kwargs['auto_disk_config'] = server_dict.get(
            'auto_disk_config')

    def server_xml_extract_server_deserialize(self, server_node, server_dict):
        auto_disk_config =\
            server_node.getAttribute('os-disk-config:disk_config')
        if auto_disk_config:
            server_dict['os-disk-config:disk_config'] = auto_disk_config

    def server_rebuild(self, rebuild_dict, rebuild_kwargs):
        if 'auto_disk_config' in rebuild_dict:
            rebuild_kwargs['auto_disk_config'] = rebuild_dict[
                'auto_disk_config']

    def server_xml_extract_rebuild_deserialize(self, rebuild_node,
                                               rebuild_dict):
        if rebuild_node.hasAttribute("os-disk-config:disk_config"):
            rebuild_dict['os-disk-config:disk_config'] =\
                rebuild_node.getAttribute("os-disk-config:disk_config")

    def server_resize(self, resize_dict, resize_kwargs):
        if 'auto_disk_config' in resize_dict:
            resize_kwargs['auto_disk_config'] = resize_dict[
                'auto_disk_config']

    def server_xml_extract_resize_deserialize(self, resize_node,
                                              resize_dict):
        if resize_node.hasAttribute("os-disk-config:disk_config"):
            resize_dict['os-disk-config:disk_config'] =\
                resize_node.getAttribute("os-disk-config:disk_config")

    def server_update(self, update_dict, update_kwargs):
        if 'auto_disk_config' in update_dict:
            update_kwargs['auto_disk_config'] = update_dict['auto_disk_config']
