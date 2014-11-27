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

from nova.api.openstack.compute.schemas.v3 import services
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception
from nova.i18n import _
from nova import servicegroup

ALIAS = "os-services"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class ServiceController(wsgi.Controller):

    def __init__(self):
        self.host_api = compute.HostAPI()
        self.servicegroup_api = servicegroup.API()

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

    def _get_service_detail(self, svc):
        alive = self.servicegroup_api.service_is_up(svc)
        state = (alive and "up") or "down"
        active = 'enabled'
        if svc['disabled']:
            active = 'disabled'
        service_detail = {'binary': svc['binary'], 'host': svc['host'],
                     'id': svc['id'],
                     'zone': svc['availability_zone'],
                     'status': active, 'state': state,
                     'updated_at': svc['updated_at'],
                     'disabled_reason': svc['disabled_reason']}

        return service_detail

    def _get_services_list(self, req):
        services = self._get_services(req)
        svcs = []
        for svc in services:
            svcs.append(self._get_service_detail(svc))

        return svcs

    @wsgi.response(204)
    @extensions.expected_errors((400, 404))
    def delete(self, req, id):
        """Deletes the specified service."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            self.host_api.service_delete(context, id)
        except exception.ServiceNotFound:
            explanation = _("Service %s not found.") % id
            raise webob.exc.HTTPNotFound(explanation=explanation)

    @extensions.expected_errors(())
    def index(self, req):
        """Return a list of all running services. Filter by host & service
        name
        """
        services = self._get_services_list(req)

        return {'services': services}

    @extensions.expected_errors((400, 404))
    @validation.schema(services.service_update)
    def update(self, req, id, body):
        """Enable/Disable scheduling for a service."""
        context = req.environ['nova.context']
        authorize(context)

        if id == "enable":
            disabled = False
            status = "enabled"
        elif id in ("disable", "disable-log-reason"):
            disabled = True
            status = "disabled"
        else:
            msg = _("Unknown action")
            raise webob.exc.HTTPNotFound(explanation=msg)

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
            try:
                reason = body['disabled_reason']
            except (KeyError):
                msg = _('Missing disabled reason field')
                raise webob.exc.HTTPBadRequest(explanation=msg)

            status_detail['disabled_reason'] = reason
            ret_value['service']['disabled_reason'] = reason

        try:
            self.host_api.service_update(context, host, binary, status_detail)
        except exception.HostBinaryNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        return ret_value


class Services(extensions.V3APIExtensionBase):
    """Services support."""

    name = "Services"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = [extensions.ResourceExtension(ALIAS,
                                               ServiceController())]
        return resources

    def get_controller_extensions(self):
        return []
