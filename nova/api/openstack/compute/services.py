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

from nova.api.openstack import api_version_request
from nova.api.openstack.compute.schemas import services
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception
from nova.i18n import _
from nova.policies import services as services_policies
from nova import servicegroup
from nova import utils

ALIAS = "os-services"


class ServiceController(wsgi.Controller):

    def __init__(self):
        self.host_api = compute.HostAPI()
        self.aggregate_api = compute.api.AggregateAPI()
        self.servicegroup_api = servicegroup.API()
        self.actions = {"enable": self._enable,
                        "disable": self._disable,
                        "disable-log-reason": self._disable_log_reason}

    def _get_services(self, req):
        api_services = ('nova-osapi_compute', 'nova-ec2', 'nova-metadata')

        context = req.environ['nova.context']
        context.can(services_policies.BASE_POLICY_NAME)

        _services = [
           s
           for s in self.host_api.service_get_all(context, set_zones=True,
                                                  all_cells=True)
           if s['binary'] not in api_services
        ]

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

    def _get_service_detail(self, svc, additional_fields):
        alive = self.servicegroup_api.service_is_up(svc)
        state = (alive and "up") or "down"
        active = 'enabled'
        if svc['disabled']:
            active = 'disabled'
        updated_time = self.servicegroup_api.get_updated_time(svc)

        service_detail = {'binary': svc['binary'],
                          'host': svc['host'],
                          'id': svc['id'],
                          'zone': svc['availability_zone'],
                          'status': active,
                          'state': state,
                          'updated_at': updated_time,
                          'disabled_reason': svc['disabled_reason']}

        for field in additional_fields:
            service_detail[field] = svc[field]

        return service_detail

    def _get_services_list(self, req, additional_fields=()):
        _services = self._get_services(req)
        return [self._get_service_detail(svc, additional_fields)
                for svc in _services]

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

    def _forced_down(self, body, context):
        """Set or unset forced_down flag for the service"""
        try:
            forced_down = body["forced_down"]
        except KeyError:
            msg = _('Missing forced_down field')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        host = body['host']
        binary = body['binary']

        ret_value = {'service': {'host': host,
                                 'binary': binary,
                                 'forced_down': forced_down}}
        self._update(context, host, binary, {"forced_down": forced_down})
        return ret_value

    def _update(self, context, host, binary, payload):
        """Do the actual PUT/update"""
        try:
            self.host_api.service_update(context, host, binary, payload)
        except (exception.HostBinaryNotFound,
                exception.HostMappingNotFound) as exc:
            raise webob.exc.HTTPNotFound(explanation=exc.format_message())

    def _perform_action(self, req, id, body, actions):
        """Calculate action dictionary dependent on provided fields"""
        context = req.environ['nova.context']
        context.can(services_policies.BASE_POLICY_NAME)

        try:
            action = actions[id]
        except KeyError:
            msg = _("Unknown action")
            raise webob.exc.HTTPNotFound(explanation=msg)

        return action(body, context)

    @wsgi.response(204)
    @extensions.expected_errors((400, 404))
    def delete(self, req, id):
        """Deletes the specified service."""
        context = req.environ['nova.context']
        context.can(services_policies.BASE_POLICY_NAME)

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        try:
            service = self.host_api.service_get_by_id(context, id)
            # remove the service from all the aggregates in which it's included
            if service.binary == 'nova-compute':
                aggrs = self.aggregate_api.get_aggregates_by_host(context,
                                                                  service.host)
                for ag in aggrs:
                    self.aggregate_api.remove_host_from_aggregate(context,
                                                                  ag.id,
                                                                  service.host)
            self.host_api.service_delete(context, id)

        except exception.ServiceNotFound:
            explanation = _("Service %s not found.") % id
            raise webob.exc.HTTPNotFound(explanation=explanation)
        except exception.ServiceNotUnique:
            explanation = _("Service id %s refers to multiple services.") % id
            raise webob.exc.HTTPBadRequest(explanation=explanation)

    @extensions.expected_errors(())
    def index(self, req):
        """Return a list of all running services. Filter by host & service
        name
        """
        if api_version_request.is_supported(req, min_version='2.11'):
            _services = self._get_services_list(req, ['forced_down'])
        else:
            _services = self._get_services_list(req)

        return {'services': _services}

    @extensions.expected_errors((400, 404))
    @validation.schema(services.service_update, '2.0', '2.10')
    @validation.schema(services.service_update_v211, '2.11')
    def update(self, req, id, body):
        """Perform service update"""
        if api_version_request.is_supported(req, min_version='2.11'):
            actions = self.actions.copy()
            actions["force-down"] = self._forced_down
        else:
            actions = self.actions

        return self._perform_action(req, id, body, actions)


class Services(extensions.V21APIExtensionBase):
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
