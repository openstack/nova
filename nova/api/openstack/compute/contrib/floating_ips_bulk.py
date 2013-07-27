# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM Corp.
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
from oslo.config import cfg
import webob.exc

from nova.api.openstack import extensions
from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

CONF = cfg.CONF
CONF.import_opt('default_floating_pool', 'nova.network.floating_ips')
CONF.import_opt('public_interface', 'nova.network.linux_net')


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'floating_ips_bulk')


class FloatingIPBulkController(object):

    def index(self, req):
        """Return a list of all floating ips."""
        context = req.environ['nova.context']
        authorize(context)

        return self._get_floating_ip_info(context)

    def show(self, req, id):
        """Return a list of all floating ips for a given host."""
        context = req.environ['nova.context']
        authorize(context)

        return self._get_floating_ip_info(context, id)

    def _get_floating_ip_info(self, context, host=None):
        floating_ip_info = {"floating_ip_info": []}

        try:
            if host is None:
                floating_ips = db.floating_ip_get_all(context)
            else:
                floating_ips = db.floating_ip_get_all_by_host(context, host)
        except exception.NoFloatingIpsDefined:
            return floating_ip_info

        for floating_ip in floating_ips:
            instance_uuid = None
            if floating_ip['fixed_ip_id']:
                fixed_ip = db.fixed_ip_get(context, floating_ip['fixed_ip_id'])
                instance_uuid = fixed_ip['instance_uuid']

            result = {'address': floating_ip['address'],
                      'pool': floating_ip['pool'],
                      'interface': floating_ip['interface'],
                      'project_id': floating_ip['project_id'],
                      'instance_uuid': instance_uuid}
            floating_ip_info['floating_ip_info'].append(result)

        return floating_ip_info

    def create(self, req, body):
        """Bulk create floating ips."""
        context = req.environ['nova.context']
        authorize(context)

        if 'floating_ips_bulk_create' not in body:
            raise webob.exc.HTTPUnprocessableEntity()
        params = body['floating_ips_bulk_create']

        LOG.debug(params)

        if 'ip_range' not in params:
            raise webob.exc.HTTPUnprocessableEntity()
        ip_range = params['ip_range']

        pool = params.get('pool', CONF.default_floating_pool)
        interface = params.get('interface', CONF.public_interface)

        try:
            ips = ({'address': str(address),
                    'pool': pool,
                    'interface': interface}
                   for address in self._address_to_hosts(ip_range))
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        try:
            db.floating_ip_bulk_create(context, ips)
        except exception.FloatingIpExists as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        return {"floating_ips_bulk_create": {"ip_range": ip_range,
                                               "pool": pool,
                                               "interface": interface}}

    def update(self, req, id, body):
        """Bulk delete floating IPs."""
        context = req.environ['nova.context']
        authorize(context)

        if id != "delete":
            raise webob.exc.HTTPNotFound("Unknown action")

        try:
            ip_range = body['ip_range']
        except (TypeError, KeyError):
            raise webob.exc.HTTPUnprocessableEntity()

        try:
            ips = ({'address': str(address)}
                   for address in self._address_to_hosts(ip_range))
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
        db.floating_ip_bulk_destroy(context, ips)

        return {"floating_ips_bulk_delete": ip_range}

    def _address_to_hosts(self, addresses):
        """
        Iterate over hosts within an address range.

        If an explicit range specifier is missing, the parameter is
        interpreted as a specific individual address.
        """
        try:
            return [netaddr.IPAddress(addresses)]
        except ValueError:
            net = netaddr.IPNetwork(addresses)
            if net.size < 4:
                reason = _("/%s should be specified as single address(es) "
                           "not in cidr format") % net.prefixlen
                raise exception.InvalidInput(reason=reason)
            else:
                return net.iter_hosts()
        except netaddr.AddrFormatError as exc:
            raise exception.InvalidInput(reason=str(exc))


class Floating_ips_bulk(extensions.ExtensionDescriptor):
    """Bulk handling of Floating IPs."""

    name = "FloatingIpsBulk"
    alias = "os-floating-ips-bulk"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "floating_ips_bulk/api/v2")
    updated = "2012-10-29T13:25:27-06:00"

    def __init__(self, ext_mgr):
        ext_mgr.register(self)

    def get_resources(self):
        resources = []
        resource = extensions.ResourceExtension('os-floating-ips-bulk',
                                                FloatingIPBulkController())
        resources.append(resource)
        return resources
