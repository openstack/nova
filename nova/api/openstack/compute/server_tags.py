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

from webob import exc

from nova.api.openstack.compute.schemas import server_tags as schema
from nova.api.openstack.compute.views import server_tags
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.i18n import _
from nova import objects


ALIAS = "os-server-tags"
authorize = extensions.os_compute_authorizer(ALIAS)


def _get_tags_names(tags):
    return [t.tag for t in tags]


class ServerTagsController(wsgi.Controller):
    _view_builder_class = server_tags.ViewBuilder

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @extensions.expected_errors(404)
    def show(self, req, server_id, id):
        context = req.environ["nova.context"]
        authorize(context, action='show')

        try:
            exists = objects.Tag.exists(context, server_id, id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        if not exists:
            msg = (_("Server %(server_id)s has no tag '%(tag)s'")
                   % {'server_id': server_id, 'tag': id})
            raise exc.HTTPNotFound(explanation=msg)

    @wsgi.Controller.api_version("2.26")
    @extensions.expected_errors(404)
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        authorize(context, action='index')

        try:
            tags = objects.TagList.get_by_resource_id(context, server_id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        return {'tags': _get_tags_names(tags)}

    @wsgi.Controller.api_version("2.26")
    @extensions.expected_errors((400, 404))
    @validation.schema(schema.update)
    def update(self, req, server_id, id, body):
        context = req.environ["nova.context"]
        authorize(context, action='update')

        try:
            jsonschema.validate(id, schema.tag)
        except jsonschema.ValidationError as e:
            msg = (_("Tag '%(tag)s' is invalid. It must be a string without "
                     "characters '/' and ','. Validation error message: "
                     "%(err)s") % {'tag': id, 'err': e.message})
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            tags = objects.TagList.get_by_resource_id(context, server_id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        if len(tags) >= objects.instance.MAX_TAG_COUNT:
            msg = (_("The number of tags exceeded the per-server limit %d")
                   % objects.instance.MAX_TAG_COUNT)
            raise exc.HTTPBadRequest(explanation=msg)

        if len(id) > objects.tag.MAX_TAG_LENGTH:
            msg = (_("Tag '%(tag)s' is too long. Maximum length of a tag "
                     "is %(length)d") % {'tag': id,
                                         'length': objects.tag.MAX_TAG_LENGTH})
            raise exc.HTTPBadRequest(explanation=msg)

        if id in _get_tags_names(tags):
            # NOTE(snikitin): server already has specified tag
            return exc.HTTPNoContent()

        tag = objects.Tag(context=context, resource_id=server_id, tag=id)

        try:
            tag.create()
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        response = exc.HTTPCreated()
        response.headers['Location'] = self._view_builder.get_location(
            req, server_id, id)
        return response

    @wsgi.Controller.api_version("2.26")
    @extensions.expected_errors((400, 404))
    @validation.schema(schema.update_all)
    def update_all(self, req, server_id, body):
        context = req.environ["nova.context"]
        authorize(context, action='update_all')

        invalid_tags = []
        for tag in body['tags']:
            try:
                jsonschema.validate(tag, schema.tag)
            except jsonschema.ValidationError:
                invalid_tags.append(tag)
        if invalid_tags:
            msg = (_("Tags '%s' are invalid. Each tag must be a string "
                     "without characters '/' and ','.") % invalid_tags)
            raise exc.HTTPBadRequest(explanation=msg)

        tag_count = len(body['tags'])
        if tag_count > objects.instance.MAX_TAG_COUNT:
            msg = (_("The number of tags exceeded the per-server limit "
                     "%(max)d. The number of tags in request is %(count)d.")
                   % {'max': objects.instance.MAX_TAG_COUNT,
                      'count': tag_count})
            raise exc.HTTPBadRequest(explanation=msg)

        long_tags = [
            t for t in body['tags'] if len(t) > objects.tag.MAX_TAG_LENGTH]
        if long_tags:
            msg = (_("Tags %(tags)s are too long. Maximum length of a tag "
                     "is %(length)d") % {'tags': long_tags,
                                         'length': objects.tag.MAX_TAG_LENGTH})
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            tags = objects.TagList.create(context, server_id, body['tags'])
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        return {'tags': _get_tags_names(tags)}

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @extensions.expected_errors(404)
    def delete(self, req, server_id, id):
        context = req.environ["nova.context"]
        authorize(context, action='delete')

        try:
            objects.Tag.destroy(context, server_id, id)
        except exception.InstanceTagNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.Controller.api_version("2.26")
    @wsgi.response(204)
    @extensions.expected_errors(404)
    def delete_all(self, req, server_id):
        context = req.environ["nova.context"]
        authorize(context, action='delete_all')

        try:
            objects.TagList.destroy(context, server_id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())


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
