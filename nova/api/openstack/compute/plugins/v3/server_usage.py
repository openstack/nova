#   Copyright 2013 Openstack Foundation
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
from nova.api.openstack import xmlutil
from nova import compute
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

ALIAS = "os-server-usage"
authorize = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)


class ServerUsageController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ServerUsageController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def _extend_server(self, server, instance):
        for k in ['launched_at', 'terminated_at']:
            key = "%s:%s" % (ServerUsage.alias, k)
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
            # Attach our slave template to the response object
            resp_obj.attach(xml=ServerUsageTemplate())
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ServerUsagesTemplate())
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(server, db_instance)


class ServerUsage(extensions.V3APIExtensionBase):
    """Adds launched_at and terminated_at on Servers."""

    name = "ServerUsage"
    alias = ALIAS
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "os-server-usage/api/v3")
    version = 1

    def get_controller_extensions(self):
        controller = ServerUsageController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []


def make_server(elem):
    elem.set('{%s}launched_at' % ServerUsage.namespace,
             '%s:launched_at' % ServerUsage.alias)
    elem.set('{%s}terminated_at' % ServerUsage.namespace,
             '%s:terminated_at' % ServerUsage.alias)


class ServerUsageTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            ServerUsage.alias: ServerUsage.namespace})


class ServerUsagesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            ServerUsage.alias: ServerUsage.namespace})
