# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack Foundation
# All Rights Reserved.
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

import webob
from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.console import api as console_api
from nova import exception


def _translate_keys(cons):
    """Coerces a console instance into proper dictionary format."""
    pool = cons['pool']
    info = {'id': cons['id'],
            'console_type': pool['console_type']}
    return dict(console=info)


def _translate_detail_keys(cons):
    """Coerces a console instance into proper dictionary format with detail."""
    pool = cons['pool']
    info = {'id': cons['id'],
            'console_type': pool['console_type'],
            'password': cons['password'],
            'instance_name': cons['instance_name'],
            'port': cons['port'],
            'host': pool['public_hostname']}
    return dict(console=info)


class ConsoleTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('console', selector='console')

        id_elem = xmlutil.SubTemplateElement(root, 'id', selector='id')
        id_elem.text = xmlutil.Selector()

        port_elem = xmlutil.SubTemplateElement(root, 'port', selector='port')
        port_elem.text = xmlutil.Selector()

        host_elem = xmlutil.SubTemplateElement(root, 'host', selector='host')
        host_elem.text = xmlutil.Selector()

        passwd_elem = xmlutil.SubTemplateElement(root, 'password',
                                                 selector='password')
        passwd_elem.text = xmlutil.Selector()

        constype_elem = xmlutil.SubTemplateElement(root, 'console_type',
                                                   selector='console_type')
        constype_elem.text = xmlutil.Selector()

        return xmlutil.MasterTemplate(root, 1)


class ConsolesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('consoles')
        console = xmlutil.SubTemplateElement(root, 'console',
                                             selector='consoles')
        console.append(ConsoleTemplate())

        return xmlutil.MasterTemplate(root, 1)


class ConsolesController(object):
    """The Consoles controller for the OpenStack API."""

    def __init__(self):
        self.console_api = console_api.API()

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=ConsolesTemplate)
    def index(self, req, server_id):
        """Returns a list of consoles for this instance."""
        try:
            consoles = self.console_api.get_consoles(
                req.environ['nova.context'], server_id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return dict(consoles=[_translate_keys(console)
                              for console in consoles])

    @extensions.expected_errors(404)
    @wsgi.response(201)
    def create(self, req, server_id):
        """Creates a new console."""
        try:
            self.console_api.create_console(
                req.environ['nova.context'], server_id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=ConsoleTemplate)
    def show(self, req, server_id, id):
        """Shows in-depth information on a specific console."""
        try:
            console = self.console_api.get_console(
                                        req.environ['nova.context'],
                                        server_id,
                                        int(id))
        except exception.ConsoleNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return _translate_detail_keys(console)

    @extensions.expected_errors(404)
    def delete(self, req, server_id, id):
        """Deletes a console."""
        try:
            self.console_api.delete_console(req.environ['nova.context'],
                                            server_id,
                                            int(id))
        except exception.ConsoleNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)


class Consoles(extensions.V3APIExtensionBase):
    """Consoles."""

    name = "Consoles"
    alias = "consoles"
    namespace = "http://docs.openstack.org/compute/core/consoles/v3"
    version = 1

    def get_resources(self):
        parent = {'member_name': 'server',
                  'collection_name': 'servers'}
        resources = [
            extensions.ResourceExtension(
                'consoles', ConsolesController(), parent=parent,
                member_name='console')]

        return resources

    def get_controller_extensions(self):
        return []
