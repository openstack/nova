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
"""Traits handlers for Placement API."""

import jsonschema
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import timeutils
import webob

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.schemas import trait as schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova import exception
from nova.i18n import _
from nova.objects import resource_provider as rp_obj


def _normalize_traits_qs_param(qs):
    try:
        op, value = qs.split(':', 1)
    except ValueError:
        msg = _('Badly formatted name parameter. Expected name query string '
                'parameter in form: '
                '?name=[in|startswith]:[name1,name2|prefix]. Got: "%s"')
        msg = msg % qs
        raise webob.exc.HTTPBadRequest(msg)

    filters = {}
    if op == 'in':
        filters['name_in'] = value.split(',')
    elif op == 'startswith':
        filters['prefix'] = value

    return filters


def _serialize_traits(traits, want_version):
    last_modified = None
    get_last_modified = want_version.matches((1, 15))
    trait_names = []
    for trait in traits:
        if get_last_modified:
            last_modified = util.pick_last_modified(last_modified, trait)
        trait_names.append(trait.name)

    # If there were no traits, set last_modified to now
    last_modified = last_modified or timeutils.utcnow(with_timezone=True)

    return {'traits': trait_names}, last_modified


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
def put_trait(req):
    context = req.environ['placement.context']
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    name = util.wsgi_path_item(req.environ, 'name')

    try:
        jsonschema.validate(name, schema.CUSTOM_TRAIT)
    except jsonschema.ValidationError:
        raise webob.exc.HTTPBadRequest(
            _('The trait is invalid. A valid trait must be no longer than '
              '255 characters, start with the prefix "CUSTOM_" and use '
              'following characters: "A"-"Z", "0"-"9" and "_"'))

    trait = rp_obj.Trait(context)
    trait.name = name

    try:
        trait.create()
        req.response.status = 201
    except exception.TraitExists:
        # Get the trait that already exists to get last-modified time.
        if want_version.matches((1, 15)):
            trait = rp_obj.Trait.get_by_name(context, name)
        req.response.status = 204

    req.response.content_type = None
    req.response.location = util.trait_url(req.environ, trait)
    if want_version.matches((1, 15)):
        req.response.last_modified = trait.created_at
        req.response.cache_control = 'no-cache'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
def get_trait(req):
    context = req.environ['placement.context']
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    name = util.wsgi_path_item(req.environ, 'name')

    try:
        trait = rp_obj.Trait.get_by_name(context, name)
    except exception.TraitNotFound as ex:
        raise webob.exc.HTTPNotFound(
            explanation=ex.format_message())

    req.response.status = 204
    req.response.content_type = None
    if want_version.matches((1, 15)):
        req.response.last_modified = trait.created_at
        req.response.cache_control = 'no-cache'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
def delete_trait(req):
    context = req.environ['placement.context']
    name = util.wsgi_path_item(req.environ, 'name')

    try:
        trait = rp_obj.Trait.get_by_name(context, name)
        trait.destroy()
    except exception.TraitNotFound as ex:
        raise webob.exc.HTTPNotFound(
            explanation=ex.format_message())
    except exception.TraitCannotDeleteStandard as ex:
        raise webob.exc.HTTPBadRequest(
            explanation=ex.format_message())
    except exception.TraitInUse as ex:
        raise webob.exc.HTTPConflict(
            explanation=ex.format_message())

    req.response.status = 204
    req.response.content_type = None
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
@util.check_accept('application/json')
def list_traits(req):
    context = req.environ['placement.context']
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    filters = {}

    util.validate_query_params(req, schema.LIST_TRAIT_SCHEMA)

    if 'name' in req.GET:
        filters = _normalize_traits_qs_param(req.GET['name'])
    if 'associated' in req.GET:
        if req.GET['associated'].lower() not in ['true', 'false']:
            raise webob.exc.HTTPBadRequest(
                explanation=_('The query parameter "associated" only accepts '
                              '"true" or "false"'))
        filters['associated'] = (
            True if req.GET['associated'].lower() == 'true' else False)

    traits = rp_obj.TraitList.get_all(context, filters)
    req.response.status = 200
    output, last_modified = _serialize_traits(traits, want_version)
    if want_version.matches((1, 15)):
        req.response.last_modified = last_modified
        req.response.cache_control = 'no-cache'
    req.response.body = encodeutils.to_utf8(jsonutils.dumps(output))
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
@util.check_accept('application/json')
def list_traits_for_resource_provider(req):
    context = req.environ['placement.context']
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    uuid = util.wsgi_path_item(req.environ, 'uuid')

    # Resource provider object is needed for two things: If it is
    # NotFound we'll get a 404 here, which needs to happen because
    # get_all_by_resource_provider can return an empty list.
    # It is also needed for the generation, used in the outgoing
    # representation.
    try:
        rp = rp_obj.ResourceProvider.get_by_uuid(context, uuid)
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("No resource provider with uuid %(uuid)s found: %(error)s") %
             {'uuid': uuid, 'error': exc})

    traits = rp_obj.TraitList.get_all_by_resource_provider(context, rp)
    response_body, last_modified = _serialize_traits(traits, want_version)
    response_body["resource_provider_generation"] = rp.generation

    if want_version.matches((1, 15)):
        req.response.last_modified = last_modified
        req.response.cache_control = 'no-cache'

    req.response.status = 200
    req.response.body = encodeutils.to_utf8(jsonutils.dumps(response_body))
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
@util.require_content('application/json')
def update_traits_for_resource_provider(req):
    context = req.environ['placement.context']
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    data = util.extract_json(req.body, schema.SET_TRAITS_FOR_RP_SCHEMA)
    rp_gen = data['resource_provider_generation']
    traits = data['traits']
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)

    if resource_provider.generation != rp_gen:
        raise webob.exc.HTTPConflict(
            _("Resource provider's generation already changed. Please update "
              "the generation and try again."),
            json_formatter=util.json_error_formatter)

    trait_objs = rp_obj.TraitList.get_all(
        context, filters={'name_in': traits})
    traits_name = set([obj.name for obj in trait_objs])
    non_existed_trait = set(traits) - set(traits_name)
    if non_existed_trait:
        raise webob.exc.HTTPBadRequest(
            _("No such trait %s") % ', '.join(non_existed_trait))

    resource_provider.set_traits(trait_objs)

    response_body, last_modified = _serialize_traits(trait_objs, want_version)
    response_body[
        'resource_provider_generation'] = resource_provider.generation
    if want_version.matches((1, 15)):
        req.response.last_modified = last_modified
        req.response.cache_control = 'no-cache'
    req.response.status = 200
    req.response.body = encodeutils.to_utf8(jsonutils.dumps(response_body))
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
def delete_traits_for_resource_provider(req):
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')

    resource_provider = rp_obj.ResourceProvider.get_by_uuid(context, uuid)
    try:
        resource_provider.set_traits(rp_obj.TraitList(objects=[]))
    except exception.ConcurrentUpdateDetected as e:
        raise webob.exc.HTTPConflict(explanation=e.format_message())

    req.response.status = 204
    req.response.content_type = None
    return req.response
