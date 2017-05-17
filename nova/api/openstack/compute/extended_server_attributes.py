#   Copyright 2012 OpenStack Foundation
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

"""The Extended Server Attributes API extension."""

from nova.api.openstack import api_version_request
from nova.api.openstack import wsgi
from nova import compute
from nova.policies import extended_server_attributes as esa_policies
from nova.policies import servers as servers_policies


class ExtendedServerAttributesController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ExtendedServerAttributesController, self).__init__(*args,
                                                                 **kwargs)
        self.compute_api = compute.API()

    def _extend_server(self, context, server, instance, req):
        key = "OS-EXT-SRV-ATTR:hypervisor_hostname"
        server[key] = instance.node

        properties = ['host', 'name']
        if api_version_request.is_supported(req, min_version='2.3'):
            # NOTE(mriedem): These will use the OS-EXT-SRV-ATTR prefix below
            # and that's OK for microversion 2.3 which is being compatible
            # with v2.0 for the ec2 API split out from Nova. After this,
            # however, new microversions should not be using the
            # OS-EXT-SRV-ATTR prefix.
            properties += ['reservation_id', 'launch_index',
                           'hostname', 'kernel_id', 'ramdisk_id',
                           'root_device_name', 'user_data']
        for attr in properties:
            if attr == 'name':
                key = "OS-EXT-SRV-ATTR:instance_%s" % attr
            else:
                # NOTE(mriedem): Nothing after microversion 2.3 should use the
                # OS-EXT-SRV-ATTR prefix for the attribute key name.
                key = "OS-EXT-SRV-ATTR:%s" % attr
            server[key] = instance[attr]

    def _server_host_status(self, context, server, instance, req):
        host_status = self.compute_api.get_instance_host_status(instance)
        server['host_status'] = host_status

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        authorize_extend = False
        authorize_host_status = False
        if context.can(esa_policies.BASE_POLICY_NAME, fatal=False):
            authorize_extend = True
        if (api_version_request.is_supported(req, min_version='2.16') and
            context.can(servers_policies.SERVERS % 'show:host_status',
                        fatal=False)):
            authorize_host_status = True
        if authorize_extend or authorize_host_status:
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            if authorize_extend:
                self._extend_server(context, server, db_instance, req)
            if authorize_host_status:
                self._server_host_status(context, server, db_instance, req)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        authorize_extend = False
        authorize_host_status = False
        if context.can(esa_policies.BASE_POLICY_NAME, fatal=False):
            authorize_extend = True
        if (api_version_request.is_supported(req, min_version='2.16') and
            context.can(servers_policies.SERVERS % 'show:host_status',
                        fatal=False)):
            authorize_host_status = True
        if authorize_extend or authorize_host_status:
            servers = list(resp_obj.obj['servers'])
            # NOTE(dinesh-bhor): Skipping fetching of instances from cache as
            # servers list can be empty if invalid status is provided to the
            # core API 'detail' method.
            if servers:
                instances = req.get_db_instances()
                if authorize_host_status:
                    host_statuses = (
                        self.compute_api.get_instances_host_statuses(
                                instances.values()))
                for server in servers:
                    if authorize_extend:
                        instance = instances[server['id']]
                        self._extend_server(context, server, instance, req)
                    if authorize_host_status:
                        server['host_status'] = host_statuses[server['id']]
