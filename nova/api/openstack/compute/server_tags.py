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

import jsonschema
import webob

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import server_tags as schema
from nova.api.openstack.compute.views import server_tags
from nova.api.openstack import wsgi
from nova.api import validation
from nova.api.validation import parameter_types
from nova import compute
from nova.compute import vm_states
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.notifications import base as notifications_base
from nova import objects
from nova.policies import server_tags as st_policies


def _get_tags_names(tags):
    return [t.tag for t in tags]


def _get_instance_mapping(context, server_id):
    try:
        return objects.InstanceMapping.get_by_instance_uuid(context,
                                                            server_id)
    except exception.InstanceMappingNotFound as e:
        raise webob.exc.HTTPNotFound(explanation=e.format_message())


class ServerTagsController(wsgi.Controller):
    _view_builder_class = server_tags.ViewBuilder

    def __init__(self):
        self.compute_api = compute.API()
        super(ServerTagsController, self).__init__()

    def _check_instance_in_valid_state(self, context, server_id, action):
        instance = common.get_instance(self.compute_api, context, server_id)
        if instance.vm_state not in (vm_states.ACTIVE, vm_states.PAUSED,
                                     vm_states.SUSPENDED, vm_states.STOPPED):
            exc = exception.InstanceInvalidState(attr='vm_state',
                                                 instance_uuid=instance.uuid,
                                                 state=instance.vm_state,
                                                 method=action)
            common.raise_http_conflict_for_instance_invalid_state(exc, action,
                                                                  server_id)
        return instance

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @wsgi.expected_errors(404)
    def show(self, req, server_id, id):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'show')

        try:
            im = objects.InstanceMapping.get_by_instance_uuid(context,
                                                              server_id)
            with nova_context.target_cell(context, im.cell_mapping) as cctxt:
                exists = objects.Tag.exists(cctxt, server_id, id)
        except (exception.InstanceNotFound,
                exception.InstanceMappingNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        if not exists:
            msg = (_("Server %(server_id)s has no tag '%(tag)s'")
                   % {'server_id': server_id, 'tag': id})
            raise webob.exc.HTTPNotFound(explanation=msg)

    @wsgi.Controller.api_version("2.26")
    @wsgi.expected_errors(404)
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'index')

        try:
            im = objects.InstanceMapping.get_by_instance_uuid(context,
                                                              server_id)
            with nova_context.target_cell(context, im.cell_mapping) as cctxt:
                tags = objects.TagList.get_by_resource_id(cctxt, server_id)
        except (exception.InstanceNotFound,
                exception.InstanceMappingNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        return {'tags': _get_tags_names(tags)}

    @wsgi.Controller.api_version("2.26")
    @wsgi.expected_errors((400, 404, 409))
    @validation.schema(schema.update)
    def update(self, req, server_id, id, body):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'update')
        im = _get_instance_mapping(context, server_id)

        with nova_context.target_cell(context, im.cell_mapping) as cctxt:
            instance = self._check_instance_in_valid_state(
                cctxt, server_id, 'update tag')

        try:
            jsonschema.validate(id, parameter_types.tag)
        except jsonschema.ValidationError as e:
            msg = (_("Tag '%(tag)s' is invalid. It must be a non empty string "
                     "without characters '/' and ','. Validation error "
                     "message: %(err)s") % {'tag': id, 'err': e.message})
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            with nova_context.target_cell(context, im.cell_mapping) as cctxt:
                tags = objects.TagList.get_by_resource_id(cctxt, server_id)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        if len(tags) >= objects.instance.MAX_TAG_COUNT:
            msg = (_("The number of tags exceeded the per-server limit %d")
                   % objects.instance.MAX_TAG_COUNT)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if id in _get_tags_names(tags):
            # NOTE(snikitin): server already has specified tag
            return webob.Response(status_int=204)

        try:
            with nova_context.target_cell(context, im.cell_mapping) as cctxt:
                tag = objects.Tag(context=cctxt, resource_id=server_id, tag=id)
                tag.create()
                instance.tags = objects.TagList.get_by_resource_id(cctxt,
                                                                   server_id)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        notifications_base.send_instance_update_notification(
            context, instance, service="nova-api")

        response = webob.Response(status_int=201)
        response.headers['Location'] = self._view_builder.get_location(
            req, server_id, id)
        return response

    @wsgi.Controller.api_version("2.26")
    @wsgi.expected_errors((404, 409))
    @validation.schema(schema.update_all)
    def update_all(self, req, server_id, body):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'update_all')
        im = _get_instance_mapping(context, server_id)

        with nova_context.target_cell(context, im.cell_mapping) as cctxt:
            instance = self._check_instance_in_valid_state(
                cctxt, server_id, 'update tags')

        try:
            with nova_context.target_cell(context, im.cell_mapping) as cctxt:
                tags = objects.TagList.create(cctxt, server_id, body['tags'])
                instance.tags = tags
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        notifications_base.send_instance_update_notification(
            context, instance, service="nova-api")

        return {'tags': _get_tags_names(tags)}

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @wsgi.expected_errors((404, 409))
    def delete(self, req, server_id, id):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'delete')
        im = _get_instance_mapping(context, server_id)

        with nova_context.target_cell(context, im.cell_mapping) as cctxt:
            instance = self._check_instance_in_valid_state(
                cctxt, server_id, 'delete tag')

        try:
            with nova_context.target_cell(context, im.cell_mapping) as cctxt:
                objects.Tag.destroy(cctxt, server_id, id)
                instance.tags = objects.TagList.get_by_resource_id(cctxt,
                                                                   server_id)
        except (exception.InstanceTagNotFound,
                exception.InstanceNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        notifications_base.send_instance_update_notification(
            context, instance, service="nova-api")

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @wsgi.expected_errors((404, 409))
    def delete_all(self, req, server_id):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'delete_all')
        im = _get_instance_mapping(context, server_id)

        with nova_context.target_cell(context, im.cell_mapping) as cctxt:
            instance = self._check_instance_in_valid_state(
                cctxt, server_id, 'delete tags')

        try:
            with nova_context.target_cell(context, im.cell_mapping) as cctxt:
                objects.TagList.destroy(cctxt, server_id)
                instance.tags = objects.TagList()
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        notifications_base.send_instance_update_notification(
            context, instance, service="nova-api")
