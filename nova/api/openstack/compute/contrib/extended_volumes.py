#   Copyright 2013 OpenStack Foundation
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

"""The Extended Volumes API extension."""

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova.objects import block_device as block_device_obj

authorize = extensions.soft_extension_authorizer('compute', 'extended_volumes')


class ExtendedVolumesController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ExtendedVolumesController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def _extend_server(self, context, server, instance):
        bdms = block_device_obj.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance['uuid'])
        volume_ids = [bdm.volume_id for bdm in bdms if bdm.volume_id]
        key = "%s:volumes_attached" % Extended_volumes.alias
        server[key] = [{'id': volume_id} for volume_id in volume_ids]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedVolumesServerTemplate())
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(context, server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedVolumesServersTemplate())
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(context, server, db_instance)


class Extended_volumes(extensions.ExtensionDescriptor):
    """Extended Volumes support."""

    name = "ExtendedVolumes"
    alias = "os-extended-volumes"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "extended_volumes/api/v1.1")
    updated = "2013-06-07T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedVolumesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []


def make_server(elem):
    volumes = xmlutil.SubTemplateElement(
        elem, '{%s}volume_attached' % Extended_volumes.namespace,
        selector='%s:volumes_attached' % Extended_volumes.alias)
    volumes.set('id')


class ExtendedVolumesServerTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Extended_volumes.alias: Extended_volumes.namespace})


class ExtendedVolumesServersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Extended_volumes.alias: Extended_volumes.namespace})
