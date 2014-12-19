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
from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import exception
from nova.i18n import _
from nova import network
from nova.objects import base as base_obj
from nova.objects import fields as obj_fields

ALIAS = 'os-networks'
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)
authorize_view = extensions.extension_authorizer('compute',
                                                 'v3:' + ALIAS + ':view')


def network_dict(context, network):
    fields = ('id', 'cidr', 'netmask', 'gateway', 'broadcast', 'dns1', 'dns2',
              'cidr_v6', 'gateway_v6', 'label', 'netmask_v6')
    admin_fields = ('created_at', 'updated_at', 'deleted_at', 'deleted',
                    'injected', 'bridge', 'vlan', 'vpn_public_address',
                    'vpn_public_port', 'vpn_private_address', 'dhcp_start',
                    'project_id', 'host', 'bridge_interface', 'multi_host',
                    'priority', 'rxtx_base', 'mtu', 'dhcp_server',
                    'enable_dhcp', 'share_address')
    if network:
        # NOTE(mnaser): We display a limited set of fields so users can know
        #               what networks are available, extra system-only fields
        #               are only visible if they are an admin.
        if context.is_admin:
            fields += admin_fields
        # TODO(mriedem): Remove the NovaObject type check once the
        # neutronv2 API is returning Network objects from get/get_all.
        is_obj = isinstance(network, base_obj.NovaObject)
        result = {}
        for field in fields:
            # NOTE(mriedem): If network is an object, IPAddress fields need to
            # be cast to a string so they look the same in the response as
            # before the objects conversion.
            if is_obj and isinstance(network.fields[field].AUTO_TYPE,
                                     obj_fields.IPAddress):
                val = network.get(field)
                if val is not None:
                    result[field] = str(network.get(field))
                else:
                    result[field] = val
            else:
                # It's either not an object or it's not an IPAddress field.
                result[field] = network.get(field)
        uuid = network.get('uuid')
        if uuid:
            result['id'] = uuid
        return result
    else:
        return {}


class NetworkController(wsgi.Controller):

    def __init__(self, network_api=None):
        self.network_api = network_api or network.API()

    @extensions.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']
        authorize_view(context)
        networks = self.network_api.get_all(context)
        result = [network_dict(context, net_ref) for net_ref in networks]
        return {'networks': result}

    @wsgi.response(202)
    @extensions.expected_errors((404, 501))
    @wsgi.action("disassociate")
    def _disassociate_host_and_project(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        try:
            self.network_api.associate(context, id, host=None, project=None)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        except NotImplementedError:
            msg = _('Disassociate network is not implemented by the '
                    'configured Network API')
            raise exc.HTTPNotImplemented(explanation=msg)

    @extensions.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_view(context)

        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return {'network': network_dict(context, network)}

    @wsgi.response(202)
    @extensions.expected_errors((404, 409))
    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)

        try:
            self.network_api.delete(context, id)
        except exception.NetworkInUse as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)

    @extensions.expected_errors((400, 409, 501))
    def create(self, req, body):
        context = req.environ['nova.context']
        authorize(context)

        def bad(e):
            return exc.HTTPBadRequest(explanation=e)

        if not (body and body.get("network")):
            raise bad(_("Missing network in body"))

        params = body["network"]
        if not params.get("label"):
            raise bad(_("Network label is required"))

        cidr = params.get("cidr") or params.get("cidr_v6")
        if not cidr:
            raise bad(_("Network cidr or cidr_v6 is required"))

        if params.get("project_id") == "":
            params["project_id"] = None

        params["num_networks"] = 1
        try:
            params["network_size"] = netaddr.IPNetwork(cidr).size
        except netaddr.AddrFormatError:
            msg = _('%s is not a valid ip network') % cidr
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            network = self.network_api.create(context, **params)[0]
        except (exception.InvalidCidr,
                exception.InvalidIntValue,
                exception.InvalidAddress,
                exception.NetworkNotCreated) as ex:
            raise exc.HTTPBadRequest(explanation=ex.format_message)
        except exception.CidrConflict as ex:
            raise exc.HTTPConflict(explanation=ex.format_message())
        return {"network": network_dict(context, network)}

    @wsgi.response(202)
    @extensions.expected_errors((400, 409, 501))
    def add(self, req, body):
        context = req.environ['nova.context']
        authorize(context)
        if not body:
            msg = _("Missing request body")
            raise exc.HTTPBadRequest(explanation=msg)

        network_id = body.get('id', None)
        project_id = context.project_id

        try:
            self.network_api.add_network_to_project(
                context, project_id, network_id)
        except NotImplementedError:
            msg = (_("VLAN support must be enabled"))
            raise exc.HTTPNotImplemented(explanation=msg)
        except (exception.NoMoreNetworks,
                exception.NetworkNotFoundForUUID) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())


class Networks(extensions.V3APIExtensionBase):
    """Admin-only Network Management Extension."""

    name = "Networks"
    alias = ALIAS
    version = 1

    def get_resources(self):
        member_actions = {'action': 'POST'}
        collection_actions = {'add': 'POST'}
        res = extensions.ResourceExtension(
            ALIAS, NetworkController(),
            member_actions=member_actions,
            collection_actions=collection_actions)
        return [res]

    def get_controller_extensions(self):
        return []
