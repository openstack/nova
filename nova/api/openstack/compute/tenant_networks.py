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
from oslo_config import cfg
from oslo_log import log as logging
import six
from webob import exc

from nova.api.openstack.compute.schemas import tenant_networks as schema
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.i18n import _LE
import nova.network
from nova import quota


CONF = cfg.CONF
CONF.import_opt('enable_network_quota', 'nova.api.openstack.compute.'
                'legacy_v2.contrib.os_tenant_networks')
CONF.import_opt('use_neutron_default_nets', 'nova.api.openstack.compute.'
                'legacy_v2.contrib.os_tenant_networks')
CONF.import_opt('neutron_default_tenant_id', 'nova.api.openstack.compute.'
                'legacy_v2.contrib.os_tenant_networks')
CONF.import_opt('quota_networks', 'nova.api.openstack.compute.'
                'legacy_v2.contrib.os_tenant_networks')


ALIAS = 'os-tenant-networks'

QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)
authorize = extensions.os_compute_authorizer(ALIAS)


def network_dict(network):
    # NOTE(danms): Here, network should be an object, which could have come
    # from neutron and thus be missing most of the attributes. Providing a
    # default to get() avoids trying to lazy-load missing attributes.
    return {"id": network.get("uuid", None) or network.get("id", None),
                        "cidr": str(network.get("cidr", None)),
                        "label": network.get("label", None)}


class TenantNetworkController(wsgi.Controller):
    def __init__(self, network_api=None):
        self.network_api = nova.network.API(skip_policy_check=True)
        self._default_networks = []

    def _refresh_default_networks(self):
        self._default_networks = []
        if CONF.use_neutron_default_nets == "True":
            try:
                self._default_networks = self._get_default_networks()
            except Exception:
                LOG.exception(_LE("Failed to get default networks"))

    def _get_default_networks(self):
        project_id = CONF.neutron_default_tenant_id
        ctx = nova_context.RequestContext(user_id=None,
                                          project_id=project_id)
        networks = {}
        for n in self.network_api.get_all(ctx):
            networks[n['id']] = n['label']
        return [{'id': k, 'label': v} for k, v in six.iteritems(networks)]

    @extensions.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']
        authorize(context)
        networks = list(self.network_api.get_all(context))
        if not self._default_networks:
            self._refresh_default_networks()
        networks.extend(self._default_networks)
        return {'networks': [network_dict(n) for n in networks]}

    @extensions.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return {'network': network_dict(network)}

    @extensions.expected_errors((403, 404, 409))
    @wsgi.response(202)
    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        reservation = None
        try:
            if CONF.enable_network_quota:
                reservation = QUOTAS.reserve(context, networks=-1)
        except Exception:
            reservation = None
            LOG.exception(_LE("Failed to update usages deallocating "
                              "network."))

        def _rollback_quota(reservation):
            if CONF.enable_network_quota and reservation:
                QUOTAS.rollback(context, reservation)

        try:
            self.network_api.disassociate(context, id)
            self.network_api.delete(context, id)
        except exception.PolicyNotAuthorized as e:
            _rollback_quota(reservation)
            raise exc.HTTPForbidden(explanation=six.text_type(e))
        except exception.NetworkInUse as e:
            _rollback_quota(reservation)
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.NetworkNotFound:
            _rollback_quota(reservation)
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)

        if CONF.enable_network_quota and reservation:
            QUOTAS.commit(context, reservation)

    @extensions.expected_errors((400, 403, 409, 503))
    @validation.schema(schema.create)
    def create(self, req, body):
        context = req.environ["nova.context"]
        authorize(context)

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

        networks = []
        try:
            if CONF.enable_network_quota:
                reservation = QUOTAS.reserve(context, networks=1)
        except exception.OverQuota:
            msg = _("Quota exceeded, too many networks.")
            raise exc.HTTPBadRequest(explanation=msg)

        kwargs['project_id'] = context.project_id

        try:
            networks = self.network_api.create(context,
                                               label=label, **kwargs)
            if CONF.enable_network_quota:
                QUOTAS.commit(context, reservation)
        except exception.PolicyNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=six.text_type(e))
        except exception.CidrConflict as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except Exception:
            if CONF.enable_network_quota:
                QUOTAS.rollback(context, reservation)
            msg = _("Create networks failed")
            LOG.exception(msg, extra=network)
            raise exc.HTTPServiceUnavailable(explanation=msg)
        return {"network": network_dict(networks[0])}


class TenantNetworks(extensions.V21APIExtensionBase):
    """Tenant-based Network Management Extension."""

    name = "OSTenantNetworks"
    alias = ALIAS
    version = 1

    def get_resources(self):
        ext = extensions.ResourceExtension(ALIAS, TenantNetworkController())
        return [ext]

    def get_controller_extensions(self):
        return []


def _sync_networks(context, project_id, session):
    ctx = nova_context.RequestContext(user_id=None, project_id=project_id)
    ctx = ctx.elevated()
    networks = nova.network.api.API().get_all(ctx)
    return dict(networks=len(networks))


if CONF.enable_network_quota:
    QUOTAS.register_resource(quota.ReservableResource('networks',
                                                      _sync_networks,
                                                      'quota_networks'))
