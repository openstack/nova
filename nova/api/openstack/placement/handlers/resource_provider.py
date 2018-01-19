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
from oslo_utils import encodeutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import webob

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova import exception
from nova.i18n import _
from nova.objects import resource_provider as rp_obj


POST_RESOURCE_PROVIDER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 200
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

# Placement API microversion 1.14 adds an optional parent_provider_uuid field
# to the POST and PUT request schemas
POST_RP_SCHEMA_V1_14 = copy.deepcopy(POST_RESOURCE_PROVIDER_SCHEMA)
POST_RP_SCHEMA_V1_14["properties"]["parent_provider_uuid"] = {
    "anyOf": [
        {
            "type": "string",
            "format": "uuid",
        },
        {
            "type": "null",
        }
    ]
}
PUT_RP_SCHEMA_V1_14 = copy.deepcopy(POST_RP_SCHEMA_V1_14)
PUT_RP_SCHEMA_V1_14['properties'].pop('uuid')

# Represents the allowed query string parameters to the GET /resource_providers
# API call
GET_RPS_SCHEMA_1_0 = {
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
    "additionalProperties": False,
}

# Placement API microversion 1.3 adds support for a member_of attribute
GET_RPS_SCHEMA_1_3 = copy.deepcopy(GET_RPS_SCHEMA_1_0)
GET_RPS_SCHEMA_1_3['properties']['member_of'] = {
    "type": "string"
}

# Placement API microversion 1.4 adds support for requesting resource providers
# having some set of capacity for some resources. The query string is a
# comma-delimited set of "$RESOURCE_CLASS_NAME:$AMOUNT" strings. The validation
# of the string is left up to the helper code in the
# normalize_resources_qs_param() function.
GET_RPS_SCHEMA_1_4 = copy.deepcopy(GET_RPS_SCHEMA_1_3)
GET_RPS_SCHEMA_1_4['properties']['resources'] = {
    "type": "string"
}

# Placement API microversion 1.14 adds support for requesting resource
# providers within a tree of providers. The 'in_tree' query string parameter
# should be the UUID of a resource provider. The result of the GET call will
# include only those resource providers in the same "provider tree" as the
# provider with the UUID represented by 'in_tree'
GET_RPS_SCHEMA_1_14 = copy.deepcopy(GET_RPS_SCHEMA_1_4)
GET_RPS_SCHEMA_1_14['properties']['in_tree'] = {
    "type": "string",
    "format": "uuid",
}


def _serialize_links(environ, resource_provider):
    url = util.resource_provider_url(environ, resource_provider)
    links = [{'rel': 'self', 'href': url}]
    rel_types = ['inventories', 'usages']
    want_version = environ[microversion.MICROVERSION_ENVIRON]
    if want_version >= (1, 1):
        rel_types.append('aggregates')
    if want_version >= (1, 6):
        rel_types.append('traits')
    if want_version >= (1, 11):
        rel_types.append('allocations')
    for rel in rel_types:
        links.append({'rel': rel, 'href': '%s/%s' % (url, rel)})
    return links


def _serialize_provider(environ, resource_provider, want_version):
    data = {
        'uuid': resource_provider.uuid,
        'name': resource_provider.name,
        'generation': resource_provider.generation,
        'links': _serialize_links(environ, resource_provider)
    }
    if want_version.matches((1, 14)):
        data['parent_provider_uuid'] = resource_provider.parent_provider_uuid
        data['root_provider_uuid'] = resource_provider.root_provider_uuid
    return data


def _serialize_providers(environ, resource_providers, want_version):
    output = []
    last_modified = None
    get_last_modified = want_version.matches((1, 15))
    for provider in resource_providers:
        if get_last_modified:
            last_modified = util.pick_last_modified(last_modified, provider)
        provider_data = _serialize_provider(environ, provider, want_version)
        output.append(provider_data)
    last_modified = last_modified or timeutils.utcnow(with_timezone=True)
    return ({"resource_providers": output}, last_modified)


@wsgi_wrapper.PlacementWsgify
@util.require_content('application/json')
def create_resource_provider(req):
    """POST to create a resource provider.

    On success return a 201 response with an empty body and a location
    header pointing to the newly created resource provider.
    """
    context = req.environ['placement.context']
    schema = POST_RESOURCE_PROVIDER_SCHEMA
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    if want_version.matches((1, 14)):
        schema = POST_RP_SCHEMA_V1_14
    data = util.extract_json(req.body, schema)

    try:
        uuid = data.setdefault('uuid', uuidutils.generate_uuid())
        resource_provider = rp_obj.ResourceProvider(context, **data)
        resource_provider.create()
    except db_exc.DBDuplicateEntry as exc:
        # Whether exc.columns has one or two entries (in the event
        # of both fields being duplicates) appears to be database
        # dependent, so going with the complete solution here.
        duplicate = ', '.join(['%s: %s' % (column, data[column])
                          for column in exc.columns])
        raise webob.exc.HTTPConflict(
            _('Conflicting resource provider %(duplicate)s already exists.') %
            {'duplicate': duplicate})
    except exception.ObjectActionError as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unable to create resource provider "%(name)s", %(rp_uuid)s: '
              '%(error)s') %
            {'name': data['name'], 'rp_uuid': uuid, 'error': exc})

    req.response.location = util.resource_provider_url(
        req.environ, resource_provider)
    req.response.status = 201
    req.response.content_type = None
    return req.response


