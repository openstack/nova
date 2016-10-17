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
"""Placement API handlers for resource providers."""

import copy

from oslo_db import exception as db_exc
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
import webob

from nova.api.openstack.placement import util
from nova import exception
from nova.i18n import _
from nova import objects


POST_RESOURCE_PROVIDER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string"
        },
        "uuid": {
            "type": "string",
            "format": "uuid"
        }
    },
    "required": [
        "name"
     ],
    "additionalProperties": False,
}
# Remove uuid to create the schema for PUTting a resource provider
PUT_RESOURCE_PROVIDER_SCHEMA = copy.deepcopy(POST_RESOURCE_PROVIDER_SCHEMA)
PUT_RESOURCE_PROVIDER_SCHEMA['properties'].pop('uuid')


def _serialize_links(environ, resource_provider):
    url = util.resource_provider_url(environ, resource_provider)
    links = [{'rel': 'self', 'href': url}]
    for rel in ('aggregates', 'inventories', 'usages'):
        links.append({'rel': rel, 'href': '%s/%s' % (url, rel)})
    return links


def _serialize_provider(environ, resource_provider):
    data = {
        'uuid': resource_provider.uuid,
        'name': resource_provider.name,
        'generation': resource_provider.generation,
        'links': _serialize_links(environ, resource_provider)
    }
    return data


def _serialize_providers(environ, resource_providers):
    output = []
    for provider in resource_providers:
        provider_data = _serialize_provider(environ, provider)
        output.append(provider_data)
    return {"resource_providers": output}


@webob.dec.wsgify
@util.require_content('application/json')
def create_resource_provider(req):
    """POST to create a resource provider.

    On success return a 201 response with an empty body and a location
    header pointing to the newly created resource provider.
    """
    context = req.environ['placement.context']
    data = util.extract_json(req.body, POST_RESOURCE_PROVIDER_SCHEMA)

    try:
        uuid = data.get('uuid', uuidutils.generate_uuid())
        resource_provider = objects.ResourceProvider(
            context, name=data['name'], uuid=uuid)
        resource_provider.create()
    except db_exc.DBDuplicateEntry as exc:
        raise webob.exc.HTTPConflict(
            _('Conflicting resource provider already exists: %(error)s') %
            {'error': exc},
            json_formatter=util.json_error_formatter)
    except exception.ObjectActionError as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unable to create resource provider %(rp_uuid)s: %(error)s') %
            {'rp_uuid': uuid, 'error': exc},
            json_formatter=util.json_error_formatter)

    req.response.location = util.resource_provider_url(
        req.environ, resource_provider)
    req.response.status = 201
    req.response.content_type = None
    return req.response


@webob.dec.wsgify
def delete_resource_provider(req):
    """DELETE to destroy a single resource provider.

    On success return a 204 and an empty body.
    """
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    context = req.environ['placement.context']
    # The containing application will catch a not found here.
    try:
        resource_provider = objects.ResourceProvider.get_by_uuid(
            context, uuid)
        resource_provider.destroy()
    except exception.ResourceProviderInUse as exc:
        raise webob.exc.HTTPConflict(
            _('Unable to delete resource provider %(rp_uuid)s: %(error)s') %
            {'rp_uuid': uuid, 'error': exc},
            json_formatter=util.json_error_formatter)
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("No resource provider with uuid %s found for delete") % uuid)
    req.response.status = 204
    req.response.content_type = None
    return req.response


@webob.dec.wsgify
@util.check_accept('application/json')
def get_resource_provider(req):
    """Get a single resource provider.

    On success return a 200 with an application/json body representing
    the resource provider.
    """
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    # The containing application will catch a not found here.
    context = req.environ['placement.context']

    resource_provider = objects.ResourceProvider.get_by_uuid(
        context, uuid)

    req.response.body = jsonutils.dumps(
        _serialize_provider(req.environ, resource_provider))
    req.response.content_type = 'application/json'
    return req.response


@webob.dec.wsgify
@util.check_accept('application/json')
def list_resource_providers(req):
    """GET a list of resource providers.

    On success return a 200 and an application/json body representing
    a collection of resource providers.
    """
    context = req.environ['placement.context']

    allowed_filters = set(objects.ResourceProviderList.allowed_filters)
    passed_filters = set(req.GET.keys())
    invalid_filters = passed_filters - allowed_filters
    if invalid_filters:
        raise webob.exc.HTTPBadRequest(
            _('Invalid filters: %(filters)s') %
            {'filters': ', '.join(invalid_filters)},
            json_formatter=util.json_error_formatter)

    if 'uuid' in req.GET and not uuidutils.is_uuid_like(req.GET['uuid']):
        raise webob.exc.HTTPBadRequest(
            _('Invalid uuid value: %(uuid)s') % {'uuid': req.GET['uuid']},
            json_formatter=util.json_error_formatter)

    filters = {}
    for attr in objects.ResourceProviderList.allowed_filters:
        if attr in req.GET:
            filters[attr] = req.GET[attr]
    resource_providers = objects.ResourceProviderList.get_all_by_filters(
        context, filters)

    response = req.response
    response.body = jsonutils.dumps(_serialize_providers(
        req.environ, resource_providers))
    response.content_type = 'application/json'
    return response


@webob.dec.wsgify
@util.require_content('application/json')
def update_resource_provider(req):
    """PUT to update a single resource provider.

    On success return a 200 response with a representation of the updated
    resource provider.
    """
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    context = req.environ['placement.context']

    # The containing application will catch a not found here.
    resource_provider = objects.ResourceProvider.get_by_uuid(
        context, uuid)

    data = util.extract_json(req.body, PUT_RESOURCE_PROVIDER_SCHEMA)

    resource_provider.name = data['name']

    try:
        resource_provider.save()
    except db_exc.DBDuplicateEntry as exc:
        raise webob.exc.HTTPConflict(
            _('Conflicting resource provider already exists: %(error)s') %
            {'error': exc},
            json_formatter=util.json_error_formatter)
    except exception.ObjectActionError as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unable to save resource provider %(rp_uuid)s: %(error)s') %
            {'rp_uuid': uuid, 'error': exc},
            json_formatter=util.json_error_formatter)

    req.response.body = jsonutils.dumps(
        _serialize_provider(req.environ, resource_provider))
    req.response.status = 200
    req.response.content_type = 'application/json'
    return req.response
