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

import webob
import webob.exc

from nova.api.openstack import extensions
from nova import exception
from nova.i18n import _
from nova import objects

authorize = extensions.extension_authorizer('compute', 'fixed_ips')


class FixedIPController(object):
    def show(self, req, id):
        """Return data about the given fixed IP."""
        context = req.environ['nova.context']
        authorize(context)

        attrs = ['network', 'instance']
        try:
            fixed_ip = objects.FixedIP.get_by_address(context, id,
                                                      expected_attrs=attrs)
        except exception.FixedIpNotFoundForAddress as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())
        except exception.FixedIpInvalid as ex:
            raise webob.exc.HTTPBadRequest(explanation=ex.format_message())

        fixed_ip_info = {"fixed_ip": {}}
        if fixed_ip is None:
            msg = _("Fixed IP %s has been deleted") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

        fixed_ip_info['fixed_ip']['cidr'] = str(fixed_ip.network.cidr)
        fixed_ip_info['fixed_ip']['address'] = str(fixed_ip.address)

        if fixed_ip.instance:
            fixed_ip_info['fixed_ip']['hostname'] = fixed_ip.instance.hostname
            fixed_ip_info['fixed_ip']['host'] = fixed_ip.instance.host
        else:
            fixed_ip_info['fixed_ip']['hostname'] = None
            fixed_ip_info['fixed_ip']['host'] = None

        return fixed_ip_info

    def action(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        if 'reserve' in body:
            return self._set_reserved(context, id, True)
        elif 'unreserve' in body:
            return self._set_reserved(context, id, False)
        else:
            raise webob.exc.HTTPBadRequest(
                explanation="No valid action specified")

    def _set_reserved(self, context, address, reserved):
        try:
            fixed_ip = objects.FixedIP.get_by_address(context, address)
            fixed_ip.reserved = reserved
            fixed_ip.save()
        except exception.FixedIpNotFoundForAddress:
            msg = _("Fixed IP %s not found") % address
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.FixedIpInvalid as ex:
            raise webob.exc.HTTPBadRequest(explanation=ex.format_message())

        return webob.Response(status_int=202)


class Fixed_ips(extensions.ExtensionDescriptor):
    """Fixed IPs support."""

    name = "FixedIPs"
    alias = "os-fixed-ips"
    namespace = "http://docs.openstack.org/compute/ext/fixed_ips/api/v2"
    updated = "2012-10-18T19:25:27Z"

    def get_resources(self):
        member_actions = {'action': 'POST'}
        resources = []
        resource = extensions.ResourceExtension('os-fixed-ips',
                                                FixedIPController(),
                                                member_actions=member_actions)
        resources.append(resource)
        return resources
