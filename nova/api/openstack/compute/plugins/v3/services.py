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
authorize = extensions.os_compute_authorizer(ALIAS)


class ServiceController(wsgi.Controller):

    def __init__(self):
        self.host_api = compute.HostAPI()
        self.servicegroup_api = servicegroup.API()

    def _get_services(self, req):
        context = req.environ['nova.context']
        authorize(context)
        _services = self.host_api.service_get_all(context, set_zones=True)

        host = ''
        if 'host' in req.GET:
            host = req.GET['host']
        binary = ''
        if 'binary' in req.GET:
            binary = req.GET['binary']
        if host:
            _services = [s for s in _services if s['host'] == host]
        if binary:
            _services = [s for s in _services if s['binary'] == binary]

        return _services

    def _get_service_detail(self, svc):
        alive = self.servicegroup_api.service_is_up(svc)
        state = (alive and "up") or "down"
        active = 'enabled'
        if svc['disabled']:
            active = 'disabled'
        service_detail = {'binary': svc['binary'],
                          'host': svc['host'],
                          'id': svc['id'],
                          'zone': svc['availability_zone'],
                          'status': active,
                          'state': state,
                          'updated_at': svc['updated_at'],
                          'disabled_reason': svc['disabled_reason']}

        return service_detail

    def _get_services_list(self, req):
        _services = self._get_services(req)
        return [self._get_service_detail(svc) for svc in _services]

    def _enable(self, body, context):
        """Enable scheduling for a service."""
        return self._enable_disable(body, context, "enabled",
                                    {'disabled': False,
                                     'disabled_reason': None})

    def _disable(self, body, context, reason=None):
        """Disable scheduling for a service with optional log."""
        return self._enable_disable(body, context, "disabled",
                                    {'disabled': True,
                                     'disabled_reason': reason})

    def _disable_log_reason(self, body, context):
        """Disable scheduling for a service with a log."""
        try:
            reason = body['disabled_reason']
        except KeyError:
            msg = _('Missing disabled reason field')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return self._disable(body, context, reason)

    def _enable_disable(self, body, context, status, params_to_update):
        """Enable/Disable scheduling for a service."""
        reason = params_to_update.get('disabled_reason')

        ret_value = {
            'service': {
                'host': body['host'],
                'binary': body['binary'],
                'status': status
            },
        }

        if reason:
            ret_value['service']['disabled_reason'] = reason

        self._update(context, body['host'], body['binary'], params_to_update)
        return ret_value

    def _update(self, context, host, binary, payload):
        """Do the actual PUT/update"""
        try:
            self.host_api.service_update(context, host, binary, payload)
        except exception.HostBinaryNotFound as exc:
            raise webob.exc.HTTPNotFound(explanation=exc.format_message())

    @wsgi.response(204)
    @extensions.expected_errors(404)
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
        return {'services': self._get_services_list(req)}

    @extensions.expected_errors((400, 404))
    @validation.schema(services.service_update)
    def update(self, req, id, body):
        """Perform service update"""
        context = req.environ['nova.context']
        authorize(context)

        actions = {"enable": self._enable,
                   "disable": self._disable,
                   "disable-log-reason": self._disable_log_reason}

        try:
            action = actions[id]
        except KeyError:
            msg = _("Unknown action")
            raise webob.exc.HTTPNotFound(explanation=msg)

        return action(body, context)


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
