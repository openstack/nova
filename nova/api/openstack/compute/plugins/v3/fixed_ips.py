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
from nova.api.openstack import wsgi
from nova import exception
from nova.i18n import _
from nova import objects

ALIAS = 'os-fixed-ips'
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class FixedIPController(wsgi.Controller):
    @extensions.expected_errors((400, 404))
    def show(self, req, id):
        """Return data about the given fixed ip."""
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

    @wsgi.response(202)
    @extensions.expected_errors((400, 404))
    @wsgi.action('reserve')
    def reserve(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        return self._set_reserved(context, id, True)

    @wsgi.response(202)
    @extensions.expected_errors((400, 404))
    @wsgi.action('unreserve')
    def unreserve(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        return self._set_reserved(context, id, False)

    def _set_reserved(self, context, address, reserved):
        try:
            fixed_ip = objects.FixedIP.get_by_address(context, address)
            fixed_ip.reserved = reserved
            fixed_ip.save()
        except exception.FixedIpNotFoundForAddress:
            msg = _("Fixed IP %s not found") % address
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.FixedIpInvalid:
            msg = _("Fixed IP %s not valid") % address
            raise webob.exc.HTTPBadRequest(explanation=msg)


class FixedIps(extensions.V3APIExtensionBase):
    """Fixed IPs support."""

    name = "FixedIPs"
    alias = ALIAS
    version = 1

    def get_resources(self):
        member_actions = {'action': 'POST'}
        resources = extensions.ResourceExtension(ALIAS,
                                                FixedIPController(),
                                                member_actions=member_actions)
        return [resources]

    def get_controller_extensions(self):
        return []
