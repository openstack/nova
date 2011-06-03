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
from nova.api.openstack import faults
import nova.api.openstack.views.addresses
from nova.api.openstack import wsgi


class Controller(object):
    """The servers addresses API controller for the Openstack API."""

    def __init__(self):
        self.compute_api = nova.compute.API()
        self.builder = nova.api.openstack.views.addresses.ViewBuilderV10()

    def index(self, req, server_id):
        try:
            instance = self.compute_api.get(req.environ['nova.context'], id)
        except nova.exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return {'addresses': self.builder.build(instance)}

    def public(self, req, server_id):
        try:
            instance = self.compute_api.get(req.environ['nova.context'], id)
        except nova.exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return {'public': self.builder.build_public_parts(instance)}

    def private(self, req, server_id):
        try:
            instance = self.compute_api.get(req.environ['nova.context'], id)
        except nova.exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return {'private': self.builder.build_private_parts(instance)}

    def show(self, req, server_id, id):
        return faults.Fault(exc.HTTPNotImplemented())

    def create(self, req, server_id, body):
        return faults.Fault(exc.HTTPNotImplemented())

    def delete(self, req, server_id, id):
        return faults.Fault(exc.HTTPNotImplemented())


def create_resource():
    metadata = {
        'list_collections': {
            'public':  {'item_name': 'ip', 'item_key': 'addr'},
            'private': {'item_name': 'ip', 'item_key': 'addr'},
        },
    }

    serializers = {
        'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                  xmlns=wsgi.XMLNS_V10),
    }

    return wsgi.Resource(Controller(), serializers=serializers)
