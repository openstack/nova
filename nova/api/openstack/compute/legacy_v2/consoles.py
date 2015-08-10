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

from nova.api.openstack import wsgi
from nova.console import api as console_api
from nova import exception


def _translate_keys(cons):
    """Coerces a console instance into proper dictionary format."""
    pool = cons['pool']
    info = {'id': cons['id'],
            'console_type': pool['console_type']}
    return dict(console=info)


def _translate_detail_keys(cons):
    """Coerces a console instance into proper dictionary format with
    correctly mapped attributes.
    """
    pool = cons['pool']
    info = {'id': cons['id'],
            'console_type': pool['console_type'],
            'password': cons['password'],
            'instance_name': cons['instance_name'],
            'port': cons['port'],
            'host': pool['public_hostname']}
    return dict(console=info)


class Controller(object):
    """The Consoles controller for the OpenStack API."""

    def __init__(self):
        self.console_api = console_api.API()

    def index(self, req, server_id):
        """Returns a list of consoles for this instance."""
        consoles = self.console_api.get_consoles(
                                    req.environ['nova.context'],
                                    server_id)
        return dict(consoles=[_translate_keys(console)
                              for console in consoles])

    def create(self, req, server_id, body):
        """Creates a new console."""
        try:
            self.console_api.create_console(
                                req.environ['nova.context'],
                                server_id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    def show(self, req, server_id, id):
        """Shows in-depth information on a specific console."""
        try:
            console = self.console_api.get_console(
                                        req.environ['nova.context'],
                                        server_id,
                                        int(id))
        except exception.NotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return _translate_detail_keys(console)

    def delete(self, req, server_id, id):
        """Deletes a console."""
        try:
            self.console_api.delete_console(req.environ['nova.context'],
                                            server_id,
                                            int(id))
        except exception.NotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return webob.Response(status_int=202)


def create_resource():
    return wsgi.Resource(Controller())
