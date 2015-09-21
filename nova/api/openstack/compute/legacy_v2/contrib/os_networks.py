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
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import network
from nova.objects import base as base_obj
from nova.objects import fields as obj_fields

authorize = extensions.extension_authorizer('compute', 'networks')
authorize_view = extensions.extension_authorizer('compute',
                                                 'networks:view')
extended_fields = ('mtu', 'dhcp_server', 'enable_dhcp', 'share_address')


def network_dict(context, network, extended):
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
            if extended:
                fields += extended_fields
        # TODO(mriedem): Remove the NovaObject type check once the
        # network.create API is returning objects.
        is_obj = isinstance(network, base_obj.NovaObject)
        result = {}
        for field in fields:
            # NOTE(mriedem): If network is an object, IPAddress fields need to
            # be cast to a string so they look the same in the response as
            # before the objects conversion.
            if is_obj and isinstance(network.fields[field].AUTO_TYPE,
                                     obj_fields.IPAddress):
                # NOTE(danms): Here, network should be an object, which could
                # have come from neutron and thus be missing most of the
                # attributes. Providing a default to get() avoids trying to
                # lazy-load missing attributes.
                val = network.get(field, None)
                if val is not None:
                    result[field] = str(val)
                else:
                    result[field] = val
            else:
                # It's either not an object or it's not an IPAddress field.
                result[field] = network.get(field, None)
        uuid = network.get('uuid')
        if uuid:
            result['id'] = uuid
        return result
    else:
        return {}


class NetworkController(wsgi.Controller):

    def __init__(self, network_api=None, ext_mgr=None):
        self.network_api = network_api or network.API()
        if ext_mgr:
            self.extended = ext_mgr.is_loaded('os-extended-networks')
        else:
            self.extended = False

    def index(self, req):
        context = req.environ['nova.context']
        authorize_view(context)
        networks = self.network_api.get_all(context)
        result = [network_dict(context, net_ref, self.extended)
                  for net_ref in networks]
        return {'networks': result}

    @wsgi.action("disassociate")
    def _disassociate_host_and_project(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        # NOTE(shaohe-feng): back-compatible with db layer hard-code
        # admin permission checks.  call db API objects.Network.associate
        nova_context.require_admin_context(context)

        try:
            self.network_api.associate(context, id, host=None, project=None)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        except NotImplementedError:
            msg = _('Disassociate network is not implemented by the '
                    'configured Network API')
            raise exc.HTTPNotImplemented(explanation=msg)
        return webob.Response(status_int=202)

    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_view(context)

        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return {'network': network_dict(context, network, self.extended)}

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
        return webob.Response(status_int=202)

    def create(self, req, body):
        context = req.environ['nova.context']
        authorize(context)
        # NOTE(shaohe-feng): back-compatible with db layer hard-code
        # admin permission checks.  call db API objects.Network.create
        nova_context.require_admin_context(context)

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
            msg = _('%s is not a valid IP network') % cidr
            raise exc.HTTPBadRequest(explanation=msg)

        if not self.extended:
            create_params = ('allowed_start', 'allowed_end')
            for field in extended_fields + create_params:
                if field in params:
                    del params[field]

        try:
            network = self.network_api.create(context, **params)[0]
        except (exception.InvalidCidr,
                exception.InvalidIntValue,
                exception.InvalidAddress,
                exception.NetworkNotCreated) as ex:
            raise exc.HTTPBadRequest(explanation=ex.format_message)
        except exception.CidrConflict as ex:
            raise exc.HTTPConflict(explanation=ex.format_message())
        return {"network": network_dict(context, network, self.extended)}

    def add(self, req, body):
        context = req.environ['nova.context']
        authorize(context)
        # NOTE(shaohe-feng): back-compatible with db layer hard-code
        # admin permission checks.  call db API objects.Network.associate
        nova_context.require_admin_context(context)
        if not body:
            raise exc.HTTPUnprocessableEntity()

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

        return webob.Response(status_int=202)


class Os_networks(extensions.ExtensionDescriptor):
    """Admin-only Network Management Extension."""

    name = "Networks"
    alias = "os-networks"
    namespace = ("http://docs.openstack.org/compute/"
                 "ext/os-networks/api/v1.1")
    updated = "2011-12-23T00:00:00Z"

    def get_resources(self):
        member_actions = {'action': 'POST'}
        collection_actions = {'add': 'POST'}
        res = extensions.ResourceExtension(
            'os-networks',
            NetworkController(ext_mgr=self.ext_mgr),
            member_actions=member_actions,
            collection_actions=collection_actions)
        return [res]
