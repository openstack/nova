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
from oslo.config import cfg
import six
import webob
from webob import exc

from nova.api.openstack import extensions
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.i18n import _LE
import nova.network
from nova.openstack.common import log as logging
from nova import quota


CONF = cfg.CONF

os_network_opts = [
    cfg.BoolOpt("enable_network_quota",
                default=False,
                help='Enables or disables quota checking for tenant '
                     'networks'),
    cfg.StrOpt('use_neutron_default_nets',
                     default="False",
                     help='Control for checking for default networks'),
    cfg.StrOpt('neutron_default_tenant_id',
                     default="default",
                     help='Default tenant id when creating neutron '
                          'networks'),
    cfg.IntOpt('quota_networks',
               default=3,
               help='Number of private networks allowed per project'),
]
CONF.register_opts(os_network_opts)

QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'os-tenant-networks')


def network_dict(network):
    # NOTE(danms): Here, network should be an object, which could have come
    # from neutron and thus be missing most of the attributes. Providing a
    # default to get() avoids trying to lazy-load missing attributes.
    return {"id": network.get("uuid", None) or network.get("id", None),
                        "cidr": str(network.get("cidr", None)),
                        "label": network.get("label", None)}


class NetworkController(object):
    def __init__(self, network_api=None):
        self.network_api = nova.network.API()
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
        return [{'id': k, 'label': v} for k, v in networks.iteritems()]

    def index(self, req):
        context = req.environ['nova.context']
        authorize(context)
        networks = list(self.network_api.get_all(context))
        if not self._default_networks:
            self._refresh_default_networks()
        networks.extend(self._default_networks)
        return {'networks': [network_dict(n) for n in networks]}

    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context)

        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        return {'network': network_dict(network)}

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
        response = webob.Response(status_int=202)

        return response

    def create(self, req, body):
        if not body:
            raise exc.HTTPUnprocessableEntity()

        context = req.environ["nova.context"]
        authorize(context)

        network = body["network"]
        keys = ["cidr", "cidr_v6", "ipam", "vlan_start", "network_size",
                "num_networks"]
        kwargs = dict((k, network.get(k)) for k in keys)

        label = network["label"]

        if not (kwargs["cidr"] or kwargs["cidr_v6"]):
            msg = _("No CIDR requested")
            raise exc.HTTPBadRequest(explanation=msg)
        if kwargs["cidr"]:
            try:
                net = netaddr.IPNetwork(kwargs["cidr"])
                if net.size < 4:
                    msg = _("Requested network does not contain "
                            "enough (2+) usable hosts")
                    raise exc.HTTPBadRequest(explanation=msg)
            except netexc.AddrFormatError:
                msg = _("CIDR is malformed.")
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

        try:
            networks = self.network_api.create(context,
                                               label=label, **kwargs)
            if CONF.enable_network_quota:
                QUOTAS.commit(context, reservation)
        except exception.PolicyNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=six.text_type(e))
        except Exception:
            if CONF.enable_network_quota:
                QUOTAS.rollback(context, reservation)
            msg = _("Create networks failed")
            LOG.exception(msg, extra=network)
            raise exc.HTTPServiceUnavailable(explanation=msg)
        return {"network": network_dict(networks[0])}


class Os_tenant_networks(extensions.ExtensionDescriptor):
    """Tenant-based Network Management Extension."""

    name = "OSTenantNetworks"
    alias = "os-tenant-networks"
    namespace = ("http://docs.openstack.org/compute/"
                 "ext/os-tenant-networks/api/v2")
    updated = "2012-03-07T14:46:43Z"

    def get_resources(self):
        ext = extensions.ResourceExtension('os-tenant-networks',
                                           NetworkController())
        return [ext]


def _sync_networks(context, project_id, session):
    ctx = nova_context.RequestContext(user_id=None, project_id=project_id)
    ctx = ctx.elevated()
    networks = nova.network.api.API().get_all(ctx)
    return dict(networks=len(networks))


if CONF.enable_network_quota:
    QUOTAS.register_resource(quota.ReservableResource('networks',
                                                      _sync_networks,
                                                      'quota_networks'))
