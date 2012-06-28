# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Grid Dynamics
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


from webob import exc

from nova.api.openstack import extensions
from nova import exception
from nova import flags
import nova.network.api
from nova.openstack.common import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'networks')
authorize_view = extensions.extension_authorizer('compute', 'networks:view')


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
        result = dict((field, network[field]) for field in fields)
        if 'uuid' in network:
            result['id'] = network['uuid']
        return result
    else:
        return {}


class NetworkController(object):

    def __init__(self, network_api=None):
        self.network_api = network_api or nova.network.api.API()

    def action(self, req, id, body):
        _actions = {
            'disassociate': self._disassociate,
        }

        for action, data in body.iteritems():
            try:
                return _actions[action](req, id, body)
            except KeyError:
                msg = _("Network does not have %s action") % action
                raise exc.HTTPBadRequest(explanation=msg)

        raise exc.HTTPBadRequest(explanation=_("Invalid request body"))

    def _disassociate(self, request, network_id, body):
        context = request.environ['nova.context']
        authorize(context)
        LOG.debug(_("Disassociating network with id %s"), network_id)
        try:
            self.network_api.disassociate(context, network_id)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return exc.HTTPAccepted()

    def index(self, req):
        context = req.environ['nova.context']
        authorize_view(context)
        networks = self.network_api.get_all(context)
        result = [network_dict(context, net_ref) for net_ref in networks]
        return {'networks': result}

    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_view(context)
        LOG.debug(_("Showing network with id %s") % id)
        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return {'network': network_dict(context, network)}

    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        LOG.info(_("Deleting network with id %s") % id)
        try:
            self.network_api.delete(context, id)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return exc.HTTPAccepted()

    def create(self, req, id, body=None):
        raise exc.HTTPNotImplemented()


class Networks(extensions.ExtensionDescriptor):
    """Admin-only Network Management Extension"""

    name = "Networks"
    alias = "os-networks"
    namespace = "http://docs.openstack.org/compute/ext/networks/api/v1.1"
    updated = "2011-12-23T00:00:00+00:00"

    def get_resources(self):
        member_actions = {'action': 'POST'}
        res = extensions.ResourceExtension('os-networks',
                                           NetworkController(),
                                           member_actions=member_actions)
        return [res]
