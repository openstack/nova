# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import console
from nova import exception


def _translate_keys(cons):
    """Coerces a console instance into proper dictionary format """
    pool = cons['pool']
    info = {'id': cons['id'],
            'console_type': pool['console_type']}
    return dict(console=info)


def _translate_detail_keys(cons):
    """Coerces a console instance into proper dictionary format with
    correctly mapped attributes """
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


class Controller(object):
    """The Consoles controller for the Openstack API"""

    def __init__(self):
        self.console_api = console.API()

    @wsgi.serializers(xml=ConsolesTemplate)
    def index(self, req, server_id):
        """Returns a list of consoles for this instance"""
        consoles = self.console_api.get_consoles(
                                    req.environ['nova.context'],
                                    server_id)
        return dict(consoles=[_translate_keys(console)
                              for console in consoles])

    def create(self, req, server_id):
        """Creates a new console"""
        self.console_api.create_console(
                                req.environ['nova.context'],
                                server_id)

    @wsgi.serializers(xml=ConsoleTemplate)
    def show(self, req, server_id, id):
        """Shows in-depth information on a specific console"""
        try:
            console = self.console_api.get_console(
                                        req.environ['nova.context'],
                                        server_id,
                                        int(id))
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return _translate_detail_keys(console)

    def update(self, req, server_id, id):
        """You can't update a console"""
        raise exc.HTTPNotImplemented()

    def delete(self, req, server_id, id):
        """Deletes a console"""
        try:
            self.console_api.delete_console(req.environ['nova.context'],
                                            server_id,
                                            int(id))
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)


def create_resource():
    return wsgi.Resource(Controller())
