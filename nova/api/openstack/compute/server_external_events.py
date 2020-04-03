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

from nova.api.openstack.compute.schemas import server_external_events
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import context as nova_context
from nova import objects
from nova.policies import server_external_events as see_policies


LOG = logging.getLogger(__name__)


TAG_REQUIRED = ('volume-extended', 'power-update',
                'accelerator-request-bound')


class ServerExternalEventsController(wsgi.Controller):

    def __init__(self):
        super(ServerExternalEventsController, self).__init__()
        self.compute_api = compute.API()

    @staticmethod
    def _is_event_tag_present_when_required(event):
        if event.name in TAG_REQUIRED and event.tag is None:
            return False
        return True

    def _get_instances_all_cells(self, context, instance_uuids,
                                 instance_mappings):
        cells = {}
        instance_uuids_by_cell = {}
        for im in instance_mappings:
            if im.cell_mapping.uuid not in cells:
                cells[im.cell_mapping.uuid] = im.cell_mapping
            instance_uuids_by_cell.setdefault(im.cell_mapping.uuid, list())
            instance_uuids_by_cell[im.cell_mapping.uuid].append(
                im.instance_uuid)

        instances = {}
        for cell_uuid, cell in cells.items():
            with nova_context.target_cell(context, cell) as cctxt:
                instances.update(
                    {inst.uuid: inst for inst in
                     objects.InstanceList.get_by_filters(
                         cctxt, {'uuid': instance_uuids_by_cell[cell_uuid]},
                         expected_attrs=['migration_context', 'info_cache'])})

        return instances

    @wsgi.expected_errors(403)
    @wsgi.response(200)
    @validation.schema(server_external_events.create, '2.0', '2.50')
    @validation.schema(server_external_events.create_v251, '2.51', '2.75')
    @validation.schema(server_external_events.create_v276, '2.76', '2.81')
    @validation.schema(server_external_events.create_v282, '2.82')
    def create(self, req, body):
        """Creates a new instance event."""
        context = req.environ['nova.context']
        context.can(see_policies.POLICY_ROOT % 'create', target={})

        response_events = []
        accepted_events = []
        accepted_instances = set()
        result = 200

        body_events = body['events']

        # Fetch instance objects for all relevant instances
        instance_uuids = set([event['server_uuid'] for event in body_events])
        instance_mappings = objects.InstanceMappingList.get_by_instance_uuids(
                context, list(instance_uuids))
        instances = self._get_instances_all_cells(context, instance_uuids,
                                                  instance_mappings)

        for _event in body_events:
            client_event = dict(_event)
            event = objects.InstanceExternalEvent(context)

            event.instance_uuid = client_event.pop('server_uuid')
            event.name = client_event.pop('name')
            event.status = client_event.pop('status', 'completed')
            event.tag = client_event.pop('tag', None)

            response_events.append(_event)

            instance = instances.get(event.instance_uuid)
            if not instance:
                LOG.debug('Dropping event %(name)s:%(tag)s for unknown '
                          'instance %(instance_uuid)s',
                          {'name': event.name, 'tag': event.tag,
                           'instance_uuid': event.instance_uuid})
                _event['status'] = 'failed'
                _event['code'] = 404
                result = 207
                continue

            # NOTE: before accepting the event, make sure the instance
            # for which the event is sent is assigned to a host; otherwise
            # it will not be possible to dispatch the event
            if not self._is_event_tag_present_when_required(event):
                LOG.debug("Event tag is missing for instance "
                          "%(instance)s. Dropping event %(event)s",
                          {'instance': event.instance_uuid,
                           'event': event.name})
                _event['status'] = 'failed'
                _event['code'] = 400
                result = 207
            elif instance.host:
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

        if accepted_events:
            self.compute_api.external_instance_event(
                context, accepted_instances, accepted_events)

        # FIXME(cyeoh): This needs some infrastructure support so that
        # we have a general way to do this
        robj = wsgi.ResponseObject({'events': response_events})
        robj._code = result
        return robj
