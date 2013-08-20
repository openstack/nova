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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil

ALIAS = "os-extended-server-attributes"
authorize = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)


class ExtendedServerAttributesController(wsgi.Controller):
    def _extend_server(self, context, server, instance):
        key = "%s:hypervisor_hostname" % ExtendedServerAttributes.alias
        server[key] = instance['node']

        for attr in ['host', 'name']:
            if attr == 'name':
                key = "%s:instance_%s" % (ExtendedServerAttributes.alias,
                                          attr)
            else:
                key = "%s:%s" % (ExtendedServerAttributes.alias, attr)
            server[key] = instance[attr]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedServerAttributeTemplate())
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
            resp_obj.attach(xml=ExtendedServerAttributesTemplate())

            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(context, server, db_instance)


class ExtendedServerAttributes(extensions.V3APIExtensionBase):
    """Extended Server Attributes support."""

    name = "ExtendedServerAttributes"
    alias = ALIAS
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "extended_server_attributes/api/v3")
    version = 1

    def get_controller_extensions(self):
        controller = ExtendedServerAttributesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []


def make_server(elem):
    elem.set('{%s}instance_name' % ExtendedServerAttributes.namespace,
             '%s:instance_name' % ExtendedServerAttributes.alias)
    elem.set('{%s}host' % ExtendedServerAttributes.namespace,
             '%s:host' % ExtendedServerAttributes.alias)
    elem.set('{%s}hypervisor_hostname' % ExtendedServerAttributes.namespace,
             '%s:hypervisor_hostname' % ExtendedServerAttributes.alias)


class ExtendedServerAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root)
        alias = ExtendedServerAttributes.alias
        namespace = ExtendedServerAttributes.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class ExtendedServerAttributesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        alias = ExtendedServerAttributes.alias
        namespace = ExtendedServerAttributes.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
