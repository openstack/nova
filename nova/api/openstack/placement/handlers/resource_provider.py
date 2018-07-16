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

from oslo_db import exception as db_exc
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import webob

from nova.api.openstack.placement import errors
from nova.api.openstack.placement import exception
from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.api.openstack.placement.policies import resource_provider as policies
from nova.api.openstack.placement.schemas import resource_provider as rp_schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova.i18n import _


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
    context.can(policies.CREATE)
    schema = rp_schema.POST_RESOURCE_PROVIDER_SCHEMA
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    if want_version.matches((1, 14)):
        schema = rp_schema.POST_RP_SCHEMA_V1_14
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
            {'duplicate': duplicate},
            comment=errors.DUPLICATE_NAME)
    except exception.ObjectActionError as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unable to create resource provider "%(name)s", %(rp_uuid)s: '
              '%(error)s') %
            {'name': data['name'], 'rp_uuid': uuid, 'error': exc})

    req.response.location = util.resource_provider_url(
        req.environ, resource_provider)
    if want_version.matches(min_version=(1, 20)):
        req.response.body = encodeutils.to_utf8(jsonutils.dumps(
            _serialize_provider(req.environ, resource_provider, want_version)))
        req.response.content_type = 'application/json'
        modified = util.pick_last_modified(None, resource_provider)
        req.response.last_modified = modified
        req.response.cache_control = 'no-cache'
    else:
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
    context.can(policies.DELETE)
    # The containing application will catch a not found here.
    try:
        resource_provider = rp_obj.ResourceProvider.get_by_uuid(
            context, uuid)
        resource_provider.destroy()
    except exception.ResourceProviderInUse as exc:
        raise webob.exc.HTTPConflict(
            _('Unable to delete resource provider %(rp_uuid)s: %(error)s') %
            {'rp_uuid': uuid, 'error': exc},
            comment=errors.PROVIDER_IN_USE)
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("No resource provider with uuid %s found for delete") % uuid)
    except exception.CannotDeleteParentResourceProvider as exc:
        raise webob.exc.HTTPConflict(
            _("Unable to delete parent resource provider %(rp_uuid)s: "
              "It has child resource providers.") % {'rp_uuid': uuid},
            comment=errors.PROVIDER_CANNOT_DELETE_PARENT)
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
    context = req.environ['placement.context']
    context.can(policies.SHOW)

    # The containing application will catch a not found here.
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
    context.can(policies.LIST)
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]

    schema = rp_schema.GET_RPS_SCHEMA_1_0
    if want_version.matches((1, 18)):
        schema = rp_schema.GET_RPS_SCHEMA_1_18
    elif want_version.matches((1, 14)):
        schema = rp_schema.GET_RPS_SCHEMA_1_14
    elif want_version.matches((1, 4)):
        schema = rp_schema.GET_RPS_SCHEMA_1_4
    elif want_version.matches((1, 3)):
        schema = rp_schema.GET_RPS_SCHEMA_1_3

    allow_forbidden = want_version.matches((1, 22))

    util.validate_query_params(req, schema)

    filters = {}
    # special handling of member_of qparam since we allow multiple member_of
    # params at microversion 1.24.
    if 'member_of' in req.GET:
        filters['member_of'] = util.normalize_member_of_qs_params(req)

    qpkeys = ('uuid', 'name', 'in_tree', 'resources', 'required')
    for attr in qpkeys:
        if attr in req.GET:
            value = req.GET[attr]
            if attr == 'resources':
                value = util.normalize_resources_qs_param(value)
            elif attr == 'required':
                value = util.normalize_traits_qs_param(
                    value, allow_forbidden=allow_forbidden)
            filters[attr] = value
    try:
        resource_providers = rp_obj.ResourceProviderList.get_all_by_filters(
            context, filters)
    except exception.ResourceClassNotFound as exc:
        raise webob.exc.HTTPBadRequest(
            _('Invalid resource class in resources parameter: %(error)s') %
            {'error': exc})
    except exception.TraitNotFound as exc:
        raise webob.exc.HTTPBadRequest(
            _('Invalid trait(s) in "required" parameter: %(error)s') %
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
    context.can(policies.UPDATE)
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]

    # The containing application will catch a not found here.
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)

    schema = rp_schema.PUT_RESOURCE_PROVIDER_SCHEMA
    if want_version.matches((1, 14)):
        schema = rp_schema.PUT_RP_SCHEMA_V1_14

    data = util.extract_json(req.body, schema)

    for field in rp_obj.ResourceProvider.SETTABLE_FIELDS:
        if field in data:
            setattr(resource_provider, field, data[field])

    try:
        resource_provider.save()
    except db_exc.DBDuplicateEntry as exc:
        raise webob.exc.HTTPConflict(
            _('Conflicting resource provider %(name)s already exists.') %
            {'name': data['name']},
            comment=errors.DUPLICATE_NAME)
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
