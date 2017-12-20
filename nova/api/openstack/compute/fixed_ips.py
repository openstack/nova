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

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack.compute.schemas import fixed_ips
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.i18n import _
from nova import objects
from nova.policies import fixed_ips as fi_policies


class FixedIPController(wsgi.Controller):

    @wsgi.Controller.api_version('2.1', '2.3')
    def _fill_reserved_status(self, req, fixed_ip, fixed_ip_info):
        # NOTE(mriedem): To be backwards compatible, < 2.4 version does not
        # show anything about reserved status.
        pass

    @wsgi.Controller.api_version('2.4')     # noqa
    def _fill_reserved_status(self, req, fixed_ip, fixed_ip_info):
        fixed_ip_info['fixed_ip']['reserved'] = fixed_ip.reserved

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 404))
    def show(self, req, id):
        """Return data about the given fixed IP."""
        context = req.environ['nova.context']
        context.can(fi_policies.BASE_POLICY_NAME)

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

        self._fill_reserved_status(req, fixed_ip, fixed_ip_info)

        return fixed_ip_info

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404))
    @validation.schema(fixed_ips.reserve)
    @wsgi.action('reserve')
    def reserve(self, req, id, body):
        context = req.environ['nova.context']
        context.can(fi_policies.BASE_POLICY_NAME)

        return self._set_reserved(context, id, True)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404))
    @validation.schema(fixed_ips.unreserve)
    @wsgi.action('unreserve')
    def unreserve(self, req, id, body):
        context = req.environ['nova.context']
        context.can(fi_policies.BASE_POLICY_NAME)
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
