# Copyright 2011 OpenStack Foundation
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

from webob import exc

import nova
from nova.api.openstack import common
from nova.api.openstack.compute.views import addresses as views_addresses
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.openstack.common.gettextutils import _


class IPsController(wsgi.Controller):
    """The servers addresses API controller for the OpenStack API."""

    _view_builder_class = views_addresses.ViewBuilderV3

    def __init__(self, **kwargs):
        super(IPsController, self).__init__(**kwargs)
        self._compute_api = nova.compute.API()

    def _get_instance(self, context, server_id):
        try:
            instance = self._compute_api.get(context, server_id)
        except nova.exception.NotFound:
            msg = _("Instance does not exist")
            raise exc.HTTPNotFound(explanation=msg)
        return instance

    def create(self, req, server_id, body):
        raise exc.HTTPNotImplemented()

    def delete(self, req, server_id, id):
        raise exc.HTTPNotImplemented()

    def index(self, req, server_id):
        context = req.environ["nova.context"]
        instance = self._get_instance(context, server_id)
        networks = common.get_networks_for_instance(context, instance)
        return self._view_builder.index(networks)

    def show(self, req, server_id, id):
        context = req.environ["nova.context"]
        instance = self._get_instance(context, server_id)
        networks = common.get_networks_for_instance(context, instance)
        if id not in networks:
            msg = _("Instance is not a member of specified network")
            raise exc.HTTPNotFound(explanation=msg)

        return self._view_builder.show(networks[id], id)


class IPs(extensions.V3APIExtensionBase):
    """Server addresses."""

    name = "ips"
    alias = "ips"
    version = 1

    def get_resources(self):
        parent = {'member_name': 'server',
                  'collection_name': 'servers'}
        resources = [
            extensions.ResourceExtension(
                'ips', IPsController(), parent=parent, member_name='ip')]

        return resources

    def get_controller_extensions(self):
        return []
