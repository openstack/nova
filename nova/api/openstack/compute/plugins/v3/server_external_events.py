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

import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.objects import external_event as external_event_obj
from nova.objects import instance as instance_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)
ALIAS = 'os-server-external-events'
authorize = extensions.extension_authorizer('compute',
                                            'v3:' + ALIAS)


class ServerExternalEventsController(wsgi.Controller):

    def __init__(self):
        self.compute_api = compute.API()
        super(ServerExternalEventsController, self).__init__()

    @extensions.expected_errors((400, 403, 404))
    @wsgi.response(200)
    def create(self, req, body):
        """Creates a new instance event."""
        context = req.environ['nova.context']
        authorize(context, action='create')

        events = []
        accepted = []
        instances = {}
        result = 200

        body_events = body.get('events', [])
        if not isinstance(body_events, list) or not len(body_events):
            raise webob.exc.HTTPBadRequest()

        for _event in body_events:
            client_event = dict(_event)
            event = external_event_obj.InstanceExternalEvent()

            try:
                event.instance_uuid = client_event.pop('server_uuid')
                event.name = client_event.pop('name')
                event.status = client_event.pop('status', 'completed')
                event.tag = client_event.pop('tag', None)
            except KeyError as missing_key:
                msg = _('event entity requires key %(key)s') % missing_key
                raise webob.exc.HTTPBadRequest(explanation=msg)

            if client_event:
                msg = (_('event entity contains unsupported items: %s') %
                       ', '.join(client_event.keys()))
                raise webob.exc.HTTPBadRequest(explanation=msg)

            if event.status not in external_event_obj.EVENT_STATUSES:
                raise webob.exc.HTTPBadRequest(
                    _('Invalid event status `%s\'') % event.status)

            events.append(_event)
            if event.instance_uuid not in instances:
                try:
                    instance = instance_obj.Instance.get_by_uuid(
                        context, event.instance_uuid)
                    instances[event.instance_uuid] = instance
                except exception.InstanceNotFound:
                    LOG.debug(_('Dropping event %(name)s:%(tag)s for unknown '
                                'instance %(server_uuid)s'), _event)
                    _event['status'] = 'failed'
                    _event['code'] = 404
                    result = 207

            if event.instance_uuid in instances:
                accepted.append(event)
                _event['code'] = 200
                LOG.audit(_('Create event %(name)s:%(tag)s for instance '
                            '%(instance_uuid)s'),
                          dict(event.iteritems()))

        if accepted:
            self.compute_api.external_instance_event(context,
                                                     instances.values(),
                                                     accepted)
        else:
            msg = _('No instances found for any event')
            raise webob.exc.HTTPNotFound(msg)

        # FIXME(cyeoh): This needs some infrastructure support so that
        # we have a general way to do this
        robj = wsgi.ResponseObject({'events': events})
        robj._code = result
        return robj


class ServerExternalEvents(extensions.V3APIExtensionBase):
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
