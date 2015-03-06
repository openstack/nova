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
from nova.api.openstack.compute.views import addresses as view_addresses
from nova.api.openstack import wsgi
from nova.i18n import _


class Controller(wsgi.Controller):
    """The servers addresses API controller for the OpenStack API."""

    _view_builder_class = view_addresses.ViewBuilder

    def __init__(self, **kwargs):
        super(Controller, self).__init__(**kwargs)
        self._compute_api = nova.compute.API()

    def index(self, req, server_id):
        context = req.environ["nova.context"]
        instance = common.get_instance(self._compute_api, context, server_id)
        networks = common.get_networks_for_instance(context, instance)
        return self._view_builder.index(networks)

    def show(self, req, server_id, id):
        context = req.environ["nova.context"]
        instance = common.get_instance(self._compute_api, context, server_id)
        networks = common.get_networks_for_instance(context, instance)
        if id not in networks:
            msg = _("Instance is not a member of specified network")
            raise exc.HTTPNotFound(explanation=msg)

        return self._view_builder.show(networks[id], id)


def create_resource():
    return wsgi.Resource(Controller())
