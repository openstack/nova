#   Copyright 2012 Openstack, LLC.
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

from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception
from nova import flags
from nova import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api.openstack.compute.contrib."
                        "extended_server_attributes")
authorize = extensions.soft_extension_authorizer('compute',
                                                 'extended_server_attributes')


class ExtendedServerAttributesController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ExtendedServerAttributesController, self).__init__(*args,
                                                                 **kwargs)
        self.compute_api = compute.API()

    def _get_instances(self, context, instance_uuids):
        filters = {'uuid': instance_uuids}
        instances = self.compute_api.get_all(context, filters)
        return dict((instance['uuid'], instance) for instance in instances)

    def _extend_server(self, server, instance):
        for attr in ['host', 'name']:
            if attr == 'name':
                key = "%s:instance_%s" % (Extended_server_attributes.alias,
                                          attr)
            else:
                key = "%s:%s" % (Extended_server_attributes.alias, attr)
            server[key] = instance[attr]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedServerAttributesTemplate())

            try:
                instance = self.compute_api.get(context, id)
            except exception.NotFound:
                explanation = _("Server not found.")
                raise exc.HTTPNotFound(explanation=explanation)

            self._extend_server(resp_obj.obj['server'], instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedServerAttributesTemplate())

            servers = list(resp_obj.obj['servers'])
            instance_uuids = [server['id'] for server in servers]
            instances = self._get_instances(context, instance_uuids)

            for server_object in servers:
                try:
                    instance_data = instances[server_object['id']]
                except KeyError:
                    # Ignore missing instance data
                    continue

                self._extend_server(server_object, instance_data)


class Extended_server_attributes(extensions.ExtensionDescriptor):
    """Extended Server Attributes support."""

    name = "ExtendedServerAttributes"
    alias = "OS-EXT-SRV-ATTR"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "extended_status/api/v1.1"
    updated = "2011-11-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedServerAttributesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]


def make_server(elem):
    elem.set('{%s}instance_name' % Extended_server_attributes.namespace,
             '%s:instance_name' % Extended_server_attributes.alias)
    elem.set('{%s}host' % Extended_server_attributes.namespace,
             '%s:host' % Extended_server_attributes.alias)


class ExtendedServerAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Extended_server_attributes.alias: \
            Extended_server_attributes.namespace})


class ExtendedServerAttributesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Extended_server_attributes.alias: \
            Extended_server_attributes.namespace})