@wsgi_wrapper.PlacementWsgify
def delete_resource_provider(req):
    """DELETE to destroy a single resource provider.

    On success return a 204 and an empty body.
    """
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    context = req.environ['placement.context']
    # The containing application will catch a not found here.
    try:
        resource_provider = rp_obj.ResourceProvider.get_by_uuid(
            context, uuid)
        resource_provider.destroy()
    except exception.ResourceProviderInUse as exc:
        raise webob.exc.HTTPConflict(
            _('Unable to delete resource provider %(rp_uuid)s: %(error)s') %
            {'rp_uuid': uuid, 'error': exc})
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("No resource provider with uuid %s found for delete") % uuid)
    req.response.status = 204
    req.response.content_type = None
    return req.response


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
def get_resource_provider(req):
    """Get a single resource provider.

    On success return a 200 with an application/json body representing
    the resource provider.
    """
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    # The containing application will catch a not found here.
    context = req.environ['placement.context']

    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)

    response = req.response
    response.body = encodeutils.to_utf8(jsonutils.dumps(
        _serialize_provider(req.environ, resource_provider, want_version)))
    response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        modified = util.pick_last_modified(None, resource_provider)
        response.last_modified = modified
        response.cache_control = 'no-cache'
    return response


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
def list_resource_providers(req):
    """GET a list of resource providers.

    On success return a 200 and an application/json body representing
    a collection of resource providers.
    """
    context = req.environ['placement.context']
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]

    schema = GET_RPS_SCHEMA_1_0
    if want_version.matches((1, 14)):
        schema = GET_RPS_SCHEMA_1_14
    elif want_version.matches((1, 4)):
        schema = GET_RPS_SCHEMA_1_4
    elif want_version.matches((1, 3)):
        schema = GET_RPS_SCHEMA_1_3

    util.validate_query_params(req, schema)

    filters = {}
    for attr in ['uuid', 'name', 'member_of', 'in_tree']:
        if attr in req.GET:
            value = req.GET[attr]
            # special case member_of to always make its value a
            # list, either by accepting the single value, or if it
            # starts with 'in:' splitting on ','.
            # NOTE(cdent): This will all change when we start using
            # JSONSchema validation of query params.
            if attr == 'member_of':
                if value.startswith('in:'):
                    value = value[3:].split(',')
                else:
                    value = [value]
                # Make sure the values are actually UUIDs.
                for aggr_uuid in value:
                    if not uuidutils.is_uuid_like(aggr_uuid):
                        raise webob.exc.HTTPBadRequest(
                            _('Invalid uuid value: %(uuid)s') %
                            {'uuid': aggr_uuid})
            filters[attr] = value
    if 'resources' in req.GET:
        resources = util.normalize_resources_qs_param(req.GET['resources'])
        filters['resources'] = resources
    try:
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            context, filters)
    except exception.ResourceClassNotFound as exc:
        raise webob.exc.HTTPBadRequest(
            _('Invalid resource class in resources parameter: %(error)s') %
            {'error': exc})

    response = req.response
    output, last_modified = _serialize_providers(
        req.environ, resource_providers, want_version)
    response.body = encodeutils.to_utf8(jsonutils.dumps(output))
    response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        response.last_modified = last_modified
        response.cache_control = 'no-cache'
    return response


@wsgi_wrapper.PlacementWsgify
@util.require_content('application/json')
def update_resource_provider(req):
    """PUT to update a single resource provider.

    On success return a 200 response with a representation of the updated
    resource provider.
    """
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    context = req.environ['placement.context']
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]

    # The containing application will catch a not found here.
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)

    schema = PUT_RESOURCE_PROVIDER_SCHEMA
    if want_version.matches((1, 14)):
        schema = PUT_RP_SCHEMA_V1_14

    data = util.extract_json(req.body, schema)

    for field in rp_obj.ResourceProvider.SETTABLE_FIELDS:
        if field in data:
            setattr(resource_provider, field, data[field])

    try:
        resource_provider.save()
    except db_exc.DBDuplicateEntry as exc:
        raise webob.exc.HTTPConflict(
            _('Conflicting resource provider %(name)s already exists.') %
            {'name': data['name']})
    except exception.ObjectActionError as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unable to save resource provider %(rp_uuid)s: %(error)s') %
            {'rp_uuid': uuid, 'error': exc})

    response = req.response
    response.status = 200
    response.body = encodeutils.to_utf8(jsonutils.dumps(
        _serialize_provider(req.environ, resource_provider, want_version)))
    response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        response.last_modified = resource_provider.updated_at
        response.cache_control = 'no-cache'
    return response
