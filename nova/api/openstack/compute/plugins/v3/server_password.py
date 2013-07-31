# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Nebula, Inc.
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

"""The server password extension."""

import webob

from nova.api.metadata import password
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import db
from nova import exception


ALIAS = 'os-server-password'
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class ServerPasswordTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('password', selector='password')
        root.text = unicode
        return xmlutil.MasterTemplate(root, 1)


class ServerPasswordController(object):
    """The Server Password API controller for the OpenStack API."""
    def __init__(self):
        self.compute_api = compute.API()

    def _get_instance(self, context, server_id):
        try:
            return self.compute_api.get(context, server_id)
        except exception.InstanceNotFound as exp:
            raise webob.exc.HTTPNotFound(explanation=exp.format_message())

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=ServerPasswordTemplate)
    def index(self, req, server_id):
        context = req.environ['nova.context']
        authorize(context)
        instance = self._get_instance(context, server_id)

        passw = password.extract_password(instance)
        return {'password': passw or ''}

    @extensions.expected_errors(404)
    @wsgi.response(204)
    def clear(self, req, server_id):
        """
        Removes the encrypted server password from the metadata server

        Note that this does not actually change the instance server
        password.
        """

        context = req.environ['nova.context']
        authorize(context)
        instance = self._get_instance(context, server_id)
        meta = password.convert_password(context, None)
        db.instance_system_metadata_update(context, instance['uuid'],
                                           meta, False)


class ServerPassword(extensions.V3APIExtensionBase):
    """Server password support."""

    name = "ServerPassword"
    alias = ALIAS
    namespace = ("http://docs.openstack.org/compute/ext/" + ALIAS + "/api/v3")
    version = 1

    def get_resources(self):
        resources = [
            extensions.ResourceExtension(
                ALIAS, ServerPasswordController(),
                collection_actions={'clear': 'DELETE'},
                parent=dict(member_name='server', collection_name='servers'))]
        return resources

    def get_controller_extensions(self):
        return []
