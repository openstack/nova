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

import copy

import jsonschema
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
import webob

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova import exception
from nova.i18n import _
from nova import objects

TRAIT = {
    "type": "string",
    'minLength': 1, 'maxLength': 255,
}

CUSTOM_TRAIT = copy.deepcopy(TRAIT)
CUSTOM_TRAIT.update({"pattern": "^CUSTOM_[A-Z0-9_]+$"})

PUT_TRAITS_SCHEMA = {
    "type": "object",
    "properties": {
        "traits": {
            "type": "array",
            "items": CUSTOM_TRAIT,
        }
    },
    'required': ['traits'],
    'additionalProperties': False
}

SET_TRAITS_FOR_RP_SCHEMA = copy.deepcopy(PUT_TRAITS_SCHEMA)
SET_TRAITS_FOR_RP_SCHEMA['properties']['traits']['items'] = TRAIT
SET_TRAITS_FOR_RP_SCHEMA['properties'][
    'resource_provider_generation'] = {'type': 'integer'}
SET_TRAITS_FOR_RP_SCHEMA['required'].append('resource_provider_generation')


LIST_TRAIT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string"
        },
        "associated": {
            "type": "string",
        }
    },
    "additionalProperties": False
}


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


def _serialize_traits(traits):
    return {'traits': [trait.name for trait in traits]}


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
def put_trait(req):
    context = req.environ['placement.context']
    name = util.wsgi_path_item(req.environ, 'name')

    try:
        jsonschema.validate(name, CUSTOM_TRAIT)
    except jsonschema.ValidationError:
        raise webob.exc.HTTPBadRequest(
            _('The trait is invalid. A valid trait must be no longer than '
              '255 characters, start with the prefix "CUSTOM_" and use '
              'following characters: "A"-"Z", "0"-"9" and "_"'))

    trait = objects.Trait(context)
    trait.name = name

    try:
        trait.create()
        req.response.status = 201
    except exception.TraitExists:
        req.response.status = 204

    req.response.content_type = None
    req.response.location = util.trait_url(req.environ, trait)
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
def get_trait(req):
    context = req.environ['placement.context']
    name = util.wsgi_path_item(req.environ, 'name')

    try:
        objects.Trait.get_by_name(context, name)
    except exception.TraitNotFound as ex:
        raise webob.exc.HTTPNotFound(ex.format_message())

    req.response.status = 204
    req.response.content_type = None
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
def delete_trait(req):
    context = req.environ['placement.context']
    name = util.wsgi_path_item(req.environ, 'name')

    try:
        trait = objects.Trait.get_by_name(context, name)
        trait.destroy()
    except exception.TraitNotFound as ex:
        raise webob.exc.HTTPNotFound(ex.format_message())
    except exception.TraitCannotDeleteStandard as ex:
        raise webob.exc.HTTPBadRequest(ex.format_message())
    except exception.TraitInUse as ex:
        raise webob.exc.HTTPConflict(ex.format_message())

    req.response.status = 204
    req.response.content_type = None
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
@util.check_accept('application/json')
def list_traits(req):
    context = req.environ['placement.context']
    filters = {}

    try:
        jsonschema.validate(dict(req.GET), LIST_TRAIT_SCHEMA,
                            format_checker=jsonschema.FormatChecker())
    except jsonschema.ValidationError as exc:
        raise webob.exc.HTTPBadRequest(
            _('Invalid query string parameters: %(exc)s') %
            {'exc': exc})

    if 'name' in req.GET:
        filters = _normalize_traits_qs_param(req.GET['name'])
    if 'associated' in req.GET:
        if req.GET['associated'].lower() not in ['true', 'false']:
            raise webob.exc.HTTPBadRequest(
                _('The query parameter "associated" only accepts '
                  '"true" or "false"'))
        filters['associated'] = (
            True if req.GET['associated'].lower() == 'true' else False)

    traits = objects.TraitList.get_all(context, filters)
    req.response.status = 200
    req.response.body = encodeutils.to_utf8(
        jsonutils.dumps(_serialize_traits(traits)))
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
@util.check_accept('application/json')
def list_traits_for_resource_provider(req):
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')

    resource_provider = objects.ResourceProvider.get_by_uuid(
        context, uuid)

    response_body = _serialize_traits(resource_provider.get_traits())
    response_body[
        "resource_provider_generation"] = resource_provider.generation

    req.response.status = 200
    req.response.body = encodeutils.to_utf8(jsonutils.dumps(response_body))
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
@util.require_content('application/json')
def update_traits_for_resource_provider(req):
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    data = util.extract_json(req.body, SET_TRAITS_FOR_RP_SCHEMA)
    rp_gen = data['resource_provider_generation']
    traits = data['traits']
    resource_provider = objects.ResourceProvider.get_by_uuid(
        context, uuid)

    if resource_provider.generation != rp_gen:
        raise webob.exc.HTTPConflict(
            _("Resource provider's generation already changed. Please update "
              "the generation and try again."),
            json_formatter=util.json_error_formatter)

    trait_objs = objects.TraitList.get_all(
        context, filters={'name_in': traits})
    traits_name = set([obj.name for obj in trait_objs])
    non_existed_trait = set(traits) - set(traits_name)
    if non_existed_trait:
        raise webob.exc.HTTPBadRequest(
            _("No such trait %s") % ', '.join(non_existed_trait))

    resource_provider.set_traits(trait_objs)

    response_body = _serialize_traits(trait_objs)
    response_body[
        'resource_provider_generation'] = resource_provider.generation
    req.response.status = 200
    req.response.body = encodeutils.to_utf8(jsonutils.dumps(response_body))
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.6')
def delete_traits_for_resource_provider(req):
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')

    resource_provider = objects.ResourceProvider.get_by_uuid(context, uuid)
    try:
        resource_provider.set_traits(objects.TraitList(objects=[]))
    except exception.ConcurrentUpdateDetected as e:
        raise webob.exc.HTTPConflict(e.format_message())

    req.response.status = 204
    req.response.content_type = None
    return req.response
