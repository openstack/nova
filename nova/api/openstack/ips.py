# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import time

from webob import exc

import nova
import nova.api.openstack.views.addresses
from nova.api.openstack import wsgi
from nova import db


class Controller(object):
    """The servers addresses API controller for the Openstack API."""

    def __init__(self):
        self.compute_api = nova.compute.API()

    def _get_instance(self, req, server_id):
        try:
            instance = self.compute_api.get(
                req.environ['nova.context'], server_id)
        except nova.exception.NotFound:
            raise exc.HTTPNotFound()
        return instance

    def create(self, req, server_id, body):
        raise exc.HTTPNotImplemented()

    def delete(self, req, server_id, id):
        raise exc.HTTPNotImplemented()


class ControllerV10(Controller):

    def index(self, req, server_id):
        instance = self._get_instance(req, server_id)
        builder = nova.api.openstack.views.addresses.ViewBuilderV10()
        return {'addresses': builder.build(instance)}

    def show(self, req, server_id, id):
        instance = self._get_instance(req, server_id)
        builder = self._get_view_builder(req)
        if id == 'private':
            view = builder.build_private_parts(instance)
        elif id == 'public':
            view = builder.build_public_parts(instance)
        else:
            msg = _("Only private and public networks available")
            raise exc.HTTPNotFound(explanation=msg)

        return {id: view}

    def _get_view_builder(self, req):
        return nova.api.openstack.views.addresses.ViewBuilderV10()


class ControllerV11(Controller):

    def index(self, req, server_id):
        context = req.environ['nova.context']
        interfaces = self._get_virtual_interfaces(context, server_id)
        networks = self._get_view_builder(req).build(interfaces)
        return {'addresses': networks}

    def show(self, req, server_id, id):
        context = req.environ['nova.context']
        interfaces = self._get_virtual_interfaces(context, server_id)
        network = self._get_view_builder(req).build_network(interfaces, id)

        if network is None:
            msg = _("Instance is not a member of specified network")
            raise exc.HTTPNotFound(explanation=msg)

        return network

    def _get_virtual_interfaces(self, context, server_id):
        try:
            return db.api.virtual_interface_get_by_instance(context, server_id)
        except nova.exception.InstanceNotFound:
            msg = _("Instance does not exist")
            raise exc.HTTPNotFound(explanation=msg)

    def _get_view_builder(self, req):
        return nova.api.openstack.views.addresses.ViewBuilderV11()


def create_resource(version):
    controller = {
        '1.0': ControllerV10,
        '1.1': ControllerV11,
    }[version]()

    xmlns = {
        '1.0': wsgi.XMLNS_V10,
        '1.1': wsgi.XMLNS_V11,
    }[version]

    metadata = {
        'list_collections': {
            'public':  {'item_name': 'ip', 'item_key': 'addr'},
            'private': {'item_name': 'ip', 'item_key': 'addr'},
        },
    }

    body_serializers = {
        'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                  xmlns=xmlns),
    }
    serializer = wsgi.ResponseSerializer(body_serializers)

    return wsgi.Resource(controller, serializer=serializer)
