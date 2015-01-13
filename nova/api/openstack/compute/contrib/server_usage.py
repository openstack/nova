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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)
authorize = extensions.soft_extension_authorizer('compute', 'server_usage')


class ServerUsageController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ServerUsageController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def _extend_server(self, server, instance):
        for k in ['launched_at', 'terminated_at']:
            key = "%s:%s" % (Server_usage.alias, k)
            # NOTE(danms): Historically, this timestamp has been generated
            # merely by grabbing str(datetime) of a TZ-naive object. The
            # only way we can keep that with instance objects is to strip
            # the tzinfo from the stamp and str() it.
            server[key] = (instance[k].replace(tzinfo=None)
                           if instance[k] else None)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(server, db_instance)


class Server_usage(extensions.ExtensionDescriptor):
    """Adds launched_at and terminated_at on Servers."""

    name = "ServerUsage"
    alias = "OS-SRV-USG"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "server_usage/api/v1.1")
    updated = "2013-04-29T00:00:00Z"

    def get_controller_extensions(self):
        controller = ServerUsageController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
