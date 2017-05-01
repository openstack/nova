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
import six
import webob.exc

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack.compute.schemas import floating_ips_bulk
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova.policies import floating_ips_bulk as fib_policies

CONF = nova.conf.CONF


class FloatingIPBulkController(wsgi.Controller):

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors(404)
    def index(self, req):
        """Return a list of all floating IPs."""
        context = req.environ['nova.context']
        context.can(fib_policies.BASE_POLICY_NAME)

        return self._get_floating_ip_info(context)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors(404)
    def show(self, req, id):
        """Return a list of all floating IPs for a given host."""
        context = req.environ['nova.context']
        context.can(fib_policies.BASE_POLICY_NAME)

        return self._get_floating_ip_info(context, id)

    def _get_floating_ip_info(self, context, host=None):
        floating_ip_info = {"floating_ip_info": []}

        if host is None:
            try:
                floating_ips = objects.FloatingIPList.get_all(context)
            except exception.NoFloatingIpsDefined:
                return floating_ip_info
        else:
            try:
                floating_ips = objects.FloatingIPList.get_by_host(context,
                                                                  host)
            except exception.FloatingIpNotFoundForHost as e:
                raise webob.exc.HTTPNotFound(explanation=e.format_message())

        for floating_ip in floating_ips:
            instance_uuid = None
            fixed_ip = None
            if floating_ip.fixed_ip:
                instance_uuid = floating_ip.fixed_ip.instance_uuid
                fixed_ip = str(floating_ip.fixed_ip.address)

            result = {'address': str(floating_ip.address),
                      'pool': floating_ip.pool,
                      'interface': floating_ip.interface,
                      'project_id': floating_ip.project_id,
                      'instance_uuid': instance_uuid,
                      'fixed_ip': fixed_ip}
            floating_ip_info['floating_ip_info'].append(result)

        return floating_ip_info

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((400, 409))
    @validation.schema(floating_ips_bulk.create)
    def create(self, req, body):
        """Bulk create floating IPs."""
        context = req.environ['nova.context']
        context.can(fib_policies.BASE_POLICY_NAME)

        params = body['floating_ips_bulk_create']
        ip_range = params['ip_range']

        pool = params.get('pool', CONF.default_floating_pool)
        interface = params.get('interface', CONF.public_interface)

        try:
            ips = [objects.FloatingIPList.make_ip_info(addr, pool, interface)
                   for addr in self._address_to_hosts(ip_range)]
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        try:
            objects.FloatingIPList.create(context, ips)
        except exception.FloatingIpExists as exc:
            raise webob.exc.HTTPConflict(explanation=exc.format_message())

        return {"floating_ips_bulk_create": {"ip_range": ip_range,
                                               "pool": pool,
                                               "interface": interface}}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((400, 404))
    @validation.schema(floating_ips_bulk.delete)
    def update(self, req, id, body):
        """Bulk delete floating IPs."""
        context = req.environ['nova.context']
        context.can(fib_policies.BASE_POLICY_NAME)

        if id != "delete":
            msg = _("Unknown action")
            raise webob.exc.HTTPNotFound(explanation=msg)
        ip_range = body['ip_range']
        try:
            ips = (objects.FloatingIPList.make_ip_info(address, None, None)
                   for address in self._address_to_hosts(ip_range))
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
        objects.FloatingIPList.destroy(context, ips)

        return {"floating_ips_bulk_delete": ip_range}

    def _address_to_hosts(self, addresses):
        """Iterate over hosts within an address range.

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
            raise exception.InvalidInput(reason=six.text_type(exc))
