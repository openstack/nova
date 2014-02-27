# Copyright 2011 Grid Dynamics
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

import netaddr
import webob
from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import exception
from nova import network
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'networks')
authorize_view = extensions.extension_authorizer('compute',
                                                 'networks:view')


def network_dict(context, network):
    fields = ('id', 'cidr', 'netmask', 'gateway', 'broadcast', 'dns1', 'dns2',
              'cidr_v6', 'gateway_v6', 'label', 'netmask_v6')
    admin_fields = ('created_at', 'updated_at', 'deleted_at', 'deleted',
                    'injected', 'bridge', 'vlan', 'vpn_public_address',
                    'vpn_public_port', 'vpn_private_address', 'dhcp_start',
                    'project_id', 'host', 'bridge_interface', 'multi_host',
                    'priority', 'rxtx_base')
    if network:
        # NOTE(mnaser): We display a limited set of fields so users can know
        #               what networks are available, extra system-only fields
        #               are only visible if they are an admin.
        if context.is_admin:
            fields += admin_fields
        result = dict((field, network.get(field)) for field in fields)
        uuid = network.get('uuid')
        if uuid:
            result['id'] = uuid
        return result
    else:
        return {}


class NetworkController(wsgi.Controller):

    def __init__(self, network_api=None):
        self.network_api = network_api or network.API()

    def index(self, req):
        context = req.environ['nova.context']
        authorize_view(context)
        networks = self.network_api.get_all(context)
        result = [network_dict(context, net_ref) for net_ref in networks]
        return {'networks': result}

    @wsgi.action("disassociate")
    def _disassociate_host_and_project(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        LOG.debug(_("Disassociating network with id %s"), id)

        try:
            self.network_api.associate(context, id, host=None, project=None)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return exc.HTTPAccepted()

    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_view(context)
        LOG.debug(_("Showing network with id %s") % id)
        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return {'network': network_dict(context, network)}

    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        LOG.info(_("Deleting network with id %s") % id)
        try:
            self.network_api.delete(context, id)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return exc.HTTPAccepted()

    def create(self, req, body):
        context = req.environ['nova.context']
        authorize(context)

        def bad(e):
            return exc.HTTPUnprocessableEntity(explanation=e)

        if not (body and body.get("network")):
            raise bad(_("Missing network in body"))

        params = body["network"]
        if not params.get("label"):
            raise bad(_("Network label is required"))

        cidr = params.get("cidr") or params.get("cidr_v6")
        if not cidr:
            raise bad(_("Network cidr or cidr_v6 is required"))

        LOG.debug(_("Creating network with label %s") % params["label"])

        params["num_networks"] = 1
        params["network_size"] = netaddr.IPNetwork(cidr).size

        network = self.network_api.create(context, **params)[0]
        return {"network": network_dict(context, network)}

    def add(self, req, body):
        context = req.environ['nova.context']
        authorize(context)
        if not body:
            raise exc.HTTPUnprocessableEntity()

        network_id = body.get('id', None)
        project_id = context.project_id
        LOG.debug(_("Associating network %(network)s"
                    " with project %(project)s") %
                  {"network": network_id or "",
                   "project": project_id})
        try:
            self.network_api.add_network_to_project(
                context, project_id, network_id)
        except NotImplementedError:
            msg = (_("VLAN support must be enabled"))
            raise exc.HTTPNotImplemented(explanation=msg)
        except Exception as ex:
            msg = (_("Cannot associate network %(network)s"
                     " with project %(project)s: %(message)s") %
                   {"network": network_id or "",
                    "project": project_id,
                    "message": getattr(ex, "value", str(ex))})
            raise exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=202)


class Os_networks(extensions.ExtensionDescriptor):
    """Admin-only Network Management Extension."""

    name = "Networks"
    alias = "os-networks"
    namespace = ("http://docs.openstack.org/compute/"
                 "ext/os-networks/api/v1.1")
    updated = "2011-12-23T00:00:00+00:00"

    def get_resources(self):
        member_actions = {'action': 'POST'}
        collection_actions = {'add': 'POST'}
        res = extensions.ResourceExtension(
            'os-networks',
            NetworkController(),
            member_actions=member_actions,
            collection_actions=collection_actions)
        return [res]
