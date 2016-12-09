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
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova.api.validation import parameter_types
from nova import compute
from nova.compute import vm_states
from nova import exception
from nova.i18n import _
from nova import objects
from nova.policies import server_tags as st_policies


ALIAS = "os-server-tags"


def _get_tags_names(tags):
    return [t.tag for t in tags]


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

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @extensions.expected_errors(404)
    def show(self, req, server_id, id):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'show')

        try:
            exists = objects.Tag.exists(context, server_id, id)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        if not exists:
            msg = (_("Server %(server_id)s has no tag '%(tag)s'")
                   % {'server_id': server_id, 'tag': id})
            raise webob.exc.HTTPNotFound(explanation=msg)

    @wsgi.Controller.api_version("2.26")
    @extensions.expected_errors(404)
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'index')

        try:
            tags = objects.TagList.get_by_resource_id(context, server_id)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        return {'tags': _get_tags_names(tags)}

    @wsgi.Controller.api_version("2.26")
    @extensions.expected_errors((400, 404, 409))
    @validation.schema(schema.update)
    def update(self, req, server_id, id, body):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'update')
        self._check_instance_in_valid_state(context, server_id, 'update tag')

        try:
            jsonschema.validate(id, parameter_types.tag)
        except jsonschema.ValidationError as e:
            msg = (_("Tag '%(tag)s' is invalid. It must be a non empty string "
                     "without characters '/' and ','. Validation error "
                     "message: %(err)s") % {'tag': id, 'err': e.message})
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            tags = objects.TagList.get_by_resource_id(context, server_id)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        if len(tags) >= objects.instance.MAX_TAG_COUNT:
            msg = (_("The number of tags exceeded the per-server limit %d")
                   % objects.instance.MAX_TAG_COUNT)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if id in _get_tags_names(tags):
            # NOTE(snikitin): server already has specified tag
            return webob.Response(status_int=204)

        tag = objects.Tag(context=context, resource_id=server_id, tag=id)

        try:
            tag.create()
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        response = webob.Response(status_int=201)
        response.headers['Location'] = self._view_builder.get_location(
            req, server_id, id)
        return response

    @wsgi.Controller.api_version("2.26")
    @extensions.expected_errors((400, 404, 409))
    @validation.schema(schema.update_all)
    def update_all(self, req, server_id, body):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'update_all')
        self._check_instance_in_valid_state(context, server_id, 'update tags')

        try:
            tags = objects.TagList.create(context, server_id, body['tags'])
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        return {'tags': _get_tags_names(tags)}

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @extensions.expected_errors((404, 409))
    def delete(self, req, server_id, id):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'delete')
        self._check_instance_in_valid_state(context, server_id, 'delete tag')

        try:
            objects.Tag.destroy(context, server_id, id)
        except exception.InstanceTagNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @extensions.expected_errors((404, 409))
    def delete_all(self, req, server_id):
        context = req.environ["nova.context"]
        context.can(st_policies.POLICY_ROOT % 'delete_all')
        self._check_instance_in_valid_state(context, server_id, 'delete tags')

        try:
            objects.TagList.destroy(context, server_id)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())


class ServerTags(extensions.V21APIExtensionBase):
    """Server tags support."""

    name = "ServerTags"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        return []

    def get_resources(self):
        res = extensions.ResourceExtension('tags',
                                           ServerTagsController(),
                                           parent=dict(
                                               member_name='server',
                                               collection_name='servers'),
                                           collection_actions={
                                               'delete_all': 'DELETE',
                                               'update_all': 'PUT'})
        return [res]
