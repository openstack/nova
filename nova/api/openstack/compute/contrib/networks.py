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
from nova import log as logging
import nova.network.api


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.api.openstack.compute.contrib.networks')


def network_dict(network):
    if network:
        fields = ('bridge', 'vpn_public_port', 'dhcp_start',
                  'bridge_interface', 'updated_at', 'id', 'cidr_v6',
                  'deleted_at', 'gateway', 'label', 'project_id',
                  'vpn_private_address', 'deleted', 'vlan', 'broadcast',
                  'netmask', 'injected', 'cidr', 'vpn_public_address',
                  'multi_host', 'dns1', 'host', 'gateway_v6', 'netmask_v6',
                  'created_at')
        return dict((field, network[field]) for field in fields)
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
        LOG.debug(_("Disassociating network with id %s" % network_id))
        try:
            self.network_api.disassociate(context, network_id)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return exc.HTTPAccepted()

    def index(self, req):
        context = req.environ['nova.context']
        networks = self.network_api.get_all(context)
        result = [network_dict(net_ref) for net_ref in networks]
        return  {'networks': result}

    def show(self, req, id):
        context = req.environ['nova.context']
        LOG.debug(_("Showing network with id %s") % id)
        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return {'network': network_dict(network)}

    def delete(self, req, id):
        context = req.environ['nova.context']
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
    updated = "2011-12-23 00:00:00"
    admin_only = True

    def get_resources(self):
        member_actions = {'action': 'POST'}
        res = extensions.ResourceExtension('os-networks',
                                           NetworkController(),
                                           member_actions=member_actions)
        return [res]
