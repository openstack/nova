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
from nova.api.openstack import api_version_request
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import objects

ALIAS = "os-extended-volumes"
soft_authorize = extensions.os_compute_soft_authorizer(ALIAS)


class ExtendedVolumesController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ExtendedVolumesController, self).__init__(*args, **kwargs)

    def _extend_server(self, context, server, req, bdms):
        volumes_attached = []
        for bdm in bdms:
            if bdm.get('volume_id'):
                volume_attached = {'id': bdm['volume_id']}
                if api_version_request.is_supported(req, min_version='2.3'):
                    volume_attached['delete_on_termination'] = (
                        bdm['delete_on_termination'])
                volumes_attached.append(volume_attached)
        # NOTE(mriedem): The os-extended-volumes prefix should not be used for
        # new attributes after v2.1. They are only in v2.1 for backward compat
        # with v2.0.
        key = "%s:volumes_attached" % ExtendedVolumes.alias
        server[key] = volumes_attached

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if soft_authorize(context):
            server = resp_obj.obj['server']
            bdms = objects.BlockDeviceMappingList.bdms_by_instance_uuid(
                context, [server['id']])
            instance_bdms = self._get_instance_bdms(bdms, server)
            self._extend_server(context, server, req, instance_bdms)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if soft_authorize(context):
            servers = list(resp_obj.obj['servers'])
            instance_uuids = [server['id'] for server in servers]
            bdms = objects.BlockDeviceMappingList.bdms_by_instance_uuid(
                context, instance_uuids)
            for server in servers:
                instance_bdms = self._get_instance_bdms(bdms, server)
                self._extend_server(context, server, req, instance_bdms)

    def _get_instance_bdms(self, bdms, server):
        # server['id'] is guaranteed to be in the cache due to
        # the core API adding it in the 'detail' or 'show' method.
        # If that instance has since been deleted, it won't be in the
        # 'bdms' dictionary though, so use 'get' to avoid KeyErrors.
        return bdms.get(server['id'], [])


class ExtendedVolumes(extensions.V21APIExtensionBase):
    """Extended Volumes support."""

    name = "ExtendedVolumes"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = ExtendedVolumesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
