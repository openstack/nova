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
from nova.api.openstack import wsgi
from nova import objects
from nova.policies import extended_volumes as ev_policies


class ExtendedVolumesController(wsgi.Controller):
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
        key = "os-extended-volumes:volumes_attached"
        server[key] = volumes_attached

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if context.can(ev_policies.BASE_POLICY_NAME, fatal=False):
            server = resp_obj.obj['server']
            bdms = objects.BlockDeviceMappingList.bdms_by_instance_uuid(
                context, [server['id']])
            instance_bdms = self._get_instance_bdms(bdms, server)
            self._extend_server(context, server, req, instance_bdms)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if context.can(ev_policies.BASE_POLICY_NAME, fatal=False):
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
