# Copyright 2013 OpenStack Foundation
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
import netaddr.core as netexc
from oslo_log import log as logging
import six
from webob import exc

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack.compute.schemas import tenant_networks as schema
from nova.api.openstack import wsgi
from nova.api import validation
import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
import nova.network
from nova import objects
from nova.policies import tenant_networks as tn_policies
from nova import quota


CONF = nova.conf.CONF

QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)


def network_dict(network):
    # NOTE(danms): Here, network should be an object, which could have come
    # from neutron and thus be missing most of the attributes. Providing a
    # default to get() avoids trying to lazy-load missing attributes.
    return {"id": network.get("uuid", None) or network.get("id", None),
                        "cidr": str(network.get("cidr", None)),
                        "label": network.get("label", None)}


class TenantNetworkController(wsgi.Controller):
    def __init__(self, network_api=None):
        super(TenantNetworkController, self).__init__()
        # TODO(stephenfin): 'network_api' is only being passed for use by tests
        self.network_api = nova.network.API()
        self._default_networks = []

    def _refresh_default_networks(self):
        self._default_networks = []
        if CONF.api.use_neutron_default_nets:
            try:
                self._default_networks = self._get_default_networks()
            except Exception:
                LOG.exception("Failed to get default networks")

    def _get_default_networks(self):
        project_id = CONF.api.neutron_default_tenant_id
        ctx = nova_context.RequestContext(user_id=None,
                                          project_id=project_id)
        networks = {}
        for n in self.network_api.get_all(ctx):
            networks[n['id']] = n['label']
        return [{'id': k, 'label': v} for k, v in networks.items()]

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']
        context.can(tn_policies.BASE_POLICY_NAME)
        networks = list(self.network_api.get_all(context))
        if not self._default_networks:
            self._refresh_default_networks()
        networks.extend(self._default_networks)
        return {'networks': [network_dict(n) for n in networks]}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(tn_policies.BASE_POLICY_NAME)
        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return {'network': network_dict(network)}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((403, 404, 409))
    @wsgi.response(202)
    def delete(self, req, id):
        context = req.environ['nova.context']
        context.can(tn_policies.BASE_POLICY_NAME)

        try:
            self.network_api.disassociate(context, id)
            self.network_api.delete(context, id)
        except exception.PolicyNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=six.text_type(e))
        except exception.NetworkInUse as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 403, 409, 503))
    @validation.schema(schema.create)
    def create(self, req, body):
        context = req.environ["nova.context"]
        context.can(tn_policies.BASE_POLICY_NAME)

        network = body["network"]
        keys = ["cidr", "cidr_v6", "ipam", "vlan_start", "network_size",
                "num_networks"]
        kwargs = {k: network.get(k) for k in keys}

        label = network["label"]

        if kwargs["cidr"]:
            try:
                net = netaddr.IPNetwork(kwargs["cidr"])
                if net.size < 4:
                    msg = _("Requested network does not contain "
                            "enough (2+) usable hosts")
                    raise exc.HTTPBadRequest(explanation=msg)
            except netexc.AddrConversionError:
                msg = _("Address could not be converted.")
                raise exc.HTTPBadRequest(explanation=msg)

        try:
            if CONF.enable_network_quota:
                objects.Quotas.check_deltas(context, {'networks': 1},
                                            context.project_id)
        except exception.OverQuota:
            msg = _("Quota exceeded, too many networks.")
            raise exc.HTTPForbidden(explanation=msg)

        kwargs['project_id'] = context.project_id

        try:
            networks = self.network_api.create(context,
                                               label=label, **kwargs)
        except exception.PolicyNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=six.text_type(e))
        except exception.CidrConflict as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except Exception:
            msg = _("Create networks failed")
            LOG.exception(msg, extra=network)
            raise exc.HTTPServiceUnavailable(explanation=msg)

        # NOTE(melwitt): We recheck the quota after creating the object to
        # prevent users from allocating more resources than their allowed quota
        # in the event of a race. This is configurable because it can be
        # expensive if strict quota limits are not required in a deployment.
        if CONF.quota.recheck_quota and CONF.enable_network_quota:
            try:
                objects.Quotas.check_deltas(context, {'networks': 0},
                                            context.project_id)
            except exception.OverQuota:
                self.network_api.delete(context,
                                        network_dict(networks[0])['id'])
                msg = _("Quota exceeded, too many networks.")
                raise exc.HTTPForbidden(explanation=msg)

        return {"network": network_dict(networks[0])}


def _network_count(context, project_id):
    # NOTE(melwitt): This assumes a single cell.
    ctx = nova_context.RequestContext(user_id=None, project_id=project_id)
    ctx = ctx.elevated()
    networks = nova.network.api.API().get_all(ctx)
    return {'project': {'networks': len(networks)}}


def _register_network_quota():
    if CONF.enable_network_quota:
        QUOTAS.register_resource(quota.CountableResource('networks',
                                                          _network_count,
                                                         'quota_networks'))


_register_network_quota()
