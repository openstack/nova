# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, 2013 IBM Corp.
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
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

ALIAS = "os-fixed-ips"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class FixedIPController(object):
    @extensions.expected_errors(404)
    def show(self, req, id):
        """Return data about the given fixed ip."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            fixed_ip = db.fixed_ip_get_by_address_detailed(context, id)
        except exception.FixedIpNotFoundForAddress as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())

        fixed_ip_info = {"fixed_ip": {}}
        if not fixed_ip[1]:
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

    @extensions.expected_errors((400, 404))
    def action(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        if 'reserve' in body:
            LOG.debug(_("Reserving IP address %s") % id)
            return self._set_reserved(context, id, True)
        elif 'unreserve' in body:
            LOG.debug(_("Unreserving IP address %s") % id)
            return self._set_reserved(context, id, False)
        else:
            raise webob.exc.HTTPBadRequest(
                explanation="No valid action specified")

    def _set_reserved(self, context, address, reserved):
        try:
            fixed_ip = db.fixed_ip_get_by_address(context, address)
            db.fixed_ip_update(context, fixed_ip['address'],
                               {'reserved': reserved})
        except exception.FixedIpNotFoundForAddress:
            msg = _("Fixed IP %s not found") % address
            raise webob.exc.HTTPNotFound(explanation=msg)

        return webob.exc.HTTPAccepted()


class FixedIPs(extensions.V3APIExtensionBase):
    """Fixed IPs support."""

    name = "FixedIPs"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/ext/fixed_ips/api/v3"
    version = 1

    def get_resources(self):
        member_actions = {'action': 'POST'}
        resources = [
            extensions.ResourceExtension('os-fixed-ips',
                                         FixedIPController(),
                                         member_actions=member_actions)]
        return resources

    def get_controller_extensions(self):
        return []
