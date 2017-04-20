# Copyright 2014 Red Hat, Inc.
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

from oslo_log import log as logging
import webob

from nova.api.openstack.compute.schemas import server_external_events
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.policies import server_external_events as see_policies


LOG = logging.getLogger(__name__)
ALIAS = 'os-server-external-events'


class ServerExternalEventsController(wsgi.Controller):

    def __init__(self):
        self.compute_api = compute.API()
        super(ServerExternalEventsController, self).__init__()

    @extensions.expected_errors((400, 403, 404))
    @wsgi.response(200)
    @validation.schema(server_external_events.create)
    def create(self, req, body):
        """Creates a new instance event."""
        context = req.environ['nova.context']
        context.can(see_policies.POLICY_ROOT % 'create')

        response_events = []
        accepted_events = []
        accepted_instances = set()
        instances = {}
        mappings = {}
        result = 200

        body_events = body['events']

        for _event in body_events:
            client_event = dict(_event)
            event = objects.InstanceExternalEvent(context)

            event.instance_uuid = client_event.pop('server_uuid')
            event.name = client_event.pop('name')
            event.status = client_event.pop('status', 'completed')
            event.tag = client_event.pop('tag', None)

            instance = instances.get(event.instance_uuid)
            if not instance:
                try:
                    mapping = objects.InstanceMapping.get_by_instance_uuid(
                        context, event.instance_uuid)
                    cell_mapping = mapping.cell_mapping
                    mappings[event.instance_uuid] = cell_mapping

                    # Load migration_context and info_cache here in a single DB
                    # operation because we need them later on
                    with nova_context.target_cell(context,
                                                  cell_mapping) as cctxt:
                        instance = objects.Instance.get_by_uuid(
                            cctxt, event.instance_uuid,
                            expected_attrs=['migration_context', 'info_cache'])
                    instances[event.instance_uuid] = instance
                except (exception.InstanceNotFound,
                        exception.InstanceMappingNotFound):
                    LOG.debug('Dropping event %(name)s:%(tag)s for unknown '
                              'instance %(instance_uuid)s',
                              {'name': event.name, 'tag': event.tag,
                               'instance_uuid': event.instance_uuid})
                    _event['status'] = 'failed'
                    _event['code'] = 404
                    result = 207

            # NOTE: before accepting the event, make sure the instance
            # for which the event is sent is assigned to a host; otherwise
            # it will not be possible to dispatch the event
            if instance:
                if instance.host:
                    accepted_events.append(event)
                    accepted_instances.add(instance)
                    LOG.info('Creating event %(name)s:%(tag)s for '
                             'instance %(instance_uuid)s on %(host)s',
                              {'name': event.name, 'tag': event.tag,
                               'instance_uuid': event.instance_uuid,
                               'host': instance.host})
                    # NOTE: as the event is processed asynchronously verify
                    # whether 202 is a more suitable response code than 200
                    _event['status'] = 'completed'
                    _event['code'] = 200
                else:
                    LOG.debug("Unable to find a host for instance "
                              "%(instance)s. Dropping event %(event)s",
                              {'instance': event.instance_uuid,
                               'event': event.name})
                    _event['status'] = 'failed'
                    _event['code'] = 422
                    result = 207

            response_events.append(_event)

        if accepted_events:
            self.compute_api.external_instance_event(
                context, accepted_instances, mappings, accepted_events)
        else:
            msg = _('No instances found for any event')
            raise webob.exc.HTTPNotFound(explanation=msg)

        # FIXME(cyeoh): This needs some infrastructure support so that
        # we have a general way to do this
        robj = wsgi.ResponseObject({'events': response_events})
        robj._code = result
        return robj


class ServerExternalEvents(extensions.V21APIExtensionBase):
    """Server External Event Triggers."""

    name = "ServerExternalEvents"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resource = extensions.ResourceExtension(ALIAS,
                ServerExternalEventsController())

        return [resource]

    def get_controller_extensions(self):
        return []
