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

import webob.exc

from nova.api.openstack import extensions
from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _

authorize = extensions.extension_authorizer('compute', 'fixed_ips')


class FixedIPController(object):
    def show(self, req, id):
        """Return data about the given fixed ip."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            fixed_ip = db.fixed_ip_get_by_address_detailed(context, id)
        except (exception.FixedIpNotFoundForAddress,
                exception.FixedIpInvalid) as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())

        fixed_ip_info = {"fixed_ip": {}}
        if fixed_ip[1] is None:
            msg = _("Fixed IP %s has been deleted") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

        fixed_ip_info['fixed_ip']['cidr'] = fixed_ip[1]['cidr']
        fixed_ip_info['fixed_ip']['address'] = fixed_ip[0]['address']

        if fixed_ip[2]:
            fixed_ip_info['fixed_ip']['hostname'] = fixed_ip[2]['hostname']
            fixed_ip_info['fixed_ip']['host'] = fixed_ip[2]['host']
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
            fixed_ip = db.fixed_ip_get_by_address(context, address)
            db.fixed_ip_update(context, fixed_ip['address'],
                               {'reserved': reserved})
        except (exception.FixedIpNotFoundForAddress, exception.FixedIpInvalid):
            msg = _("Fixed IP %s not found") % address
            raise webob.exc.HTTPNotFound(explanation=msg)

        return webob.exc.HTTPAccepted()


class Fixed_ips(extensions.ExtensionDescriptor):
    """Fixed IPs support."""

    name = "FixedIPs"
    alias = "os-fixed-ips"
    namespace = "http://docs.openstack.org/compute/ext/fixed_ips/api/v2"
    updated = "2012-10-18T13:25:27-06:00"

    def __init__(self, ext_mgr):
        ext_mgr.register(self)

    def get_resources(self):
        member_actions = {'action': 'POST'}
        resources = []
        resource = extensions.ResourceExtension('os-fixed-ips',
                                                FixedIPController(),
                                                member_actions=member_actions)
        resources.append(resource)
        return resources
