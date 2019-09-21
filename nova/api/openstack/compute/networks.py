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

from webob import exc

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import wsgi
from nova import exception
from nova.i18n import _
from nova import network
from nova.objects import base as base_obj
from nova.objects import fields as obj_fields
from nova.policies import networks as net_policies


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

    def __init__(self, network_api=None):
        super(NetworkController, self).__init__()
        # TODO(stephenfin): 'network_api' is only being passed for use by tests
        self.network_api = network_api or network.API()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']
        context.can(net_policies.POLICY_ROOT % 'view')
        networks = self.network_api.get_all(context)
        result = [network_dict(context, net_ref) for net_ref in networks]
        return {'networks': result}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(net_policies.POLICY_ROOT % 'view')

        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return {'network': network_dict(context, network)}

    @wsgi.expected_errors(410)
    @wsgi.action("disassociate")
    def _disassociate_host_and_project(self, req, id, body):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    def delete(self, req, id):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    def create(self, req, body):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    def add(self, req, body):
        raise exc.HTTPGone()
