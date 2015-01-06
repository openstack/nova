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
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.i18n import _
from nova import servicegroup
from nova import utils

authorize = extensions.extension_authorizer('compute', 'services')


class ServiceController(object):

    def __init__(self, ext_mgr=None, *args, **kwargs):
        self.host_api = compute.HostAPI()
        self.servicegroup_api = servicegroup.API()
        self.ext_mgr = ext_mgr

    def _get_services(self, req):
        context = req.environ['nova.context']
        authorize(context)
        services = self.host_api.service_get_all(
            context, set_zones=True)

        host = ''
        if 'host' in req.GET:
            host = req.GET['host']
        binary = ''
        if 'binary' in req.GET:
            binary = req.GET['binary']
        if host:
            services = [s for s in services if s['host'] == host]
        if binary:
            services = [s for s in services if s['binary'] == binary]

        return services

    def _get_service_detail(self, svc, detailed):
        alive = self.servicegroup_api.service_is_up(svc)
        state = (alive and "up") or "down"
        active = 'enabled'
        if svc['disabled']:
            active = 'disabled'
        service_detail = {'binary': svc['binary'], 'host': svc['host'],
                     'zone': svc['availability_zone'],
                     'status': active, 'state': state,
                     'updated_at': svc['updated_at']}
        if self.ext_mgr.is_loaded('os-extended-services-delete'):
            service_detail['id'] = svc['id']
        if detailed:
            service_detail['disabled_reason'] = svc['disabled_reason']

        return service_detail

    def _get_services_list(self, req, detailed):
        services = self._get_services(req)
        svcs = []
        for svc in services:
            svcs.append(self._get_service_detail(svc, detailed))

        return svcs

    def _is_valid_as_reason(self, reason):
        try:
            utils.check_string_length(reason.strip(), 'Disabled reason',
                                      min_length=1, max_length=255)
        except exception.InvalidInput:
            return False

        return True

    @wsgi.response(204)
    def delete(self, req, id):
        """Deletes the specified service."""
        if not self.ext_mgr.is_loaded('os-extended-services-delete'):
            raise webob.exc.HTTPMethodNotAllowed()

        context = req.environ['nova.context']
        authorize(context)

        try:
            self.host_api.service_delete(context, id)
        except exception.ServiceNotFound:
            explanation = _("Service %s not found.") % id
            raise webob.exc.HTTPNotFound(explanation=explanation)

    def index(self, req):
        """Return a list of all running services."""
        detailed = self.ext_mgr.is_loaded('os-extended-services')
        services = self._get_services_list(req, detailed)

        return {'services': services}

    def update(self, req, id, body):
        """Enable/Disable scheduling for a service."""
        context = req.environ['nova.context']
        authorize(context)

        ext_loaded = self.ext_mgr.is_loaded('os-extended-services')
        if id == "enable":
            disabled = False
            status = "enabled"
        elif (id == "disable" or
                (id == "disable-log-reason" and ext_loaded)):
            disabled = True
            status = "disabled"
        else:
            msg = _("Unknown action")
            raise webob.exc.HTTPNotFound(explanation=msg)
        try:
            host = body['host']
            binary = body['binary']
            ret_value = {
                'service': {
                    'host': host,
                    'binary': binary,
                    'status': status,
                },
            }
            status_detail = {
                'disabled': disabled,
                'disabled_reason': None,
            }
            if id == "disable-log-reason":
                reason = body['disabled_reason']
                if not self._is_valid_as_reason(reason):
                    msg = _('The string containing the reason for disabling '
                            'the service contains invalid characters or is '
                            'too long.')
                    raise webob.exc.HTTPBadRequest(explanation=msg)

                status_detail['disabled_reason'] = reason
                ret_value['service']['disabled_reason'] = reason
        except (TypeError, KeyError):
            msg = _('Invalid attribute in the request')
            if 'host' in body and 'binary' in body:
                msg = _('Missing disabled reason field')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            self.host_api.service_update(context, host, binary, status_detail)
        except exception.HostBinaryNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        return ret_value


class Services(extensions.ExtensionDescriptor):
    """Services support."""

    name = "Services"
    alias = "os-services"
    namespace = "http://docs.openstack.org/compute/ext/services/api/v2"
    updated = "2012-10-28T00:00:00Z"

    def get_resources(self):
        resources = []
        resource = extensions.ResourceExtension('os-services',
                                               ServiceController(self.ext_mgr))

        resources.append(resource)
        return resources
